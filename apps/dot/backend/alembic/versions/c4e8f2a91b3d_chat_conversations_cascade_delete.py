"""chat_conversations FK cascade on cliente delete

Revision ID: c4e8f2a91b3d
Revises: 8a3f2c1e5b7d
Create Date: 2026-06-08 16:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c4e8f2a91b3d"
down_revision: Union[str, None] = "8a3f2c1e5b7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "chat_conversations_cliente_id_fkey",
        "chat_conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "chat_conversations_cliente_id_fkey",
        "chat_conversations",
        "clientes_suscripcion",
        ["cliente_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chat_conversations_cliente_id_fkey",
        "chat_conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "chat_conversations_cliente_id_fkey",
        "chat_conversations",
        "clientes_suscripcion",
        ["cliente_id"],
        ["id"],
    )
