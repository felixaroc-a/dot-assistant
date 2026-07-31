"""Conexion SQLAlchemy con inyeccion de dependencias (sin singletons globales).

PgBouncer-compatible: pool_pre_ping=True, pool_recycle=3600 para
trabajar con connection pooling en produccion (ver infra/billing/pgbouncer.md).
En desarrollo con SQLite, el engine usa check_same_thread=False.
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import settings


def _normalize_url(raw: str) -> str:
    u = raw.strip()
    if u.startswith("sqlite:///") and not u.startswith("sqlite+pysqlite"):
        return "sqlite+pysqlite:///" + u.removeprefix("sqlite:///")
    return u


_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    """Singleton thread-safe para testing; en produccion usar create_engine() directo."""
    global _engine
    if _engine is None:
        db_url = (settings.database_url or "").strip()
        if not db_url:
            raise RuntimeError("DATABASE_URL no configurada.")
        db_url = _normalize_url(db_url)
        connect_args: dict[str, bool] = {}
        is_sqlite = db_url.startswith("sqlite")
        if is_sqlite:
            connect_args["check_same_thread"] = False

        # PgBouncer-compatible pool settings:
        # - pool_pre_ping=True: verifica que la conexión siga viva antes de usarla
        #   (PgBouncer puede cerrar conexiones inactivas)
        # - pool_recycle=3600: recicla conexiones cada 1h, debe ser MENOR que
        #   server_lifetime de PgBouncer (7200). Ver infra/billing/pgbouncer.md.
        # - max_overflow=10: permite hasta 10 conexiones extra bajo carga pico
        #   (pool_size=5 default + overflow=10 = max 15 conexiones a PgBouncer)
        engine_kwargs: dict = {"connect_args": connect_args}
        if not is_sqlite:
            # PgBouncer-compatible pool (Postgres only; SQLite rejects max_overflow)
            engine_kwargs.update(
                pool_pre_ping=True,
                pool_recycle=3600,
                max_overflow=10,
            )
        _engine = create_engine(db_url, **engine_kwargs)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory


def get_billing_db() -> Generator[Session, None, None]:
    """FastAPI dependency: provee sesion SQLAlchemy."""
    if not (settings.database_url or "").strip():
        raise HTTPException(status_code=503, detail="DATABASE_URL no configurada en el servidor.")
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
