"""Contrato: columnas ORM == DDL en infra/billing/schema.sql."""
from __future__ import annotations

import re
from pathlib import Path

from dot_billing.models import ClienteORM, SubscriptionReminderOutboxORM

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / "infra" / "billing" / "schema.sql"


def _parse_create_columns(sql: str, table: str) -> set[str]:
    pattern = rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\);"
    match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
    assert match, f"No se encontró CREATE TABLE {table}"
    block = match.group(1)
    cols: set[str] = set()
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        if line.upper().startswith(("CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN")):
            continue
        name = line.split()[0].strip(",").lower()
        cols.add(name)
    return cols


def test_clientes_suscripcion_columns_match_orm():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    ddl_cols = _parse_create_columns(sql, "clientes_suscripcion")
    orm_cols = {c.name for c in ClienteORM.__table__.columns}
    assert ddl_cols == orm_cols, f"DDL {ddl_cols - orm_cols} ORM {orm_cols - ddl_cols}"


def test_subscription_reminder_outbox_columns_match_orm():
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    ddl_cols = _parse_create_columns(sql, "subscription_reminder_outbox")
    orm_cols = {c.name for c in SubscriptionReminderOutboxORM.__table__.columns}
    assert ddl_cols == orm_cols
