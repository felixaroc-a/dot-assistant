"""Alembic env (sync). Lee DATABASE_URL desde backend/.env a traves de settings."""
from __future__ import annotations

import logging

from alembic import context
from sqlalchemy import engine_from_config, pool

logging.basicConfig(level=logging.WARNING)

# MetaData de modelos
from app.billing_models import Base  # noqa: E402

# Importar modelos de chat para que Alembic los detecte
from app import chat_models  # noqa: E402, F401

target_metadata = Base.metadata

# Forzar carga de settings para que init_firebase/etc no fallen
from app.settings import settings  # noqa: E402


def _get_url() -> str:
    """Usa DATABASE_URL del .env si esta disponible, sino el default de alembic.ini."""
    url = settings.database_url.strip()
    if url:
        return url
    return context.config.get_main_option("sqlalchemy.url", "sqlite+pysqlite:///./dot_local.sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = context.config.get_section(context.config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
