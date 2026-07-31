"""Entidades de mensajería WhatsApp."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class InboundWhatsAppMessage:
    """Mensaje entrante desde el bridge Electron/Baileys."""

    message_id: str
    from_phone: str
    to_phone: str
    text: str
    timestamp: str
    source: str = "baileys"
    is_group: bool = False
    group_name: str | None = None
    group_subject: str | None = None
    sender_name: str | None = None
    chat_jid: str | None = None
    # B07: notas de voz - URL del media y flag de audio
    media_url: str | None = None
    has_audio: bool = False
    has_image: bool = False
    has_document: bool = False
    media_mime_type: str | None = None
    media_data_base64: str | None = None
    media_filename: str | None = None


@dataclass
class StoredWhatsAppMessage:
    """Mensaje persistido para consulta posterior."""

    id: str
    uid: str
    from_phone: str
    to_phone: str
    text: str
    timestamp: str
    direction: str  # "inbound" | "outbound"
    status: str = "received"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
