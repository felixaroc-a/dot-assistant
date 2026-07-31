"""Esquemas de respuesta para consumo IA."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UsagePeriodResponse(BaseModel):
    start: str = Field(description="Inicio del mes de facturación (YYYY-MM-DD)")
    end: str = Field(description="Fin del mes de facturación (YYYY-MM-DD)")


class UsageBreakdownResponse(BaseModel):
    chat_usd: float = 0.0
    reasoning_usd: float = 0.0
    vision_usd: float = 0.0
    image_usd: float = 0.0


class UsageDailyItemResponse(BaseModel):
    date: str = Field(description="Fecha ISO (YYYY-MM-DD)")
    usd: float = Field(description="Costo en USD de ese día")


class UsageDailyResponse(BaseModel):
    days: list[UsageDailyItemResponse]


class UsageSummaryResponse(BaseModel):
    cliente_id: str
    period: UsagePeriodResponse
    limit_usd: float
    consumed_usd: float
    consumed_percent: int
    remaining_usd: float
    limit_enabled: bool
    blocked: bool
    breakdown: UsageBreakdownResponse | None = None
    projected_depletion_date: str | None = Field(
        None,
        description="Fecha estimada de agotamiento (DD/MM) o null si no se agota este mes",
    )
