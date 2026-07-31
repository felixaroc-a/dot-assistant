"""add usage_tokens table for AI consumption tracking.

Revision ID: d7a1b2c3e4f5
Revises: c4e8f2a91b3d
Create Date: 2026-07-07
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d7a1b2c3e4f5"
down_revision: Union[str, None] = "c4e8f2a91b3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.billing_models import UsageTokenORM  # noqa: F401

    bind = op.get_bind()
    UsageTokenORM.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    from app.billing_models import UsageTokenORM

    bind = op.get_bind()
    UsageTokenORM.__table__.drop(bind=bind, checkfirst=True)
