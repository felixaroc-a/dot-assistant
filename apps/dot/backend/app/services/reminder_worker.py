"""Worker de recordatorios: dispara reminders vencidos y notifica al usuario.

Se ejecuta via APScheduler cada 60s.
F4 — Tiempo relativo (canvas automatizaciones agenticas).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger("dot.reminder_worker")


def _mark_pending_for_reminder(uid: str, auto_id: str, auto_name: str, message: str) -> None:
    """Marca resultado pendiente en Firestore como notificacion."""
    try:
        from app.firebase_db import get_db as get_firestore_client

        db = get_firestore_client()
        preview = message.replace("\r", " ").replace("\n", " ").strip()[:280]
        db.collection("users").document(uid).set(
            {
                "pending_automation_results": {
                    "has_new": True,
                    "last_auto_id": auto_id,
                    "last_auto_name": auto_name,
                    "last_executed_at": datetime.now(timezone.utc).isoformat(),
                    "last_result_preview": preview,
                }
            },
            merge=True,
        )
    except Exception as e:
        log.warning("Error marking pending reminder: %s", e)


def _send_wa_reminder(to_uid: str, message: str) -> bool:
    """Envia recordatorio por WhatsApp al dueño del mandato."""
    try:
        import asyncio

        from app.services.whatsapp_client import send_whatsapp_message
        from app.services.whatsapp_link import get_channel_state

        state = get_channel_state(to_uid)
        if not state.linked or not state.phone_number:
            log.warning("Cannot send WA reminder: WA not linked for uid=%s", to_uid[:8])
            return False

        phone = state.phone_number
        reminder_text = f"Recordatorio DOT: {message}"
        ok, err = asyncio.run(send_whatsapp_message(phone, reminder_text))
        if ok:
            log.info("WA reminder sent to uid=%s phone=%s", to_uid[:8], phone[-4:])
        else:
            log.warning("WA reminder failed uid=%s: %s", to_uid[:8], err)
        return ok
    except Exception as e:
        log.warning("WA reminder error uid=%s: %s", to_uid[:8], e)
        return False


def fire_due_reminders() -> None:
    """Revisa y dispara recordatorios vencidos. Fire-and-forget via APScheduler."""
    try:
        from app.services.reminder_service import get_reminder_service

        svc = get_reminder_service()
        if svc is not None and svc.is_enabled:
            svc.process_due_reminders()

        from app.application.agent.tools.schedule_reminder import get_and_fire_due_reminders

        due = get_and_fire_due_reminders()
        if not due:
            return

        for rem in due:
            uid = rem["uid"]
            message = rem["message"]
            channel = rem["channel"]

            if channel == "whatsapp":
                ok = _send_wa_reminder(uid, message)
                if ok:
                    log.info("Reminder %s delivered via WA", rem["id"])
                else:
                    # Fallback a notify si WA falla
                    _mark_pending_for_reminder(uid, rem["id"], "Recordatorio", message)
            else:
                _mark_pending_for_reminder(uid, rem["id"], "Recordatorio", message)
                log.info("Reminder %s delivered via notify", rem["id"])

    except Exception as e:
        log.warning("Error in fire_due_reminders: %s", e, exc_info=True)
