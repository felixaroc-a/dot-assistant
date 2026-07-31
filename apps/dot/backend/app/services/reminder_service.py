"""Servicio de recordatorios persistentes con Firestore + APScheduler (AsyncIOScheduler).

T01: Migrado a AsyncIOScheduler (Jul 2026).
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from firebase_admin import firestore

from app.firebase_db import get_db as get_firestore_client

log = logging.getLogger("dot.reminder_service")

_ACTIVE_REMINDER_SERVICE: "ReminderService | None" = None


def set_active_reminder_service(service: "ReminderService | None") -> None:
    global _ACTIVE_REMINDER_SERVICE
    _ACTIVE_REMINDER_SERVICE = service


def get_reminder_service() -> "ReminderService | None":
    return _ACTIVE_REMINDER_SERVICE


class ReminderServiceDisabledError(RuntimeError):
    """El servicio de recordatorios está deshabilitado."""


def _to_utc_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ReminderService:
    """Gestiona recordatorios persistentes y marca pendientes vencidos."""

    def __init__(self, enabled: bool, poll_seconds: int = 60):
        self._enabled = enabled
        self._poll_seconds = poll_seconds
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        if not enabled:
            log.warning(
                "ReminderService deshabilitado: Firebase no disponible, no se programará polling."
            )
            return

        self._scheduler.add_job(
            self.process_due_reminders,
            trigger=IntervalTrigger(seconds=poll_seconds),
            id="dot_reminder_due_scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info("ReminderService iniciado (AsyncIOScheduler, poll cada %ss)", poll_seconds)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _assert_enabled(self) -> None:
        if not self._enabled:
            raise ReminderServiceDisabledError(
                "Recordatorios no disponibles: Firebase no inicializado."
            )

    def create_reminder(
        self,
        uid: str,
        text: str,
        due_at: datetime,
        *,
        channel: str = "notify",
    ) -> dict:
        """Crea un recordatorio persistente para un usuario."""
        self._assert_enabled()
        clean_uid = uid.strip()
        clean_text = text.strip()
        if not clean_uid:
            raise ValueError("uid requerido")
        if not clean_text:
            raise ValueError("text requerido")

        due_at_utc = _to_utc_datetime(due_at)
        if due_at_utc is None:
            raise ValueError("due_at inválido")

        clean_channel = str(channel or "notify").strip().lower()
        if clean_channel not in ("notify", "whatsapp"):
            clean_channel = "notify"

        db = get_firestore_client()
        reminder_id = str(uuid.uuid4())
        payload = {
            "id": reminder_id,
            "uid": clean_uid,
            "text": clean_text,
            "channel": clean_channel,
            "due_at": due_at_utc,
            "due_at_iso": due_at_utc.isoformat(),
            "notified": False,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        db.collection("users").document(clean_uid).collection("reminders").document(
            reminder_id
        ).set(payload)
        return {
            "id": reminder_id,
            "text": clean_text,
            "due_at": due_at_utc.isoformat(),
            "channel": clean_channel,
            "notified": False,
        }

    def process_due_reminders(self) -> int:
        """Marca recordatorios vencidos como notificados y los encola para el cliente."""
        if not self._enabled:
            return 0
        db = get_firestore_client()
        now = datetime.now(timezone.utc)
        due_count = 0
        try:
            for user_doc in db.collection("users").stream():
                uid = user_doc.id
                reminders = (
                    user_doc.reference.collection("reminders")
                    .where("notified", "==", False)
                    .stream()
                )
                for reminder_doc in reminders:
                    data = reminder_doc.to_dict() or {}
                    due_at = _to_utc_datetime(data.get("due_at") or data.get("due_at_iso"))
                    if due_at is None or due_at > now:
                        continue

                    text = str(data.get("text", "")).strip()
                    if not text:
                        continue

                    channel = str(data.get("channel") or "notify").strip().lower()
                    if channel == "whatsapp":
                        if _send_whatsapp_reminder(uid, text):
                            reminder_doc.reference.set(
                                {
                                    "notified": True,
                                    "notified_at": firestore.SERVER_TIMESTAMP,
                                    "delivered_via": "whatsapp",
                                },
                                merge=True,
                            )
                            due_count += 1
                            continue

                    pending_ref = (
                        user_doc.reference.collection("pending_reminder_notifications")
                        .document(reminder_doc.id)
                    )
                    pending_ref.set(
                        {
                            "id": reminder_doc.id,
                            "uid": uid,
                            "text": text,
                            "due_at": due_at,
                            "due_at_iso": due_at.isoformat(),
                            "queued_at": firestore.SERVER_TIMESTAMP,
                        }
                    )
                    reminder_doc.reference.set(
                        {
                            "notified": True,
                            "notified_at": firestore.SERVER_TIMESTAMP,
                        },
                        merge=True,
                    )
                    due_count += 1
        except Exception as exc:
            log.warning("Error procesando recordatorios vencidos: %s", exc)
            return 0

        if due_count:
            log.info("Recordatorios vencidos encolados: %d", due_count)
        return due_count

    def list_pending_notifications(self, uid: str, limit: int = 25) -> list[dict]:
        """Lista notificaciones de recordatorios pendientes para el cliente."""
        self._assert_enabled()
        clean_uid = uid.strip()
        if not clean_uid:
            return []
        db = get_firestore_client()
        try:
            docs = (
                db.collection("users")
                .document(clean_uid)
                .collection("pending_reminder_notifications")
                .order_by("queued_at")
                .limit(limit)
                .stream()
            )
        except Exception:
            log.warning(
                "Fallback: consulta sin orden en pending_reminder_notifications para uid=%s",
                clean_uid[:8],
                exc_info=True,
            )
            docs = (
                db.collection("users")
                .document(clean_uid)
                .collection("pending_reminder_notifications")
                .stream()
            )

        reminders: list[dict] = []
        for doc in docs:
            data = doc.to_dict() or {}
            due_at = _to_utc_datetime(data.get("due_at") or data.get("due_at_iso"))
            reminders.append(
                {
                    "id": doc.id,
                    "text": str(data.get("text", "")).strip(),
                    "due_at": due_at.isoformat() if due_at else "",
                }
            )
        return [r for r in reminders if r["text"]]

    def ack_notifications(self, uid: str, reminder_ids: list[str]) -> int:
        """Confirma notificaciones ya mostradas al usuario."""
        self._assert_enabled()
        clean_uid = uid.strip()
        if not clean_uid:
            return 0
        db = get_firestore_client()
        base = (
            db.collection("users")
            .document(clean_uid)
            .collection("pending_reminder_notifications")
        )
        ids = [str(rem_id).strip() for rem_id in reminder_ids if str(rem_id).strip()]
        if not ids:
            ids = [doc.id for doc in base.stream()]
        for rem_id in ids:
            base.document(rem_id).delete()
        return len(ids)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("ReminderService detenido")


def _send_whatsapp_reminder(uid: str, message: str) -> bool:
    """Envía recordatorio por WhatsApp si el usuario tiene el canal vinculado."""
    try:
        import asyncio

        from app.services.whatsapp_client import send_whatsapp_message
        from app.services.whatsapp_link import get_channel_state

        state = get_channel_state(uid)
        if not state.linked or not state.phone_number:
            return False
        reminder_text = f"Recordatorio DOT: {message}"
        ok, _err = asyncio.run(send_whatsapp_message(state.phone_number, reminder_text))
        return ok
    except Exception as exc:
        log.warning("WA reminder error uid=%s: %s", uid[:8], exc)
        return False
