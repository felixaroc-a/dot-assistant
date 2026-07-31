"""Tests de disparadores proactivos (P1 Loop-9)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.agent_heartbeat import run_agent_heartbeat
from app.services.proactive_triggers_service import (
    ProactiveTriggersSettings,
    ensure_default_onboarding,
    save_settings,
    user_calendar_triggers_enabled,
    user_composite_enabled,
    user_heartbeat_enabled,
    user_wa_triggers_enabled,
)


def test_proactive_settings_defaults_off():
    s = ProactiveTriggersSettings.from_dict(None)
    assert s.heartbeat_enabled is False
    assert s.wa_triggers_enabled is False
    assert s.calendar_triggers_enabled is False
    assert s.composite_enabled is False


@patch("app.services.proactive_triggers_service.get_user_profile")
def test_user_heartbeat_respects_profile(mock_profile):
    mock_profile.return_value = {
        "proactive_triggers": {"heartbeat_enabled": True},
    }
    assert user_heartbeat_enabled("uid-test") is True


@patch("app.services.proactive_triggers_service.get_user_profile")
def test_user_wa_triggers_default_off(mock_profile):
    mock_profile.return_value = {}
    assert user_wa_triggers_enabled("uid-test") is False


@patch("app.services.proactive_triggers_service.merge_user_profile")
@patch("app.services.proactive_triggers_service.get_user_profile")
def test_save_settings_persists(mock_get, mock_merge):
    mock_get.return_value = {}
    save_settings("uid-x", ProactiveTriggersSettings(heartbeat_enabled=True))
    mock_merge.assert_called_once()
    payload = mock_merge.call_args[0][1]
    assert payload["proactive_triggers"]["heartbeat_enabled"] is True


@patch("app.services.proactive_triggers_service.settings")
@patch("app.services.proactive_triggers_service.get_user_profile")
def test_global_calendar_flag_overrides(mock_profile, mock_settings):
    mock_settings.automations_calendar_triggers = True
    mock_profile.return_value = {}
    assert user_calendar_triggers_enabled("uid-test") is True


def test_agent_heartbeat_skips_execute_when_user_disabled():
    fake_doc = MagicMock()
    fake_doc.id = "uid12345678"
    fake_doc.to_dict.return_value = {
        "saved_automations": [
            {
                "id": "a1",
                "active": True,
                "schedule": "manual",
                "instruction": "Si confirman cita por WA, créala",
                "name": "Citas",
            }
        ],
        "proactive_triggers": {"heartbeat_enabled": False},
    }
    fake_db = MagicMock()
    fake_db.collection.return_value.limit.return_value.stream.return_value = [fake_doc]
    fake_db.collection.return_value.document.return_value.set = MagicMock()

    with patch("app.firebase_db.get_db", return_value=fake_db):
        with patch.dict("os.environ", {}, clear=True):
            result = run_agent_heartbeat(max_users=5)

    assert result["ok"] is True
    assert result["executed"] == 0


@patch("app.services.proactive_triggers_service.merge_user_profile")
@patch("app.services.proactive_triggers_service.get_user_profile")
@patch("app.services.proactive_triggers_service._whatsapp_linked", return_value=True)
def test_ensure_default_onboarding_sets_soft_defaults(mock_wa, mock_get, mock_merge):
    mock_get.return_value = {"integrations": ["google-calendar"]}
    ensure_default_onboarding("uid-new")
    mock_merge.assert_called_once()
    payload = mock_merge.call_args[0][1]["proactive_triggers"]
    assert payload["heartbeat_enabled"] is True
    assert payload["composite_enabled"] is True
    assert payload["wa_triggers_enabled"] is True
    assert payload["calendar_triggers_enabled"] is True


@patch("app.services.proactive_triggers_service.get_user_profile")
def test_user_composite_respects_profile(mock_profile):
    mock_profile.return_value = {
        "proactive_triggers": {"composite_enabled": True},
    }
    assert user_composite_enabled("uid-test") is True


@patch("app.services.proactive_triggers_service.settings")
@patch("app.services.proactive_triggers_service.get_user_profile")
def test_user_composite_global_flag_overrides(mock_profile, mock_settings):
    mock_settings.automations_composite_enabled = True
    mock_profile.return_value = {}
    assert user_composite_enabled("uid-test") is True
