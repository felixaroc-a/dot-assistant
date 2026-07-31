"""Calculadora de costos multi-proveedor para IA de DOT.

Tarifas por proveedor + modelo (USD por 1M tokens).
Usada por usage_service.py para tracking preciso de costos por proveedor.

Las tarifas se mantienen sincronizadas con model_registry.py.
Fuente de verdad: precios oficiales de cada proveedor (Jul 2026).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger("dot.cost_calculator")

MILLION = Decimal("1000000")


# ── Tarifas por proveedor + modelo ────────────────────────────────────────

@dataclass(frozen=True)
class ModelTariff:
    provider: str
    model: str
    input_per_1m: Decimal  # USD por 1M tokens de entrada
    output_per_1m: Decimal  # USD por 1M tokens de salida


_TARIFFS: dict[str, ModelTariff] = {
    # ── DeepSeek ─────────────────────────────
    "deepseek-chat": ModelTariff(
        provider="deepseek",
        model="deepseek-chat",
        input_per_1m=Decimal("0.14"),
        output_per_1m=Decimal("0.28"),
    ),
    "deepseek-reasoner": ModelTariff(
        provider="deepseek",
        model="deepseek-reasoner",
        input_per_1m=Decimal("0.55"),
        output_per_1m=Decimal("2.19"),
    ),

    # ── OpenAI ───────────────────────────────
    "gpt-4o-mini": ModelTariff(
        provider="openai",
        model="gpt-4o-mini",
        input_per_1m=Decimal("0.15"),
        output_per_1m=Decimal("0.60"),
    ),
    "gpt-4o": ModelTariff(
        provider="openai",
        model="gpt-4o",
        input_per_1m=Decimal("2.50"),
        output_per_1m=Decimal("10.00"),
    ),

    # ── Anthropic ─────────────────────────────
    "claude-3-haiku-20240307": ModelTariff(
        provider="anthropic",
        model="claude-3-haiku-20240307",
        input_per_1m=Decimal("0.25"),
        output_per_1m=Decimal("1.25"),
    ),
    "claude-3-5-sonnet-20241022": ModelTariff(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        input_per_1m=Decimal("3.00"),
        output_per_1m=Decimal("15.00"),
    ),

    # ── Groq (FREE tier) ─────────────────────
    "llama-3.3-70b-versatile": ModelTariff(
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_per_1m=Decimal("0"),
        output_per_1m=Decimal("0"),
    ),
    "mixtral-8x7b-32768": ModelTariff(
        provider="groq",
        model="mixtral-8x7b-32768",
        input_per_1m=Decimal("0"),
        output_per_1m=Decimal("0"),
    ),

    # ── Google Gemini ─────────────────────────
    "gemini-2.5-flash": ModelTariff(
        provider="gemini",
        model="gemini-2.5-flash",
        input_per_1m=Decimal("0.15"),
        output_per_1m=Decimal("0.60"),
    ),
    "gemini-2.5-pro": ModelTariff(
        provider="gemini",
        model="gemini-2.5-pro",
        input_per_1m=Decimal("1.25"),
        output_per_1m=Decimal("5.00"),
    ),
}


def get_tariff(model_id: str) -> ModelTariff | None:
    """Obtiene la tarifa para un modelo específico."""
    return _TARIFFS.get(model_id)


def calculate_cost(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> Decimal:
    """Calcula el costo en USD para un uso específico de tokens.

    Args:
        provider: nombre del proveedor (deepseek, openai, gemini, etc.)
        model: ID del modelo (deepseek-chat, gemini-2.5-flash, etc.)
        tokens_in: tokens de entrada/prompt
        tokens_out: tokens de salida/completion

    Returns:
        Costo en USD como Decimal con 6 decimales.
    """
    tariff = _TARIFFS.get(model)
    if tariff is None:
        log.warning(
            "cost_calculator: tarifa no registrada para %s, usando DeepSeek chat como fallback",
            model,
        )
        tariff = _TARIFFS["deepseek-chat"]

    tokens_in_dec = Decimal(str(max(0, int(tokens_in))))
    tokens_out_dec = Decimal(str(max(0, int(tokens_out))))

    cost = (
        tokens_in_dec * tariff.input_per_1m / MILLION
        + tokens_out_dec * tariff.output_per_1m / MILLION
    )

    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass
class ProviderBreakdown:
    """Desglose de costos por proveedor."""
    provider: str
    total_usd: Decimal = Decimal("0")
    tokens_in: int = 0
    tokens_out: int = 0
    models: dict[str, Decimal] = field(default_factory=dict)


def get_cost_breakdown(
    db,
    uid: str,
    period=None,
) -> dict[str, ProviderBreakdown]:
    """Calcula el desglose de costos por proveedor para un usuario en un período.

    Args:
        db: sesión de base de datos (SQLAlchemy)
        uid: UID del usuario (string)
        period: BillingPeriod opcional (usa mes actual si None)

    Returns:
        Dict con clave=provider_name y valor=ProviderBreakdown.
    """
    from app.billing_models import UsageTokenORM
    from app.services.usage_service import current_billing_period
    from sqlalchemy import func, select

    period = period or current_billing_period()

    # Agrupar por modelo y sumar tokens + costo
    rows = db.execute(
        select(
            UsageTokenORM.modelo,
            func.coalesce(func.sum(UsageTokenORM.tokens_prompt), 0),
            func.coalesce(func.sum(UsageTokenORM.tokens_completion), 0),
            func.coalesce(func.sum(UsageTokenORM.costo_total), 0),
        ).where(
            UsageTokenORM.cliente_id == uid,
            UsageTokenORM.fecha >= period.start,
            UsageTokenORM.fecha <= period.end,
            UsageTokenORM.operation.in_(["chat", "reasoning"]),
        ).group_by(UsageTokenORM.modelo)
    ).all()

    breakdown: dict[str, ProviderBreakdown] = {}

    for model_name, prompt_tokens, completion_tokens, total_cost in rows:
        model_str = str(model_name or "unknown")
        tariff = _TARIFFS.get(model_str)
        provider = tariff.provider if tariff else "unknown"

        if provider not in breakdown:
            breakdown[provider] = ProviderBreakdown(provider=provider)

        cost = Decimal(str(total_cost or 0))
        breakdown[provider].total_usd += cost
        breakdown[provider].tokens_in += int(prompt_tokens or 0)
        breakdown[provider].tokens_out += int(completion_tokens or 0)
        breakdown[provider].models[model_str] = cost

    return breakdown


def get_provider_cost_summary(
    db,
    uid: str,
    period=None,
) -> list[dict]:
    """Resumen de costos por proveedor para mostrar en UI.

    Returns:
        Lista de dicts con provider, total_usd, model_count, tokens_total.
    """
    breakdown = get_cost_breakdown(db, uid, period)
    return [
        {
            "provider": p.provider,
            "total_usd": float(p.total_usd),
            "tokens_in": p.tokens_in,
            "tokens_out": p.tokens_out,
            "models": {m: float(c) for m, c in p.models.items()},
        }
        for p in sorted(breakdown.values(), key=lambda x: float(x.total_usd), reverse=True)
    ]
