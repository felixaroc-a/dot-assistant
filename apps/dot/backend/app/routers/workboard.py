"""REST endpoints para Workboard (Kanban) y Goal Trees.

Endpoints:
  Cards:
    POST   /v1/workboard/cards              — crear card
    GET    /v1/workboard/cards              — listar cards (?status=)
    GET    /v1/workboard/cards/{id}         — obtener card
    PATCH  /v1/workboard/cards/{id}         — actualizar card
    PATCH  /v1/workboard/cards/{id}/move    — mover a columna
    DELETE /v1/workboard/cards/{id}         — archivar card
    GET    /v1/workboard/cards/{id}/tree    — jerarquía de card
    GET    /v1/workboard/columns            — tablero completo por columnas
    POST   /v1/workboard/cards/{id}/assign  — asignar a sub-agente

  Goals:
    POST   /v1/workboard/goals/decompose    — descomponer objetivo en árbol
    GET    /v1/workboard/goals/{id}/tree    — obtener árbol de goals
    POST   /v1/workboard/goals/{id}/execute — ejecutar hojas con sub-agentes
    POST   /v1/workboard/goals/{id}/complete — marcar goal completado
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services.goal_tree_service import (
    GoalStatus,
    get_goal_tree_service,
)
from app.services.workboard_service import (
    CardPriority,
    CardStatus,
    get_workboard_service,
)

log = logging.getLogger("dot.workboard_router")

router = APIRouter(prefix="/v1/workboard", tags=["workboard"])

# ── Schemas ──────────────────────────────────────────────

class CreateCardRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Título de la card")
    description: str = Field(default="", max_length=2000)
    parent_id: str | None = Field(default=None, description="Card padre (jerarquía)")
    priority: str = Field(default="medium", description="low | medium | high | urgent")
    deadline: str | None = Field(default=None, description="Fecha límite ISO 8601")
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateCardRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, description="todo | in_progress | done | blocked")
    assignee: str | None = Field(default=None)
    priority: str | None = Field(default=None, description="low | medium | high | urgent")
    deadline: str | None = Field(default=None)
    labels: list[str] | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class MoveCardRequest(BaseModel):
    status: str = Field(..., description="Nueva columna: todo | in_progress | done | blocked")


class AssignCardRequest(BaseModel):
    sub_agent_id: str = Field(..., description="ID del sub-agente a asignar")


class DecomposeGoalRequest(BaseModel):
    goal_text: str = Field(..., min_length=1, description="Texto del objetivo a descomponer")
    max_depth: int = Field(default=3, ge=1, le=5, description="Profundidad máxima del árbol")
    use_llm: bool = Field(default=True, description="Usar LLM para descomposición")


class ExecuteGoalsRequest(BaseModel):
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools permitidas para los sub-agentes (vacío = todas)",
    )


class CardResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    assignee: str | None = None
    parent_id: str | None = None
    priority: str
    deadline: str | None = None
    labels: list[str]
    created_at: str
    updated_at: str
    stale_warning: bool = False
    metadata: dict[str, Any]


def _card_to_response(card) -> CardResponse:
    return CardResponse(
        id=card.id,
        title=card.title,
        description=card.description,
        status=card.status.value,
        assignee=card.assignee,
        parent_id=card.parent_id,
        priority=card.priority.value,
        deadline=card.deadline,
        labels=card.labels,
        created_at=card.created_at,
        updated_at=card.updated_at,
        stale_warning=card.stale_warning,
        metadata=card.metadata,
    )


# ═══════════════════════════════════════════════════════════
# CARDS — Kanban
# ═══════════════════════════════════════════════════════════

@router.post("/cards", response_model=CardResponse)
def create_card(
    request: Request,
    body: CreateCardRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Crea una nueva card en el tablero kanban del usuario."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    try:
        priority = CardPriority(body.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Prioridad inválida: {body.priority}. Usar: low, medium, high, urgent")

    card = svc.create_card(
        uid=uid,
        title=body.title,
        description=body.description,
        parent_id=body.parent_id,
        priority=priority,
        deadline=body.deadline,
        labels=body.labels,
        metadata=body.metadata,
    )

    if card is None:
        raise HTTPException(status_code=503, detail="Workboard no disponible")

    return _card_to_response(card)


@router.get("/cards", response_model=list[CardResponse])
def list_cards(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    status: str | None = Query(default=None, description="Filtrar por status: todo, in_progress, done, blocked"),
):
    """Lista las cards del tablero del usuario. Opcionalmente filtradas por status."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    cards = svc.list_cards(uid, status_filter=status)
    return [_card_to_response(c) for c in cards]


@router.get("/cards/{card_id}", response_model=CardResponse)
def get_card(
    card_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene una card por su ID."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    card = svc.get_card(uid, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return _card_to_response(card)


@router.patch("/cards/{card_id}", response_model=CardResponse)
def update_card(
    card_id: str,
    request: Request,
    body: UpdateCardRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Actualiza una card existente."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    status_enum = None
    if body.status is not None:
        try:
            status_enum = CardStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Status inválido: {body.status}. Usar: todo, in_progress, done, blocked")

    priority_enum = None
    if body.priority is not None:
        try:
            priority_enum = CardPriority(body.priority)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Prioridad inválida: {body.priority}")

    card = svc.update_card(
        uid=uid,
        card_id=card_id,
        title=body.title,
        description=body.description,
        status=status_enum,
        assignee=body.assignee,
        priority=priority_enum,
        deadline=body.deadline,
        labels=body.labels,
        metadata=body.metadata,
    )

    if card is None:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return _card_to_response(card)


@router.patch("/cards/{card_id}/move", response_model=CardResponse)
def move_card(
    card_id: str,
    request: Request,
    body: MoveCardRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Mueve una card a otra columna (cambia su status)."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    try:
        new_status = CardStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Status inválido: {body.status}. Usar: todo, in_progress, done, blocked")

    card = svc.move_card(uid, card_id, new_status)
    if card is None:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return _card_to_response(card)


@router.post("/cards/{card_id}/assign", response_model=CardResponse)
def assign_card(
    card_id: str,
    request: Request,
    body: AssignCardRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Asigna una card a un sub-agente específico."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    card = svc.assign_card(uid, card_id, body.sub_agent_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return _card_to_response(card)


@router.delete("/cards/{card_id}")
def archive_card(
    card_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Archiva (soft-delete) una card del tablero."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    deleted = svc.delete_card(uid, card_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return {"deleted": True, "card_id": card_id}


@router.get("/cards/{card_id}/tree")
def get_card_tree(
    card_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el árbol jerárquico de una card y sus hijos."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    tree = svc.get_card_tree(uid, card_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Card no encontrada")

    return tree


@router.get("/columns")
def get_board_columns(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve el tablero completo organizado por columnas."""
    uid = claims_uid(claims)
    svc = get_workboard_service()

    columns = svc.get_columns(uid)
    return {
        column: [_card_to_response(card).model_dump() for card in cards]
        for column, cards in columns.items()
    }


# ═══════════════════════════════════════════════════════════
# GOALS — Goal Tree
# ═══════════════════════════════════════════════════════════

@router.post("/goals/decompose")
def decompose_goal(
    request: Request,
    body: DecomposeGoalRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Descompone un objetivo en un árbol jerárquico de sub-objetivos.

    Cada sub-objetivo puede asignarse a un sub-agente para ejecución paralela.
    """
    uid = claims_uid(claims)
    svc = get_goal_tree_service()

    root = svc.decompose_goal(
        uid=uid,
        goal_text=body.goal_text,
        max_depth=body.max_depth,
        use_llm=body.use_llm,
    )

    if root is None:
        raise HTTPException(status_code=503, detail="Goal Tree no disponible")

    tree = svc.get_goal_tree(uid, root.id)
    return {
        "root_goal_id": root.id,
        "goal_text": body.goal_text,
        "tree": tree,
    }


@router.get("/goals/{goal_id}/tree")
def get_goal_tree(
    goal_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el árbol completo de un goal y sus sub-objetivos."""
    uid = claims_uid(claims)
    svc = get_goal_tree_service()

    tree = svc.get_goal_tree(uid, goal_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Goal no encontrado")

    return tree


@router.post("/goals/{goal_id}/complete")
def complete_goal(
    goal_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Marca un goal como completado. Auto-completa el padre si todos los hijos están completados."""
    uid = claims_uid(claims)
    svc = get_goal_tree_service()

    node = svc.mark_complete(uid, goal_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Goal no encontrado")

    return {
        "goal_id": node.id,
        "status": node.status.value,
        "description": node.description,
        "parent_id": node.parent_id,
    }


@router.post("/goals/{goal_id}/execute")
def execute_goal_leaves(
    goal_id: str,
    request: Request,
    body: ExecuteGoalsRequest = ExecuteGoalsRequest(),
    claims: dict = Depends(require_product_jwt),
):
    """Ejecuta todos los goals hoja del árbol usando sub-agentes en paralelo.

    Cada goal hoja se delega a un sub-agente independiente.
    Los resultados se recolectan y los goals se marcan como completados o fallidos.
    """
    uid = claims_uid(claims)
    svc = get_goal_tree_service()

    tree = svc.get_goal_tree(uid, goal_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Goal no encontrado")

    results = svc.execute_leaf_goals(
        uid=uid,
        root_goal_id=goal_id,
        allowed_tools=body.allowed_tools or None,
    )

    # Obtener árbol actualizado post-ejecución
    updated_tree = svc.get_goal_tree(uid, goal_id)

    completed = sum(1 for r in results if r["status"] == "completed")
    failed = sum(1 for r in results if r["status"] in ("failed", "cancelled", "idle_timeout"))

    return {
        "root_goal_id": goal_id,
        "results": results,
        "summary": f"{completed} completados, {failed} fallidos de {len(results)} goals hoja",
        "tree": updated_tree,
    }
