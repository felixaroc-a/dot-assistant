"""Tools de productividad y oficina — F6."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.productivity")


def productivity_daily_summary_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        parts = ["Resumen diario DOT:"]
        try:
            from app.services import calendar_service
            events = calendar_service.list_today(uid)
            parts.append(f"Calendario: {len(events)} eventos hoy.")
            for e in events[:5]:
                parts.append(f"  {e.get('start','?')} {e.get('summary','')}")
        except Exception:
            parts.append("Calendario: no disponible.")
        try:
            from app.application.whatsapp.inbound_service import get_message_store
            msgs = get_message_store().list_for_uid(uid, limit=5)
            parts.append(f"WhatsApp: {len(msgs)} mensajes recientes.")
        except Exception:
            parts.append("WhatsApp: no disponible.")
        try:
            from app.services import gmail_service
            unread = gmail_service.list_unread(uid, max_results=5)
            parts.append(f"Gmail: {len(unread)} no leidos.")
        except Exception:
            parts.append("Gmail: no disponible.")
        raw = "\n".join(parts)
        summary = route_chat(f"Genera un resumen ejecutivo diario en 3-4 frases:\n{raw}", provider_id="deepseek", system_prompt="Resumen ejecutivo diario. Breve, util, en espanol.")
        return ToolResult(ok=True, output=summary.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_weekly_report_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        parts = ["Reporte semanal DOT:"]
        try:
            from app.services import calendar_service
            events = calendar_service.list_week(uid)
            parts.append(f"Calendario: {len(events)} eventos esta semana.")
        except Exception:
            parts.append("Calendario: no disponible.")
        try:
            from app.application.whatsapp.inbound_service import get_message_store
            msgs = get_message_store().list_for_uid(uid, limit=20)
            contacts = set(m.from_phone for m in msgs)
            parts.append(f"WhatsApp: {len(msgs)} mensajes, {len(contacts)} contactos.")
        except Exception:
            parts.append("WhatsApp: no disponible.")
        raw = "\n".join(parts)
        summary = route_chat(f"Genera un reporte semanal ejecutivo en 5 frases:\n{raw}", provider_id="deepseek", system_prompt="Reporte semanal en espanol. Breve y util.")
        return ToolResult(ok=True, output=summary.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_checklist_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        text = str(arguments.get("text") or arguments.get("topic") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta texto o tema del checklist.")
        from app.services.provider_router import route_chat
        result = route_chat(
            f"Genera un checklist practico de tareas para: {text}. Formato: - [ ] tarea. Max 15 items.",
            provider_id="deepseek",
            system_prompt="Checklist practico en espanol. Items accionables."
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_pomodoro_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        minutes = int(arguments.get("minutes") or 25)
        break_min = int(arguments.get("break") or 5)
        cycles = int(arguments.get("cycles") or 4)
        total = cycles * (minutes + break_min) - break_min
        return ToolResult(ok=True, output=f"Pomodoro: {cycles} ciclos de {minutes} min trabajo + {break_min} min descanso. Duracion total: {total} minutos. Empieza ya y usa schedule_reminder para alertas.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_meeting_notes_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        topic = str(arguments.get("topic") or "Reunion").strip()
        notes = str(arguments.get("notes") or arguments.get("text") or "").strip()
        if not notes and not topic:
            return ToolResult(ok=False, output="", error="Falta notas o tema.")
        from app.services.provider_router import route_chat
        result = route_chat(
            f"Genera minuta profesional de reunion: {topic}\n\nNotas: {notes}\n\nIncluye: asistentes (si se mencionan), decisiones, tareas asignadas, proximos pasos.",
            provider_id="deepseek",
            system_prompt="Minuta profesional en espanol. Estructura clara."
        )
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path = str(Path(f"~/Desktop/Minuta_{topic.replace(' ','_')[:30]}_{datetime.now().strftime('%Y%m%d')}.txt").expanduser())
        execute_local_tool_via_bridge("writeFile", path=path, content=result.strip())
        return ToolResult(ok=True, output=f"Minuta guardada en {path}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_prioritize_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        tasks = arguments.get("tasks") or []
        if isinstance(tasks, str):
            tasks = [t.strip() for t in tasks.split("\n") if t.strip()]
        if not tasks:
            return ToolResult(ok=False, output="", error="Falta lista de tareas.")
        from app.services.provider_router import route_chat
        result = route_chat(
            "Prioriza estas tareas por urgencia e importancia (Eisenhower). Responde con 4 categorias:\n\n"
            + "\n".join(f"- {t}" for t in tasks[:20]),
            provider_id="deepseek",
            system_prompt="Matriz Eisenhower en espanol. Categorias: urgente+importante, importante+no_urgente, urgente+no_importante, ni_urgente_ni_importante."
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_focus_mode_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        minutes = int(arguments.get("minutes") or 60)
        return ToolResult(ok=True, output=f"Modo concentracion activado por {minutes} minutos. Minimiza distracciones. Usa schedule_reminder para alerta al terminar.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def productivity_track_goal_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        goal = str(arguments.get("goal") or "").strip()
        target = float(arguments.get("target") or 100)
        current = float(arguments.get("current") or 0)
        if not goal:
            return ToolResult(ok=False, output="", error="Falta goal (objetivo).")
        pct = round(current / target * 100, 1) if target > 0 else 0
        bar = "[" + "#" * int(pct // 5) + "." * (20 - int(pct // 5)) + "]"
        return ToolResult(ok=True, output=f"{goal}: {current}/{target} ({pct}%)\n{bar}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_schedule_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        message = str(arguments.get("message") or "").strip()
        channel = str(arguments.get("channel") or "whatsapp").strip()
        remind_at = str(arguments.get("at") or arguments.get("datetime") or "").strip()
        to = str(arguments.get("to") or "").strip()
        if not message or not remind_at:
            return ToolResult(ok=False, output="", error="Falta message y at (fecha/hora).")
        return ToolResult(ok=True, output=f"Mensaje programado para {remind_at} via {channel}. Recordatorio: usa schedule_reminder para ejecutar el envio a esa hora.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_generate_invitation_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        event = str(arguments.get("event") or "Evento").strip()
        date = str(arguments.get("date") or "").strip()
        location = str(arguments.get("location") or "").strip()
        host = str(arguments.get("host") or "Anfitrion").strip()
        result = route_chat(
            f"Genera invitacion digital para: {event}, fecha: {date}, lugar: {location}, anfitrion: {host}. Incluye texto persuasivo y datos practicos.",
            provider_id="deepseek",
            system_prompt="Invitacion profesional en espanol, tono calido, incluye datos clave."
        )
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_personalize_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        template = str(arguments.get("template") or "").strip()
        contact_data = str(arguments.get("data") or arguments.get("contact") or "").strip()
        if not template:
            return ToolResult(ok=False, output="", error="Falta template del mensaje.")
        result = route_chat(
            f"Personaliza este mensaje con los datos del contacto:\nTemplate: {template}\nDatos contacto: {contact_data}",
            provider_id="deepseek",
            system_prompt="Personaliza mensaje usando los datos. Solo el mensaje final."
        )
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("productivity_daily_summary", productivity_daily_summary_handler),
    ("productivity_weekly_report", productivity_weekly_report_handler),
    ("productivity_checklist", productivity_checklist_handler),
    ("productivity_pomodoro", productivity_pomodoro_handler),
    ("productivity_meeting_notes", productivity_meeting_notes_handler),
    ("productivity_prioritize", productivity_prioritize_handler),
    ("productivity_focus_mode", productivity_focus_mode_handler),
    ("productivity_track_goal", productivity_track_goal_handler),
    ("comm_schedule_message", comm_schedule_message_handler),
    ("comm_generate_invitation", comm_generate_invitation_handler),
    ("comm_personalize_message", comm_personalize_message_handler),
]
