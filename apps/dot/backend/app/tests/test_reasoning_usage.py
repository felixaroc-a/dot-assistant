"""Tests billing de reasoning en usage summary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.billing_models import UsageTokenORM
from app.services import usage_service


def test_breakdown_includes_reasoning_usd(db_session) -> None:
    cliente_id = uuid4()
    period = usage_service.BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 31))
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente_id,
            fecha=date(2026, 7, 10),
            modelo="deepseek-chat",
            costo_total=Decimal("1.20"),
            operation=usage_service.OPERATION_CHAT,
        )
    )
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente_id,
            fecha=date(2026, 7, 11),
            modelo="deepseek-reasoner",
            costo_total=Decimal("0.40"),
            operation=usage_service.OPERATION_REASONING,
        )
    )
    db_session.commit()

    summary = usage_service.build_usage_summary(db_session, cliente_id, period=period)
    assert summary.breakdown is not None
    assert summary.breakdown.chat_usd == Decimal("1.20")
    assert summary.breakdown.reasoning_usd == Decimal("0.40")
    assert summary.consumed_usd == Decimal("1.60")
