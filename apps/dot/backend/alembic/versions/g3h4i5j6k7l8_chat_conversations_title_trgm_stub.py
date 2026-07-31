"""FREE-CH06: pg_trgm para búsqueda fuzzy en título de conversaciones.

Crea extensión pg_trgm (solo Postgres) e índice GIN en título.
En SQLite la migración es no-op (sigue usando ILIKE).

Revision ID: g3h4i5j6k7l8
Revises: f2b1c3d4e5a6
Create Date: 2026-07-24 05:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "g3h4i5j6k7l8"
down_revision: Union[str, None] = "f2b1c3d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chat_conv_title_trgm "
            "ON chat_conversations USING gin (title gin_trgm_ops)"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_chat_conv_title_trgm")
