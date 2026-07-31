"""Tool create_automation — automatizaciones desde chat en lenguaje natural (P1).

Unifica recordatorios únicos, rutinas recurrentes y jobs compuestos
(búsqueda/correo/calendario + aviso WhatsApp) sin abrir drawers técnicos.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.time_parser import (
    extract_structured_schedule,
    format_recurring_confirmation,
    format_spanish_datetime,
    format_structured_schedule_human,
    parse_recurring_schedule,
    parse_spanish_datetime,
    resolve_remind_at,
)

log = logging.getLogger("dot.agent.tools.automation")

_ACTION_PATTERNS = (
    r"\b(busca|buscar|revisa|revisar|lee|leer|chequea|chequear|consulta|monitorea|escanea)\b",
    r"\b(gmail|correo|email|bandeja|calendario|agenda|internet|web|noticias)\b",
)

_RECURRING_HINTS = (
    r"\b(cada|todos los|todas las|diariamente|semanalmente)\b",
    r"\b(daily:|weekly:)\b",
)

_ONE_SHOT_HINTS = (
    r"\b(ma[nñ]ana|pasado ma[nñ]ana|hoy|en\s+\d+\s+(hora|minuto|min))\b",
    r"\b(el\s+(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo))\b",
)

TOOL_SCHEMAS: dict[str, dict] = {
    "create_automation": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": (
                    "Petición completa del usuario en español. Ej: "
                    "'Cada lunes busca noticias de IA y avísame por WhatsApp'."
                ),
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Opcional si ya está en request. Ej: 'cada lunes a las 9', "
                    "'daily:09:00', 'weekly:mon:09:00'."
                ),
            },
            "channel": {
                "type": "string",
                "description": "notify (app) o whatsapp. Inferir del request si falta.",
            },
            "name": {
                "type": "string",
                "description": "Nombre corto opcional para la automatización.",
            },
        },
        "required": ["request"],
    },
}


def _normalize(text: str) -> str:
    return text.strip()


def _detect_channel(text: str, explicit: str) -> str:
    channel = (explicit or "").strip().lower()
    if channel in ("notify", "whatsapp"):
        return channel
    lower = text.lower()
    if re.search(r"\b(whatsapp|whats\s*app|por\s+wa\b)\b", lower):
        return "whatsapp"
    if re.search(r"\b(av[ií]same|notif[ií]came|env[ií]ame|manda\s+un\s+mensaje)\b", lower):
        return "whatsapp"
    return "notify"


def _is_complex_automation(text: str) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in _ACTION_PATTERNS)


def _is_multi_step(text: str) -> bool:
    try:
        from app.services.chat_context import detect_pipeline_intent

        return detect_pipeline_intent(text)
    except Exception:
        lower = text.lower()
        return bool(
            re.search(r"\b(luego|despu[eé]s|y\s+despu[eé]s|si\s+hay)\b", lower)
            and re.search(r"\b(gu[aá]rda|av[ií]sa|env[ií]a|notif[ií]ca)\b", lower)
        )


def _is_recurring(text: str) -> bool:
    lower = text.lower()
    if parse_recurring_schedule(text):
        return True
    return any(re.search(p, lower) for p in _RECURRING_HINTS)


def _is_one_shot_reminder(text: str) -> bool:
    if _is_recurring(text):
        return False
    if _is_complex_automation(text):
        return False
    lower = text.lower()
    if any(re.search(p, lower) for p in _ONE_SHOT_HINTS):
        return True
    return bool(parse_spanish_datetime(text))


def _extract_reminder_message(text: str) -> str:
    cleaned = text
    for prefix in (
        r"^recu[eé]rdame\s+(que\s+)?",
        r"^av[ií]same\s+(que\s+)?",
        r"^notif[ií]came\s+(que\s+)?",
        r"^programa\s+(un\s+)?recordatorio\s+(para\s+)?",
    ):
        cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned[:500] or text[:500]


def _derive_name(text: str, explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()[:120]
    snippet = re.sub(r"\s+", " ", text).strip()
    if len(snippet) > 60:
        snippet = snippet[:57].rsplit(" ", 1)[0] + "…"
    return snippet or "Automatización"


def _detect_integration(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(gmail|correo|email|bandeja)\b", lower):
        return "gmail"
    if re.search(r"\b(calendario|agenda|reuni[oó]n|evento)\b", lower):
        return "google-calendar"
    return "third-option"


def _resolve_schedule(text: str, explicit: str) -> str:
    if explicit.strip():
        structured = extract_structured_schedule(explicit)
        if structured:
            return structured
        lower = explicit.lower()
        if lower.startswith(("daily:", "weekly:", "every:", "manual")):
            return explicit.strip()
    structured = extract_structured_schedule(text)
    if structured:
        return structured
    return "manual"


def _channel_label(channel: str) -> str:
    return "WhatsApp" if channel == "whatsapp" else "notificación en la app"


def _reload_scheduler(uid: str) -> None:
    try:
        from app.services.automation_scheduler import get_scheduler

        sch = get_scheduler()
        if sch is not None:
            sch.reload_user_automations(uid)
    except Exception as e:
        log.debug("Scheduler no rehidratado tras create_automation: %s", e)


def _schedule_pipeline(uid: str, pipeline) -> None:
    if not pipeline.schedule or pipeline.schedule == "manual" or not pipeline.active:
        return
    try:
        from app.services.automation_jobs import parse_schedule, schedule_automation
        from app.services.automation_scheduler import get_scheduler
        from app.services.pipeline_orchestrator import PipelineOrchestrator

        sch = get_scheduler()
        if sch is None:
            return
        trigger = parse_schedule(pipeline.schedule)
        if not trigger:
            return
        orchestrator = PipelineOrchestrator()
        payload = orchestrator.to_task_payload(pipeline)
        schedule_automation(
            sch._scheduler,
            uid,
            payload,
            "mensual",
            job_fn=sch._on_trigger,
        )
    except Exception as e:
        log.warning("Error programando pipeline %s: %s", pipeline.id, e)


def _create_saved_automation(
    uid: str,
    *,
    name: str,
    instruction: str,
    schedule: str,
    channel: str,
    integration_id: str,
    is_pipeline: bool = False,
    pipeline_steps: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    from app.firebase_db import get_db as get_firestore_client

    db = get_firestore_client()
    doc = db.collection("users").document(uid).get()
    profile = doc.to_dict() if doc.exists else {}
    autos = list(profile.get("saved_automations") or [])
    if not isinstance(autos, list):
        autos = []

    auto_id = uuid.uuid4().hex[:12]
    output_type = "whatsapp" if channel == "whatsapp" else "notify"
    new_auto: dict[str, Any] = {
        "id": auto_id,
        "name": name[:120],
        "instruction": instruction[:4000],
        "integration_id": integration_id,
        "schedule": schedule,
        "output_type": output_type,
        "description": instruction[:500],
        "active": True,
        "source": "chat",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if is_pipeline and pipeline_steps:
        new_auto["is_pipeline"] = True
        new_auto["pipeline_steps"] = pipeline_steps

    autos.append(new_auto)
    db.collection("users").document(uid).set({"saved_automations": autos}, merge=True)
    _reload_scheduler(uid)
    return auto_id, new_auto


def _create_pipeline_automation(
    uid: str,
    request: str,
    schedule: str,
    name: str,
) -> ToolResult:
    from app.models.pipeline import PipelineCreateRequest
    from app.services.pipeline_orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()
    try:
        pipeline = orchestrator.create_pipeline(
            uid,
            PipelineCreateRequest(
                natural_language=request,
                schedule=schedule,
                name=name,
            ),
        )
    except Exception as e:
        log.warning("Pipeline LLM falló, usando heurístico: %s", e)
        pipeline = orchestrator._heuristic_pipeline_from_text(request)
        pipeline.schedule = schedule
        pipeline.id = f"pl_{uuid.uuid4().hex[:12]}"
        pipeline.name = name or pipeline.name
        orchestrator._save_to_firestore(uid, pipeline)

    _schedule_pipeline(uid, pipeline)
    schedule_human = format_structured_schedule_human(pipeline.schedule)
    return ToolResult(
        ok=True,
        output=(
            f"Listo, quedó programada tu automatización «{pipeline.name}».\n"
            f"• Frecuencia: {schedule_human}\n"
            f"• Pasos: {len(pipeline.steps)} (correo, archivos, búsqueda, etc.)\n"
            f"• Te avisará al final por WhatsApp o en la app según lo pediste.\n"
            f"• Sobrevive reinicios — no necesitas abrir el panel técnico.\n"
            f"(id={pipeline.id[:12]})"
        ),
    )


def _create_instruction_automation(
    uid: str,
    request: str,
    schedule: str,
    channel: str,
    name: str,
) -> ToolResult:
    instruction = request.strip()
    if channel == "whatsapp" and "whatsapp" not in instruction.lower():
        instruction = f"{instruction}. Al terminar, envíame un resumen por WhatsApp."

    integration_id = _detect_integration(request)
    auto_id, _ = _create_saved_automation(
        uid,
        name=name,
        instruction=instruction,
        schedule=schedule,
        channel=channel,
        integration_id=integration_id,
    )
    schedule_human = format_structured_schedule_human(schedule)
    channel_label = _channel_label(channel)
    return ToolResult(
        ok=True,
        output=(
            f"Listo, quedó programada tu automatización «{name}».\n"
            f"• Frecuencia: {schedule_human}\n"
            f"• Qué hará: {instruction[:120]}{'…' if len(instruction) > 120 else ''}\n"
            f"• Aviso: {channel_label}\n"
            f"• Sobrevive reinicios — no necesitas abrir el panel técnico.\n"
            f"(id={auto_id})"
        ),
    )


def create_automation_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea automatizaciones reales desde lenguaje natural (persisten tras reinicio)."""
    request = _normalize(str(arguments.get("request") or arguments.get("instruction") or ""))
    if not request:
        return ToolResult(
            ok=False,
            output="",
            error=(
                "Falta request. Ejemplo: "
                "'Cada lunes busca noticias de IA y avísame por WhatsApp'."
            ),
        )

    schedule = _resolve_schedule(request, str(arguments.get("schedule") or ""))
    channel = _detect_channel(request, str(arguments.get("channel") or ""))
    name = _derive_name(request, str(arguments.get("name") or ""))

    # ─── Recordatorio único ───────────────────────────────
    if _is_one_shot_reminder(request):
        from app.application.agent.tools.schedule_reminder import schedule_reminder_handler

        message = _extract_reminder_message(request)
        when_dt = resolve_remind_at({"when": request}) or parse_spanish_datetime(request)
        args: dict[str, Any] = {"message": message, "channel": channel}
        if when_dt:
            args["when"] = when_dt.isoformat()
        else:
            args["when"] = request
        result = schedule_reminder_handler(uid, args)
        if result.ok and when_dt:
            when_human = format_spanish_datetime(when_dt)
            return ToolResult(
                ok=True,
                output=(
                    f"Listo, te aviso el {when_human} por {_channel_label(channel)}: "
                    f"{message[:80]}{'…' if len(message) > 80 else ''}"
                ),
            )
        return result

    # ─── Rutina simple (solo aviso, sin acciones complejas) ─
    if _is_recurring(request) and not _is_complex_automation(request):
        from app.application.agent.tools.cron_tools import cron_schedule_routine_handler

        schedule_nl = str(arguments.get("schedule") or request)
        message = _extract_reminder_message(request)
        return cron_schedule_routine_handler(
            uid,
            {
                "message": message,
                "schedule": schedule_nl,
                "name": name,
                "channel": channel,
            },
        )

    # ─── Automatización compuesta multi-paso ──────────────
    if _is_multi_step(request):
        if schedule == "manual":
            return ToolResult(
                ok=False,
                output="",
                error=(
                    "Indica cuándo debe repetirse. Ejemplo: 'cada lunes a las 9' "
                    "o schedule='weekly:mon:09:00'."
                ),
            )
        return _create_pipeline_automation(uid, request, schedule, name)

    # ─── Job programado con instrucción (busca X, revisa correo, etc.) ─
    if schedule == "manual":
        return ToolResult(
            ok=False,
            output="",
            error=(
                "Para automatizaciones recurrentes indica la frecuencia. "
                "Ejemplo: 'cada lunes', 'todos los días a las 8'."
            ),
        )
    return _create_instruction_automation(uid, request, schedule, channel, name)


TOOLS = [
    ("create_automation", create_automation_handler),
]
