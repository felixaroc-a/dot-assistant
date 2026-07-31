"""Tools avanzadas de Calendar — F6b."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.calendar_advanced")


def calendar_find_free_slot_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca el primer hueco libre en un rango de dias."""
    try:
        from app.services import calendar_service

        start_str = str(arguments.get("start_date") or arguments.get("from_date") or "").strip()
        end_str = str(arguments.get("end_date") or "").strip()
        duration_min = int(arguments.get("duration_minutes") or 60)
        start_hour = int(arguments.get("start_hour") or 8)
        end_hour = int(arguments.get("end_hour") or 18)

        if not start_str:
            start_dt = datetime.now()
        else:
            start_dt = datetime.fromisoformat(start_str[:10])

        if not end_str:
            end_dt = start_dt + timedelta(days=7)
        else:
            end_dt = datetime.fromisoformat(end_str[:10])

        slot = calendar_service.find_free_slot(
            uid, start_dt, end_dt, duration_min, start_hour, end_hour,
        )
        if slot:
            from app.services.time_parser import format_spanish_datetime

            when_human = format_spanish_datetime(slot)
            return ToolResult(
                ok=True,
                output=(
                    f"Hueco libre el {when_human} "
                    f"({duration_min} min, ISO: {slot.isoformat()})."
                ),
            )
        return ToolResult(ok=True, output=f"No hay huecos de {duration_min} min entre {start_hour}:00 y {end_hour}:00.")
    except Exception as e:
        log.warning("calendar_find_free_slot error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def calendar_delete_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        event_id = str(arguments.get("event_id") or arguments.get("id") or "").strip()
        if not event_id:
            return ToolResult(ok=False, output="", error="Falta event_id.")
        calendar_service.delete_event(uid, event_id)
        return ToolResult(ok=True, output="Evento eliminado.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_update_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        event_id = str(arguments.get("event_id") or arguments.get("id") or "").strip()
        if not event_id:
            return ToolResult(ok=False, output="", error="Falta event_id.")
        updates = {}
        for key in ("summary", "start", "end", "description", "location"):
            val = arguments.get(key)
            if val is not None and str(val).strip():
                updates[key] = str(val).strip()
        if not updates:
            return ToolResult(ok=False, output="", error="Sin campos para actualizar.")
        evt = calendar_service.update_event(uid, event_id, updates)
        return ToolResult(ok=True, output=f"Evento actualizado: {evt.get('summary','?')}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_get_busy_times_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        date_str = str(arguments.get("date") or "").strip()
        if not date_str:
            return ToolResult(ok=False, output="", error="Falta date (YYYY-MM-DD).")
        busy = calendar_service.get_busy_times(uid, date_str)
        if not busy:
            return ToolResult(ok=True, output=f"Todo libre el {date_str}.")
        lines = [f"Ocupado el {date_str}:"]
        for b in busy[:20]:
            lines.append(f"- {b.get('start','?')} -> {b.get('end','?')}: {b.get('summary','')}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_suggest_meeting_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        days = int(arguments.get("days") or 5)
        duration = int(arguments.get("duration_minutes") or 30)
        slots = calendar_service.suggest_meeting_times(uid, days, duration)
        if not slots:
            return ToolResult(ok=True, output="No se encontraron huecos disponibles.")
        lines = ["Horarios sugeridos:"]
        for s in slots[:5]:
            lines.append(f"- {s}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_recurring_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        summary = str(arguments.get("summary") or "Evento recurrente")
        start_str = str(arguments.get("start") or "").strip()
        freq = str(arguments.get("frequency") or "weekly").upper()
        count = int(arguments.get("occurrences") or 10)
        if not start_str:
            return ToolResult(ok=False, output="", error="Falta start (ISO 8601).")
        evt = calendar_service.create_recurring_event(
            uid, summary=summary, start_str=start_str, freq=freq, count=count,
        )
        return ToolResult(ok=True, output=f"Evento recurrente creado: {evt.get('summary')}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_share_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        event_id = str(arguments.get("event_id") or "").strip()
        email = str(arguments.get("email") or "").strip()
        if not event_id or not email:
            return ToolResult(ok=False, output="", error="Falta event_id y email.")
        calendar_service.share_event(uid, event_id, email)
        return ToolResult(ok=True, output=f"Evento compartido con {email}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_export_week_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        events = calendar_service.list_week(uid)
        if not events:
            return ToolResult(ok=True, output="Sin eventos esta semana.")
        lines = ["Agenda semanal:"]
        for e in events:
            lines.append(f"{e.get('start','?')} | {e.get('summary','')}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))

TOOLS = [("calendar_find_free_slot", calendar_find_free_slot_handler), ("calendar_delete_event", calendar_delete_event_handler), ("calendar_update_event", calendar_update_event_handler), ("calendar_get_busy_times", calendar_get_busy_times_handler), ("calendar_suggest_meeting", calendar_suggest_meeting_handler), ("calendar_recurring_event", calendar_recurring_event_handler), ("calendar_share_event", calendar_share_event_handler), ("calendar_export_week", calendar_export_week_handler)]
