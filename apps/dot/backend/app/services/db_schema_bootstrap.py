"""Bootstrap idempotente de esquema billing + chat (create_all + columnas IA)."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app import chat_models  # noqa: F401 — registra tablas chat en Base.metadata
from app import refresh_store  # noqa: F401 — registra refresh_token_families en Base.metadata
from app.billing_models import Base, UsageTokenORM  # noqa: F401 — registra usage_tokens
from app.services.db_schema_checklist import MissingTablesReport, missing_tables


def _ensure_ai_columns(engine: Engine) -> list[str]:
    applied: list[str] = []
    insp = inspect(engine)
    if "clientes_suscripcion" not in insp.get_table_names():
        return applied
    cols = {c["name"] for c in insp.get_columns("clientes_suscripcion")}
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if "ai_provider_id" not in cols:
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "ALTER TABLE clientes_suscripcion "
                        "ADD COLUMN ai_provider_id VARCHAR(20) NOT NULL DEFAULT 'deepseek'"
                    )
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE clientes_suscripcion "
                        "ADD COLUMN IF NOT EXISTS ai_provider_id VARCHAR(20) NOT NULL DEFAULT 'deepseek'"
                    )
                )
            applied.append("ai_provider_id")
        if "ai_billing_mode" not in cols:
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "ALTER TABLE clientes_suscripcion "
                        "ADD COLUMN ai_billing_mode VARCHAR(20) NOT NULL DEFAULT 'mensual'"
                    )
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE clientes_suscripcion "
                        "ADD COLUMN IF NOT EXISTS ai_billing_mode VARCHAR(20) NOT NULL DEFAULT 'mensual'"
                    )
                )
            applied.append("ai_billing_mode")
    return applied


def ensure_backend_schema(engine: Engine) -> tuple[MissingTablesReport, list[str]]:
    """Crea tablas billing + chat y aplica columnas IA faltantes."""
    Base.metadata.create_all(bind=engine)
    applied = _ensure_ai_columns(engine)
    return missing_tables(engine, check_chat=True), applied
