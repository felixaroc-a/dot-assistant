"""Tools de Google Calendar para el Agent Runtime.

calendar_list_today, calendar_list_week, calendar_create_event, calendar_check_conflicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.calendar")


def _build_event_lines(events: list[dict], max_items: int = 20) -> str:
    if not events:
        return "No hay eventos."
    lines = []
    for e in events[:max_items]:
        summary = e.get("summary", "(sin título)")
        start = e.get("start", "?")
        end = e.get("end", "")
        location = e.get("location", "")
        desc = e.get("description", "")
        line = f"- {start}"
        if end and end != start:
            line += f" → {end}"
        line += f" | {summary}"
        if location:
            line += f" | 📍 {location}"
        if desc and len(desc) < 200:
            line += f" | {desc[:120]}"
        lines.append(line)
    if len(events) > max_items:
        lines.append(f"… y {len(events) - max_items} más.")
    return "\n".join(lines)


def calendar_list_today_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Lista los eventos de Google Calendar para hoy."""
    try:
        from app.services import calendar_service

        events = calendar_service.list_today(uid)
        output = _build_event_lines(events)
        return ToolResult(
            ok=True,
            output=f"Agenda de hoy ({len(events)} eventos):\n{output}",
        )
    except Exception as e:
        log.warning("calendar_list_today error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude consultar tu calendario: {e}. ¿Está vinculado Google?",
        )


def calendar_list_week_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Lista los eventos de Google Calendar para esta semana."""
    try:
        from app.services import calendar_service

        events = calendar_service.list_week(uid)
        output = _build_event_lines(events)
        return ToolResult(
            ok=True,
            output=f"Agenda semanal ({len(events)} eventos):\n{output}",
        )
    except Exception as e:
        log.warning("calendar_list_week error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude consultar tu calendario: {e}. ¿Está vinculado Google?",
        )


def calendar_create_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea un evento en Google Calendar del usuario."""
    try:
        from app.services import calendar_service

        summary = str(arguments.get("summary") or arguments.get("title") or "").strip()
        if not summary:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el título/summary del evento.",
            )

        start_str = str(arguments.get("start") or arguments.get("start_time") or "").strip()
        end_str = str(arguments.get("end") or arguments.get("end_time") or "").strip()
        description = str(arguments.get("description") or arguments.get("notes") or "").strip()
        location = str(arguments.get("location") or "").strip()

        if not start_str:
            return ToolResult(
                ok=False,
                output="",
                error="Falta la fecha/hora de inicio (start). Usa formato ISO: 2026-07-21T15:00:00",
            )

        # Parsear fechas
        try:
            start_dt = datetime.fromisoformat(start_str)
        except ValueError:
            return ToolResult(
                ok=False,
                output="",
                error=f"Formato de fecha inválido: {start_str}. Usa ISO 8601 (YYYY-MM-DDTHH:MM:SS).",
            )

        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str)
            except ValueError:
                end_dt = start_dt + timedelta(minutes=60)
        else:
            duration_min = int(arguments.get("duration_minutes") or 60)
            end_dt = start_dt + timedelta(minutes=max(15, min(duration_min, 480)))

        body_parts = []
        if description:
            body_parts.append(description)
        body_parts.append("\n\n---\nCreado por DOT (automatización).")
        full_desc = "\n".join(body_parts)

        kwargs: dict = {
            "summary": summary,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "description": full_desc,
        }
        if location:
            kwargs["location"] = location

        event = calendar_service.create_event(uid, **kwargs)
        from app.services.time_parser import format_spanish_datetime

        when_human = format_spanish_datetime(start_dt)
        title = event.get("summary", summary)
        return ToolResult(
            ok=True,
            output=(
                f"✅ Evento creado: «{title}» el {when_human} "
                f"(ISO: {event.get('start', start_str)})."
            ),
        )
    except Exception as e:
        log.warning("calendar_create_event error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude crear el evento: {e}. ¿Está vinculado Google Calendar?",
        )


def calendar_check_conflicts_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica si hay conflictos en Google Calendar para una fecha/hora."""
    try:
        from app.services import calendar_service

        start_str = str(arguments.get("start") or arguments.get("datetime") or "").strip()
        if not start_str:
            return ToolResult(
                ok=False,
                output="",
                error="Falta la fecha/hora a verificar (start).",
            )

        try:
            start_dt = datetime.fromisoformat(start_str)
        except ValueError:
            return ToolResult(
                ok=False,
                output="",
                error=f"Formato de fecha inválido: {start_str}.",
            )

        duration_min = int(arguments.get("duration_minutes") or 60)
        end_dt = start_dt + timedelta(minutes=max(15, min(duration_min, 480)))

        conflicts = calendar_service.check_conflicts(uid, start_dt, end_dt)
        if not conflicts:
            return ToolResult(
                ok=True,
                output=f"✅ Sin conflictos: {start_str} está libre.",
            )
        lines = [
            f"- {c.get('start', '?')} → {c.get('end', '?')}"
            for c in conflicts[:10]
        ]
        return ToolResult(
            ok=True,
            output=(
                f"⚠️ {len(conflicts)} conflicto(s) detectado(s) para {start_str}:\n"
                + "\n".join(lines)
            ),
        )
    except Exception as e:
        log.warning("calendar_check_conflicts error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude verificar conflictos: {e}.",
        )
TOOLS = [('calendar_list_today', calendar_list_today_handler), ('calendar_list_week', calendar_list_week_handler), ('calendar_create_event', calendar_create_event_handler), ('calendar_check_conflicts', calendar_check_conflicts_handler)]
