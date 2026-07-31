"""Endpoints de soporte para usuarios: tickets y FAQs.

Tickets:
    POST   /v1/support/tickets          — Crear ticket
    GET    /v1/support/tickets          — Listar tickets del usuario
    GET    /v1/support/tickets/{id}     — Ver detalle de ticket
    PATCH  /v1/support/tickets/{id}     — Actualizar estado/comentario

FAQs:
    GET    /v1/support/faq              — Buscar en FAQs
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter
from app.services import support_service
from app.services.support_faqs import get_faq_response, suggest_related_faqs

log = logging.getLogger("dot.support")

router = APIRouter(prefix="/v1/support", tags=["support"])


# ─── Schemas ──────────────────────────────────────────────────────────

class CreateTicketRequest(BaseModel):
    subject: str = Field(
        min_length=5,
        max_length=200,
        description="Asunto del ticket",
        examples=["Problema con la conexión de WhatsApp"],
    )
    description: str = Field(
        min_length=10,
        max_length=5000,
        description="Descripción detallada del problema",
    )
    category: str = Field(
        default="other",
        description="Categoría del ticket",
        examples=["billing", "technical", "account", "whatsapp", "google", "automations", "pendrive", "other"],
    )
    priority: str = Field(
        default="medium",
        description="Prioridad del ticket",
        examples=["low", "medium", "high", "urgent"],
    )


class UpdateTicketRequest(BaseModel):
    status: str | None = Field(
        default=None,
        description="Nuevo estado del ticket",
        examples=["open", "in_progress", "resolved", "closed"],
    )
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Comentario a agregar al ticket",
    )


class TicketResponse(BaseModel):
    ticket_id: str
    uid: str
    subject: str
    description: str
    category: str
    status: str
    priority: str
    assigned_to: str | None = None
    created_at: str
    updated_at: str
    comments: list[dict] = []


class FAQRequest(BaseModel):
    q: str = Field(
        min_length=3,
        max_length=300,
        description="Pregunta del usuario",
    )


class FAQResponse(BaseModel):
    found: bool
    response: str
    category: str
    score: float
    related: list[dict] = []


# ─── Tickets ──────────────────────────────────────────────────────────

@router.post("/tickets", response_model=TicketResponse, status_code=201)
@limiter.limit("10/minute")
def create_ticket(
    request: Request,
    body: CreateTicketRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Crea un nuevo ticket de soporte.

    Requiere autenticación JWT. El uid se extrae de los claims del token.
    """
    uid = claims_uid(claims)

    ticket = support_service.create_ticket(
        uid=uid,
        subject=body.subject,
        description=body.description,
        category=body.category,
        priority=body.priority,
    )

    log.info("Ticket %s creado por usuario %s (categoria: %s)", ticket["ticket_id"], uid, body.category)
    return TicketResponse(**ticket)


@router.get("/tickets")
@limiter.limit("30/minute")
def list_tickets(
    request: Request,
    status: str | None = Query(default=None, description="Filtrar por estado"),
    claims: dict = Depends(require_product_jwt),
):
    """Lista los tickets del usuario autenticado.

    Requiere autenticación JWT. Retorna máximo 50 tickets ordenados por fecha.
    """
    uid = claims_uid(claims)
    tickets = support_service.get_user_tickets(uid=uid, status=status)
    return [TicketResponse(**t) for t in tickets]


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el detalle de un ticket específico.

    Solo el propietario del ticket puede verlo.
    """
    uid = claims_uid(claims)
    ticket = support_service.get_ticket(ticket_id, uid=uid)
    return TicketResponse(**ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
@limiter.limit("20/minute")
def update_ticket(
    request: Request,
    ticket_id: str,
    body: UpdateTicketRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Actualiza el estado de un ticket y/o agrega un comentario.

    Solo el propietario del ticket puede actualizarlo.
    El estado solo puede cambiarse a: open, in_progress, resolved, closed.
    Los usuarios no pueden asignar tickets (eso es solo para admins).
    """
    uid = claims_uid(claims)

    if body.status:
        ticket = support_service.update_ticket_status(
            ticket_id=ticket_id,
            uid=uid,
            new_status=body.status,
            comment=body.comment,
        )
    elif body.comment:
        ticket = support_service.add_comment(
            ticket_id=ticket_id,
            uid=uid,
            text=body.comment,
            author="user",
        )
    else:
        raise HTTPException(status_code=400, detail="Debes proporcionar status o comment.")

    return TicketResponse(**ticket)


# ─── FAQs ─────────────────────────────────────────────────────────────

@router.get("/faq", response_model=FAQResponse)
def search_faq(
    q: str = Query(
        min_length=3,
        max_length=300,
        description="Pregunta o consulta del usuario",
    ),
):
    """Busca en la base de datos de FAQs.

    Retorna la mejor coincidencia y FAQs relacionadas.
    No requiere autenticación.
    """
    result = get_faq_response(q)
    related = suggest_related_faqs(q, limit=3)

    return FAQResponse(
        found=result["found"],
        response=result["response"],
        category=result["category"],
        score=result["score"],
        related=related,
    )
