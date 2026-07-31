"""Resumen de consumo IA del mes en curso."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.auth_deps import require_product_jwt
from app.billing_db import get_billing_db
from app.billing_models import UsageTokenORM
from app.schemas.usage import (
    UsageBreakdownResponse,
    UsageDailyItemResponse,
    UsageDailyResponse,
    UsagePeriodResponse,
    UsageSummaryResponse,
)
from app.services.usage_service import (
    billing_today,
    build_usage_summary,
    current_billing_period,
    _monthly_limit_usd,
    aggregate_monthly_usd,
)
from app.settings import settings

log = logging.getLogger("dot.usage")

router = APIRouter(prefix="/v1/usage", tags=["usage"])


@router.get("/summary", response_model=UsageSummaryResponse)
def usage_summary(
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    cliente_id = UUID(str(claims["sub"]))
    summary = build_usage_summary(db, cliente_id)
    log.debug(
        "usage summary cliente=%s percent=%d blocked=%s",
        str(cliente_id)[:8],
        summary.consumed_percent,
        summary.blocked,
    )
    return UsageSummaryResponse(
        cliente_id=str(summary.cliente_id),
        period=UsagePeriodResponse(
            start=summary.period.start.isoformat(),
            end=summary.period.end.isoformat(),
        ),
        limit_usd=float(summary.limit_usd),
        consumed_usd=float(summary.consumed_usd),
        consumed_percent=summary.consumed_percent,
        remaining_usd=float(summary.remaining_usd),
        limit_enabled=summary.limit_enabled,
        blocked=summary.blocked,
        breakdown=(
            UsageBreakdownResponse(
                chat_usd=float(summary.breakdown.chat_usd),
                reasoning_usd=float(summary.breakdown.reasoning_usd),
                vision_usd=float(summary.breakdown.vision_usd),
                image_usd=float(summary.breakdown.image_usd),
            )
            if summary.breakdown is not None
            else None
        ),
        # OB04: proyección de cuándo se agota el saldo
        projected_depletion_date=_compute_depletion_projection(
            consumed_usd=float(summary.consumed_usd),
            limit_usd=float(summary.limit_usd),
            day_of_month=billing_today().day,
            days_in_month=_days_in_current_month(),
        ),
    )


def _days_in_current_month() -> int:
    period = current_billing_period()
    return (period.end - period.start).days + 1


def _compute_depletion_projection(
    consumed_usd: float,
    limit_usd: float,
    day_of_month: int,
    days_in_month: int,
) -> str | None:
    """Calcula fecha estimada de agotamiento basada en ritmo diario actual."""
    if consumed_usd <= 0 or limit_usd <= 0 or day_of_month <= 0:
        return None
    daily_rate = consumed_usd / day_of_month
    if daily_rate <= 0.0001:
        return None
    remaining = limit_usd - consumed_usd
    if remaining <= 0:
        return None
    days_left = int(remaining / daily_rate)
    if days_left > days_in_month:
        return None  # No se agota este mes
    depletion = date.today() + timedelta(days=days_left)
    return depletion.strftime("%d/%m")


@router.get("/daily", response_model=UsageDailyResponse)
def usage_daily_history(
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    days: int = Query(7, ge=1, le=31, description="Días hacia atrás"),
):
    """Historial de consumo diario de los últimos N días (OB04)."""
    cliente_id = UUID(str(claims["sub"]))
    end_date = billing_today()
    start_date = end_date - timedelta(days=days - 1)

    rows = db.execute(
        select(
            UsageTokenORM.fecha,
            func.coalesce(func.sum(UsageTokenORM.costo_total), 0),
        )
        .where(
            UsageTokenORM.cliente_id == cliente_id,
            UsageTokenORM.fecha >= start_date,
            UsageTokenORM.fecha <= end_date,
        )
        .group_by(UsageTokenORM.fecha)
        .order_by(UsageTokenORM.fecha)
    ).all()

    # Rellenar días sin consumo con $0
    row_map: dict[date, float] = {r[0]: float(r[1] or 0) for r in rows}
    items: list[UsageDailyItemResponse] = []
    cursor = start_date
    while cursor <= end_date:
        items.append(UsageDailyItemResponse(
            date=cursor.isoformat(),
            usd=row_map.get(cursor, 0.0),
        ))
        cursor += timedelta(days=1)

    return UsageDailyResponse(days=items)
