"""Revocación de JWT por jti (memoria en tests; Firestore en producción)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.settings import settings

log = logging.getLogger("dot.token_revocation")

_memory_revoked: dict[str, float] = {}  # jti → epoch exp
_memory_user_revoked_after: dict[str, int] = {}

# TTL interno: limpiar JTIs expirados cada 5 min
_MEMORY_PRUNE_INTERVAL_SEC = 300
_memory_last_prune: float = 0.0


def _prune_expired_jtis() -> None:
    """Elimina JTIs expirados de la memoria (evita memory leak)."""
    global _memory_last_prune
    now = time.time()
    if now - _memory_last_prune < _MEMORY_PRUNE_INTERVAL_SEC:
        return
    _memory_last_prune = now
    expired = [jti for jti, exp in _memory_revoked.items() if exp < now]
    for jti in expired:
        del _memory_revoked[jti]
    if expired:
        log.debug("Podados %d JTIs expirados de memoria", len(expired))


class TokenRevokedError(Exception):
    pass


def _firestore_only() -> bool:
    return settings.use_firestore_token_store_only


def _firestore_collection():
    from app.firebase_db import get_db

    return get_db().collection("revoked_tokens")


def _firestore_users_collection():
    from app.firebase_db import get_db

    return get_db().collection("revoked_users")


def revoke_jti(jti: str, exp_epoch: int | None = None) -> None:
    jti = jti.strip()
    if not jti:
        return
    if not _firestore_only():
        _memory_revoked[jti] = float(exp_epoch) if exp_epoch is not None else float('inf')

    try:
        payload: dict[str, object] = {
            "revoked_at": datetime.now(timezone.utc),
        }
        if exp_epoch is not None:
            payload["exp"] = int(exp_epoch)
        _firestore_collection().document(jti).set(payload)
    except Exception as e:
        if _firestore_only():
            raise RuntimeError("Firestore requerido para revocación de tokens") from e
        log.debug("Revocación en Firestore omitida: %s", e)


def is_jti_revoked(jti: str) -> bool:
    jti = jti.strip()
    if not jti:
        return False
    if not _firestore_only() and jti in _memory_revoked:
        _prune_expired_jtis()
        return True

    try:
        snap = _firestore_collection().document(jti).get()
        return snap.exists
    except Exception as e:
        if _firestore_only():
            raise RuntimeError(
                "Firestore no disponible - verificación de revocación deshabilitada"
            ) from e
        return jti in _memory_revoked


def revoke_user_tokens(user_id: str, revoked_after_epoch: int | None = None) -> None:
    user_id = user_id.strip()
    if not user_id:
        return

    ts = int(revoked_after_epoch or datetime.now(timezone.utc).timestamp())
    if not _firestore_only():
        _memory_user_revoked_after[user_id] = ts

    try:
        payload = {
            "revoked_after": ts,
            "revoked_at": datetime.now(timezone.utc),
        }
        _firestore_users_collection().document(user_id).set(payload, merge=True)
    except Exception as e:
        if _firestore_only():
            raise RuntimeError("Firestore requerido para revocación por usuario") from e
        log.debug("Revocación por usuario en Firestore omitida: %s", e)


def _load_user_revoked_after(user_id: str) -> int | None:
    if not _firestore_only() and user_id in _memory_user_revoked_after:
        return _memory_user_revoked_after[user_id]
    try:
        snap = _firestore_users_collection().document(user_id).get()
        if not snap.exists:
            return _memory_user_revoked_after.get(user_id) if not _firestore_only() else None
        data = snap.to_dict() or {}
        value = data.get("revoked_after")
        if value is None:
            return None
        cutoff = int(value)
        if not _firestore_only():
            _memory_user_revoked_after[user_id] = cutoff
        return cutoff
    except Exception as e:
        if _firestore_only():
            raise RuntimeError(
                "Firestore no disponible - verificación de revocación por usuario deshabilitada"
            ) from e
        return _memory_user_revoked_after.get(user_id)


def is_user_token_revoked(user_id: str, iat_epoch: int | None) -> bool:
    user_id = user_id.strip()
    if not user_id:
        return False
    cutoff = _load_user_revoked_after(user_id)
    if cutoff is None:
        return False
    if iat_epoch is None:
        return True
    return int(iat_epoch) <= cutoff


def assert_not_revoked(claims: dict[str, object]) -> None:
    jti = claims.get("jti")
    if isinstance(jti, str) and is_jti_revoked(jti):
        raise TokenRevokedError("Token revocado.")

    sub = claims.get("sub")
    iat = claims.get("iat")
    iat_val = int(iat) if isinstance(iat, (int, float)) else None
    if isinstance(sub, str) and is_user_token_revoked(sub, iat_val):
        raise TokenRevokedError("Token revocado por cambio de credenciales.")


def clear_memory_revocations() -> None:
    """Solo para tests."""
    _memory_revoked.clear()
    _memory_user_revoked_after.clear()
    global _memory_last_prune
    _memory_last_prune = 0.0
