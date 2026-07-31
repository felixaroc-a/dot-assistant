"""Tests para parseo de schedules de automatizaciones."""
from __future__ import annotations

from app.services.automation_jobs import parse_schedule


def test_parse_schedule_daily_colon_format():
    trigger = parse_schedule("daily:09:00")
    assert trigger is not None
    assert "9" in str(trigger)


def test_parse_schedule_weekly_colon_format():
    trigger = parse_schedule("weekly:mon:09:00")
    assert trigger is not None
    assert "mon" in str(trigger).lower()


def test_parse_schedule_legacy_keys():
    assert parse_schedule("daily_09") is not None
    assert parse_schedule("manual") is None
