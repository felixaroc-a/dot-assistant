"""Router para el canal Signal del cliente DOT.

Consumido por frontend Electron para gestionar el puente Signal via signal-cli.
Gate: SIGNAL_ENABLED=true habilita todos los endpoints.

Endpoints:
- GET  /v1/signal/channel/status     → estado actual del canal
- POST /v1/signal/channel/status     → actualizar estado (linked, phone, etc.)
- POST /v1/signal/channel/events     → registrar evento operacional
- POST /v1/signal/send               → enviar mensaje via signal-cli
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import require_product_jwt
from app.billing_db import get_billing_db
from app.dependencies.limiter import limiter
from app.services.signal_service import (
    get_signal_channel_state,
    update_signal_channel_state,
    record_signal_channel_event,
    send_signal_message,
    SignalChannelStatus,
)
from app.settings import settings

log = logging.getLogger("dot.signal_channel")

router = APIRouter(prefix="/v1/signal", tags=["signal"])


# ─── Schemas ──────────────────────────────────────────────────────────

class SignalChannelStatusResponse(BaseModel):
    enabled: bool = False
    linked: bool = False
    phone_number: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


class UpdateSignalStatusInput(BaseModel):
    linked: bool = False
    phone_number: str | None = None
    error: str | None = None


class SignalEventInput(BaseModel):
    event: str = Field(..., description="Nombre del evento: linked, disconnected, heartbeat, error, message_sent")
    phone_number: str | None = None
    error: str | None = None
    metadata: dict | None = None


class SignalSendInput(BaseModel):
    phone: str = Field(..., description="Número de destino en formato internacional (+584241234567)")
    text: str = Field(..., min_length=1, max_length=4096, description="Mensaje a enviar")
    attachments: list[str] | None = Field(default=None, description="Lista de rutas a archivos para adjuntar")


class SignalSendResponse(BaseModel):
    ok: bool
    message_id: str | None = None
    error: str | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.get("/channel/status", response_model=SignalChannelStatusResponse)
async def get_signal_status(
    request: Request,
    db: Session = Depends(get_billing_db),
    _=Depends(require_product_jwt),
):
    """Estado actual del canal Signal."""
    if not settings.signal_enabled:
        raise HTTPException(status_code=404, detail="Canal Signal no habilitado")

    state = get_signal_channel_state(db)
    return SignalChannelStatusResponse(
        enabled=settings.signal_enabled,
        linked=state.linked,
        phone_number=state.phone_number,
        last_linked_at=state.last_linked_at,
        last_heartbeat_at=state.last_heartbeat_at,
        last_error_at=state.last_error_at,
        error=state.error,
    )


@router.post("/channel/status")
@limiter.limit("30/minute")
async def update_signal_status(
    request: Request,
    body: UpdateSignalStatusInput,
    db: Session = Depends(get_billing_db),
    _=Depends(require_product_jwt),
):
    """Actualiza el estado del canal Signal (linked, phone, error)."""
    if not settings.signal_enabled:
        raise HTTPException(status_code=404, detail="Canal Signal no habilitado")

    update_signal_channel_state(
        db,
        linked=body.linked,
        phone_number=body.phone_number,
        error=body.error,
    )
    return {"ok": True}


@router.post("/channel/events")
@limiter.limit("60/minute")
async def record_signal_event(
    request: Request,
    body: SignalEventInput,
    db: Session = Depends(get_billing_db),
    _=Depends(require_product_jwt),
):
    """Registra un evento operacional del canal Signal."""
    if not settings.signal_enabled:
        raise HTTPException(status_code=404, detail="Canal Signal no habilitado")

    record_signal_channel_event(
        db,
        event=body.event,
        phone_number=body.phone_number,
        error=body.error,
        metadata=body.metadata,
    )
    return {"ok": True}


@router.post("/send", response_model=SignalSendResponse)
@limiter.limit("20/minute")
async def signal_send_endpoint(
    request: Request,
    body: SignalSendInput,
    _=Depends(require_product_jwt),
):
    """Envía un mensaje via Signal usando signal-cli."""
    if not settings.signal_enabled:
        raise HTTPException(status_code=404, detail="Canal Signal no habilitado")

    result = send_signal_message(
        phone=body.phone,
        text=body.text,
        attachments=body.attachments,
    )
    return SignalSendResponse(**result)
