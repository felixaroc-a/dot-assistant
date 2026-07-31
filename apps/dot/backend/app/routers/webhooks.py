"""Router para webhooks salientes (outbound webhooks).

Permite CRUD de webhooks que DOT llama en eventos específicos.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.webhooks.router")

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


# ─── Schemas ───────────────────────────────────────────────────────────


class CreateWebhookRequest(BaseModel):
    url: str = Field(..., min_length=5, description="URL donde DOT enviará el POST")
    events: list[str] = Field(
        default=["chat.new_message"],
        description="Eventos que disparan el webhook",
    )
    secret: str = Field(default="", description="Secreto para firma HMAC (opcional)")
    description: str = Field(default="", max_length=200)
    headers: dict[str, str] = Field(default={}, description="Headers HTTP adicionales")


class UpdateWebhookRequest(BaseModel):
    url: str | None = Field(default=None, min_length=5)
    events: list[str] | None = None
    secret: str | None = None
    enabled: bool | None = None
    description: str | None = None
    headers: dict[str, str] | None = None


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    enabled: bool
    description: str
    created_at: str
    last_fired_at: str | None = None
    delivery_count: int = 0
    failure_count: int = 0


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    event: str
    status: str
    status_code: int | None = None
    error: str = ""
    attempt: int = 0
    created_at: str
    completed_at: str | None = None


class FireEventRequest(BaseModel):
    event: str = Field(..., description="Nombre del evento a disparar")
    payload: dict = Field(default={}, description="Payload del evento")


class FireEventResponse(BaseModel):
    ok: bool
    webhooks_notified: int = 0


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(claims: dict = Depends(require_product_jwt)):
    """Lista todos los webhooks del usuario autenticado."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    # sync wrapper for async
    import asyncio
    webhooks = asyncio.run(service.list_webhooks(uid))

    return [
        WebhookResponse(
            id=w.id,
            url=w.url,
            events=w.events,
            enabled=w.enabled,
            description=w.description,
            created_at=w.created_at,
            last_fired_at=w.last_fired_at,
            delivery_count=w.delivery_count,
            failure_count=w.failure_count,
        )
        for w in webhooks
    ]


@router.post("", response_model=WebhookResponse)
@limiter.limit("10/minute")
def create_webhook(
    request: Request,
    body: CreateWebhookRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Crea un nuevo webhook para recibir notificaciones de eventos DOT."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    import asyncio

    try:
        config = asyncio.run(
            service.create_webhook(
                uid=uid,
                url=body.url,
                events=body.events,
                secret=body.secret,
                description=body.description,
                headers=body.headers,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return WebhookResponse(
        id=config.id,
        url=config.url,
        events=config.events,
        enabled=config.enabled,
        description=config.description,
        created_at=config.created_at,
        last_fired_at=config.last_fired_at,
        delivery_count=config.delivery_count,
        failure_count=config.failure_count,
    )


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene un webhook específico por ID."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    import asyncio
    config = asyncio.run(service.get_webhook(uid, webhook_id))

    if config is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado")

    return WebhookResponse(
        id=config.id,
        url=config.url,
        events=config.events,
        enabled=config.enabled,
        description=config.description,
        created_at=config.created_at,
        last_fired_at=config.last_fired_at,
        delivery_count=config.delivery_count,
        failure_count=config.failure_count,
    )


@router.put("/{webhook_id}", response_model=WebhookResponse)
@limiter.limit("10/minute")
def update_webhook(
    request: Request,
    webhook_id: str,
    body: UpdateWebhookRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Actualiza un webhook existente."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    import asyncio
    config = asyncio.run(
        service.update_webhook(
            uid=uid,
            webhook_id=webhook_id,
            url=body.url,
            events=body.events,
            secret=body.secret,
            enabled=body.enabled,
            description=body.description,
            headers=body.headers,
        )
    )

    if config is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado")

    return WebhookResponse(
        id=config.id,
        url=config.url,
        events=config.events,
        enabled=config.enabled,
        description=config.description,
        created_at=config.created_at,
        last_fired_at=config.last_fired_at,
        delivery_count=config.delivery_count,
        failure_count=config.failure_count,
    )


@router.delete("/{webhook_id}")
def delete_webhook(
    webhook_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Elimina un webhook."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    import asyncio
    deleted = asyncio.run(service.delete_webhook(uid, webhook_id))

    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook no encontrado")

    return {"ok": True}


@router.post("/fire", response_model=FireEventResponse)
@limiter.limit("30/minute")
def fire_event(
    request: Request,
    body: FireEventRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Dispara manualmente un evento a tus webhooks (para testing)."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    import asyncio
    count = asyncio.run(
        service.fire_event_for_user(uid, body.event, body.payload)
    )

    return FireEventResponse(ok=True, webhooks_notified=count)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
def list_deliveries(
    webhook_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Lista el historial de entregas de un webhook."""
    from app.auth_deps import claims_uid
    from app.services.webhook_service import get_webhook_service

    uid = claims_uid(claims)
    service = get_webhook_service()

    config = service.get_webhook(uid, webhook_id)
    import asyncio
    config = asyncio.run(config)

    if config is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado")

    deliveries = service.get_deliveries(webhook_id=webhook_id, limit=50)

    return [
        WebhookDeliveryResponse(
            id=d.id,
            webhook_id=d.webhook_id,
            event=d.event,
            status=d.status,
            status_code=d.status_code,
            error=d.error,
            attempt=d.attempt,
            created_at=d.created_at,
            completed_at=d.completed_at,
        )
        for d in deliveries
    ]
