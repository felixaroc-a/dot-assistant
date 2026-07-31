"""Preferencias de disparadores proactivos por usuario (P1 Loop-9/10).

Los flags globales (AUTOMATIONS_* / DOT_AGENT_HEARTBEAT_EXECUTE) siguen siendo
kill-switch opcionales; el usuario activa cada canal desde Configuración.
Tras onboarding se activan defaults suaves (heartbeat + composite; WA si vinculado).
"""
from __future__ import annotations

import logging
from typing import Any

from app.firebase_db import get_user_profile, merge_user_profile
from app.settings import settings

log = logging.getLogger("dot.proactive_triggers")


class ProactiveTriggersSettings:
    """Preferencias de automatizaciones «avísame cuando…»."""

    def __init__(
        self,
        *,
        heartbeat_enabled: bool = False,
        wa_triggers_enabled: bool = False,
        calendar_triggers_enabled: bool = False,
        composite_enabled: bool = False,
    ):
        self.heartbeat_enabled = heartbeat_enabled
        self.wa_triggers_enabled = wa_triggers_enabled
        self.calendar_triggers_enabled = calendar_triggers_enabled
        self.composite_enabled = composite_enabled

    def to_dict(self) -> dict[str, bool]:
        return {
            "heartbeat_enabled": self.heartbeat_enabled,
            "wa_triggers_enabled": self.wa_triggers_enabled,
            "calendar_triggers_enabled": self.calendar_triggers_enabled,
            "composite_enabled": self.composite_enabled,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ProactiveTriggersSettings:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            heartbeat_enabled=bool(raw.get("heartbeat_enabled", False)),
            wa_triggers_enabled=bool(raw.get("wa_triggers_enabled", False)),
            calendar_triggers_enabled=bool(raw.get("calendar_triggers_enabled", False)),
            composite_enabled=bool(raw.get("composite_enabled", False)),
        )


def load_settings(uid: str) -> ProactiveTriggersSettings:
    profile = get_user_profile(uid) or {}
    return ProactiveTriggersSettings.from_dict(profile.get("proactive_triggers"))


def save_settings(uid: str, proactive: ProactiveTriggersSettings) -> None:
    merge_user_profile(uid, {"proactive_triggers": proactive.to_dict()})


def _global_wa_allowed() -> bool:
    return bool(settings.automations_wa_triggers)


def _global_calendar_allowed() -> bool:
    return bool(settings.automations_calendar_triggers)


def user_heartbeat_enabled(uid: str) -> bool:
    """Vigilancia periódica de mandatos manuales."""
    import os

    if os.environ.get("DOT_PROACTIVE_DISABLED", "").strip() == "1":
        return False
    if os.environ.get("DOT_AGENT_HEARTBEAT_EXECUTE", "").strip() == "1":
        return True
    return load_settings(uid).heartbeat_enabled


def user_wa_triggers_enabled(uid: str) -> bool:
    """Evaluar mandatos / keywords ante WhatsApp entrante."""
    if _global_wa_allowed():
        return True
    return load_settings(uid).wa_triggers_enabled


def user_calendar_triggers_enabled(uid: str) -> bool:
    """Evaluar mandatos ante eventos de calendario."""
    if _global_calendar_allowed():
        return True
    return load_settings(uid).calendar_triggers_enabled


def user_composite_enabled(uid: str) -> bool:
    """Ejecutar pipelines multi-paso (AUTOMATIONS_COMPOSITE) por usuario."""
    import os

    if os.environ.get("DOT_PROACTIVE_DISABLED", "").strip() == "1":
        return False
    if bool(settings.automations_composite_enabled):
        return True
    return load_settings(uid).composite_enabled


def _whatsapp_linked(uid: str) -> bool:
    profile = get_user_profile(uid) or {}
    if profile.get("phone_number"):
        return True
    try:
        from app.services.whatsapp_link import get_channel_state

        return bool(get_channel_state(uid).linked)
    except Exception:
        return False


def ensure_default_onboarding(uid: str) -> None:
    """Activa defaults suaves tras onboarding (sin flags globales).

    - Heartbeat + composite: ON (con cooldown anti-spam en runtime).
    - WhatsApp: ON solo si el canal está vinculado.
    - Calendario: ON si el usuario conectó Google Calendar en onboarding.
    """
    profile = get_user_profile(uid) or {}
    if isinstance(profile.get("proactive_triggers"), dict):
        return

    integrations = profile.get("integrations") or []
    has_calendar = isinstance(integrations, list) and "google-calendar" in integrations
    wa_linked = _whatsapp_linked(uid)

    defaults = ProactiveTriggersSettings(
        heartbeat_enabled=True,
        wa_triggers_enabled=wa_linked,
        calendar_triggers_enabled=has_calendar,
        composite_enabled=True,
    )
    save_settings(uid, defaults)
    log.info(
        "Proactive defaults onboarding uid=%s heartbeat=on composite=on wa=%s cal=%s",
        uid[:8],
        wa_linked,
        has_calendar,
    )


def list_manual_mandates(profile: dict[str, Any]) -> list[dict[str, Any]]:
    autos = profile.get("saved_automations") or []
    if not isinstance(autos, list):
        return []
    return [
        a
        for a in autos
        if isinstance(a, dict) and a.get("active") and a.get("schedule") == "manual"
    ]
