"""add channel and archived_at columns to chat_conversations + idx_conv_cliente

B01: Multi-chat e historial.
  - channel:  'pc' (default) o 'whatsapp' para conversaciones WA.
  - archived_at: soft-delete (NULL = activa, valor = archivada).
  - idx_conv_cliente: índice compuesto para listado ordenado de conversaciones del usuario.

Revision ID: f2b1c3d4e5a6
Revises: e6a4b8c2d1f3
Create Date: 2026-07-19 22:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2b1c3d4e5a6"
down_revision: Union[str, None] = "e6a4b8c2d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── channel column ───────────────────────────────────────────
    op.add_column(
        "chat_conversations",
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            server_default="pc",
        ),
    )
    op.create_check_constraint(
        "ck_chat_conversations_channel",
        "chat_conversations",
        "channel IN ('pc', 'whatsapp')",
    )

    # ── archived_at column (soft-delete) ─────────────────────────
    op.add_column(
        "chat_conversations",
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ── idx_conv_cliente ─────────────────────────────────────────
    # Listado de conversaciones del usuario ordenadas por última actualización
    op.create_index(
        "idx_conv_cliente",
        "chat_conversations",
        ["cliente_id", "updated_at"],
        postgresql_ops={"updated_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_conv_cliente", table_name="chat_conversations")
    op.drop_column("chat_conversations", "archived_at")
    op.execute("ALTER TABLE chat_conversations DROP CONSTRAINT IF EXISTS ck_chat_conversations_channel")
    op.drop_column("chat_conversations", "channel")
