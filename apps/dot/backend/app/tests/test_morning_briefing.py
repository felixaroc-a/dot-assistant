"""Tests del briefing matutino proactivo."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.application.agent.ports import ToolResult
from app.services.morning_briefing_service import (
    BRIEFING_DISPLAY_NAME,
    MorningBriefingSettings,
    compose_briefing_headline,
    compose_briefing_message,
    local_hour_to_utc_schedule,
    maybe_run_on_boot,
    run_morning_briefing,
    sync_morning_briefing_cron,
)


def test_compose_briefing_with_mail_and_appointment():
    msg = compose_briefing_headline(
        unread_count=3,
        events=[{"start": "2026-07-24T09:00:00-04:00", "summary": "Reunión"}],
        google_connected=True,
    )
    assert "Buen día" in msg
    assert "3 correos" in msg
    assert "1 cita" in msg


def test_compose_briefing_full_includes_branding():
    msg = compose_briefing_message(
        unread_count=2,
        events=[{"start": "2026-07-24T10:00:00-04:00"}],
        google_connected=True,
        gmail_detail="2 sin leer: Propuesta, Factura",
        calendar_detail="- 10:00 | Standup",
    )
    assert BRIEFING_DISPLAY_NAME in msg
    assert "📬 Correo" in msg
    assert "📅 Agenda" in msg


def test_compose_briefing_without_google():
    msg = compose_briefing_headline(
        unread_count=None,
        events=None,
        google_connected=False,
    )
    assert "Integraciones" in msg


def test_compose_briefing_quiet_day():
    msg = compose_briefing_headline(
        unread_count=0,
        events=[],
        google_connected=True,
    )
    assert "tranquilo" in msg or "correo al día" in msg


def test_local_hour_to_utc_schedule_caracas():
    utc = local_hour_to_utc_schedule("08:00", "America/Caracas")
    assert utc == "12:00"


@patch("app.services.morning_briefing_service._mark_delivered_today")
@patch("app.services.morning_briefing_service._deliver_app_notification")
@patch("app.services.morning_briefing_service._already_delivered_today", return_value=False)
@patch("app.services.morning_briefing_service.load_settings")
@patch("app.services.morning_briefing_service.is_google_connected", return_value=True)
@patch("app.services.morning_briefing_service._fetch_gmail_via_tools", return_value=(2, "2 sin leer: A, B"))
@patch("app.services.morning_briefing_service._fetch_calendar_via_tools", return_value=([], "Sin citas hoy."))
def test_run_morning_briefing_delivers_app(
    mock_cal,
    mock_gmail,
    mock_google,
    mock_settings,
    mock_already,
    mock_notify,
    mock_mark,
):
    mock_settings.return_value = MorningBriefingSettings(
        enabled=True,
        notify_app=True,
        notify_whatsapp=False,
    )
    msg = run_morning_briefing("uid-test")
    assert BRIEFING_DISPLAY_NAME in msg
    assert "2 sin leer" in msg
    mock_notify.assert_called_once()
    mock_mark.assert_called_once()


@patch("app.services.morning_briefing_service.run_morning_briefing", return_value="☀️ Tu día en 30s")
@patch("app.services.morning_briefing_service._already_delivered_today", return_value=False)
@patch("app.services.morning_briefing_service.load_settings")
def test_maybe_run_on_boot_after_scheduled_hour(mock_settings, mock_already, mock_run):
    settings = MorningBriefingSettings(enabled=True, hour="06:00", timezone_name="America/Caracas")
    mock_settings.return_value = settings

    with patch("app.services.morning_briefing_service._local_now") as mock_now:
        mock_now.return_value = datetime(2026, 7, 24, 9, 0, tzinfo=ZoneInfo("America/Caracas"))
        result = maybe_run_on_boot("uid-test")

    assert result["ran"] is True
    mock_run.assert_called_once()


@patch("app.services.morning_briefing_service._already_delivered_today", return_value=False)
@patch("app.services.morning_briefing_service.load_settings")
def test_maybe_run_on_boot_before_scheduled_hour(mock_settings, mock_already):
    settings = MorningBriefingSettings(enabled=True, hour="10:00", timezone_name="America/Caracas")
    mock_settings.return_value = settings

    with patch("app.services.morning_briefing_service._local_now") as mock_now:
        mock_now.return_value = datetime(2026, 7, 24, 8, 0, tzinfo=ZoneInfo("America/Caracas"))
        result = maybe_run_on_boot("uid-test")

    assert result["ran"] is False
    assert result["reason"] == "before_scheduled_hour"


@patch("app.services.cron_service.get_cron_service")
def test_sync_morning_briefing_cron_adds_job(mock_get_cron):
    cron = MagicMock()
    cron.get_user_jobs.return_value = []
    mock_get_cron.return_value = cron
    sync_morning_briefing_cron(
        "uid-test",
        MorningBriefingSettings(enabled=True, hour="08:00"),
    )
    cron.add_cron_job.assert_called_once()
    _, kwargs = cron.add_cron_job.call_args
    assert kwargs["tool_name"] == "send_morning_briefing"
    assert kwargs["job_id"] == "morning-briefing-v1"


@patch("app.application.agent.tools.gmail_read.gmail_list_unread_handler")
def test_fetch_gmail_via_tools_parses_subjects(mock_handler):
    from app.services.morning_briefing_service import _fetch_gmail_via_tools

    mock_handler.return_value = ToolResult(
        ok=True,
        output=(
            "Correos no leídos (2):\n"
            "- Propuesta comercial | De: juan@test.com\n"
            "- Factura julio | De: maria@test.com"
        ),
    )
    count, detail = _fetch_gmail_via_tools("uid-test")
    assert count == 2
    assert "Propuesta comercial" in (detail or "")
