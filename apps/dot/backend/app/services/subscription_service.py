"""Reglas de suscripción: vencimiento, gracia de 1 día y parseo de fechas.

D05 — MASTER-EXECUTION-PLAN: 1 día de gracia post-vencimiento.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def parse_fecha_vencimiento(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        y, m, d = value.strip().split("-", 3)
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def is_subscription_expired(fecha_vencimiento: date, *, today: date | None = None) -> bool:
    """True solo si venció hace más de 1 día (D05: gracia de 1 día).

    - El día de vencimiento: la app funciona normalmente.
    - El día siguiente (gracia): la app funciona con mensaje de aviso.
    - 2+ días después del vencimiento: bloqueo.
    """
    today = today or datetime.now(timezone.utc).date()
    return today > fecha_vencimiento + timedelta(days=1)


def is_in_grace_period(fecha_vencimiento: date, *, today: date | None = None) -> bool:
    """True si la suscripción venció ayer (hoy es el día de gracia)."""
    today = today or datetime.now(timezone.utc).date()
    return today == fecha_vencimiento + timedelta(days=1)
