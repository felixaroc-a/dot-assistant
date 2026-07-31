"""Integración Google Calendar para flujos de WhatsApp y automatizaciones."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app import crypto_tokens
from app.firebase_db import get_user_google_tokens_ciphertext

log = logging.getLogger("dot.calendar_service")


class CalendarIntegrationError(RuntimeError):
    """Error base de integración de Calendar."""


class MissingCalendarCredentialsError(CalendarIntegrationError):
    """El usuario no tiene OAuth Google vinculado."""


def _format_event_time(raw: str | None) -> str:
    if not raw:
        return "sin hora"
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%H:%M")
    except Exception:
        log.debug("Error parseando hora de evento calendar: %s", raw, exc_info=True)
        return raw


def render_today_agenda(events: list[dict[str, Any]]) -> str:
    if not events:
        return "Hoy no tienes eventos en Google Calendar."
    lines: list[str] = []
    for idx, event in enumerate(events, start=1):
        start = _format_event_time(event.get("start"))
        end = _format_event_time(event.get("end"))
        summary = str(event.get("summary") or "(sin título)")
        lines.append(f"{idx}. {summary} ({start} - {end})")
    return "\n".join(lines)


def _load_google_credentials(user_id: str) -> Credentials:
    ciphertext = get_user_google_tokens_ciphertext(user_id)
    if not ciphertext:
        raise MissingCalendarCredentialsError(
            "Google Calendar no está vinculado para este usuario."
        )

    token_data = crypto_tokens.decrypt_token_blob(ciphertext)
    token = token_data.get("token")
    refresh_token = token_data.get("refresh_token")
    token_uri = token_data.get("token_uri")
    client_id = token_data.get("client_id")
    client_secret = token_data.get("client_secret")
    scopes = token_data.get("scopes")

    if not all([token, refresh_token, token_uri, client_id, client_secret]):
        raise CalendarIntegrationError(
            "El token OAuth de Google está incompleto para este usuario."
        )

    return Credentials(
        token=str(token),
        refresh_token=str(refresh_token),
        token_uri=str(token_uri),
        client_id=str(client_id),
        client_secret=str(client_secret),
        scopes=[str(s) for s in scopes] if isinstance(scopes, list) else None,
    )


def _build_event_summary(message_text: str) -> str:
    text = " ".join(message_text.strip().split())
    if not text:
        return "Cita agendada desde WhatsApp"
    trimmed = text[:90]
    return f"Cita WhatsApp: {trimmed}"


def _calendar_service(user_id: str):
    creds = _load_google_credentials(user_id)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(
    user_id: str,
    summary: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    description: str | None = None,
    timezone_name: str = "America/Caracas",
) -> dict[str, Any]:
    service = _calendar_service(user_id)
    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_name},
    }
    event = (
        service.events()  # type: ignore[no-untyped-call]
        .insert(calendarId="primary", body=body)
        .execute()
    )
    return {
        "id": event.get("id"),
        "summary": event.get("summary") or summary,
        "html_link": event.get("htmlLink"),
        "start": body["start"]["dateTime"],
        "end": body["end"]["dateTime"],
    }


def list_events(
    user_id: str,
    *,
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    service = _calendar_service(user_id)
    response = (
        service.events()  # type: ignore[no-untyped-call]
        .list(
            calendarId="primary",
            timeMin=time_min.isoformat() + "Z",
            timeMax=time_max.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )
    items = response.get("items") or []
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary") or "(sin título)",
            "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
            "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
            "html_link": item.get("htmlLink"),
        }
        for item in items
    ]


def list_today(user_id: str) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return list_events(user_id, time_min=start, time_max=end)


def get_upcoming_events(user_id: str, lookahead_hours: int = 12) -> list[dict[str, Any]]:
    """Eventos desde ahora hasta lookahead_hours (para recordatorios cron)."""
    now = datetime.utcnow()
    end = now + timedelta(hours=max(1, lookahead_hours))
    return list_events(user_id, time_min=now, time_max=end)


def list_week(user_id: str) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return list_events(user_id, time_min=start, time_max=end)


def check_conflicts(user_id: str, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
    service = _calendar_service(user_id)
    body = {
        "timeMin": start_dt.isoformat() + "Z",
        "timeMax": end_dt.isoformat() + "Z",
        "items": [{"id": "primary"}],
    }
    result = service.freebusy().query(body=body).execute()  # type: ignore[no-untyped-call]
    calendars = result.get("calendars", {})
    primary = calendars.get("primary", {})
    busy = primary.get("busy", []) or []
    return [{"start": slot.get("start"), "end": slot.get("end")} for slot in busy]


def create_event_from_whatsapp(
    user_id: str,
    message_text: str,
    date_str: str,
    time_str: str,
    *,
    duration_minutes: int = 30,
    timezone_name: str = "America/Caracas",
) -> dict[str, Any]:
    """Crea evento de Calendar a partir de texto y fecha/hora detectada."""
    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise CalendarIntegrationError("No se pudo interpretar fecha/hora de la cita.") from exc

    end_dt = start_dt + timedelta(minutes=max(15, duration_minutes))
    event = create_event(
        user_id=user_id,
        summary=_build_event_summary(message_text),
        start_dt=start_dt,
        end_dt=end_dt,
        description=f"Generado desde WhatsApp.\n\nMensaje original:\n{message_text}",
        timezone_name=timezone_name,
    )
    log.info(
        "Evento Calendar creado para uid=%s id=%s start=%s",
        user_id,
        event.get("id"),
        event.get("start"),
    )
    return event


def find_free_slot(
    user_id: str,
    start_dt: datetime,
    end_dt: datetime,
    duration_min: int = 60,
    start_hour: int = 8,
    end_hour: int = 18,
) -> datetime | None:
    """Primer hueco libre de ``duration_min`` min entre ``start_hour`` y ``end_hour``."""
    duration = timedelta(minutes=max(15, min(duration_min, 480)))
    cursor = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if cursor < start_dt:
        cursor = start_dt.replace(second=0, microsecond=0)

    while cursor.date() <= end_dt.date():
        day_start = cursor.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        day_end = cursor.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        slot = day_start if day_start >= cursor else cursor
        while slot + duration <= day_end:
            busy = check_conflicts(user_id, slot, slot + duration)
            if not busy:
                return slot
            slot += timedelta(minutes=15)
        cursor = (cursor + timedelta(days=1)).replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
    return None


def get_busy_times(user_id: str, date_str: str) -> list[dict[str, Any]]:
    """Horarios ocupados de un día (YYYY-MM-DD)."""
    day = datetime.strptime(date_str[:10], "%Y-%m-%d")
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    events = list_events(user_id, time_min=start, time_max=end)
    return [
        {
            "start": _format_event_time(str(e.get("start") or "")),
            "end": _format_event_time(str(e.get("end") or "")),
            "summary": e.get("summary") or "",
        }
        for e in events
    ]


def suggest_meeting_times(
    user_id: str,
    days: int = 5,
    duration_min: int = 30,
) -> list[str]:
    """Sugerencias legibles de huecos libres en los próximos ``days`` días."""
    start = datetime.utcnow()
    end = start + timedelta(days=max(1, min(days, 14)))
    slots: list[str] = []
    cursor = start
    while len(slots) < 5 and cursor.date() <= end.date():
        slot = find_free_slot(user_id, cursor, end, duration_min)
        if slot is None:
            break
        slots.append(slot.strftime("%A %d/%m %H:%M"))
        cursor = slot + timedelta(minutes=max(15, duration_min))
    return slots


def delete_event(user_id: str, event_id: str) -> None:
    service = _calendar_service(user_id)
    service.events().delete(calendarId="primary", eventId=event_id).execute()  # type: ignore[no-untyped-call]


def update_event(user_id: str, event_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    service = _calendar_service(user_id)
    body: dict[str, Any] = {}
    if "summary" in updates:
        body["summary"] = updates["summary"]
    if "description" in updates:
        body["description"] = updates["description"]
    if "location" in updates:
        body["location"] = updates["location"]
    if "start" in updates:
        body["start"] = {"dateTime": updates["start"], "timeZone": "America/Caracas"}
    if "end" in updates:
        body["end"] = {"dateTime": updates["end"], "timeZone": "America/Caracas"}
    event = (
        service.events()  # type: ignore[no-untyped-call]
        .patch(calendarId="primary", eventId=event_id, body=body)
        .execute()
    )
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start", {}).get("dateTime"),
        "end": event.get("end", {}).get("dateTime"),
    }


def create_recurring_event(
    user_id: str,
    *,
    summary: str,
    start_str: str,
    freq: str = "WEEKLY",
    count: int = 10,
) -> dict[str, Any]:
    service = _calendar_service(user_id)
    body = {
        "summary": summary,
        "start": {"dateTime": start_str, "timeZone": "America/Caracas"},
        "end": {
            "dateTime": (
                datetime.fromisoformat(start_str) + timedelta(minutes=60)
            ).isoformat(),
            "timeZone": "America/Caracas",
        },
        "recurrence": [f"RRULE:FREQ={freq};COUNT={max(1, min(count, 52))}"],
    }
    event = service.events().insert(calendarId="primary", body=body).execute()  # type: ignore[no-untyped-call]
    return {"id": event.get("id"), "summary": event.get("summary") or summary}


def share_event(user_id: str, event_id: str, email: str) -> None:
    service = _calendar_service(user_id)
    event = service.events().get(calendarId="primary", eventId=event_id).execute()  # type: ignore[no-untyped-call]
    attendees = list(event.get("attendees") or [])
    attendees.append({"email": email})
    service.events().patch(  # type: ignore[no-untyped-call]
        calendarId="primary",
        eventId=event_id,
        body={"attendees": attendees},
        sendUpdates="all",
    ).execute()
