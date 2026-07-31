"""Claves de sesión para serializar runs del Agent Runtime."""
from __future__ import annotations


def build_session_key(
    uid: str,
    channel: str,
    *,
    conversation_id: str = "",
    chat_jid: str = "",
) -> str:
    """Construye una clave estable por usuario + canal + conversación.

    WhatsApp usa chat_jid; chat PC usa conversation_id.
    """
    parts = [uid.strip(), channel.strip()]
    conv = (conversation_id or "").strip()
    jid = (chat_jid or "").strip()
    if conv:
        parts.append(f"conv:{conv}")
    elif jid:
        parts.append(f"jid:{jid}")
    return "|".join(parts)
