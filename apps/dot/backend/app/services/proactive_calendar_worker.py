"""Evaluación proactiva de mandatos manuales ante calendario (P1 Loop-9)."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("dot.proactive_calendar")


def run_proactive_calendar_check(*, max_users: int = 10, max_mandates_per_user: int = 2) -> dict[str, Any]:
    """Job periódico: revisa eventos próximos y evalúa mandatos manuales relacionados."""
    from app.firebase_db import get_db as get_firestore_client
    from app.services.proactive_triggers_service import (
        list_manual_mandates,
        user_calendar_triggers_enabled,
    )

    scanned = 0
    with_mandates = 0
    evaluated = 0
    errors = 0

    try:
        db = get_firestore_client()
        docs = list(db.collection("users").limit(max_users).stream())
    except Exception as e:
        log.warning("proactive_calendar: no se pudo listar users: %s", e)
        return {"ok": False, "error": str(e), "scanned": 0}

    for doc in docs:
        scanned += 1
        uid = doc.id
        if not user_calendar_triggers_enabled(uid):
            continue
        try:
            profile = doc.to_dict() or {}
            mandates = list_manual_mandates(profile)
            if not mandates:
                continue
            calendar_mandates = [
                m
                for m in mandates
                if _is_calendar_related(str(m.get("instruction") or ""))
                or str(m.get("integration_id") or "") == "google-calendar"
            ]
            if not calendar_mandates:
                continue
            with_mandates += 1

            try:
                from app.services.calendar_service import get_upcoming_events

                events = get_upcoming_events(uid, lookahead_hours=4)
            except Exception as e:
                log.debug("Calendario no disponible uid=%s: %s", uid[:8], e)
                continue

            if not events:
                continue

            events_summary = _format_events(events[:8])
            from app.application.agent.runtime import run_agent
            from app.application.agent.tools import build_default_registry

            registry = build_default_registry(include_web_search=False)
            for auto in calendar_mandates[:max_mandates_per_user]:
                instruction = str(auto.get("instruction") or "").strip()
                if not instruction:
                    continue
                prompt = (
                    "Revisión proactiva de calendario DOT. Eventos próximos:\n"
                    f"{events_summary}\n\n"
                    f"Mandato activo: {instruction}\n"
                    "Actúa SOLO si algún evento lo dispara ahora. "
                    "Si no hay acción inmediata, responde CALENDAR_OK."
                )
                result = run_agent(
                    uid=uid,
                    channel="automation_calendar",
                    text=prompt,
                    system_prompt=(
                        "Eres el vigilante de calendario de DOT. Sé breve. "
                        "Si no hay nada que hacer, di exactamente CALENDAR_OK."
                    ),
                    registry=registry,
                    max_steps=6,
                )
                evaluated += 1
                final = (result.final_text or "").strip()
                if final and "CALENDAR_OK" not in final:
                    from worker.executor import AutomationExecutor

                    auto_id = str(auto.get("id") or "calendar")
                    AutomationExecutor.mark_pending(
                        uid, auto_id, str(auto.get("name") or "mandato"), final
                    )
                    AutomationExecutor.save_result(
                        uid, auto_id, final, auto.get("output_type", "notify")
                    )
        except Exception as e:
            errors += 1
            log.warning("proactive_calendar error uid=%s: %s", uid[:8], e)

    summary = {
        "ok": True,
        "scanned": scanned,
        "with_mandates": with_mandates,
        "evaluated": evaluated,
        "errors": errors,
    }
    log.info("proactive_calendar done %s", summary)
    return summary


def _is_calendar_related(text: str) -> bool:
    lower = text.lower()
    keywords = (
        "calendario",
        "agenda",
        "reunión",
        "reunion",
        "cita",
        "evento",
        "meeting",
    )
    return any(k in lower for k in keywords)


def _format_events(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for ev in events:
        summary = str(ev.get("summary") or "Sin título")
        start = str(ev.get("start") or "?")
        lines.append(f"- {summary} ({start})")
    return "\n".join(lines) if lines else "(sin eventos)"
