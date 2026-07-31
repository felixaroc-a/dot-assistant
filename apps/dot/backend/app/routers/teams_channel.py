"""Router para el canal Microsoft Teams del cliente DOT.

Consumido por frontend Electron para gestionar el puente Teams via MS Graph API.
Gate: TEAMS_ENABLED=true habilita todos los endpoints.
Requiere app registration en Azure AD (Teams app con permisos TeamsMessaging).

Endpoints:
- GET  /v1/teams/channel/status     → estado actual del canal
- POST /v1/teams/channel/status     → actualizar estado
- POST /v1/teams/channel/events     → registrar evento operacional
- POST /v1/teams/webhook            → webhook para mensajes entrantes (Teams Activity Feed)
- POST /v1/teams/send               → enviar mensaje a chat/canal
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter
from app.services.teams_service import (
    get_teams_channel_state,
    update_teams_channel_state,
    record_teams_channel_event,
    send_teams_message,
    process_teams_webhook,
    TeamsChannelStatus,
)
from app.settings import settings

log = logging.getLogger("dot.teams_channel")

router = APIRouter(prefix="/v1/teams", tags=["teams"])


# ─── Schemas ──────────────────────────────────────────────────────────

class TeamsChannelStatusResponse(BaseModel):
    enabled: bool = False
    linked: bool = False
    tenant_id: str | None = None
    app_name: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


class UpdateTeamsStatusInput(BaseModel):
    linked: bool = False
    app_name: str | None = None
    error: str | None = None


class TeamsEventInput(BaseModel):
    event: str = Field(..., description="Nombre del evento: linked, disconnected, heartbeat, error, message_sent")
    app_name: str | None = None
    error: str | None = None
    metadata: dict | None = None


class TeamsSendInput(BaseModel):
    chat_id: str | None = Field(default=None, description="ID del chat 1:1 o grupo de Teams")
    team_id: str | None = Field(default=None, description="ID del team (si se envía a canal)")
    channel_id: str | None = Field(default=None, description="ID del canal dentro del team")
    text: str = Field(..., min_length=1, max_length=25000, description="Mensaje (soporta HTML básico)")
    importance: str | None = Field(default=None, pattern="^(low|normal|high)$", description="Importancia del mensaje")


class TeamsSendResponse(BaseModel):
    ok: bool
    message_id: str | None = None
    error: str | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.get("/channel/status", response_model=TeamsChannelStatusResponse)
async def get_teams_status(
    request: Request,
    _=Depends(require_product_jwt),
):
    """Estado actual del canal Teams."""
    if not settings.teams_enabled:
        raise HTTPException(status_code=404, detail="Canal Teams no habilitado")

    state = get_teams_channel_state()
    return TeamsChannelStatusResponse(
        enabled=settings.teams_enabled,
        linked=state.linked,
        tenant_id=settings.teams_tenant_id or None,
        app_name=state.app_name,
        last_linked_at=state.last_linked_at,
        last_heartbeat_at=state.last_heartbeat_at,
        last_error_at=state.last_error_at,
        error=state.error,
    )


@router.post("/channel/status")
@limiter.limit("30/minute")
async def update_teams_status(
    request: Request,
    body: UpdateTeamsStatusInput,
    _=Depends(require_product_jwt),
):
    """Actualiza el estado del canal Teams."""
    if not settings.teams_enabled:
        raise HTTPException(status_code=404, detail="Canal Teams no habilitado")

    update_teams_channel_state(
        linked=body.linked,
        app_name=body.app_name,
        error=body.error,
    )
    return {"ok": True}


@router.post("/channel/events")
@limiter.limit("60/minute")
async def record_teams_event(
    request: Request,
    body: TeamsEventInput,
    _=Depends(require_product_jwt),
):
    """Registra un evento operacional del canal Teams."""
    if not settings.teams_enabled:
        raise HTTPException(status_code=404, detail="Canal Teams no habilitado")

    record_teams_channel_event(
        event=body.event,
        app_name=body.app_name,
        error=body.error,
        metadata=body.metadata,
    )
    return {"ok": True}


@router.post("/webhook")
@limiter.limit("120/minute")
async def teams_webhook(
    request: Request,
    validation_token: str | None = Query(default=None, alias="validationToken"),
):
    """Webhook para mensajes entrantes y notificaciones de Teams.

    Microsoft Graph envía notificaciones de cambio (subscriptions) a este endpoint.
    Soporta el flujo de validación inicial (validationToken) requerido por MS Graph.

    Docs: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
    """
    if not settings.teams_enabled:
        raise HTTPException(status_code=404, detail="Canal Teams no habilitado")

    # Flujo de validación inicial de MS Graph subscriptions
    if validation_token:
        return {"validationToken": validation_token}

    body_bytes = await request.body()
    result = process_teams_webhook(body_bytes)
    if not result.get("ok"):
        log.warning("teams_webhook fail: %s", result.get("error"))
        raise HTTPException(status_code=400, detail=result.get("error", "Invalid notification"))

    return {"ok": True, "processed": result.get("processed", 0)}


@router.post("/send", response_model=TeamsSendResponse)
@limiter.limit("20/minute")
async def teams_send_endpoint(
    request: Request,
    body: TeamsSendInput,
    _=Depends(require_product_jwt),
):
    """Envía un mensaje via Microsoft Teams usando MS Graph API.

    Soporta envío a chat 1:1 (chat_id) o a canal (team_id + channel_id).
    """
    if not settings.teams_enabled:
        raise HTTPException(status_code=404, detail="Canal Teams no habilitado")

    if not body.chat_id and not (body.team_id and body.channel_id):
        raise HTTPException(status_code=400, detail="Se requiere chat_id o team_id+channel_id")

    result = send_teams_message(
        chat_id=body.chat_id,
        team_id=body.team_id,
        channel_id=body.channel_id,
        text=body.text,
        importance=body.importance,
    )
    return TeamsSendResponse(**result)
