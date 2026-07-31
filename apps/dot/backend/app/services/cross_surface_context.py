"""Contexto reciente del otro punto de contacto (PC ↔ WhatsApp).

Loop-13 / P1: continuidad tangible — un solo cerebro. Inyecta en el system
prompt un resumen humano de lo último que pasó en la otra superficie, sin
jerga de canales técnicos.
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.chat_models import ConversationORM, MessageORM
from app.services.chat_crypto import decrypt_message

log = logging.getLogger("dot.cross_surface_context")

# Mensajes recientes del otro lado (ligero — no duplica historial completo)
MAX_OTHER_SURFACE_MESSAGES = 8
MAX_MESSAGE_CHARS = 400

_WA_PREFIX_RE = re.compile(r"^\[WA\s[^\]]+\]\s*", re.IGNORECASE)

_SURFACE_LABELS = {
    "pc": "el PC",
    "whatsapp": "WhatsApp",
}

_OTHER_SURFACE = {
    "pc": "whatsapp",
    "whatsapp": "pc",
}

_CONTINUITY_HINT = (
    "=== CONTINUIDAD (mismo DOT en PC y WhatsApp) ===\n"
    "Si el usuario pregunta qué pidió en el PC, qué quedó pendiente, o qué "
    "hablaron por WhatsApp, responde con naturalidad usando el bloque de abajo. "
    "No digas «canal», «plataforma» ni nombres técnicos: usa «en el PC», "
    "«por WhatsApp», «antes me pediste», «recién hablamos»."
)


def _clean_message_text(text: str, *, from_whatsapp: bool) -> str:
    cleaned = (text or "").strip()
    if from_whatsapp:
        cleaned = _WA_PREFIX_RE.sub("", cleaned).strip()
    if len(cleaned) > MAX_MESSAGE_CHARS:
        return cleaned[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return cleaned


def _find_latest_conversation(
    db: Session,
    uid: str,
    surface: str,
) -> ConversationORM | None:
    try:
        uid_uuid = UUID(uid)
    except ValueError:
        return None

    return (
        db.query(ConversationORM)
        .filter(
            ConversationORM.cliente_id == uid_uuid,
            ConversationORM.channel == surface,
            ConversationORM.archived_at.is_(None),
        )
        .order_by(ConversationORM.updated_at.desc())
        .first()
    )


def _load_recent_messages(
    db: Session,
    conversation_id: UUID,
    *,
    limit: int = MAX_OTHER_SURFACE_MESSAGES,
) -> list[MessageORM]:
    messages = (
        db.query(MessageORM)
        .filter(MessageORM.conversation_id == conversation_id)
        .order_by(MessageORM.created_at.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return messages


def format_other_surface_exchange(
    messages: list[MessageORM],
    *,
    source_surface: str,
) -> str:
    """Formatea mensajes recientes del otro lado en prosa legible."""
    if not messages:
        return ""

    from_whatsapp = source_surface == "whatsapp"
    label = _SURFACE_LABELS.get(source_surface, source_surface)
    lines: list[str] = [
        f"=== LO RECIENTE EN {label.upper()} ===",
        f"(Antes de este mensaje, en {label} hablaron así:)",
    ]
    for msg in messages:
        role_label = "Tú" if msg.role == "user" else "DOT"
        content = _clean_message_text(
            decrypt_message(msg.content),
            from_whatsapp=from_whatsapp,
        )
        if not content:
            continue
        lines.append(f"{role_label}: {content}")
    lines.append("--- Fin del reciente ---")
    return "\n".join(lines)


def build_other_surface_context_block(
    db: Session,
    uid: str,
    current_surface: str,
) -> str:
    """Bloque para system prompt con lo último del otro punto de contacto."""
    other = _OTHER_SURFACE.get(current_surface)
    if not other:
        return ""

    conv = _find_latest_conversation(db, uid, other)
    if conv is None:
        return ""

    try:
        messages = _load_recent_messages(db, conv.id)
    except Exception:
        log.warning(
            "Error cargando mensajes cross-surface uid=%s other=%s",
            uid[:8],
            other,
            exc_info=True,
        )
        return ""

    exchange = format_other_surface_exchange(messages, source_surface=other)
    if not exchange:
        return ""

    return f"{_CONTINUITY_HINT}\n\n{exchange}"


def build_other_surface_context_block_safe(uid: str, current_surface: str) -> str:
    """Wrapper con sesión DB; falla en silencio si Postgres no está disponible."""
    try:
        from app.billing_db import get_session_factory

        factory = get_session_factory()
        db = factory()
        try:
            return build_other_surface_context_block(db, uid, current_surface)
        finally:
            db.close()
    except Exception:
        log.debug(
            "Sin contexto cross-surface para uid=%s surface=%s",
            uid[:8],
            current_surface,
            exc_info=True,
        )
        return ""
