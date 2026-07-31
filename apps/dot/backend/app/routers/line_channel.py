"""Router para el canal LINE Messaging del cliente DOT.

Consumido por frontend Electron para gestionar el puente LINE via Messaging API.
Gate: LINE_ENABLED=true habilita todos los endpoints.

Endpoints:
- GET  /v1/line/channel/status     → estado actual del canal
- POST /v1/line/channel/status     → actualizar estado
- POST /v1/line/channel/events     → registrar evento operacional
- POST /v1/line/webhook            → webhook para mensajes entrantes
- POST /v1/line/send               → enviar mensaje push
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter
from app.services.line_service import (
    get_line_channel_state,
    update_line_channel_state,
    record_line_channel_event,
    send_line_push_message,
    process_line_webhook,
    LineChannelStatus,
)
from app.settings import settings

log = logging.getLogger("dot.line_channel")

router = APIRouter(prefix="/v1/line", tags=["line"])


# ─── Schemas ──────────────────────────────────────────────────────────

class LineChannelStatusResponse(BaseModel):
    enabled: bool = False
    linked: bool = False
    bot_name: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


class UpdateLineStatusInput(BaseModel):
    linked: bool = False
    bot_name: str | None = None
    error: str | None = None


class LineEventInput(BaseModel):
    event: str = Field(..., description="Nombre del evento: linked, disconnected, heartbeat, error, message_sent")
    bot_name: str | None = None
    error: str | None = None
    metadata: dict | None = None


class LineSendInput(BaseModel):
    user_id: str = Field(..., description="LINE user ID del destinatario")
    text: str = Field(..., min_length=1, max_length=5000)
    notification_disabled: bool = Field(default=False, description="Si true, no envía notificación push")


class LineSendResponse(BaseModel):
    ok: bool
    message_id: str | None = None
    error: str | None = None


class LineMulticastInput(BaseModel):
    user_ids: list[str] = Field(..., min_length=1, max_length=500)
    text: str = Field(..., min_length=1, max_length=5000)


class LineMulticastResponse(BaseModel):
    ok: bool
    sent_to: int = 0
    error: str | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.get("/channel/status", response_model=LineChannelStatusResponse)
async def get_line_status(
    request: Request,
    _=Depends(require_product_jwt),
):
    """Estado actual del canal LINE."""
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    state = get_line_channel_state()
    return LineChannelStatusResponse(
        enabled=settings.line_enabled,
        linked=state.linked,
        bot_name=state.bot_name,
        last_linked_at=state.last_linked_at,
        last_heartbeat_at=state.last_heartbeat_at,
        last_error_at=state.last_error_at,
        error=state.error,
    )


@router.post("/channel/status")
@limiter.limit("30/minute")
async def update_line_status(
    request: Request,
    body: UpdateLineStatusInput,
    _=Depends(require_product_jwt),
):
    """Actualiza el estado del canal LINE."""
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    update_line_channel_state(
        linked=body.linked,
        bot_name=body.bot_name,
        error=body.error,
    )
    return {"ok": True}


@router.post("/channel/events")
@limiter.limit("60/minute")
async def record_line_event(
    request: Request,
    body: LineEventInput,
    _=Depends(require_product_jwt),
):
    """Registra un evento operacional del canal LINE."""
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    record_line_channel_event(
        event=body.event,
        bot_name=body.bot_name,
        error=body.error,
        metadata=body.metadata,
    )
    return {"ok": True}


@router.post("/webhook")
@limiter.limit("120/minute")
async def line_webhook(
    request: Request,
):
    """Webhook para mensajes entrantes de LINE Messaging API.

    LINE envía eventos (message, follow, unfollow, join, leave, postback)
    a este endpoint. Requiere verificar firma con LINE_CHANNEL_SECRET.
    """
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    body_bytes = await request.body()
    signature = request.headers.get("x-line-signature", "")

    result = process_line_webhook(body_bytes, signature)
    if not result.get("ok"):
        log.warning("line_webhook fail: %s", result.get("error"))
        raise HTTPException(status_code=400, detail=result.get("error", "Invalid signature"))

    return {"ok": True, "events_processed": result.get("events_processed", 0)}


@router.post("/send", response_model=LineSendResponse)
@limiter.limit("20/minute")
async def line_send_endpoint(
    request: Request,
    body: LineSendInput,
    _=Depends(require_product_jwt),
):
    """Envía un mensaje push a un usuario via LINE Messaging API."""
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    result = send_line_push_message(
        user_id=body.user_id,
        text=body.text,
        notification_disabled=body.notification_disabled,
    )
    return LineSendResponse(**result)


@router.post("/multicast", response_model=LineMulticastResponse)
@limiter.limit("10/minute")
async def line_multicast_endpoint(
    request: Request,
    body: LineMulticastInput,
    _=Depends(require_product_jwt),
):
    """Envía un mensaje multicast a múltiples usuarios LINE."""
    if not settings.line_enabled:
        raise HTTPException(status_code=404, detail="Canal LINE no habilitado")

    result = send_line_push_message(
        user_ids=body.user_ids,
        text=body.text,
    )
    return LineMulticastResponse(
        ok=result.get("ok", False),
        sent_to=len(body.user_ids) if result.get("ok") else 0,
        error=result.get("error"),
    )
