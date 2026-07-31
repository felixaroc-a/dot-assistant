"""Procesamiento de mensajes WhatsApp entrantes."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re

from app.domain.whatsapp.message import InboundWhatsAppMessage, StoredWhatsAppMessage
from app.infrastructure.whatsapp.message_store import WhatsAppMessageStore
from app.infrastructure.whatsapp.phone_resolver import (
    phones_match,
    resolve_uid_by_to_phone,
    to_e164,
)
from app.services.whatsapp_link import get_channel_state, record_channel_event
from app.settings import settings

log = logging.getLogger("dot.whatsapp.inbound")

_store = WhatsAppMessageStore()

# B07: mensaje humano cuando STT falla en nota de voz WhatsApp
WHATSAPP_STT_FAILURE_MESSAGE = "No pude escuchar el audio, ¿me lo escribes?"



def get_message_store() -> WhatsAppMessageStore:
    return _store


def normalize_phone(phone: str) -> str:
    e164 = to_e164(phone)
    if e164:
        return e164.lstrip("+")
    digits = re.sub(r"\D", "", phone or "")
    return digits[-15:] if digits else ""


def normalize_inbound_text(text: str) -> str:
    """Con Baileys el texto llega limpio, sin prefijos que limpiar."""
    return (text or "").strip()


def build_message_id(message: InboundWhatsAppMessage) -> str:
    if message.message_id.strip():
        return message.message_id.strip()
    digest = hashlib.sha256(
        f"{message.from_phone}|{message.to_phone}|{message.timestamp}|{message.text}".encode()
    ).hexdigest()[:24]
    return f"wa_in_{digest}"


def _escape_regex(value: str) -> str:
    return re.escape(value)


def is_dot_group_name(name: str | None, expected: str | None = None) -> bool:
    needle = (expected or settings.whatsapp_reply_group_name or "DOT").strip()
    if not needle:
        return False
    hay = (name or "").strip()
    if not hay:
        return False
    if hay.casefold() == needle.casefold():
        return True
    # No tratar JIDs @g.us como nombre de grupo.
    if "@g.us" in hay.lower():
        return False
    pattern = re.compile(
        rf"(?:^|[^a-z0-9]){_escape_regex(needle)}(?:[^a-z0-9]|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(hay))


def text_mentions_dot(text: str, token: str | None = None) -> bool:
    needle = (token or settings.whatsapp_reply_mention_token or "DOT").strip()
    if not needle:
        return False
    body = text or ""
    if not body:
        return False
    pattern = re.compile(
        rf"(?:^|[^a-z0-9_])@?{_escape_regex(needle)}(?:[^a-z0-9_]|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(body))


def should_allow_auto_reply(
    *,
    from_phone: str,
    linked_phone: str | None,
    text: str = "",
    is_group: bool = False,
    group_name: str | None = None,
    chat_jid: str | None = None,
) -> bool:
    """
    Política WhatsApp (`WHATSAPP_REPLY_POLICY`):

    - dot_group_mention (default Fase A): solo grupo cuyo nombre es/contiene "DOT"
      y el cuerpo menciona "DOT"; opcionalmente remite el dueño (linked phone).
    - self_only: solo auto-responder si el remitente es el número vinculado.
    - all: permitir auto-reply a cualquier remitente (no recomendado).

    Mensajes de terceros se pueden ingerir/loguear, pero no encolar reply automático.
    """
    policy = (settings.whatsapp_reply_policy or "dot_group_mention").strip().lower()

    if policy == "all":
        return True

    if policy in {"dot_group_mention", "dot_group"}:
        if not is_group:
            return False
        allowed_jids = {
            j.strip()
            for j in (settings.whatsapp_reply_group_jids or "").split(",")
            if j.strip()
        }
        jid_ok = bool(chat_jid and chat_jid in allowed_jids)
        if not is_dot_group_name(group_name) and not jid_ok:
            return False
        if settings.whatsapp_reply_require_mention and not text_mentions_dot(text):
            return False
        if settings.whatsapp_reply_require_self:
            # WhatsApp a veces identifica al remitente con LID (no E.164).
            # Si no hay teléfono comparable, no bloquear el reply del grupo DOT+mención.
            if linked_phone and from_phone and phones_match(linked_phone, from_phone):
                return True
            if not from_phone or len(re.sub(r"\D", "", from_phone or "")) > 13:
                log.info(
                    "Auto-reply grupo DOT: require_self omitido (remitente LID/no-E164) from=%s",
                    from_phone,
                )
                return True
            return False
        return True

    # self_only (y cualquier valor desconocido → fail-closed a self_only)
    if not linked_phone:
        return False
    return phones_match(linked_phone, from_phone)


def _persist_to_chat_history(uid: str, text: str, from_phone: str, timestamp: str) -> str | None:
    """Persiste un mensaje WhatsApp inbound en chat_history para que aparezca en el chat PC.

    B3 (BIBLIA §19.3): Single DOT thread, two entry screens.
    Los mensajes que llegan por WhatsApp deben verse en el timeline del chat PC.

    Returns:
        conversation_id (str) si ok, None si falló.
    """
    try:
        from app.billing_db import get_session_factory
        from app.services.chat_persistence import append_whatsapp_chat_message

        ts_label = ""
        if timestamp:
            try:
                from datetime import datetime as dt
                parsed = dt.fromisoformat(timestamp.replace("Z", "+00:00"))
                local = parsed.astimezone()
                ts_label = local.strftime("%d/%m %H:%M")
            except (ValueError, TypeError):
                pass

        phone_label = from_phone[-10:] if len(from_phone) > 10 else from_phone or "WA"
        prefix = f"[WA {phone_label}"
        if ts_label:
            prefix += f" {ts_label}"
        prefix += "]"

        content = f"{prefix} {text}"

        factory = get_session_factory()
        session = factory()
        try:
            conv = append_whatsapp_chat_message(session, uid, "user", content)
            log.debug(
                "Mensaje WA persistido en chat_history uid=%s conv=%s chars=%d",
                uid[:8], str(conv.id)[:8], len(content),
            )
            return str(conv.id)
        finally:
            session.close()
    except Exception:
        log.warning(
            "No se pudo persistir mensaje WA en chat_history uid=%s (DB no disponible o sin cifrado)",
            uid[:8] if uid else "?",
            exc_info=True,
        )
        return None


def process_inbound_message(message: InboundWhatsAppMessage) -> dict:
    """
    Persiste un mensaje entrante y actualiza heartbeat del canal.

    B07: Si el mensaje es una nota de voz (has_audio=True), descarga y
    transcribe el audio vía voice_service, luego procesa la transcripción
    como texto normal.

    Returns:
        dict con status, uid, message_id, stored, allow_auto_reply
    """
    text = normalize_inbound_text(message.text)
    from_phone = normalize_phone(message.from_phone)
    to_phone = normalize_phone(message.to_phone)
    group_name = (message.group_name or message.group_subject or "").strip() or None

    # B07: detección de nota de voz
    is_voice_note = bool(message.has_audio)
    voice_transcribed = False
    voice_transcription = ""
    voice_note_label = ""

    if is_voice_note:
        voice_note_label = "🎤 Nota de voz"
        log.info(
            "WhatsApp voice note detectado from=%s media_url=%s message_id=%s",
            from_phone,
            message.media_url or "inline_data",
            message.message_id,
        )

    if not from_phone or (not text and not is_voice_note and not message.has_image and not message.has_document):
        return {"status": "ignored", "detail": "Mensaje sin remitente o contenido", "allow_auto_reply": False}

    message_id = build_message_id(message)
    # El UID se resuelve por el número del canal vinculado (campo `to` del inbound).
    uid = resolve_uid_by_to_phone(message.to_phone)
    if not uid and message.from_phone:
        # Compat: self-chat a veces intercambia from/to en logs.
        uid = resolve_uid_by_to_phone(message.from_phone)

    if uid:
        # WA cuenta como uso para retención D5 (BIBLIA §11).
        from app.services.activity_service import touch_last_active_best_effort

        touch_last_active_best_effort(uid)

    # B08: adjuntos imagen/documento cacheados para guardar en PC
    has_saveable_media = False
    media_kind: str | None = None
    media_auto_saved = False
    media_saved_path: str | None = None
    media_save_message: str | None = None

    if uid:
        from app.application.whatsapp.whatsapp_media_service import (
            cache_inbound_media,
            has_saveable_inbound_media,
            media_kind_from_message,
            try_auto_save_inbound_media,
        )

        if has_saveable_inbound_media(message):
            has_saveable_media = True
            media_kind = media_kind_from_message(message)
            cache_inbound_media(uid, message)
            auto_save = try_auto_save_inbound_media(uid, message)
            if auto_save is not None:
                media_auto_saved = auto_save.ok
                media_saved_path = auto_save.path
                if auto_save.ok:
                    media_save_message = auto_save.human_message
                else:
                    from app.application.whatsapp.whatsapp_media_service import (
                        build_save_confirmation_message,
                    )

                    media_save_message = build_save_confirmation_message(auto_save)

        # B07: transcribir nota de voz si es audio
        if is_voice_note:
            try:
                audio_bytes: bytes | None = None
                audio_mime: str = "audio/ogg"

                # Determinar MIME type del audio
                if message.media_mime_type:
                    audio_mime = message.media_mime_type
                elif message.media_url:
                    ext = (message.media_url or "").split("?")[0].rsplit(".", 1)[-1].lower()
                    mime_map = {
                        "ogg": "audio/ogg",
                        "oga": "audio/ogg",
                        "mp4": "audio/mp4",
                        "m4a": "audio/mp4",
                        "webm": "audio/webm",
                        "mp3": "audio/mpeg",
                        "wav": "audio/wav",
                        "opus": "audio/ogg",
                    }
                    audio_mime = mime_map.get(ext, "audio/ogg")

                # Intentar obtener los bytes: inline data primero, luego URL
                if message.media_data_base64:
                    audio_bytes = base64.b64decode(message.media_data_base64)
                    log.info("Voice note: usando inline base64 data len=%s", len(audio_bytes))
                elif message.media_url:
                    try:
                        import httpx

                        async def _download():
                            async with httpx.AsyncClient(timeout=30) as client:
                                resp = await client.get(message.media_url)
                                resp.raise_for_status()
                                return resp.content

                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                future = pool.submit(asyncio.run, _download())
                                audio_bytes = future.result(timeout=35)
                        else:
                            audio_bytes = asyncio.run(_download())
                        log.info(
                            "Voice note: descargado de URL len=%s url=%s",
                            len(audio_bytes),
                            message.media_url[:100],
                        )
                    except Exception as download_err:
                        log.warning("Voice note: fallo al descargar audio url=%s: %s", message.media_url, download_err)

                if audio_bytes and len(audio_bytes) >= 64:
                    from app.services.voice_service import transcribe_audio as transcribe_fn

                    voice_transcription = asyncio.run(
                        transcribe_fn(audio_bytes, audio_mime, language="es")
                    )
                    if voice_transcription:
                        voice_transcribed = True
                        log.info(
                            "Voice note transcrito ok from=%s chars=%s",
                            from_phone,
                            len(voice_transcription),
                        )
                    else:
                        log.warning("Voice note: transcripción vacía from=%s", from_phone)
                else:
                    log.warning(
                        "Voice note: sin datos de audio descargables from=%s has_inline=%s has_url=%s",
                        from_phone,
                        bool(message.media_data_base64),
                        bool(message.media_url),
                    )
            except Exception as exc:
                log.exception("Voice note: error transcribiendo from=%s: %s", from_phone, exc)

        channel = get_channel_state(uid)
        linked_phone = channel.phone_number or to_e164(message.to_phone)
        record_channel_event(
            uid,
            "heartbeat",
            phone_number=linked_phone or message.to_phone or message.from_phone,
        )

        # Texto efectivo para procesar: transcripción si es nota de voz, sino texto original
        stt_failed = is_voice_note and not voice_transcribed
        effective_text = voice_transcription if voice_transcribed else text
        if stt_failed:
            effective_text = ""
        display_text = f"{voice_note_label}: {voice_transcription}" if voice_transcribed else text
        if stt_failed:
            display_text = voice_note_label or "🎤 Nota de voz"
        if has_saveable_media and not voice_transcribed:
            if media_kind == "image":
                display_text = f"📷 Imagen{f': {text}' if text and text != '[media]' else ''}"
            elif media_kind == "document":
                fname = (message.media_filename or "").strip()
                doc_label = f"📄 {fname}" if fname else "📄 Documento"
                display_text = f"{doc_label}{f': {text}' if text and text != '[media]' else ''}"

        stored = StoredWhatsAppMessage(
            id=message_id,
            uid=uid,
            from_phone=from_phone,
            to_phone=to_phone,
            text=effective_text,
            timestamp=message.timestamp or "",
            direction="inbound",
            status="received",
        )
        _store.save(stored)

        # B3: persistir en chat_history para que el mensaje aparezca en el chat PC
        conv_id = _persist_to_chat_history(uid, display_text, from_phone, message.timestamp or "")

        allow_reply = should_allow_auto_reply(
            from_phone=message.from_phone,
            linked_phone=linked_phone or channel.phone_number,
            text=effective_text,  # usar transcripción para la política de reply
            is_group=bool(message.is_group),
            group_name=group_name,
            chat_jid=(message.chat_jid or "").strip() or None,
        )
        if not allow_reply:
            log.info(
                "Inbound WhatsApp sin auto-reply (policy=%s) uid=%s from=%s linked=%s group=%s is_group=%s",
                settings.whatsapp_reply_policy,
                uid,
                from_phone,
                linked_phone,
                group_name,
                message.is_group,
            )
        else:
            log.info(
                "Mensaje WhatsApp inbound uid=%s from=%s message_id=%s chars=%d allow_auto_reply=1",
                uid,
                from_phone,
                message_id,
                len(text),
            )
        return {
            "status": "ok",
            "uid": uid,
            "message_id": message_id,
            "stored": True,
            "allow_auto_reply": allow_reply,
            "conversation_id": conv_id,
            "effective_text": effective_text,
            "stt_failed": stt_failed,
            "voice_transcribed": voice_transcribed,
            "has_saveable_media": has_saveable_media,
            "media_kind": media_kind,
            "media_auto_saved": media_auto_saved,
            "media_saved_path": media_saved_path,
            "media_save_message": media_save_message,
        }

    log.info(
        "Mensaje WhatsApp inbound sin usuario vinculado from=%s to=%s message_id=%s",
        from_phone,
        to_phone,
        message_id,
    )
    return {
        "status": "ok",
        "uid": None,
        "message_id": message_id,
        "stored": False,
        "allow_auto_reply": False,
        "detail": "No se encontró usuario para el número vinculado",
    }
