"""Router para el canal WhatsApp del cliente DOT.

Endpoints gestionados a traves de whatsapp_link.py.
Consumido por frontend/src/lib/api/whatsapp.ts.

Endpoints:
- GET  /v1/whatsapp/channel/status     → estado actual del canal
- POST /v1/whatsapp/channel/status     → actualizar estado (linked, phone, etc.)
- POST /v1/whatsapp/channel/events     → registrar evento operacional
- POST /v1/whatsapp/channel/reconnect  → limpiar estado y reiniciar
- POST /v1/whatsapp/inbound            → webhook para mensajes entrantes (llamado por Baileys)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.whatsapp.inbound_service import process_inbound_message
from app.application.whatsapp.auto_reply_service import (
    run_whatsapp_auto_reply,
    run_whatsapp_media_save_reply,
    run_whatsapp_stt_failure_reply,
)
from app.auth_deps import claims_uid, require_product_jwt
from app.billing_db import get_billing_db
from app.dependencies.limiter import limiter
from app.domain.whatsapp.message import InboundWhatsAppMessage
from app.services.whatsapp_link import (
    ChannelEventName,
    clear_channel_state,
    get_channel_state,
    record_channel_event,
    update_channel_state,
)
from app.settings import settings

log = logging.getLogger("dot.whatsapp_channel")

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])


_wa_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="wa-reply")

def _schedule_auto_reply(
    *,
    uid: str,
    message: InboundWhatsAppMessage,
    message_id: str,
    user_text: str | None = None,
) -> None:
    """No bloquea el webhook; usa executor compartido en vez de threads ilimitados."""

    def _run() -> None:
        try:
            run_whatsapp_auto_reply(
                uid=uid,
                message=message,
                message_id=message_id,
                user_text=user_text,
            )
        except Exception:
            log.exception("Auto-reply background falló message_id=%s", message_id)

    _wa_executor.submit(_run)


def _schedule_stt_failure_reply(
    *, uid: str, message: InboundWhatsAppMessage, message_id: str
) -> None:
    """Responde con mensaje humano si STT de nota de voz falló."""

    def _run() -> None:
        try:
            run_whatsapp_stt_failure_reply(uid=uid, message=message, message_id=message_id)
        except Exception:
            log.exception("STT failure reply background falló message_id=%s", message_id)

def _schedule_media_save_reply(
    *,
    uid: str,
    message: InboundWhatsAppMessage,
    message_id: str,
    reply_text: str,
) -> None:
    """Responde confirmación humana tras guardar adjunto WA en Escritorio."""

    def _run() -> None:
        try:
            run_whatsapp_media_save_reply(
                uid=uid,
                message=message,
                message_id=message_id,
                reply_text=reply_text,
            )
        except Exception:
            log.exception("Media save reply background falló message_id=%s", message_id)

    _wa_executor.submit(_run)




class WhatsAppChannelStatusResponse(BaseModel):
    status: str = "disconnected"
    linked: bool = False
    phone_number: str | None = None
    channel_name: str | None = None
    last_linked_at: str | None = None
    last_disconnected_at: str | None = None
    last_qr_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    reconnect_required: bool = False
    reconnect_attempts: int = 0
    error: str | None = None


class UpdateWhatsAppStatusInput(BaseModel):
    linked: bool
    phone_number: str | None = None
    channel_name: str | None = None
    error: str | None = None
    source: str | None = None


class WhatsAppChannelEventInput(BaseModel):
    event: ChannelEventName
    phone_number: str | None = None
    channel_name: str | None = None
    error: str | None = None
    source: str | None = None


class InboundMessagePayload(BaseModel):
    """Payload que Baileys o el bridge Electron envia al webhook."""

    message_id: str = ""
    from_phone: str = ""
    from_: str = Field(default="", alias="from")
    to_phone: str = ""
    to: str = ""
    text: str = ""
    body: str = ""
    timestamp: str = ""
    source: str = "baileys"
    is_group: bool = False
    group_name: str | None = None
    group_subject: str | None = None
    chat_name: str | None = None
    sender_name: str | None = None
    chat_jid: str | None = None
    # B07: notas de voz
    has_media: bool = False
    media_url: str | None = None
    has_audio: bool = False
    has_image: bool = False
    has_document: bool = False
    media_mime_type: str | None = None
    media_data_base64: str | None = None
    media_filename: str | None = None

    model_config = {"populate_by_name": True}

    def to_domain(self) -> InboundWhatsAppMessage:
        group_label = (
            (self.group_name or self.group_subject or self.chat_name or "").strip() or None
        )
        chat_jid = (self.chat_jid or "").strip() or None
        if not chat_jid and group_label and "@g.us" in group_label:
            chat_jid = group_label
        return InboundWhatsAppMessage(
            message_id=self.message_id,
            from_phone=(self.from_phone or self.from_ or "").strip(),
            to_phone=(self.to_phone or self.to or "").strip(),
            text=(self.text or self.body or "").strip(),
            timestamp=self.timestamp,
            source=self.source,
            is_group=bool(
                self.is_group
                or (chat_jid and chat_jid.endswith("@g.us"))
                or "@g.us" in (self.from_phone or "").lower()
            ),
            group_name=group_label,
            group_subject=group_label,
            sender_name=self.sender_name,
            chat_jid=chat_jid,
            # B07/B08: audio / imagen / documento
            media_url=self.media_url,
            has_audio=self.has_audio,
            has_image=self.has_image,
            has_document=self.has_document,
            media_mime_type=self.media_mime_type,
            media_data_base64=self.media_data_base64,
            media_filename=self.media_filename,
        )


class InboundMessageResponse(BaseModel):
    status: str = "ok"
    uid: str | None = None
    message_id: str | None = None
    stored: bool = False
    allow_auto_reply: bool = False
    detail: str | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def _state_to_response(state) -> WhatsAppChannelStatusResponse:
    """Convierte un WhatsAppChannelState (dataclass) a response Pydantic."""
    return WhatsAppChannelStatusResponse(
        status=state.status,
        linked=state.linked,
        phone_number=state.phone_number,
        channel_name=state.channel_name,
        last_linked_at=state.last_linked_at,
        last_disconnected_at=state.last_disconnected_at,
        last_qr_at=state.last_qr_at,
        last_heartbeat_at=state.last_heartbeat_at,
        last_error_at=state.last_error_at,
        reconnect_required=state.reconnect_required,
        reconnect_attempts=state.reconnect_attempts,
        error=state.error,
    )


# ─── Endpoints: Estado del canal ────────────────────────────────────────────


@router.get("/channel/status", response_model=WhatsAppChannelStatusResponse)
def get_status(claims: dict = Depends(require_product_jwt)):
    """Obtiene el estado actual del canal WhatsApp del usuario autenticado."""
    uid = claims_uid(claims)
    state = get_channel_state(uid)
    log.debug("GET status uid=%s: linked=%s status=%s", uid, state.linked, state.status)
    return _state_to_response(state)


@router.post("/channel/status", response_model=WhatsAppChannelStatusResponse)
def update_status(
    body: UpdateWhatsAppStatusInput,
    claims: dict = Depends(require_product_jwt),
):
    """Actualiza el estado del canal WhatsApp (linked, phone, error)."""
    uid = claims_uid(claims)
    state = update_channel_state(
        uid,
        linked=body.linked,
        phone_number=body.phone_number,
        channel_name=body.channel_name,
        error=body.error,
    )
    log.info(
        "POST status uid=%s: linked=%s phone=%s source=%s",
        uid, body.linked, body.phone_number, body.source,
    )
    return _state_to_response(state)


@router.post("/channel/events", response_model=WhatsAppChannelStatusResponse)
def post_event(
    body: WhatsAppChannelEventInput,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Registra un evento operacional del canal (qr_ready, linked, disconnected, etc.)."""
    uid = claims_uid(claims)
    state = record_channel_event(
        uid,
        body.event,
        phone_number=body.phone_number,
        channel_name=body.channel_name,
        error=body.error,
    )

    # B01: auto-crear conversación WhatsApp al vincular
    if body.event == "linked" and state.linked:
        try:
            from app.services.chat_persistence import find_or_create_whatsapp_conversation
            conv = find_or_create_whatsapp_conversation(db, uid)
            log.info("B01 WhatsApp conv auto-creada uid=%s conv_id=%s", uid[:8], str(conv.id))
        except Exception:
            log.warning("No se pudo crear conversación WA para uid=%s", uid[:8], exc_info=True)

    log.info(
        "POST events uid=%s: event=%s source=%s",
        uid, body.event, body.source,
    )
    return _state_to_response(state)


@router.post("/channel/reconnect", response_model=WhatsAppChannelStatusResponse)
def reconnect(claims: dict = Depends(require_product_jwt)):
    """Limpia el estado del canal y reinicia a disconnected."""
    uid = claims_uid(claims)
    clear_channel_state(uid)
    state = get_channel_state(uid)
    log.info("POST reconnect uid=%s: estado reiniciado", uid)
    return _state_to_response(state)


# ─── Webhook: Mensajes entrantes desde Baileys ─────────────────────────────


@router.post("/inbound")
@limiter.limit("30/minute")
async def inbound_webhook(
    request: Request,
    body: InboundMessagePayload | None = None,
):
    """
    Webhook para recibir mensajes entrantes de WhatsApp desde Baileys/Electron.

    Con allow_auto_reply, encola auto-reply con el mismo cerebro del chat PC.
    """
    # Extraer payload (soporta JSON directo en el body)
    payload = body
    if payload is None:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                # Compatibilidad con contrato docs/whatsapp-integration-plan.md
                if "from" in raw and "from_phone" not in raw:
                    raw["from_phone"] = raw.get("from")
                if "body" in raw and "text" not in raw:
                    raw["text"] = raw.get("body")
            payload = InboundMessagePayload(**raw)
        except Exception as e:
            log.warning("Webhook inbound: payload invalido: %s", e)
            return InboundMessageResponse(status="error", detail="Payload invalido")

    # F1: fail-closed — auth antes de procesar (excepto TESTING=1 sin secreto).
    webhook_secret = settings.whatsapp_webhook_secret.strip()
    if not webhook_secret:
        if settings.testing.strip() != "1":
            log.error("WHATSAPP_WEBHOOK_SECRET vacío — inbound rechazado (fail-closed)")
            raise HTTPException(
                status_code=503,
                detail="Webhook WhatsApp no configurado (falta WHATSAPP_WEBHOOK_SECRET).",
            )
    else:
        received_secret = request.headers.get("X-Webhook-Secret", "")
        if received_secret != webhook_secret:
            log.warning("Webhook inbound: secreto invalido")
            raise HTTPException(status_code=401, detail="Secreto invalido")

    # B07/B08: Electron envía flags explícitos; inferir solo si faltan.
    if payload.has_media and not payload.has_audio and not payload.has_image and not payload.has_document:
        if payload.media_mime_type:
            mime = (payload.media_mime_type or "").lower()
            if mime.startswith("audio/"):
                payload.has_audio = True
            elif mime.startswith("image/"):
                payload.has_image = True
            elif mime.startswith("application/") or mime.startswith("text/"):
                payload.has_document = True
        elif payload.media_data_base64 and payload.has_audio is False:
            # Compat legacy: base64 sin MIME → asumir audio solo si no hay imagen/doc
            payload.has_audio = True

    # B07: auto-detectar audio por URL/MIME si no viene marcado
    if payload.media_url and not payload.has_audio:
        audio_exts = (".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac")
        if any(payload.media_url.lower().endswith(ext) or f".{ext}?" in payload.media_url.lower()
               for ext in audio_exts):
            payload.has_audio = True
            log.info("Webhook: audio auto-detectado por URL media_url=%s", payload.media_url[:100])
    if payload.media_mime_type and not payload.has_audio:
        if (payload.media_mime_type or "").startswith("audio/"):
            payload.has_audio = True
            log.info("Webhook: audio auto-detectado por MIME type=%s", payload.media_mime_type)

    domain = payload.to_domain()
    has_content = bool(
        domain.text
        or domain.has_audio
        or domain.has_image
        or domain.has_document
    )
    if not domain.from_phone or not has_content:
        log.warning("Webhook inbound: payload incompleto")
        return InboundMessageResponse(status="ignored", detail="Payload incompleto")

    log.info(
        "Mensaje entrante WhatsApp de=%s to=%s texto_chars=%d has_audio=%s has_image=%s has_document=%s message_id=%s source=%s",
        domain.from_phone,
        domain.to_phone,
        len(domain.text or ""),
        domain.has_audio,
        domain.has_image,
        domain.has_document,
        domain.message_id,
        domain.source,
    )

    try:
        result = process_inbound_message(domain)
    except Exception as e:
        log.exception("Error procesando mensaje entrante: %s", e)
        return InboundMessageResponse(status="error", detail="Error interno")

    effective_text = str(result.get("effective_text") or domain.text or "").strip()
    stt_failed = bool(result.get("stt_failed"))
    reply_domain = replace(domain, text=effective_text) if effective_text else domain

    # B3: Notificar al frontend via WebSocket que llego un mensaje WA
    uid_str = str(result.get("uid")) if result.get("uid") else None
    if uid_str:
        try:
            from app.services.ws_manager import notify_whatsapp_inbound
            ws_text = effective_text or domain.text
            if result.get("voice_transcribed"):
                ws_text = f"🎤 Nota de voz: {effective_text}"
            await notify_whatsapp_inbound(
                uid_str,
                {
                    "from_phone": domain.from_phone,
                    "text": ws_text,
                    "timestamp": domain.timestamp,
                    "message_id": domain.message_id,
                    "conversation_id": result.get("conversation_id"),
                    "has_audio": domain.has_audio,
                    "voice_transcribed": bool(result.get("voice_transcribed")),
                },
            )
        except Exception:
            log.debug("Error notificando WS whatsapp:inbound uid=%s", uid_str[:8], exc_info=True)

    # B1/B2: mismo cerebro chat -> outbound bridge (hilo daemon)
    if result.get("allow_auto_reply") and result.get("uid") and result.get("message_id"):
        if stt_failed:
            _schedule_stt_failure_reply(
                uid=str(result["uid"]),
                message=domain,
                message_id=str(result["message_id"]),
            )
        elif result.get("media_save_message"):
            _schedule_media_save_reply(
                uid=str(result["uid"]),
                message=domain,
                message_id=str(result["message_id"]),
                reply_text=str(result["media_save_message"]),
            )
        elif effective_text:
            _schedule_auto_reply(
                uid=str(result["uid"]),
                message=reply_domain,
                message_id=str(result["message_id"]),
                user_text=effective_text,
            )

    # F3: Evaluar mandatos activos del usuario contra este mensaje entrante
    if uid_str and effective_text:
        try:
            from app.application.whatsapp.mandate_evaluator import evaluate_mandates_async
            evaluate_mandates_async(uid_str, effective_text, domain.from_phone)
        except Exception:
            log.debug("Error lanzando evaluador de mandatos uid=%s", uid_str[:8], exc_info=True)

    return InboundMessageResponse(
        status=result.get("status", "ok"),
        uid=result.get("uid"),
        message_id=result.get("message_id"),
        stored=bool(result.get("stored")),
        allow_auto_reply=bool(result.get("allow_auto_reply")),
        detail=result.get("detail"),
    )
