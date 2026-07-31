"""Suscripción: vencimiento, gracia de 1 día (D05) y parseo de fechas."""
from __future__ import annotations

from datetime import date, timedelta


from app.services.subscription_service import (
    is_in_grace_period,
    is_subscription_expired,
    parse_fecha_vencimiento,
)


def test_parse_fecha_vencimiento_ok():
    assert parse_fecha_vencimiento("2026-12-31") == date(2026, 12, 31)


def test_parse_fecha_vencimiento_invalid():
    assert parse_fecha_vencimiento("bad") is None


def test_subscription_expired_after_grace():
    """D05: vencimiento + 1 día de gracia = expira 2 días después."""
    two_days_ago = date.today() - timedelta(days=2)
    assert is_subscription_expired(two_days_ago) is True


def test_subscription_active_today():
    today = date.today()
    assert is_subscription_expired(today) is False


def test_subscription_grace_day_not_expired():
    """D05: el día después del vencimiento aún no está expirado (gracia)."""
    yesterday = date.today() - timedelta(days=1)
    assert is_subscription_expired(yesterday, today=date.today()) is False
    assert is_in_grace_period(yesterday, today=date.today()) is True


def test_subscription_active_on_expiry_date_end_of_utc_day():
    """El día de vencimiento sigue activo."""
    expiry = date(2026, 6, 15)
    ref = date(2026, 6, 15)
    assert is_subscription_expired(expiry, today=ref) is False


def test_subscription_grace_day_after_expiry():
    """D05: el día después del vencimiento es gracia, no expirado."""
    expiry = date(2026, 6, 15)
    ref = date(2026, 6, 16)  # día de gracia
    assert is_subscription_expired(expiry, today=ref) is False
    assert is_in_grace_period(expiry, today=ref) is True


def test_subscription_expired_two_days_after():
    """D05: 2 días después del vencimiento ya está expirado."""
    expiry = date(2026, 6, 15)
    ref = date(2026, 6, 17)
    assert is_subscription_expired(expiry, today=ref) is True
    assert is_in_grace_period(expiry, today=ref) is False


def test_subscription_expired_uses_strict_calendar_gt_not_gte():
    """D05: alineado con frontend. Vence 2 días después de fecha_vencimiento."""
    expiry = date(2026, 12, 31)
    # Día de vencimiento: activo
    assert is_subscription_expired(expiry, today=date(2026, 12, 31)) is False
    # Día de gracia: activo
    assert is_subscription_expired(expiry, today=date(2027, 1, 1)) is False
    assert is_in_grace_period(expiry, today=date(2027, 1, 1)) is True
    # 2 días después: expirado
    assert is_subscription_expired(expiry, today=date(2027, 1, 2)) is True


def test_is_in_grace_period_false_when_active():
    """is_in_grace_period es False cuando la suscripción está activa."""
    expiry = date(2026, 12, 31)
    assert is_in_grace_period(expiry, today=date(2026, 12, 30)) is False
    assert is_in_grace_period(expiry, today=date(2026, 12, 31)) is False
    assert is_in_grace_period(expiry, today=date(2027, 1, 2)) is False
