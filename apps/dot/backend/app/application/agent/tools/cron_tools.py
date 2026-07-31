"""Tools de rutinas recurrentes (cron) desde chat — P0 recordatorios mágicos."""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.cron_service import CronScheduleType, get_cron_service
from app.services.time_parser import (
    format_recurring_confirmation,
    parse_recurring_schedule,
)

log = logging.getLogger("dot.agent.tools.cron")

TOOL_SCHEMAS: dict[str, dict] = {
    "cron_schedule_routine": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Texto del recordatorio o aviso (REQUERIDO).",
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Cuándo repetir en español: 'cada lunes a las 9', 'todos los días a las 8', "
                    "'cada 30 minutos'. También daily:HH:MM o weekly:mon:HH:MM."
                ),
            },
            "name": {
                "type": "string",
                "description": "Nombre corto de la rutina (opcional).",
            },
            "channel": {
                "type": "string",
                "description": "notify (app) o whatsapp.",
            },
        },
        "required": ["message", "schedule"],
    },
    "cron_list_routines": {
        "type": "object",
        "properties": {},
    },
    "cron_cancel_routine": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nombre parcial de la rutina a cancelar."},
            "job_id": {"type": "string", "description": "ID exacto del job (opcional)."},
        },
    },
}


def _parse_schedule_arg(schedule_raw: str) -> tuple[CronScheduleType, str] | None:
    schedule_raw = schedule_raw.strip()
    if not schedule_raw:
        return None

    parsed = parse_recurring_schedule(schedule_raw)
    if parsed:
        return parsed

    lower = schedule_raw.lower()
    if lower.startswith("daily:"):
        return CronScheduleType.DAILY_AT, schedule_raw.split(":", 1)[1].strip()
    if lower.startswith("weekly:"):
        parts = schedule_raw.split(":")
        if len(parts) >= 3:
            day = parts[1].strip().lower()[:3]
            time_val = parts[2].strip()
            return CronScheduleType.WEEKLY_ON, f"{day}@{time_val}"

    return None


def cron_schedule_routine_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Programa una rutina recurrente que sobrevive reinicios del backend."""
    message = str(arguments.get("message") or "").strip()
    schedule_raw = str(arguments.get("schedule") or "").strip()
    name = str(arguments.get("name") or message[:40] or "Recordatorio").strip()
    channel = str(arguments.get("channel") or "notify").strip().lower()

    if not message:
        return ToolResult(ok=False, output="", error="Falta message (qué recordarte).")
    if not schedule_raw:
        return ToolResult(
            ok=False,
            output="",
            error="Falta schedule. Ejemplo: 'cada lunes a las 9' o 'todos los días a las 8'.",
        )

    parsed = _parse_schedule_arg(schedule_raw)
    if not parsed:
        return ToolResult(
            ok=False,
            output="",
            error=f"No entendí la frecuencia '{schedule_raw}'. Prueba 'cada lunes a las 9' o 'daily:09:00'.",
        )

    schedule_type, schedule_value = parsed
    if channel not in ("notify", "whatsapp"):
        channel = "notify"

    cron = get_cron_service()
    if cron is None:
        return ToolResult(
            ok=False,
            output="",
            error="El servicio de rutinas no está disponible ahora. Intenta en unos minutos.",
        )

    try:
        job = cron.add_cron_job(
            uid=uid,
            name=name[:120],
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            tool_name="send_user_reminder",
            tool_args={"message": message, "channel": channel},
        )
    except (ValueError, RuntimeError) as e:
        return ToolResult(ok=False, output="", error=str(e))

    confirmation = format_recurring_confirmation(schedule_type, schedule_value, message)
    log.info("Rutina cron creada uid=%s job=%s", uid[:8], job.job_id[:8])
    return ToolResult(
        ok=True,
        output=f"{confirmation}\n(id={job.job_id[:8]})",
    )


def cron_list_routines_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Lista rutinas recurrentes activas del usuario."""
    cron = get_cron_service()
    if cron is None:
        return ToolResult(ok=False, output="", error="Servicio de rutinas no disponible.")

    jobs = cron.get_user_jobs(uid)
    if not jobs:
        return ToolResult(ok=True, output="No tienes rutinas programadas.")

    lines = [f"Rutinas ({len(jobs)}):"]
    for j in jobs:
        status = j.get("status", "active")
        msg = (j.get("tool_args") or {}).get("message", "")[:50]
        lines.append(
            f"  • [{status}] {j.get('name', '?')} — {j.get('schedule_type')} {j.get('schedule_value')} — {msg}"
        )
    return ToolResult(ok=True, output="\n".join(lines))


def cron_cancel_routine_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Cancela una rutina por nombre o job_id."""
    query = str(arguments.get("job_id") or arguments.get("name") or "").strip().lower()
    if not query:
        return ToolResult(ok=False, output="", error="Indica name o job_id de la rutina a cancelar.")

    cron = get_cron_service()
    if cron is None:
        return ToolResult(ok=False, output="", error="Servicio de rutinas no disponible.")

    jobs = cron.get_user_jobs(uid)
    target_id = None
    target_name = ""
    for j in jobs:
        jid = str(j.get("job_id", ""))
        jname = str(j.get("name", "")).lower()
        if jid.startswith(query) or query in jname:
            target_id = jid
            target_name = j.get("name", "")
            break

    if not target_id:
        return ToolResult(ok=False, output="", error=f"No encontré ninguna rutina que coincida con '{query}'.")

    cron.remove_cron_job(uid, target_id)
    return ToolResult(ok=True, output=f"Listo, cancelé la rutina '{target_name}'.")


TOOLS = [
    ("cron_schedule_routine", cron_schedule_routine_handler),
    ("cron_list_routines", cron_list_routines_handler),
    ("cron_cancel_routine", cron_cancel_routine_handler),
]
