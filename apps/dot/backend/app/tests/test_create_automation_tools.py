"""Tests de create_automation y helpers de schedule NL."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.application.agent.tools.automation_tools import create_automation_handler
from app.services.cron_service import CronScheduleType, CronService, set_active_cron_service
from app.services.time_parser import (
    extract_structured_schedule,
    format_structured_schedule_human,
    to_structured_schedule,
)


def test_extract_structured_schedule_weekly():
    assert extract_structured_schedule("cada lunes a las 9") == "weekly:mon:09:00"


def test_extract_structured_schedule_daily():
    assert extract_structured_schedule("todos los días a las 8") == "daily:08:00"


def test_to_structured_schedule_daily():
    assert to_structured_schedule(CronScheduleType.DAILY_AT, "09:00") == "daily:09:00"


def test_format_structured_schedule_human():
    human = format_structured_schedule_human("weekly:mon:09:00")
    assert "lunes" in human
    assert "09:00" in human


@patch("app.application.agent.tools.schedule_reminder.schedule_reminder_handler")
def test_create_automation_one_shot_delegates(mock_reminder):
    mock_reminder.return_value = MagicMock(ok=True, output="ok", error=None)
    result = create_automation_handler(
        "uid-test-123",
        {"request": "Recuérdame mañana a las 9 llamar a mamá"},
    )
    assert result.ok is True
    mock_reminder.assert_called_once()
    args = mock_reminder.call_args[0][1]
    assert args["channel"] in ("notify", "whatsapp")
    assert "llamar" in args["message"].lower() or "mamá" in args["message"].lower()


@patch("app.application.agent.tools.cron_tools.cron_schedule_routine_handler")
def test_create_automation_simple_recurring_delegates(mock_cron):
    mock_cron.return_value = MagicMock(
        ok=True,
        output="Listo, te aviso cada lunes a las 09:00: ir al gym",
        error=None,
    )
    result = create_automation_handler(
        "uid-test-123",
        {"request": "Cada lunes a las 9 recuérdame ir al gym"},
    )
    assert result.ok is True
    mock_cron.assert_called_once()


@patch("app.application.agent.tools.automation_tools._create_saved_automation")
def test_create_automation_scheduled_search(mock_saved):
    mock_saved.return_value = ("auto-abc123", {})
    result = create_automation_handler(
        "uid-test-123",
        {"request": "Cada lunes busca noticias de inteligencia artificial y avísame por WhatsApp"},
    )
    assert result.ok is True
    assert "Listo" in result.output
    assert "auto-abc123" in result.output
    mock_saved.assert_called_once()
    _, kwargs = mock_saved.call_args
    assert kwargs["schedule"] == "weekly:mon:09:00"
    assert kwargs["channel"] == "whatsapp"
    assert "third-option" == kwargs["integration_id"] or kwargs["integration_id"] == "third-option"


@patch("app.application.agent.tools.automation_tools._create_pipeline_automation")
def test_create_automation_multi_step_pipeline(mock_pipeline):
    mock_pipeline.return_value = MagicMock(
        ok=True,
        output="Listo, quedó programada tu automatización «Revisar Gmail».",
        error=None,
    )
    result = create_automation_handler(
        "uid-test-123",
        {
            "request": (
                "Cada lunes revisa mi Gmail, si hay PDFs guárdalos en el escritorio "
                "y avísame por WhatsApp"
            ),
        },
    )
    assert result.ok is True
    mock_pipeline.assert_called_once()


def test_create_automation_missing_schedule_for_complex():
    result = create_automation_handler(
        "uid-test-123",
        {"request": "Busca precio del dólar y avísame"},
    )
    assert result.ok is False
    assert "frecuencia" in (result.error or "").lower()


@patch("app.services.reminder_service.get_reminder_service")
def test_create_automation_one_shot_confirmation(mock_get_svc):
    mock_svc = MagicMock()
    mock_svc.is_enabled = True
    mock_svc.create_reminder.return_value = {
        "id": "rem-abc",
        "due_at": "2030-01-01T09:00:00+00:00",
    }
    mock_get_svc.return_value = mock_svc

    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    with patch("app.services.time_parser.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = create_automation_handler(
            "uid-test-123",
            {"request": "Recuérdame mañana a las 9 pagar la luz", "channel": "whatsapp"},
        )

    assert result.ok is True
    assert "Listo, te aviso" in result.output
    assert "WhatsApp" in result.output


def test_cron_schedule_routine_still_works():
    from app.application.agent.tools.cron_tools import cron_schedule_routine_handler

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
    set_active_cron_service(None)
