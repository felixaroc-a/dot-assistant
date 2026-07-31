"""Briefing matutino proactivo — correos + citas sin consumo de IA."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.firebase_db import get_user_google_tokens_ciphertext, get_user_profile, merge_user_profile

log = logging.getLogger("dot.morning_briefing")

MORNING_BRIEFING_JOB_ID = "morning-briefing-v1"
MORNING_BRIEFING_TOOL = "send_morning_briefing"
BRIEFING_DISPLAY_NAME = "Tu día en 30s"
DEFAULT_LOCAL_TZ = "America/Caracas"
DEFAULT_HOUR = "08:00"
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_UNREAD_COUNT_RE = re.compile(r"Correos no leídos \((\d+)\)")


class MorningBriefingSettings:
    """Preferencias de briefing matutino del usuario."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        hour: str = DEFAULT_HOUR,
        timezone_name: str = DEFAULT_LOCAL_TZ,
        notify_app: bool = True,
        notify_whatsapp: bool = False,
    ):
        self.enabled = enabled
        self.hour = self.normalize_hour(hour)
        self.timezone_name = (timezone_name or DEFAULT_LOCAL_TZ).strip() or DEFAULT_LOCAL_TZ
        self.notify_app = notify_app
        self.notify_whatsapp = notify_whatsapp

    @staticmethod
    def normalize_hour(raw: str) -> str:
        text = (raw or DEFAULT_HOUR).strip()
        match = _HHMM_RE.match(text)
        if not match:
            return DEFAULT_HOUR
        hour = max(0, min(23, int(match.group(1))))
        minute = max(0, min(59, int(match.group(2))))
        return f"{hour:02d}:{minute:02d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hour": self.hour,
            "timezone": self.timezone_name,
            "notify_app": self.notify_app,
            "notify_whatsapp": self.notify_whatsapp,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MorningBriefingSettings:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", True)),
            hour=str(raw.get("hour") or DEFAULT_HOUR),
            timezone_name=str(raw.get("timezone") or DEFAULT_LOCAL_TZ),
            notify_app=bool(raw.get("notify_app", True)),
            notify_whatsapp=bool(raw.get("notify_whatsapp", False)),
        )


def load_settings(uid: str) -> MorningBriefingSettings:
    profile = get_user_profile(uid) or {}
    return MorningBriefingSettings.from_dict(profile.get("morning_briefing"))


def save_settings(uid: str, settings: MorningBriefingSettings) -> None:
    merge_user_profile(uid, {"morning_briefing": settings.to_dict()})


def is_google_connected(uid: str) -> bool:
    return bool(get_user_google_tokens_ciphertext(uid))


def _user_timezone(settings: MorningBriefingSettings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone_name)
    except Exception:
        return ZoneInfo(DEFAULT_LOCAL_TZ)


def _local_now(settings: MorningBriefingSettings) -> datetime:
    return datetime.now(_user_timezone(settings))


def _today_local_date(settings: MorningBriefingSettings) -> str:
    return _local_now(settings).strftime("%Y-%m-%d")


def _already_delivered_today(uid: str, settings: MorningBriefingSettings) -> bool:
    profile = get_user_profile(uid) or {}
    raw = profile.get("morning_briefing") or {}
    if not isinstance(raw, dict):
        return False
    return str(raw.get("last_delivered_date") or "") == _today_local_date(settings)


def _mark_delivered_today(uid: str, settings: MorningBriefingSettings) -> None:
    profile = get_user_profile(uid) or {}
    raw = dict(profile.get("morning_briefing") or {})
    raw.update(settings.to_dict())
    raw["last_delivered_date"] = _today_local_date(settings)
    merge_user_profile(uid, {"morning_briefing": raw})


def local_hour_to_utc_schedule(local_hhmm: str, timezone_name: str = DEFAULT_LOCAL_TZ) -> str:
    """Convierte HH:MM local a HH:MM UTC para APScheduler (timezone UTC)."""
    normalized = MorningBriefingSettings.normalize_hour(local_hhmm)
    hour_str, minute_str = normalized.split(":", 1)
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_LOCAL_TZ)
    local_dt = datetime.now(tz).replace(
        hour=int(hour_str),
        minute=int(minute_str),
        second=0,
        microsecond=0,
    )
    utc_dt = local_dt.astimezone(timezone.utc)
    return f"{utc_dt.hour:02d}:{utc_dt.minute:02d}"


def _today_events(uid: str) -> list[dict[str, Any]] | None:
    try:
        from app.services.calendar_service import MissingCalendarCredentialsError, list_today

        return list_today(uid)
    except MissingCalendarCredentialsError:
        return None
    except Exception as e:
        log.warning("No se pudo leer calendario uid=%s: %s", uid[:8], e)
        return None


def _fetch_gmail_via_tools(uid: str) -> tuple[int | None, str | None]:
    """Equivalente sin IA de gmail_summarize_unread: lista + resumen humano corto."""
    try:
        from app.application.agent.tools.gmail_read import gmail_list_unread_handler

        result = gmail_list_unread_handler(uid, {"max_results": 5})
        if not result.ok:
            return None, None

        output = result.output or ""
        match = _UNREAD_COUNT_RE.search(output)
        count = int(match.group(1)) if match else 0

        subjects: list[str] = []
        for line in output.splitlines():
            if not line.startswith("- ") or " | De:" not in line:
                continue
            subject = line.split(" | De:")[0][2:].strip()
            if subject and subject != "(sin asunto)":
                subjects.append(subject)

        if count == 0:
            return 0, "Bandeja al día — sin correos pendientes."
        if subjects:
            preview = ", ".join(subjects[:3])
            if len(subjects) > 3:
                preview += "…"
            return count, f"{count} sin leer: {preview}"
        return count, f"{count} correo{'s' if count != 1 else ''} sin leer."
    except Exception as e:
        log.warning("gmail_list_unread tool falló uid=%s: %s", uid[:8], e)
        return None, None


def _fetch_calendar_via_tools(uid: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Usa calendar_list_today del agente runtime."""
    try:
        from app.application.agent.tools.calendar import calendar_list_today_handler

        result = calendar_list_today_handler(uid, {})
        if not result.ok:
            return None, None

        output = result.output or ""
        events = _today_events(uid)
        detail_lines = [line for line in output.splitlines() if line.startswith("- ")][:5]
        if not detail_lines:
            return events or [], "Sin citas hoy."
        return events, "\n".join(detail_lines)
    except Exception as e:
        log.warning("calendar_list_today tool falló uid=%s: %s", uid[:8], e)
        return None, None


def _format_event_time(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        if "T" not in normalized and len(normalized) == 10:
            return "todo el día"
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%H:%M")
    except Exception:
        return None


def compose_briefing_headline(
    *,
    unread_count: int | None,
    events: list[dict[str, Any]] | None,
    google_connected: bool,
) -> str:
    """Una línea para toast y badge."""
    greeting = "Buen día"

    if not google_connected:
        return (
            f"{greeting}. Conecta Gmail y Calendar en Integraciones "
            "y cada mañana te preparo tu resumen aquí."
        )

    summary_bits: list[str] = []
    if unread_count is not None and unread_count > 0:
        summary_bits.append(f"{unread_count} correo{'s' if unread_count != 1 else ''}")
    elif unread_count == 0:
        summary_bits.append("correo al día")

    event_count = len(events) if events is not None else None
    if event_count is not None and event_count > 0:
        first_time = _format_event_time((events or [{}])[0].get("start"))
        if event_count == 1:
            if first_time and first_time != "todo el día":
                summary_bits.append(f"1 cita a las {first_time}")
            else:
                summary_bits.append("1 cita")
        elif first_time and first_time != "todo el día":
            summary_bits.append(f"{event_count} citas (primera a las {first_time})")
        else:
            summary_bits.append(f"{event_count} citas")

    if summary_bits:
        return f"{greeting} — {' · '.join(summary_bits)}."

    if unread_count is None and events is None:
        return f"{greeting}. Revisa Integraciones para ver correos y citas."

    return f"{greeting}. Hoy parece un día tranquilo."


def compose_briefing_message(
    *,
    unread_count: int | None,
    events: list[dict[str, Any]] | None,
    google_connected: bool,
    gmail_detail: str | None = None,
    calendar_detail: str | None = None,
) -> str:
    """Genera texto humano en español sin jerga técnica."""
    headline = compose_briefing_headline(
        unread_count=unread_count,
        events=events,
        google_connected=google_connected,
    )
    lines = [f"☀️ {BRIEFING_DISPLAY_NAME}", "", headline]

    if gmail_detail:
        lines.extend(["", "📬 Correo", gmail_detail])
    if calendar_detail:
        lines.extend(["", "📅 Agenda", calendar_detail])

    return "\n".join(lines)


def _deliver_app_notification(uid: str, message: str) -> None:
    preview = message.replace("\r", " ").replace("\n", " ").strip()[:1200]
    merge_user_profile(
        uid,
        {
            "pending_automation_results": {
                "has_new": True,
                "last_auto_id": MORNING_BRIEFING_JOB_ID,
                "last_auto_name": BRIEFING_DISPLAY_NAME,
                "last_executed_at": datetime.now(timezone.utc).isoformat(),
                "last_result_preview": preview,
            }
        },
    )


def _deliver_whatsapp(uid: str, message: str) -> bool:
    """Envía al dueño vinculado (política DOT: solo outbound al número del usuario)."""
    try:
        from app.application.agent.tools.whatsapp_tools import notify_whatsapp_owner_handler

        result = notify_whatsapp_owner_handler(uid, {"message": message})
        if not result.ok:
            log.info("WhatsApp briefing omitido uid=%s: %s", uid[:8], result.error)
            return False
        return True
    except Exception as e:
        log.warning("WhatsApp briefing falló uid=%s: %s", uid[:8], e)
        return False


def run_morning_briefing(uid: str, tool_args: dict[str, Any] | None = None) -> str:
    """Ejecuta el briefing y entrega por los canales configurados."""
    _ = tool_args
    settings = load_settings(uid)
    if not settings.enabled:
        log.info("Briefing matutino desactivado uid=%s", uid[:8])
        return ""

    if _already_delivered_today(uid, settings):
        log.info("Briefing matutino ya entregado hoy uid=%s", uid[:8])
        return ""

    google_connected = is_google_connected(uid)
    unread, gmail_detail = (None, None)
    events, calendar_detail = (None, None)
    if google_connected:
        unread, gmail_detail = _fetch_gmail_via_tools(uid)
        events, calendar_detail = _fetch_calendar_via_tools(uid)

    message = compose_briefing_message(
        unread_count=unread,
        events=events,
        google_connected=google_connected,
        gmail_detail=gmail_detail,
        calendar_detail=calendar_detail,
    )

    if settings.notify_app:
        _deliver_app_notification(uid, message)
    if settings.notify_whatsapp:
        _deliver_whatsapp(uid, message)

    _mark_delivered_today(uid, settings)
    log.info("Briefing matutino entregado uid=%s", uid[:8])
    return message


def maybe_run_on_boot(uid: str) -> dict[str, Any]:
    """Dispara el briefing al abrir DOT si ya pasó la hora y aún no se entregó hoy."""
    settings = load_settings(uid)
    if not settings.enabled:
        return {"ran": False, "reason": "disabled"}

    if _already_delivered_today(uid, settings):
        return {"ran": False, "reason": "already_delivered"}

    now = _local_now(settings)
    hour_str, minute_str = settings.hour.split(":", 1)
    scheduled = now.replace(
        hour=int(hour_str),
        minute=int(minute_str),
        second=0,
        microsecond=0,
    )
    if now < scheduled:
        return {"ran": False, "reason": "before_scheduled_hour"}

    message = run_morning_briefing(uid, {"source": "boot"})
    if not message:
        return {"ran": False, "reason": "skipped"}
    return {"ran": True, "preview": message.split("\n", 1)[0][:200]}


def sync_morning_briefing_cron(uid: str, settings: MorningBriefingSettings | None = None) -> None:
    """Crea, actualiza o elimina el job cron del briefing matutino."""
    from app.services.cron_service import CronScheduleType, get_cron_service

    cfg = settings or load_settings(uid)
    cron = get_cron_service()
    if cron is None:
        log.warning("CronService no disponible — briefing no sincronizado uid=%s", uid[:8])
        return

    existing = cron.get_user_jobs(uid)
    for job in existing:
        if job.get("job_id") == MORNING_BRIEFING_JOB_ID or job.get("tool_name") == MORNING_BRIEFING_TOOL:
            cron.remove_cron_job(uid, str(job.get("job_id")))

    if not cfg.enabled:
        log.info("Briefing matutino desactivado — job cron eliminado uid=%s", uid[:8])
        return

    utc_schedule = local_hour_to_utc_schedule(cfg.hour, cfg.timezone_name)
    cron.add_cron_job(
        uid=uid,
        name=BRIEFING_DISPLAY_NAME,
        schedule_type=CronScheduleType.DAILY_AT,
        schedule_value=utc_schedule,
        tool_name=MORNING_BRIEFING_TOOL,
        tool_args={},
        job_id=MORNING_BRIEFING_JOB_ID,
    )
    log.info(
        "Briefing matutino programado uid=%s local=%s utc=%s",
        uid[:8],
        cfg.hour,
        utc_schedule,
    )


def ensure_default_onboarding(uid: str) -> None:
    """Activa briefing matutino por defecto tras onboarding (sin IA)."""
    settings = MorningBriefingSettings(
        enabled=True,
        hour=DEFAULT_HOUR,
        notify_app=True,
        notify_whatsapp=bool((get_user_profile(uid) or {}).get("phone_number")),
    )
    save_settings(uid, settings)
    sync_morning_briefing_cron(uid, settings)
