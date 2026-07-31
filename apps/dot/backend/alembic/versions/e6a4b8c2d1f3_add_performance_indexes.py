"""add performance indexes to chat_messages, usage_tokens, and refresh_token_families.

Índices creados:
  - chat_messages:    (conversation_id, created_at DESC) — carga de mensajes por conversación
  - chat_messages:    (created_at DESC)                  — historial reciente global
  - usage_tokens:     (operation)                        — filtro por tipo de operación
  - refresh_token_families: (uid)                        — búsqueda por usuario

NOTAS:
  - (cliente_id, fecha) en usage_tokens ya existe como idx_usage_cliente_mes.
  - cedula en clientes_suscripcion ya tiene índice (UNIQUE).
  - chat_messages no tiene columna cliente_id; se usan índices sobre conversation_id y created_at.

Revision ID: e6a4b8c2d1f3
Revises: d7a1b2c3e4f5
Create Date: 2026-07-19 18:11:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e6a4b8c2d1f3"
down_revision: Union[str, None] = "d7a1b2c3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── chat_messages ──────────────────────────────────────────────
    # Carga de mensajes ordenados por conversación (el 99 % de las queries)
    op.create_index(
        "idx_chat_messages_conv_created",
        "chat_messages",
        ["conversation_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    # Historial reciente global (dashboard, búsquedas sin conversación)
    op.create_index(
        "idx_chat_messages_created_desc",
        "chat_messages",
        ["created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    # ── usage_tokens ───────────────────────────────────────────────
    # Filtro por tipo de operación (chat / vision / image-gen)
    op.create_index(
        "idx_usage_tokens_operation",
        "usage_tokens",
        ["operation"],
    )

    # ── refresh_token_families ─────────────────────────────────────
    # Búsqueda de todas las familias de un usuario
    op.create_index(
        "idx_refresh_token_families_uid",
        "refresh_token_families",
        ["uid"],
    )


def downgrade() -> None:
    op.drop_index("idx_refresh_token_families_uid", table_name="refresh_token_families")
    op.drop_index("idx_usage_tokens_operation", table_name="usage_tokens")
    op.drop_index("idx_chat_messages_created_desc", table_name="chat_messages")
    op.drop_index("idx_chat_messages_conv_created", table_name="chat_messages")
