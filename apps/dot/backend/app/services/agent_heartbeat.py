"""Agent heartbeat — reevalúa mandatos activos sin depender solo de inbound WA."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("dot.agent_heartbeat")


def run_agent_heartbeat(*, max_users: int = 20, max_mandates_per_user: int = 3) -> dict[str, Any]:
    """Job periódico: para uids con mandatos manual activos, deja traza y opcional nudge.

    No dispara run_agent masivo por defecto (costo IA): solo audita y marca heartbeat.
    Ejecuta mandatos si DOT_AGENT_HEARTBEAT_EXECUTE=1 o el usuario activó
    «Vigilancia de mandatos» en Configuración (proactive_triggers.heartbeat_enabled).
    """
    import os

    from app.firebase_db import get_db as get_firestore_client
    from app.services.proactive_triggers_service import list_manual_mandates, user_heartbeat_enabled

    global_execute = os.environ.get("DOT_AGENT_HEARTBEAT_EXECUTE", "").strip() == "1"
    scanned = 0
    with_mandates = 0
    executed = 0
    errors = 0

    try:
        db = get_firestore_client()
        # Perfiles recientes: collection users (limitado)
        docs = list(db.collection("users").limit(max_users).stream())
    except Exception as e:
        log.warning("agent_heartbeat: no se pudo listar users: %s", e)
        return {"ok": False, "error": str(e), "scanned": 0}

    for doc in docs:
        scanned += 1
        uid = doc.id
        try:
            profile = doc.to_dict() or {}
            mandates = list_manual_mandates(profile)
            if not mandates:
                continue
            with_mandates += 1
            execute = global_execute or user_heartbeat_enabled(uid)
            log.info(
                "agent_heartbeat uid=%s mandates=%d",
                uid[:8],
                len(mandates),
            )
            # Marca last heartbeat en perfil (merge ligero)
            try:
                from datetime import datetime, timezone

                db.collection("users").document(uid).set(
                    {
                        "agent_heartbeat": {
                            "last_at": datetime.now(timezone.utc).isoformat(),
                            "mandates": len(mandates),
                        }
                    },
                    merge=True,
                )
            except Exception:
                pass

            if not execute:
                continue

            if _heartbeat_cooldown_active(profile):
                continue

            from app.application.agent.runtime import run_agent
            from app.application.agent.tools import build_default_registry

            registry = build_default_registry(include_web_search=False)
            for auto in mandates[:max_mandates_per_user]:
                instruction = str(auto.get("instruction") or "").strip()
                if not instruction:
                    continue
                prompt = (
                    "Heartbeat del Gateway DOT. Revisa este mandato activo del usuario "
                    f"y actúa SOLO si hay algo pendiente ahora: {instruction}. "
                    "Si no hay acción inmediata, responde HEARTBEAT_OK."
                )
                result = run_agent(
                    uid=uid,
                    channel="automation_heartbeat",
                    text=prompt,
                    system_prompt=(
                        "Eres el heartbeat de DOT. Sé breve. "
                        "Si no hay nada que hacer, di exactamente HEARTBEAT_OK."
                    ),
                    registry=registry,
                    max_steps=6,
                )
                executed += 1
                final = (result.final_text or "").strip()
                if final and "HEARTBEAT_OK" not in final:
                    from worker.executor import AutomationExecutor

                    auto_id = str(auto.get("id") or "heartbeat")
                    AutomationExecutor.mark_pending(
                        uid, auto_id, str(auto.get("name") or "mandato"), final
                    )
                    AutomationExecutor.save_result(
                        uid, auto_id, final, auto.get("output_type", "notify")
                    )
            _mark_heartbeat_executed(db, uid)
        except Exception as e:
            errors += 1
            log.warning("agent_heartbeat error uid=%s: %s", uid[:8], e)

    summary = {
        "ok": True,
        "scanned": scanned,
        "with_mandates": with_mandates,
        "executed": executed,
        "errors": errors,
        "execute_mode": global_execute,
        "user_execute_enabled": True,
    }
    log.info("agent_heartbeat done %s", summary)
    return summary


_HEARTBEAT_COOLDOWN_MINUTES = 30


def _heartbeat_cooldown_active(profile: dict) -> bool:
    """Evita spam: no más de una ejecución IA cada 30 min por usuario."""
    from datetime import datetime, timedelta, timezone

    hb = profile.get("agent_heartbeat") or {}
    last_exec = hb.get("last_execute_at")
    if not last_exec:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last_exec).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_dt < timedelta(minutes=_HEARTBEAT_COOLDOWN_MINUTES)
    except (ValueError, TypeError):
        return False


def _mark_heartbeat_executed(db, uid: str) -> None:
    from datetime import datetime, timezone

    try:
        db.collection("users").document(uid).set(
            {
                "agent_heartbeat": {
                    "last_execute_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            merge=True,
        )
    except Exception:
        pass
