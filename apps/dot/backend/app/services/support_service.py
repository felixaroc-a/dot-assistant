"""Logica de negocio para tickets de soporte.

Almacenamiento: Firestore collection "support_tickets".
Autenticacion: JWT (require_product_jwt) — uid y cliente_id de los claims.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from fastapi import HTTPException

from app.firebase_db import get_db

log = logging.getLogger("dot.support_service")


# ─── Enums ────────────────────────────────────────────────────────────

class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(str, Enum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    WHATSAPP = "whatsapp"
    GOOGLE = "google"
    AUTOMATIONS = "automations"
    PENDRIWE = "pendrive"
    OTHER = "other"


# ─── Helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_tickets_collection():
    """Retorna la coleccion Firestore de tickets o lanza HTTPException."""
    db = get_db()
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Firestore no disponible en este momento.",
        )
    return db.collection("support_tickets")


def _ticket_to_dict(
    doc_id: str,
    data: dict,
) -> dict:
    """Convierte un documento Firestore a dict de respuesta API."""
    return {
        "ticket_id": doc_id,
        "uid": data.get("uid", ""),
        "subject": data.get("subject", ""),
        "description": data.get("description", ""),
        "category": data.get("category", "other"),
        "status": data.get("status", "open"),
        "priority": data.get("priority", "medium"),
        "assigned_to": data.get("assigned_to"),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
        "comments": data.get("comments", []),
    }


# ─── CRUD ─────────────────────────────────────────────────────────────

def create_ticket(
    uid: str,
    subject: str,
    description: str,
    category: str = "other",
    priority: str = "medium",
    cedula: str | None = None,
    email: str | None = None,
) -> dict:
    """Crea un nuevo ticket de soporte en Firestore.

    Args:
        uid: ID del usuario (cliente_id)
        subject: Asunto del ticket (max 200 chars)
        description: Descripcion detallada
        category: Categoria (billing, technical, account, etc.)
        priority: Prioridad (low, medium, high, urgent)
        cedula: Cedula del usuario (opcional, para referencia)
        email: Email del usuario (opcional, para notificaciones)

    Returns:
        Dict con los datos del ticket creado, incluyendo ticket_id.

    Raises:
        HTTPException 400: Datos invalidos
        HTTPException 503: Firestore no disponible
    """
    if not subject or not subject.strip():
        raise HTTPException(status_code=400, detail="El asunto es obligatorio.")
    if len(subject) > 200:
        raise HTTPException(status_code=400, detail="El asunto no puede exceder 200 caracteres.")
    if not description or not description.strip():
        raise HTTPException(status_code=400, detail="La descripcion es obligatoria.")
    if category not in [c.value for c in TicketCategory]:
        raise HTTPException(status_code=400, detail=f"Categoria invalida: {category}")
    if priority not in [p.value for p in TicketPriority]:
        raise HTTPException(status_code=400, detail=f"Prioridad invalida: {priority}")

    tickets_ref = _get_tickets_collection()
    ticket_id = str(uuid4())
    now = _now_iso()

    ticket_data = {
        "uid": uid,
        "subject": subject.strip(),
        "description": description.strip(),
        "category": category,
        "status": TicketStatus.OPEN.value,
        "priority": priority,
        "assigned_to": None,
        "created_at": now,
        "updated_at": now,
        "comments": [
            {
                "author": "system",
                "author_uid": uid,
                "text": f"Ticket creado. Categoria: {category}. Prioridad: {priority}.",
                "timestamp": now,
            }
        ],
    }

    if cedula:
        ticket_data["cedula"] = cedula
    if email:
        ticket_data["email"] = email

    try:
        tickets_ref.document(ticket_id).set(ticket_data)
        log.info("Ticket creado: %s por usuario %s", ticket_id, uid)
    except Exception as e:
        log.exception("Error al crear ticket en Firestore")
        raise HTTPException(status_code=503, detail="Error al guardar el ticket.") from e

    return _ticket_to_dict(ticket_id, ticket_data)


def get_user_tickets(
    uid: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Lista los tickets de un usuario.

    Args:
        uid: ID del usuario
        status: Filtrar por estado (opcional)
        limit: Maximo de tickets a retornar

    Returns:
        Lista de tickets ordenados por updated_at descendente.
    """
    tickets_ref = _get_tickets_collection()

    query = tickets_ref.where("uid", "==", uid)

    if status and status in [s.value for s in TicketStatus]:
        query = query.where("status", "==", status)

    query = query.order_by("updated_at", direction="DESCENDING").limit(limit)

    try:
        docs = query.stream()
    except Exception as e:
        log.exception("Error al listar tickets del usuario %s", uid)
        raise HTTPException(status_code=503, detail="Error al consultar tickets.") from e

    tickets = [_ticket_to_dict(doc.id, doc.to_dict()) for doc in docs]
    return tickets


def get_ticket(ticket_id: str, uid: str | None = None) -> dict:
    """Obtiene un ticket por ID.

    Args:
        ticket_id: ID del ticket
        uid: Si se provee, verifica que el ticket pertenece a este usuario

    Returns:
        Datos del ticket.

    Raises:
        HTTPException 404: Ticket no encontrado
        HTTPException 403: Ticket no pertenece al usuario
    """
    tickets_ref = _get_tickets_collection()

    try:
        doc = tickets_ref.document(ticket_id).get()
    except Exception as e:
        log.exception("Error al obtener ticket %s", ticket_id)
        raise HTTPException(status_code=503, detail="Error al consultar el ticket.") from e

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    data = doc.to_dict()

    # Verificar propiedad si se provee uid
    if uid is not None and data.get("uid") != uid:
        raise HTTPException(status_code=403, detail="No tienes permiso para ver este ticket.")

    return _ticket_to_dict(doc.id, data)


def update_ticket_status(
    ticket_id: str,
    uid: str,
    new_status: str,
    comment: str | None = None,
) -> dict:
    """Actualiza el estado de un ticket (solo el propietario).

    Args:
        ticket_id: ID del ticket
        uid: ID del usuario (debe ser el propietario)
        new_status: Nuevo estado (open, in_progress, resolved, closed)
        comment: Comentario opcional

    Returns:
        Ticket actualizado.
    """
    if new_status not in [s.value for s in TicketStatus]:
        raise HTTPException(status_code=400, detail=f"Estado invalido: {new_status}")

    tickets_ref = _get_tickets_collection()
    ticket = get_ticket(ticket_id, uid=uid)

    now = _now_iso()

    updates = {
        "status": new_status,
        "updated_at": now,
    }

    # Agregar comentario si se provee
    if comment and comment.strip():
        new_comment = {
            "author": "user",
            "author_uid": uid,
            "text": comment.strip(),
            "timestamp": now,
        }
        existing_comments = ticket.get("comments", [])
        existing_comments.append(new_comment)
        updates["comments"] = existing_comments

    try:
        tickets_ref.document(ticket_id).update(updates)
        log.info("Ticket %s actualizado a estado %s por usuario %s", ticket_id, new_status, uid)
    except Exception as e:
        log.exception("Error al actualizar ticket %s", ticket_id)
        raise HTTPException(status_code=503, detail="Error al actualizar el ticket.") from e

    # Merge para respuesta
    ticket.update(updates)
    return ticket


def add_comment(ticket_id: str, uid: str, text: str, author: str = "user") -> dict:
    """Agrega un comentario a un ticket.

    Args:
        ticket_id: ID del ticket
        uid: ID del usuario que comenta
        text: Texto del comentario
        author: "user" o "admin"

    Returns:
        Ticket actualizado.
    """
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="El comentario no puede estar vacio.")

    tickets_ref = _get_tickets_collection()
    ticket = get_ticket(ticket_id, uid=uid if author == "user" else None)

    now = _now_iso()
    new_comment = {
        "author": author,
        "author_uid": uid,
        "text": text.strip(),
        "timestamp": now,
    }

    existing_comments = ticket.get("comments", [])
    existing_comments.append(new_comment)

    updates = {
        "comments": existing_comments,
        "updated_at": now,
    }

    try:
        tickets_ref.document(ticket_id).update(updates)
    except Exception as e:
        log.exception("Error al agregar comentario al ticket %s", ticket_id)
        raise HTTPException(status_code=503, detail="Error al agregar comentario.") from e

    ticket["comments"] = existing_comments
    ticket["updated_at"] = now
    return ticket


# ─── Admin ────────────────────────────────────────────────────────────

def list_all_tickets(
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Lista todos los tickets (admin). Soporta filtros.

    Args:
        status: Filtrar por estado
        priority: Filtrar por prioridad
        category: Filtrar por categoria
        limit: Maximo de tickets

    Returns:
        Lista de tickets ordenados por updated_at descendente.
    """
    tickets_ref = _get_tickets_collection()
    query = tickets_ref.order_by("updated_at", direction="DESCENDING")

    # Firestore solo permite un where con order_by desigual (limitacion),
    # asi que aplicamos filtros en memoria despues de la query base
    try:
        docs = query.limit(limit * 3).stream()  # Overfetch para filtrar en memoria
    except Exception as e:
        log.exception("Error al listar tickets admin")
        raise HTTPException(status_code=503, detail="Error al consultar tickets.") from e

    tickets = [_ticket_to_dict(doc.id, doc.to_dict()) for doc in docs]

    # Filtrar en memoria
    if status:
        tickets = [t for t in tickets if t["status"] == status]
    if priority:
        tickets = [t for t in tickets if t["priority"] == priority]
    if category:
        tickets = [t for t in tickets if t["category"] == category]

    return tickets[:limit]


def assign_ticket(ticket_id: str, admin_uid: str) -> dict:
    """Asigna un ticket a un administrador.

    Args:
        ticket_id: ID del ticket
        admin_uid: ID del admin que se asigna

    Returns:
        Ticket actualizado.
    """
    tickets_ref = _get_tickets_collection()

    # No verificamos propiedad (admin)
    try:
        doc = tickets_ref.document(ticket_id).get()
    except Exception as e:
        log.exception("Error al obtener ticket %s para asignacion", ticket_id)
        raise HTTPException(status_code=503, detail="Error al consultar el ticket.") from e

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    now = _now_iso()
    updates = {
        "assigned_to": admin_uid,
        "status": TicketStatus.IN_PROGRESS.value,
        "updated_at": now,
    }

    try:
        tickets_ref.document(ticket_id).update(updates)
        log.info("Ticket %s asignado a admin %s", ticket_id, admin_uid)
    except Exception as e:
        log.exception("Error al asignar ticket %s", ticket_id)
        raise HTTPException(status_code=503, detail="Error al asignar el ticket.") from e

    return _ticket_to_dict(doc.id, {**doc.to_dict(), **updates})


def get_support_stats() -> dict:
    """Obtiene estadisticas del dashboard de soporte.

    Returns:
        Dict con totales por estado, prioridad, y tiempos.
    """
    tickets_ref = _get_tickets_collection()

    try:
        docs = tickets_ref.stream()
    except Exception as e:
        log.exception("Error al obtener estadisticas de soporte")
        raise HTTPException(status_code=503, detail="Error al consultar estadisticas.") from e

    now = datetime.now(timezone.utc)
    total = 0
    by_status: dict[str, int] = {s.value: 0 for s in TicketStatus}
    by_priority: dict[str, int] = {p.value: 0 for p in TicketPriority}
    today_count = 0
    week_count = 0
    month_count = 0
    resolution_times: list[float] = []

    for doc in docs:
        data = doc.to_dict()
        total += 1

        status = data.get("status", "open")
        if status in by_status:
            by_status[status] += 1

        priority = data.get("priority", "medium")
        if priority in by_priority:
            by_priority[priority] += 1

        # Conteo por tiempo
        created_str = data.get("created_at", "")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                diff = now - created
                if diff.days < 1:
                    today_count += 1
                if diff.days < 7:
                    week_count += 1
                if diff.days < 30:
                    month_count += 1

                # Tiempo de resolucion
                if status in ("resolved", "closed"):
                    updated_str = data.get("updated_at", "")
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str)
                        resolution_time = (updated - created).total_seconds() / 3600.0
                        resolution_times.append(resolution_time)
            except (ValueError, TypeError):
                pass

    avg_resolution_hours = (
        sum(resolution_times) / len(resolution_times) if resolution_times else 0
    )

    return {
        "total_tickets": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "today": today_count,
        "this_week": week_count,
        "this_month": month_count,
        "avg_resolution_hours": round(avg_resolution_hours, 1),
        "open_count": by_status.get("open", 0),
        "in_progress_count": by_status.get("in_progress", 0),
        "resolved_count": by_status.get("resolved", 0),
        "closed_count": by_status.get("closed", 0),
    }
