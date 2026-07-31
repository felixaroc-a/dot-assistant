"""Tests unitarios de usage_service (Sprint 2.5)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.billing_models import UsageTokenORM
from app.services import usage_service
from app.settings import settings


@pytest.fixture(autouse=True)
def _reset_usage_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", False, raising=False)
    monkeypatch.setattr(settings, "ai_usage_monthly_limit_usd", 7.5, raising=False)
    monkeypatch.setattr(settings, "ai_usage_billing_timezone", "America/Bogota", raising=False)
    monkeypatch.setattr(settings, "ai_cost_deepseek_input_per_1m", 0.14, raising=False)
    monkeypatch.setattr(settings, "ai_cost_deepseek_output_per_1m", 0.28, raising=False)
    monkeypatch.setattr(settings, "ai_cost_gemini_vision_per_request", 0.001, raising=False)


def test_calc_deepseek_cost_from_usage_dict() -> None:
    prompt, completion, cached, cost = usage_service.cost_from_deepseek_usage(
        {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
    )
    assert prompt == 1_000_000
    assert completion == 500_000
    assert cached == 0
    assert cost == Decimal("0.280000")


def test_build_usage_summary_percent_and_remaining(db_session) -> None:
    cliente_id = uuid4()
    period = usage_service.BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 31))
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente_id,
            fecha=date(2026, 7, 15),
            modelo="deepseek-chat",
            costo_total=Decimal("2.55"),
            operation="chat",
        )
    )
    db_session.commit()

    summary = usage_service.build_usage_summary(db_session, cliente_id, period=period)
    assert summary.consumed_usd == Decimal("2.55")
    assert summary.consumed_percent == 34
    assert summary.remaining_usd == Decimal("4.95")
    assert summary.blocked is False
    assert summary.limit_enabled is False


def test_blocked_when_limit_enabled_and_consumed(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ai_usage_monthly_limit_usd", 1.0, raising=False)
    cliente_id = uuid4()
    period = usage_service.BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 31))
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente_id,
            fecha=date(2026, 7, 2),
            modelo="deepseek-chat",
            costo_total=Decimal("1.00"),
            operation="chat",
        )
    )
    db_session.commit()

    summary = usage_service.build_usage_summary(db_session, cliente_id, period=period)
    assert summary.blocked is True
    assert summary.consumed_percent == 100

    with pytest.raises(HTTPException) as exc:
        usage_service.assert_ai_usage_allowed(db_session, cliente_id)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == usage_service.USAGE_LIMIT_EXCEEDED_CODE


def test_limit_disabled_never_blocks(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", False, raising=False)
    monkeypatch.setattr(settings, "ai_usage_monthly_limit_usd", 0.01, raising=False)
    cliente_id = uuid4()
    period = usage_service.BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 31))
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente_id,
            fecha=date(2026, 7, 2),
            modelo="deepseek-chat",
            costo_total=Decimal("5.00"),
            operation="chat",
        )
    )
    db_session.commit()

    summary = usage_service.build_usage_summary(db_session, cliente_id, period=period)
    assert summary.blocked is False
    usage_service.assert_ai_usage_allowed(db_session, cliente_id)


def test_record_usage_persists_row(db_session) -> None:
    cliente_id = uuid4()
    row = usage_service.record_usage(
        db_session,
        cliente_id=cliente_id,
        modelo="gemini-2.5-flash",
        cost_usd=Decimal("0.001"),
        operation=usage_service.OPERATION_VISION,
    )
    assert row.id is not None
    assert row.operation == usage_service.OPERATION_VISION
    total = usage_service.aggregate_monthly_usd(db_session, cliente_id)
    assert total == Decimal("0.001")
