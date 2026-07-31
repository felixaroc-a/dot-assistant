"""Endpoints administrativos de soporte (solo admin).

Requiere X-Admin-Key en header para todos los endpoints.

Endpoints:
    GET    /v1/admin/support/tickets              — Listar todos los tickets
    GET    /v1/admin/support/stats                — Estadísticas del dashboard
    PATCH  /v1/admin/support/tickets/{id}/assign  — Asignar ticket a admin
    POST   /v1/admin/support/tickets/{id}/respond — Responder como admin
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db
from app.services import support_service
from app.settings import settings

log = logging.getLogger("dot.support_admin")

router = APIRouter(tags=["admin-support"])


# ─── Auth ─────────────────────────────────────────────────────────────

def _require_admin(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> str:
    """Verifica X-Admin-Key y retorna el uid del admin."""
    configured = settings.admin_api_key.strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin API key no configurada en el servidor.",
        )
    if not x_admin_key or x_admin_key.strip() != configured:
        raise HTTPException(status_code=403, detail="Admin API key invalida.")

    # El admin uid se deriva de la key (para trazabilidad en logs/tickets)
    return f"admin:{x_admin_key.strip()[:8]}"


# ─── Schemas ──────────────────────────────────────────────────────────

class AssignTicketRequest(BaseModel):
    admin_name: str = Field(
        default="admin",
        description="Nombre o identificador del administrador que toma el ticket",
    )


class AdminResponseRequest(BaseModel):
    message: str = Field(
        min_length=5,
        max_length=3000,
        description="Respuesta del administrador",
    )
    internal_note: bool = Field(
        default=False,
        description="Si es true, la respuesta es una nota interna (no visible al usuario)",
    )


class TicketAdminResponse(BaseModel):
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


# ─── Endpoints ────────────────────────────────────────────────────────

@router.get("/v1/admin/support/tickets")
def list_all_tickets(
    status: str | None = Query(default=None, description="Filtrar por estado"),
    priority: str | None = Query(default=None, description="Filtrar por prioridad"),
    category: str | None = Query(default=None, description="Filtrar por categoria"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximo de tickets"),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_billing_db),
):
    """Lista todos los tickets del sistema con filtros opcionales.

    Requiere X-Admin-Key.

    Filtros disponibles:
    - status: open, in_progress, resolved, closed
    - priority: low, medium, high, urgent
    - category: billing, technical, account, whatsapp, google, automations, pendrive, other
    """
    _require_admin(x_admin_key)

    tickets = support_service.list_all_tickets(
        status=status,
        priority=priority,
        category=category,
        limit=limit,
    )

    log.info(
        "Admin listo tickets: status=%s priority=%s category=%s → %d resultados",
        status, priority, category, len(tickets),
    )

    return [TicketAdminResponse(**t) for t in tickets]


@router.get("/v1/admin/support/stats")
def get_support_stats(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Obtiene estadisticas del dashboard de soporte.

    Requiere X-Admin-Key.

    Retorna:
    - total_tickets: Total de tickets en el sistema
    - by_status: Cantidad por estado (open, in_progress, resolved, closed)
    - by_priority: Cantidad por prioridad (low, medium, high, urgent)
    - today, this_week, this_month: Tickets en cada periodo
    - avg_resolution_hours: Tiempo promedio de resolucion
    """
    _require_admin(x_admin_key)

    stats = support_service.get_support_stats()

    log.info("Admin consulto stats de soporte: %d tickets totales", stats["total_tickets"])

    return stats


@router.patch("/v1/admin/support/tickets/{ticket_id}/assign", response_model=TicketAdminResponse)
def assign_ticket(
    ticket_id: str,
    body: AssignTicketRequest,
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Asigna un ticket a un administrador y cambia su estado a 'in_progress'.

    Requiere X-Admin-Key.
    """
    admin_uid = _require_admin(x_admin_key)

    ticket = support_service.assign_ticket(
        ticket_id=ticket_id,
        admin_uid=body.admin_name or admin_uid,
    )

    log.info("Admin %s asigno ticket %s", admin_uid, ticket_id)

    return TicketAdminResponse(**ticket)


@router.post("/v1/admin/support/tickets/{ticket_id}/respond", response_model=TicketAdminResponse)
def respond_to_ticket(
    ticket_id: str,
    body: AdminResponseRequest,
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Agrega una respuesta de administrador a un ticket.

    Requiere X-Admin-Key.

    Si internal_note=True, la respuesta se marca como nota interna.
    Si internal_note=False, es visible para el usuario.
    """
    admin_uid = _require_admin(x_admin_key)

    author = "admin_note" if body.internal_note else "admin"

    ticket = support_service.add_comment(
        ticket_id=ticket_id,
        uid=admin_uid,
        text=body.message,
        author=author,
    )

    log.info(
        "Admin %s respondio a ticket %s (%s)",
        admin_uid, ticket_id, "nota interna" if body.internal_note else "respuesta publica",
    )

    return TicketAdminResponse(**ticket)
