"""Familias de refresh token persistidas en SQLite con rotación y detección de reutilización.

Migrado de memoria RAM a SQLite para que un reinicio del servidor no invalide
todas las sesiones activas (punto de falla F2 del análisis de seguridad).
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.billing_db import get_session_factory
from app.billing_models import Base
from app.settings import settings

log = logging.getLogger("dot.refresh_store")

# Executor compartido para sync a Firestore (evita crear threads ilimitados)
_refresh_fs_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rfsh-fs")


class RefreshTokenFamilyORM(Base):
    __tablename__ = "refresh_token_families"

    family_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    uid: Mapped[str] = mapped_column(String(36), nullable=False)
    current_jti: Mapped[str] = mapped_column(String(36), nullable=False)
    used_jtis: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RefreshTokenReuseError(Exception):
    """Reutilización de refresh token → posible robo de sesión."""


def _firestore_only() -> bool:
    return settings.use_firestore_token_store_only


def _fs_collection():
    from app.firebase_db import get_db

    return get_db().collection("refresh_families")


def _doc_ref(family_id: str):
    return _fs_collection().document(family_id)


def _sync_to_firestore(
    *,
    family_id: str,
    uid: str,
    current_jti: str,
    revoked: bool,
) -> None:
    """Sincroniza a Firestore como respaldo (nunca bloquea login/refresh en modo dev)."""

    def _do_sync() -> None:
        try:
            from firebase_admin import firestore

            _doc_ref(family_id).set(
                {
                    "user_id": uid,
                    "current_jti": current_jti,
                    "revoked": revoked,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception as e:
            if _firestore_only():
                raise RuntimeError("No se pudo persistir familia refresh en Firestore") from e
            log.debug("refresh_families Firestore omitido: %s", e)

    if _firestore_only():
        _do_sync()
        return

    _refresh_fs_executor.submit(_do_sync)


def _get_session():
    return get_session_factory()()


def create_family(user_id: str) -> tuple[str, str]:
    """Devuelve (family_id, initial_jti)."""
    family_id = str(uuid4())
    jti = str(uuid4())

    orm = RefreshTokenFamilyORM(
        family_id=family_id,
        uid=user_id,
        current_jti=jti,
        used_jtis=json.dumps([jti]),
        revoked=False,
    )
    session = _get_session()
    try:
        session.add(orm)
        session.commit()
        fs_snapshot = {
            "family_id": orm.family_id,
            "uid": orm.uid,
            "current_jti": orm.current_jti,
            "revoked": orm.revoked,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if not _firestore_only():
        _sync_to_firestore(**fs_snapshot)

    return family_id, jti


def rotate_refresh(family_id: str, presented_jti: str, user_id: str) -> str:
    session = _get_session()
    fs_snapshot: dict[str, str | bool] | None = None
    new_jti = ""
    try:
        orm: RefreshTokenFamilyORM | None = session.get(RefreshTokenFamilyORM, family_id)
        if not orm or orm.revoked:
            raise RefreshTokenReuseError("Familia de refresh inválida o revocada.")

        if orm.uid != user_id:
            raise RefreshTokenReuseError("user_id no coincide con la familia.")

        if presented_jti != orm.current_jti:
            # Posible reutilización → revocar toda la familia
            orm.revoked = True
            session.commit()
            fs_snapshot = {
                "family_id": orm.family_id,
                "uid": orm.uid,
                "current_jti": orm.current_jti,
                "revoked": orm.revoked,
            }

            from app.token_revocation import revoke_jti

            revoke_jti(presented_jti)
            raise RefreshTokenReuseError("Reutilización de refresh token detectada.")

        new_jti = str(uuid4())
        orm.current_jti = new_jti

        used: list[str] = json.loads(orm.used_jtis or "[]")
        used.append(new_jti)
        orm.used_jtis = json.dumps(used)

        session.commit()
        fs_snapshot = {
            "family_id": orm.family_id,
            "uid": orm.uid,
            "current_jti": orm.current_jti,
            "revoked": orm.revoked,
        }
    except RefreshTokenReuseError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if not _firestore_only() and fs_snapshot is not None:
        _sync_to_firestore(**fs_snapshot)  # type: ignore[arg-type]

    return new_jti


def revoke_family(family_id: str) -> None:
    session = _get_session()
    fs_snapshot: dict[str, str | bool] | None = None
    try:
        orm: RefreshTokenFamilyORM | None = session.get(RefreshTokenFamilyORM, family_id)
        if orm:
            orm.revoked = True
            session.commit()
            fs_snapshot = {
                "family_id": orm.family_id,
                "uid": orm.uid,
                "current_jti": orm.current_jti,
                "revoked": orm.revoked,
            }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if not _firestore_only() and fs_snapshot is not None:
        _sync_to_firestore(**fs_snapshot)  # type: ignore[arg-type]


def clear_memory_families() -> None:
    """Solo para tests: elimina todos los registros de refresh_token_families.

    Tolerante a que la tabla no exista (ocurre durante teardown de tests
    cuando el engine ya fue restaurado a un estado anterior).
    """
    from sqlalchemy.exc import OperationalError

    session = _get_session()
    try:
        session.query(RefreshTokenFamilyORM).delete()
        session.commit()
    except OperationalError:
        session.rollback()
        log.debug("clear_memory_families: tabla refresh_token_families no existe, ignorando.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
