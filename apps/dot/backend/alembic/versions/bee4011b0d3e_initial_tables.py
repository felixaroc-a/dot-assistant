"""initial_tables - alineado con infra/billing/schema.sql y dot_billing.models.

Tablas listadas en app.services.db_schema_checklist.BILLING_TABLES.

Revision ID: bee4011b0d3e
Revises:
Create Date: 2026-05-26 03:33:52.156893
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "bee4011b0d3e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from dot_billing.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from dot_billing.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
