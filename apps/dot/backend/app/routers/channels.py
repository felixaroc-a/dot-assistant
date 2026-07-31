"""Router unificado multi-canal para DOT.

Centraliza el envío de mensajes a través de múltiples canales
(WhatsApp, Signal, Telegram, Discord) y el listado de canales disponibles.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt, claims_uid
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.channels.router")

router = APIRouter(prefix="/v1/channels", tags=["channels"])


# ─── Schemas ───────────────────────────────────────────────────────────


class SendMessageRequest(BaseModel):
    channel: str = Field(..., description="Canal: whatsapp, signal, telegram, discord")
    to: str = Field(..., min_length=1, description="Destinatario (teléfono, chat_id, etc.)")
    text: str = Field(..., min_length=1, max_length=4096, description="Mensaje a enviar")
    attachments: list[str] | None = Field(default=None, description="Archivos adjuntos")


class BroadcastRequest(BaseModel):
    channels: list[str] = Field(..., min_length=1, description="Canales a los que enviar")
    to: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=4096)
    attachments: list[str] | None = None


class ChannelInfo(BaseModel):
    id: str
    name: str
    icon: str
    enabled: bool
    status: str
    features: list[str]


class SendResponse(BaseModel):
    ok: bool
    channel: str | None = None
    message_id: str | None = None
    error: str | None = None


class BroadcastResponse(BaseModel):
    ok: bool
    results: dict[str, SendResponse] | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.get("", response_model=list[ChannelInfo])
async def list_channels():
    """Lista todos los canales de mensajería disponibles con su estado."""
    from app.services.channel_service import get_available_channels

    channels = get_available_channels()
    return [ChannelInfo(**ch) for ch in channels]


@router.post("/send", response_model=SendResponse)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Envía un mensaje a través del canal especificado.

    Canales soportados: whatsapp, signal, telegram, discord.
    Cada canal requiere su propia configuración (API key, token, etc.).
    """
    uid = claims_uid(claims)

    from app.services.channel_service import send_message as channel_send

    result = await channel_send(
        channel=body.channel,
        to=body.to,
        text=body.text,
        attachments=body.attachments,
        uid=uid,
    )

    return SendResponse(
        ok=result.get("ok", False),
        channel=body.channel,
        message_id=result.get("message_id"),
        error=result.get("error"),
    )


@router.post("/broadcast", response_model=BroadcastResponse)
@limiter.limit("10/minute")
async def broadcast_message(
    request: Request,
    body: BroadcastRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Envía el mismo mensaje a múltiples canales simultáneamente.

    Útil para notificaciones que deben llegar por todos los medios disponibles.
    """
    uid = claims_uid(claims)

    from app.services.channel_service import broadcast_message as channel_broadcast

    result = await channel_broadcast(
        channels=body.channels,
        to=body.to,
        text=body.text,
        attachments=body.attachments,
        uid=uid,
    )

    broadcast_results = {}
    for ch, r in result.get("results", {}).items():
        broadcast_results[ch] = SendResponse(
            ok=r.get("ok", False),
            channel=ch,
            message_id=r.get("message_id"),
            error=r.get("error"),
        )

    return BroadcastResponse(
        ok=result.get("ok", False),
        results=broadcast_results,
    )
