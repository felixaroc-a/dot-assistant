"""Tests de parseo de tiempo en español y tools de recordatorios."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.application.agent.tools.cron_tools import cron_schedule_routine_handler
from app.application.agent.tools.schedule_reminder import schedule_reminder_handler
from app.services.cron_service import CronScheduleType, CronService, set_active_cron_service
from app.services.time_parser import (
    format_recurring_confirmation,
    parse_recurring_schedule,
    parse_spanish_datetime,
    resolve_remind_at,
)


def test_parse_manana_a_las_9():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    dt = parse_spanish_datetime("mañana a las 9", now=now)
    assert dt is not None
    assert dt.day == 25
    assert dt.hour == 9
    assert dt.minute == 0


def test_parse_en_2_horas():
    now = datetime(2026, 7, 24, 10, 30, tzinfo=timezone.utc)
    dt = parse_spanish_datetime("en 2 horas", now=now)
    assert dt is not None
    assert dt.hour == 12
    assert dt.minute == 30


def test_parse_recurring_cada_lunes():
    parsed = parse_recurring_schedule("cada lunes a las 9")
    assert parsed is not None
    st, val = parsed
    assert st == CronScheduleType.WEEKLY_ON
    assert val == "mon@09:00"


def test_parse_recurring_todos_los_dias():
    parsed = parse_recurring_schedule("todos los días a las 8")
    assert parsed is not None
    st, val = parsed
    assert st == CronScheduleType.DAILY_AT
    assert val == "08:00"


def test_resolve_remind_at_when():
    now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
    with patch("app.services.time_parser.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        dt = resolve_remind_at({"when": "mañana a las 9"})
    assert dt is not None
    assert dt.day == 25


def test_format_recurring_confirmation():
    msg = format_recurring_confirmation(CronScheduleType.WEEKLY_ON, "mon@09:00", "revisar correo")
    assert "lunes" in msg
    assert "09:00" in msg
    assert msg.startswith("Listo")


@patch("app.services.reminder_service.get_reminder_service")
def test_schedule_reminder_firestore(mock_get_svc):
    mock_svc = MagicMock()
    mock_svc.is_enabled = True
    mock_svc.create_reminder.return_value = {"id": "rem-abc", "due_at": "2030-01-01T09:00:00+00:00"}
    mock_get_svc.return_value = mock_svc

    result = schedule_reminder_handler(
        "uid-test-123",
        {"message": "llamar a mamá", "when": "2030-01-01T09:00:00+00:00"},
    )
    assert result.ok is True
    assert "Listo, te aviso" in result.output
    mock_svc.create_reminder.assert_called_once()


def test_cron_schedule_routine():
    cron = CronService(enabled=False)
    cron.add_cron_job = MagicMock(
        return_value=MagicMock(job_id="job-12345678", name="Gym", next_run="2030-01-01T09:00:00+00:00")
    )
    set_active_cron_service(cron)

    result = cron_schedule_routine_handler(
        "uid-test-123",
        {"message": "ir al gym", "schedule": "cada lunes a las 9", "name": "Gym"},
    )
    assert result.ok is True
    assert "Listo" in result.output
    cron.add_cron_job.assert_called_once()
    _, kwargs = cron.add_cron_job.call_args
    assert kwargs["tool_name"] == "send_user_reminder"
    assert kwargs["schedule_type"] == CronScheduleType.WEEKLY_ON

    set_active_cron_service(None)
