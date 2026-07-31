"""Router de mensajeria WhatsApp bidireccional.

Endpoints:
- POST /v1/whatsapp/message        → enviar mensaje saliente
- GET  /v1/whatsapp/messages       → listar mensajes recientes de una conversacion
- POST /v1/whatsapp/messages/list  → listar mensajes recientes (alternativa POST)

Consume los servicios:
- whatsapp_client.send_whatsapp_message() para envio
- capabilities para catalogo de funcionalidades
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.whatsapp.inbound_service import get_message_store
from app.auth_deps import claims_uid, require_product_jwt
from app.domain.whatsapp.message import StoredWhatsAppMessage
from app.services.error_messages import translate_whatsapp_error
from app.services.document_output_service import resolve_document_path_for_send
from app.services.whatsapp_client import send_whatsapp_media, send_whatsapp_message
from app.services.whatsapp_link import get_channel_state

log = logging.getLogger("dot.whatsapp_messaging")

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])

# ─── Schemas ─────────────────────────────────────────────────────────────────


class SendMessageInput(BaseModel):
    to: str
    text: str


class SendMediaInput(BaseModel):
    path: str
    to: str | None = None
    caption: str = ""
    media_type: str = "document"


class SendMessageOutput(BaseModel):
    success: bool
    message_id: str | None = None
    error: str | None = None


class MessageItem(BaseModel):
    id: str
    from_me: bool
    text: str
    timestamp: str
    status: str = "sent"


class ListMessagesOutput(BaseModel):
    messages: list[MessageItem]
    phone_number: str | None = None
    error: str | None = None


class ListMessagesInput(BaseModel):
    phone: str | None = None
    limit: int = 50


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/message", response_model=SendMessageOutput)
async def send_message(
    body: SendMessageInput,
    claims: dict = Depends(require_product_jwt),
):
    """Envia un mensaje de WhatsApp a traves del bridge Baileys/Electron."""
    uid = claims_uid(claims)

    # Validar que el canal este vinculado
    state = get_channel_state(uid)
    if not state.linked:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp no esta vinculado. Escanea el QR primero.",
        )

    if not body.to.strip():
        raise HTTPException(status_code=400, detail="El destino (to) no puede estar vacio.")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="El texto del mensaje no puede estar vacio.")

    ok, bridge_result = await send_whatsapp_message(body.to.strip(), body.text.strip())
    if not ok:
        user_error = translate_whatsapp_error(bridge_result or "bridge_send_failed")
        return SendMessageOutput(success=False, error=user_error)

    message_id = bridge_result or f"wa_{int(datetime.now(timezone.utc).timestamp())}_{uid[:8]}"
    get_message_store().save(
        StoredWhatsAppMessage(
            id=message_id,
            uid=uid,
            from_phone=state.phone_number or "",
            to_phone=body.to.strip(),
            text=body.text.strip(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            direction="outbound",
            status="sent",
        )
    )
    log.info("Mensaje WhatsApp enviado uid=%s to=%s message_id=%s", uid, body.to, message_id)
    return SendMessageOutput(success=True, message_id=message_id)


@router.post("/outbound", response_model=SendMessageOutput)
async def send_outbound(
    body: SendMessageInput,
    claims: dict = Depends(require_product_jwt),
):
    """Alias operativo de POST /v1/whatsapp/message para envios salientes."""
    return await send_message(body, claims)


@router.post("/outbound/media", response_model=SendMessageOutput)
async def send_outbound_media(
    body: SendMediaInput,
    claims: dict = Depends(require_product_jwt),
):
    """Envia imagen o documento por WhatsApp via bridge local."""
    uid = claims_uid(claims)
    state = get_channel_state(uid)
    if not state.linked:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp no esta vinculado. Escanea el QR primero.",
        )

    path_raw = body.path.strip()
    if not path_raw:
        raise HTTPException(status_code=400, detail="La ruta del archivo no puede estar vacia.")

    resolved = resolve_document_path_for_send(path_raw)
    if resolved is None:
        return SendMessageOutput(success=False, error="No encuentro el archivo en esa ruta.")

    to = (body.to or state.phone_number or "").strip()
    if not to:
        raise HTTPException(
            status_code=400,
            detail="No hay numero de WhatsApp vinculado para enviar el documento.",
        )

    media_type = (body.media_type or "document").strip().lower()
    if media_type not in {"document", "image", "voice"}:
        media_type = "document"

    ok, bridge_result = await send_whatsapp_media(
        to,
        str(resolved),
        media_type=media_type,
        caption=body.caption.strip(),
    )
    if not ok:
        user_error = translate_whatsapp_error(bridge_result or "bridge_send_media_failed")
        return SendMessageOutput(success=False, error=user_error)

    message_id = bridge_result or f"wa_media_{int(datetime.now(timezone.utc).timestamp())}_{uid[:8]}"
    caption_note = body.caption.strip() or f"Documento: {resolved.name}"
    get_message_store().save(
        StoredWhatsAppMessage(
            id=message_id,
            uid=uid,
            from_phone=state.phone_number or "",
            to_phone=to,
            text=caption_note,
            timestamp=datetime.now(timezone.utc).isoformat(),
            direction="outbound",
            status="sent",
        )
    )
    log.info(
        "Documento WhatsApp enviado uid=%s to=%s path=%s message_id=%s",
        uid,
        to,
        resolved,
        message_id,
    )
    return SendMessageOutput(success=True, message_id=message_id)


@router.get("/messages", response_model=ListMessagesOutput)
async def list_messages(
    phone: str | None = None,
    limit: int = 50,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene mensajes recientes de WhatsApp desde el bridge local."""
    uid = claims_uid(claims)
    state = get_channel_state(uid)

    if not state.linked:
        return ListMessagesOutput(messages=[], phone_number=None)

    phone_number = phone or state.phone_number
    # Si phone_number aún es null (legado), listar igual por uid para no ocultar inbound ya guardado.
    stored = get_message_store().list_for_uid(uid, phone=phone_number, limit=limit)
    messages = [
        MessageItem(
            id=msg.id,
            from_me=msg.direction == "outbound",
            text=msg.text,
            timestamp=msg.timestamp or msg.created_at,
            status=msg.status,
        )
        for msg in stored
    ]
    log.debug("Listados %d mensajes para uid=%s phone=%s", len(messages), uid, phone_number)
    return ListMessagesOutput(messages=messages, phone_number=phone_number)


@router.post("/messages/list", response_model=ListMessagesOutput)
async def list_messages_post(
    body: ListMessagesInput,
    claims: dict = Depends(require_product_jwt),
):
    """Alternativa POST para listar mensajes recientes."""
    return await list_messages(
        phone=body.phone,
        limit=body.limit,
        claims=claims,
    )



