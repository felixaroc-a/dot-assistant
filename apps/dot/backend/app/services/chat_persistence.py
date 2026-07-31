"""Persistencia de conversaciones y mensajes de chat en Postgres.

Separa la lógica de CRUD de chat_models del enrutador, manteniendo
la integridad referencial y el cifrado en reposo.

B01: Multi-chat — channel, soft-delete (archived_at), paginación de mensajes.
CH06: búsqueda con pg_trgm similarity (Postgres) o ILIKE fallback (SQLite).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.chat_models import ConversationORM, MessageORM
from app.services.chat_crypto import encrypt_message

log = logging.getLogger("dot.chat_persistence")

_TITLE_MAX_LEN = 200
_TRGM_SIMILARITY_THRESHOLD = 0.15


def conversation_title_from_user_text(user_text: str, max_len: int = _TITLE_MAX_LEN) -> str:
    """Deriva un título legible del primer mensaje (normaliza espacios, trunca en palabra)."""
    normalized = " ".join((user_text or "").split())
    if not normalized:
        return "Nueva conversación"
    if len(normalized) <= max_len:
        return normalized
    cut = normalized[:max_len].rsplit(" ", 1)[0]
    base = (cut or normalized[:max_len]).rstrip()
    return f"{base}…" if base else normalized[:max_len]


def parse_conversation_id(conversation_id: str) -> UUID:
    """Convierte string a UUID; lanza 404 si es inválido."""
    try:
        return UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail="Conversación no encontrada.",
        ) from exc


def get_owned_conversation(
    db: Session,
    conv_id: UUID,
    uid: str,
    include_archived: bool = False,
) -> ConversationORM:
    """Devuelve la conversación solo si pertenece al cliente del JWT.

    Por defecto excluye conversaciones archivadas (soft-delete).
    """
    q = db.query(ConversationORM).filter(ConversationORM.id == conv_id)
    if not include_archived:
        q = q.filter(ConversationORM.archived_at.is_(None))
    conv = q.first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    if str(conv.cliente_id) != uid:
        raise HTTPException(
            status_code=403,
            detail="No tienes acceso a esta conversación.",
        )
    return conv


def get_or_create_conversation(
    db: Session,
    uid: str,
    conversation_id: str,
    provider: str,
    user_text: str,
    channel: str = "pc",
) -> tuple[ConversationORM, UUID]:
    """Obtiene o crea una conversación; retorna (ORM, UUID)."""
    conv_id = (
        parse_conversation_id(conversation_id)
        if len(conversation_id) == 36
        else uuid.uuid4()
    )

    conv = (
        db.query(ConversationORM)
        .filter(ConversationORM.id == conv_id, ConversationORM.archived_at.is_(None))
        .first()
    )
    if conv is None:
        conv = ConversationORM(
            id=conv_id,
            cliente_id=UUID(uid),
            title=conversation_title_from_user_text(user_text),
            provider=provider,
            channel=channel,
        )
        db.add(conv)
    else:
        get_owned_conversation(db, conv_id, uid)

    return conv, conv_id


def save_message(
    uid: str,
    conversation: ConversationORM,
    role: str,
    content: str,
    tokens: int = 0,
    db: Session | None = None,
) -> MessageORM:
    """Crea y persiste un mensaje cifrado en la conversación."""
    msg = MessageORM(
        conversation_id=conversation.id,
        role=role,
        content=encrypt_message(content),
        tokens=tokens,
    )
    if db is not None:
        db.add(msg)
    return msg


def save_exchange(
    db: Session,
    uid: str,
    conversation_id: str,
    user_text: str,
    assistant_text: str,
    provider: str,
    tokens: int = 0,
) -> bool:
    """Persiste intercambio user+assistant; devuelve True si ok.

    En caso de error HTTP (ownership, 404) lo relanza; otros errores
    se loggean y devuelven False.
    """
    try:
        conv, _ = get_or_create_conversation(db, uid, conversation_id, provider, user_text)

        user_msg = save_message(uid, conv, "user", user_text, db=db)
        assistant_msg = save_message(uid, conv, "assistant", assistant_text, tokens, db=db)

        conv.message_count = (conv.message_count or 0) + 2
        conv.updated_at = datetime.now(timezone.utc)

        db.add(user_msg)
        db.add(assistant_msg)
        db.commit()
        return True
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        log.error(
            "No se pudo guardar historial de chat (uid=%s, conversation_id=%s)",
            uid,
            conversation_id,
            exc_info=True,
        )
        return False


def load_recent_history(
    db: Session,
    uid: str,
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MessageORM], int]:
    """Carga mensajes paginados de una conversación validando ownership.

    Returns:
        (mensajes, total) para paginación.
    """
    conv_id = parse_conversation_id(conversation_id)
    get_owned_conversation(db, conv_id, uid)

    total = (
        db.query(MessageORM)
        .filter(MessageORM.conversation_id == conv_id)
        .count()
    )

    messages = (
        db.query(MessageORM)
        .filter(MessageORM.conversation_id == conv_id)
        .order_by(MessageORM.created_at)
        .offset(offset)
        .limit(limit)
        .all()
    )

    return messages, total


def list_user_conversations(
    db: Session,
    uid: str,
    limit: int = 50,
    query: str | None = None,
    include_archived: bool = False,
    search_messages: bool = False,
) -> list[ConversationORM]:
    """Lista conversaciones del usuario ordenadas por última actualización.

    CH06: con ``query``, filtra títulos vía pg_trgm similarity (Postgres) o
    ILIKE (SQLite fallback). Si ``search_messages`` es True, también busca en
    los últimos N mensajes descifrados por conversación. El contenido de
    mensajes está cifrado en reposo; la búsqueda en cuerpo descifra en app
    tras el filtro de título.
    """
    uid_uuid = UUID(uid)
    q = db.query(ConversationORM).filter(
        ConversationORM.cliente_id == uid_uuid,
    )
    if not include_archived:
        q = q.filter(ConversationORM.archived_at.is_(None))
    needle = (query or "").strip()
    if needle and not search_messages:
        from app.services.search_service import _detect_pg_trgm

        if _detect_pg_trgm(db):
            # Postgres pg_trgm: similarity con ranking
            q = q.filter(
                func.similarity(ConversationORM.title, needle) > _TRGM_SIMILARITY_THRESHOLD
            ).order_by(
                func.similarity(ConversationORM.title, needle).desc()
            )
        else:
            # SQLite / fallback: ILIKE + ranking por longitud de coincidencia
            q = q.filter(ConversationORM.title.ilike(f"%{needle}%"))
            q = q.order_by(func.length(ConversationORM.title).asc())
    convs = q.order_by(ConversationORM.updated_at.desc()).limit(limit).all() if (not needle or search_messages) else \
        q.limit(limit).all()

    if needle and search_messages:
        # Filtro post-consulta: descifrar últimos mensajes y buscar en contenido
        from app.services.chat_crypto import decrypt_message
        filtered: list[ConversationORM] = []
        for conv in convs:
            # Coincidencia en título
            if needle.lower() in (conv.title or "").lower():
                filtered.append(conv)
                continue
            # Buscar en últimos 100 mensajes de esta conversación
            recent = (
                db.query(MessageORM)
                .filter(MessageORM.conversation_id == conv.id)
                .order_by(MessageORM.created_at.desc())
                .limit(100)
                .all()
            )
            for msg in recent:
                try:
                    plain = decrypt_message(msg.content)
                    if needle.lower() in plain.lower():
                        filtered.append(conv)
                        break
                except Exception:
                    continue
        return filtered

    return convs


def append_whatsapp_chat_message(
    db: Session,
    uid: str,
    role: str,
    content: str,
) -> ConversationORM:
    """Añade un mensaje a la conversación WhatsApp unificada (B3/W06b)."""
    conv = find_or_create_whatsapp_conversation(db, uid)
    msg = MessageORM(
        conversation_id=conv.id,
        role=role,
        content=encrypt_message(content),
    )
    db.add(msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def create_conversation(
    db: Session,
    uid: str,
    title: str | None = None,
    provider: str = "deepseek",
    channel: str = "pc",
) -> ConversationORM:
    """Crea una conversación vacía y la persiste."""
    conv_id = uuid.uuid4()
    conv = ConversationORM(
        id=conv_id,
        cliente_id=UUID(uid),
        title=title or "Nueva conversación",
        provider=provider,
        channel=channel,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def rename_conversation(
    db: Session,
    uid: str,
    conversation_id: str,
    new_title: str,
) -> ConversationORM:
    """Renombra una conversación validando ownership."""
    conv_id = parse_conversation_id(conversation_id)
    conv = get_owned_conversation(db, conv_id, uid)
    conv.title = new_title
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def delete_conversation(
    db: Session,
    uid: str,
    conversation_id: str,
) -> None:
    """Soft-delete: marca archived_at. Los mensajes se preservan."""
    conv_id = parse_conversation_id(conversation_id)
    conv = get_owned_conversation(db, conv_id, uid)
    conv.archived_at = datetime.now(timezone.utc)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()


def auto_title_conversation(
    db: Session,
    uid: str,
    conversation_id: str,
    title: str,
) -> ConversationORM:
    """Actualiza el título de una conversación vía LLM (CH07)."""
    conv_id = parse_conversation_id(conversation_id)
    conv = get_owned_conversation(db, conv_id, uid)
    conv.title = title[:200]
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def list_archived_conversations(
    db: Session,
    uid: str,
    limit: int = 50,
    query: str | None = None,
    search_messages: bool = False,
) -> list[ConversationORM]:
    """Lista conversaciones archivadas del usuario.

    CH06: con ``query`` y ``search_messages``, filtra por título y contenido
    de mensajes (misma lógica que conversaciones activas).
    """
    uid_uuid = UUID(uid)
    q = (
        db.query(ConversationORM)
        .filter(
            ConversationORM.cliente_id == uid_uuid,
            ConversationORM.archived_at.isnot(None),
        )
    )
    needle = (query or "").strip()
    if needle and not search_messages:
        q = q.filter(ConversationORM.title.ilike(f"%{needle}%"))
    convs = (
        q.order_by(ConversationORM.archived_at.desc()).limit(limit).all()
        if (not needle or search_messages)
        else q.limit(limit).all()
    )

    if needle and search_messages:
        from app.services.chat_crypto import decrypt_message

        filtered: list[ConversationORM] = []
        for conv in convs:
            if needle.lower() in (conv.title or "").lower():
                filtered.append(conv)
                continue
            recent = (
                db.query(MessageORM)
                .filter(MessageORM.conversation_id == conv.id)
                .order_by(MessageORM.created_at.desc())
                .limit(100)
                .all()
            )
            for msg in recent:
                try:
                    plain = decrypt_message(msg.content)
                    if needle.lower() in plain.lower():
                        filtered.append(conv)
                        break
                except Exception:
                    continue
        return filtered

    return convs


def unarchive_conversation(
    db: Session,
    uid: str,
    conversation_id: str,
) -> ConversationORM:
    """Restaura una conversación archivada."""
    conv_id = parse_conversation_id(conversation_id)
    conv = get_owned_conversation(db, conv_id, uid, include_archived=True)
    conv.archived_at = None
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def search_conversation_messages(
    db: Session,
    uid: str,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Busca en los mensajes descifrados de todas las conversaciones del usuario.

    Recorre las conversaciones activas, descifra los últimos N mensajes de cada una
    y devuelve coincidencias con snippet de contexto.
    """
    from app.services.chat_crypto import decrypt_message

    uid_uuid = UUID(uid)
    needle = (query or "").strip().lower()
    if not needle:
        return []

    convs = (
        db.query(ConversationORM)
        .filter(
            ConversationORM.cliente_id == uid_uuid,
            ConversationORM.archived_at.is_(None),
        )
        .order_by(ConversationORM.updated_at.desc())
        .limit(50)
        .all()
    )

    results: list[dict] = []
    for conv in convs:
        if len(results) >= limit:
            break
        recent = (
            db.query(MessageORM)
            .filter(MessageORM.conversation_id == conv.id)
            .order_by(MessageORM.created_at.desc())
            .limit(100)
            .all()
        )
        for msg in recent:
            if len(results) >= limit:
                break
            try:
                plain = decrypt_message(msg.content)
                idx = plain.lower().find(needle)
                if idx >= 0:
                    start = max(0, idx - 30)
                    end = min(len(plain), idx + len(needle) + 60)
                    snippet = ("..." if start > 0 else "") + plain[start:end] + ("..." if end < len(plain) else "")
                    results.append({
                        "conversation_id": str(conv.id),
                        "conversation_title": conv.title or "Nueva conversación",
                        "message_id": str(msg.id),
                        "role": msg.role,
                        "snippet": snippet,
                        "created_at": msg.created_at.isoformat() if msg.created_at else "",
                    })
            except Exception:
                continue
    return results


def find_or_create_whatsapp_conversation(
    db: Session,
    uid: str,
) -> ConversationORM:
    """Busca conversación WhatsApp activa del usuario o la crea."""
    uid_uuid = UUID(uid)
    conv = (
        db.query(ConversationORM)
        .filter(
            ConversationORM.cliente_id == uid_uuid,
            ConversationORM.channel == "whatsapp",
            ConversationORM.archived_at.is_(None),
        )
        .order_by(ConversationORM.created_at)
        .first()
    )
    if conv is None:
        conv_id = uuid.uuid4()
        conv = ConversationORM(
            id=conv_id,
            cliente_id=uid_uuid,
            title="WhatsApp",
            provider="deepseek",
            channel="whatsapp",
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv
