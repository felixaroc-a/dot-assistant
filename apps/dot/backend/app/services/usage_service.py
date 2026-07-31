"""Tracking y límite mensual de consumo IA ($7.50 USD por cliente/pendrive)."""
from __future__ import annotations

import logging
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing_models import UsageTokenORM
from app.settings import settings

log = logging.getLogger("dot.usage_service")

USAGE_LIMIT_EXCEEDED_CODE = "ai_usage_limit_exceeded"
USAGE_WARNING_THRESHOLD_PERCENT = 80
USAGE_WARNING_MESSAGE = (
    "Te queda poco saldo de IA este mes. "
    "Recarga en tu tienda Nordik-IA más cercana cuando lo necesites."
)
USAGE_LIMIT_EXCEEDED_MESSAGE = (
    "Has alcanzado tu límite de IA de este mes. "
    "Visita tu tienda Nordik-IA más cercana para recargar."
)

OPERATION_CHAT = "chat"
OPERATION_VISION = "vision"
OPERATION_IMAGE_GEN = "image_generation"
OPERATION_REASONING = "reasoning"


def _derive_provider_from_model(model_name: str) -> str | None:
    """Deriva el proveedor del nombre del modelo usando las tarifas registradas."""
    from app.services.cost_calculator import get_tariff

    tariff = get_tariff(model_name)
    return tariff.provider if tariff else None


@dataclass(frozen=True)
class BillingPeriod:
    start: date
    end: date


@dataclass(frozen=True)
class UsageBreakdown:
    chat_usd: Decimal
    reasoning_usd: Decimal
    vision_usd: Decimal
    image_usd: Decimal


@dataclass(frozen=True)
class UsageBreakdown:
    chat_usd: Decimal
    reasoning_usd: Decimal
    vision_usd: Decimal
    image_usd: Decimal
    provider_breakdown: dict | None = None  # {provider: {"total_usd": ..., "models": {...}}}



@dataclass(frozen=True)
class UsageSummary:
    cliente_id: UUID
    period: BillingPeriod
    limit_usd: Decimal
    consumed_usd: Decimal
    consumed_percent: int
    remaining_usd: Decimal
    limit_enabled: bool
    blocked: bool
    breakdown: UsageBreakdown | None = None


def _billing_timezone() -> ZoneInfo:
    raw = (settings.ai_usage_billing_timezone or "America/Bogota").strip()
    try:
        return ZoneInfo(raw)
    except Exception:
        log.warning("Zona horaria inválida '%s', usando America/Bogota", raw, exc_info=True)
        return ZoneInfo("America/Bogota")


def billing_today(*, now: datetime | None = None) -> date:
    tz = _billing_timezone()
    local_now = (now or datetime.now(tz)).astimezone(tz)
    return local_now.date()


def current_billing_period(*, now: datetime | None = None) -> BillingPeriod:
    tz = _billing_timezone()
    local_now = (now or datetime.now(tz)).astimezone(tz)
    start = date(local_now.year, local_now.month, 1)
    last_day = monthrange(local_now.year, local_now.month)[1]
    end = date(local_now.year, local_now.month, last_day)
    return BillingPeriod(start=start, end=end)


def _monthly_limit_usd() -> Decimal:
    return Decimal(str(settings.ai_usage_monthly_limit_usd))


def calc_deepseek_cost_usd(
    tokens_prompt: int,
    tokens_completion: int,
    tokens_cached: int = 0,
) -> Decimal:
    input_rate = Decimal(str(settings.ai_cost_deepseek_input_per_1m))
    output_rate = Decimal(str(settings.ai_cost_deepseek_output_per_1m))
    million = Decimal("1000000")
    billable_prompt = max(0, int(tokens_prompt) - int(tokens_cached))
    cost = (
        Decimal(billable_prompt) * input_rate / million
        + Decimal(max(0, int(tokens_completion))) * output_rate / million
    )
    return cost.quantize(Decimal("0.000001"))


def calc_deepseek_reasoner_cost_usd(
    tokens_prompt: int,
    tokens_completion: int,
    tokens_cached: int = 0,
) -> Decimal:
    input_rate = Decimal(str(settings.ai_cost_deepseek_reasoner_input_per_1m))
    output_rate = Decimal(str(settings.ai_cost_deepseek_reasoner_output_per_1m))
    million = Decimal("1000000")
    billable_prompt = max(0, int(tokens_prompt) - int(tokens_cached))
    cost = (
        Decimal(billable_prompt) * input_rate / million
        + Decimal(max(0, int(tokens_completion))) * output_rate / million
    )
    return cost.quantize(Decimal("0.000001"))


def calc_vision_cost_usd() -> Decimal:
    return Decimal(str(settings.ai_cost_gemini_vision_per_request)).quantize(Decimal("0.000001"))


def calc_image_gen_cost_usd(image_count: int = 1) -> Decimal:
    unit = Decimal(str(settings.ai_cost_imagen_per_image))
    return (unit * Decimal(max(1, int(image_count)))).quantize(Decimal("0.000001"))


def estimate_chat_tokens_from_text(prompt_text: str, completion_text: str) -> tuple[int, int]:
    prompt_tokens = max(1, len(prompt_text) // 4)
    completion_tokens = max(1, len(completion_text) // 4)
    return prompt_tokens, completion_tokens


def cost_from_deepseek_usage(usage: dict | None) -> tuple[int, int, int, Decimal]:
    if not usage:
        return 0, 0, 0, Decimal("0")
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int(
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cached_tokens")
        or 0
    )
    cost = calc_deepseek_cost_usd(prompt, completion, cached)
    return prompt, completion, cached, cost


def aggregate_breakdown_by_operation(
    db: Session,
    cliente_id: UUID,
    period: BillingPeriod | None = None,
) -> UsageBreakdown:
    period = period or current_billing_period()
    rows = db.execute(
        select(UsageTokenORM.operation, func.coalesce(func.sum(UsageTokenORM.costo_total), 0)).where(
            UsageTokenORM.cliente_id == cliente_id,
            UsageTokenORM.fecha >= period.start,
            UsageTokenORM.fecha <= period.end,
        ).group_by(UsageTokenORM.operation)
    ).all()
    totals: dict[str, Decimal] = {}
    for operation, amount in rows:
        key = str(operation or OPERATION_CHAT)
        totals[key] = Decimal(str(amount or 0))

    # Calcular desglose por proveedor usando cost_calculator
    provider_breakdown = _compute_provider_breakdown(db, cliente_id, period)

    return UsageBreakdown(
        chat_usd=totals.get(OPERATION_CHAT, Decimal("0")),
        reasoning_usd=totals.get(OPERATION_REASONING, Decimal("0")),
        vision_usd=totals.get(OPERATION_VISION, Decimal("0")),
        image_usd=totals.get(OPERATION_IMAGE_GEN, Decimal("0")),
        provider_breakdown=provider_breakdown,
    )


def _compute_provider_breakdown(
    db: Session,
    cliente_id: UUID,
    period: BillingPeriod,
) -> dict | None:
    """Calcula desglose de costos por proveedor usando cost_calculator."""
    from app.services.cost_calculator import get_provider_cost_summary

    try:
        return get_provider_cost_summary(db, cliente_id, period)
    except Exception:
        log.debug("Error calculando provider_breakdown", exc_info=True)
        return None


def aggregate_monthly_usd(
    db: Session,
    cliente_id: UUID,
    period: BillingPeriod | None = None,
) -> Decimal:
    period = period or current_billing_period()
    total = db.scalar(
        select(func.coalesce(func.sum(UsageTokenORM.costo_total), 0)).where(
            UsageTokenORM.cliente_id == cliente_id,
            UsageTokenORM.fecha >= period.start,
            UsageTokenORM.fecha <= period.end,
        )
    )
    return Decimal(str(total or 0))


def build_usage_summary(
    db: Session,
    cliente_id: UUID,
    *,
    period: BillingPeriod | None = None,
) -> UsageSummary:
    period = period or current_billing_period()
    limit_enabled = bool(settings.ai_usage_limit_enabled)
    limit_usd = _monthly_limit_usd()
    consumed_usd = aggregate_monthly_usd(db, cliente_id, period)
    breakdown = aggregate_breakdown_by_operation(db, cliente_id, period)
    if limit_usd > 0:
        raw_percent = (consumed_usd / limit_usd) * Decimal("100")
        consumed_percent = int(raw_percent.to_integral_value(rounding=ROUND_FLOOR))
        # Cualquier gasto real debe verse en el % (evita 0% engañoso con montos chicos).
        if consumed_usd > 0 and consumed_percent < 1:
            consumed_percent = 1
    else:
        consumed_percent = 0
    consumed_percent = max(0, min(100, consumed_percent))
    remaining_usd = max(Decimal("0"), limit_usd - consumed_usd)
    blocked = limit_enabled and consumed_usd >= limit_usd
    return UsageSummary(
        cliente_id=cliente_id,
        period=period,
        limit_usd=limit_usd,
        consumed_usd=consumed_usd,
        consumed_percent=consumed_percent,
        remaining_usd=remaining_usd,
        limit_enabled=limit_enabled,
        blocked=blocked,
        breakdown=breakdown,
    )


def record_usage(
    db: Session,
    *,
    cliente_id: UUID,
    modelo: str,
    cost_usd: Decimal,
    operation: str,
    tokens_prompt: int = 0,
    tokens_completion: int = 0,
    tokens_cached: int = 0,
    request_id: str | None = None,
    usage_date: date | None = None,
    provider: str | None = None,
) -> UsageTokenORM:
    # Lock solo en Postgres (SQLite de desarrollo no tiene pg_advisory_xact_lock).
    # Sin esto el stream del chat muere al terminar el turno del agente en DOT_ENV local.
    try:
        bind = db.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    except Exception:
        dialect_name = ""
    if dialect_name == "postgresql":
        lock_id = hash(cliente_id) & 0x7FFFFFFF
        db.execute(select(func.pg_advisory_xact_lock(lock_id)))

    # Re-chequear límite DENTRO de la transacción (check-then-insert atómico)
    if settings.ai_usage_limit_enabled:
        period = current_billing_period()
        consumed = aggregate_monthly_usd(db, cliente_id, period)
        limit_usd = _monthly_limit_usd()
        if consumed >= limit_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": USAGE_LIMIT_EXCEEDED_CODE,
                    "message": USAGE_LIMIT_EXCEEDED_MESSAGE,
                },
            )
    row = UsageTokenORM(
        id=uuid4(),
        cliente_id=cliente_id,
        fecha=usage_date or billing_today(),
        modelo=modelo,
        provider=provider or _derive_provider_from_model(modelo),
        tokens_prompt=max(0, int(tokens_prompt)),
        tokens_completion=max(0, int(tokens_completion)),
        tokens_cached=max(0, int(tokens_cached)),
        costo_total=cost_usd,
        operation=operation,
        request_id=request_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def topup_ai_usage(
    db: Session,
    *,
    cliente_id: UUID,
    amount_usd_paid: Decimal,
) -> dict:
    """Registra recarga IA vía servicio técnico (D25).

    Margen: 25% Nordik, 75% usuario.
    - amount_usd_paid: lo que el usuario pagó en tienda (ej. $5.00).
    - credit_amount = amount_usd_paid * 0.75 (llega al usuario).
    - nordik_profit = amount_usd_paid * 0.25 (ganancia Nordik).

    Crea un registro negativo en usage_tokens que compensa el consumo del mes.
    """
    if amount_usd_paid <= Decimal("0"):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_amount", "message": "El monto de recarga debe ser mayor a 0."},
        )

    credit_amount = (amount_usd_paid * Decimal("0.75")).quantize(Decimal("0.01"))
    nordik_profit = (amount_usd_paid * Decimal("0.25")).quantize(Decimal("0.01"))

    row = UsageTokenORM(
        id=uuid4(),
        cliente_id=cliente_id,
        fecha=billing_today(),
        modelo="recarga",
        tokens_prompt=0,
        tokens_completion=0,
        tokens_cached=0,
        costo_total=-credit_amount,
        operation="recarga_ia",
        request_id=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    period = current_billing_period()
    summary = build_usage_summary(db, cliente_id, period=period)

    return {
        "topup_id": str(row.id),
        "amount_usd_paid": float(amount_usd_paid),
        "credit_added": float(credit_amount),
        "nordik_profit": float(nordik_profit),
        "new_balance": float(summary.remaining_usd),
        "consumed_percent": summary.consumed_percent,
        "blocked": summary.blocked,
    }


def assert_ai_usage_allowed(db: Session, cliente_id: UUID) -> None:
    if not settings.ai_usage_limit_enabled:
        return
    summary = build_usage_summary(db, cliente_id)
    if summary.blocked:
        raise HTTPException(
            status_code=402,
            detail={
                "code": USAGE_LIMIT_EXCEEDED_CODE,
                "message": USAGE_LIMIT_EXCEEDED_MESSAGE,
            },
        )
