"""Almacén en memoria de mensajes WhatsApp (Fase A)."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock

from app.domain.whatsapp.message import StoredWhatsAppMessage


class WhatsAppMessageStore:
    """Store thread-safe por uid. Suficiente para Fase A / pruebas locales."""

    def __init__(self) -> None:
        self._by_uid: dict[str, list[StoredWhatsAppMessage]] = defaultdict(list)
        self._lock = Lock()
        self._max_per_uid = 200

    def save(self, message: StoredWhatsAppMessage) -> None:
        with self._lock:
            bucket = self._by_uid[message.uid]
            if any(existing.id == message.id for existing in bucket):
                return
            bucket.append(message)
            if len(bucket) > self._max_per_uid:
                del bucket[: len(bucket) - self._max_per_uid]

    def list_for_uid(
        self,
        uid: str,
        *,
        phone: str | None = None,
        limit: int = 50,
    ) -> list[StoredWhatsAppMessage]:
        with self._lock:
            items = list(self._by_uid.get(uid, []))
        if phone:
            needle = "".join(ch for ch in phone if ch.isdigit())[-10:]
            if needle:
                items = [
                    msg
                    for msg in items
                    if needle in msg.from_phone[-10:] or needle in msg.to_phone[-10:]
                ]
        items.sort(key=lambda m: m.created_at, reverse=True)
        return items[: max(1, min(limit, 200))]

    def clear_uid(self, uid: str) -> None:
        with self._lock:
            self._by_uid.pop(uid, None)
