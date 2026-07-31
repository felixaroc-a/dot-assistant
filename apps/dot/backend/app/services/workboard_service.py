"""Workboard Service — Kanban de tareas con jerarquía y heartbeat.

Cada usuario tiene su propio tablero en Firestore:
  users/{uid}/workboard/cards/{card_id}

Columnas por defecto: todo, in_progress, done, blocked (configurables).

Características:
- CRUD de cards con jerarquía parent_id.
- Movimiento entre columnas.
- Heartbeat: detección de cards stale (in_progress > 24h).
- Asignación a sub-agentes.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.firebase_db import get_db

log = logging.getLogger("dot.workboard_service")

STALE_IN_PROGRESS_HOURS = 24

DEFAULT_COLUMNS = ["todo", "in_progress", "done", "blocked"]


class CardStatus(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"


class CardPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


@dataclass
class WorkboardCard:
    id: str
    title: str
    description: str = ""
    status: CardStatus = CardStatus.todo
    assignee: str | None = None  # sub_agent_id opcional
    parent_id: str | None = None  # card padre para jerarquía
    priority: CardPriority = CardPriority.medium
    deadline: str | None = None  # ISO 8601
    labels: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    stale_warning: bool = False  # True si in_progress > 24h
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "assignee": self.assignee,
            "parent_id": self.parent_id,
            "priority": self.priority.value,
            "deadline": self.deadline,
            "labels": self.labels,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stale_warning": self.stale_warning,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, card_id: str, data: dict[str, Any]) -> "WorkboardCard":
        status_raw = data.get("status", "todo")
        try:
            status = CardStatus(status_raw)
        except ValueError:
            status = CardStatus.todo

        priority_raw = data.get("priority", "medium")
        try:
            priority = CardPriority(priority_raw)
        except ValueError:
            priority = CardPriority.medium

        return cls(
            id=card_id,
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=status,
            assignee=data.get("assignee"),
            parent_id=data.get("parent_id"),
            priority=priority,
            deadline=data.get("deadline"),
            labels=data.get("labels", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            stale_warning=data.get("stale_warning", False),
            metadata=data.get("metadata", {}),
        )


class WorkboardService:
    """Gestor del tablero kanban por usuario.

    Persistencia: Firestore users/{uid}/workboard/cards/{card_id}.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @property
    def _disabled(self) -> bool:
        return not self.enabled

    def _cards_collection(self, uid: str):
        db = get_db()
        if db is None:
            return None
        return (
            db.collection("users")
            .document(uid)
            .collection("workboard")
            .document("_data")
            .collection("cards")
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── CRUD ──────────────────────────────────────────────

    def create_card(
        self,
        uid: str,
        title: str,
        description: str = "",
        parent_id: str | None = None,
        priority: CardPriority = CardPriority.medium,
        deadline: str | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkboardCard | None:
        """Crea una nueva card en el tablero del usuario."""
        if self._disabled:
            return None

        col = self._cards_collection(uid)
        if col is None:
            log.warning("Firestore no disponible para crear card uid=%s", uid[:8])
            return None

        card_id = str(uuid.uuid4())
        now = self._now_iso()

        card = WorkboardCard(
            id=card_id,
            title=title.strip(),
            description=description.strip(),
            parent_id=parent_id,
            priority=priority,
            deadline=deadline,
            labels=labels or [],
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        try:
            col.document(card_id).set(card.to_dict())
            log.info("Card creada: uid=%s card=%s title=%s", uid[:8], card_id[:8], title[:60])
            return card
        except Exception:
            log.exception("Error creando card uid=%s", uid[:8])
            return None

    def get_card(self, uid: str, card_id: str) -> WorkboardCard | None:
        """Obtiene una card por ID."""
        if self._disabled:
            return None

        col = self._cards_collection(uid)
        if col is None:
            return None

        try:
            doc = col.document(card_id).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            card = WorkboardCard.from_dict(card_id, data)
            # Verificar stale warning
            card = self._check_stale(card)
            return card
        except Exception:
            log.exception("Error leyendo card uid=%s card=%s", uid[:8], card_id[:8])
            return None

    def list_cards(self, uid: str, status_filter: str | None = None) -> list[WorkboardCard]:
        """Lista todas las cards del usuario, opcionalmente filtradas por status.

        Args:
            uid: ID del usuario.
            status_filter: Filtrar por status (todo, in_progress, done, blocked).
        """
        if self._disabled:
            return []

        col = self._cards_collection(uid)
        if col is None:
            return []

        try:
            if status_filter:
                docs = col.where("status", "==", status_filter).stream()
            else:
                docs = col.stream()

            cards = []
            for doc in docs:
                data = doc.to_dict() or {}
                card = WorkboardCard.from_dict(doc.id, data)
                card = self._check_stale(card)
                cards.append(card)

            # Ordenar por prioridad (urgent > high > medium > low) y created_at descendente
            priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
            cards.sort(key=lambda c: (
                priority_order.get(c.priority.value, 2),
                c.created_at,
            ), reverse=False)

            return cards
        except Exception:
            log.exception("Error listando cards uid=%s", uid[:8])
            return []

    def update_card(
        self,
        uid: str,
        card_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        status: CardStatus | None = None,
        assignee: str | None = None,
        parent_id: str | None = None,
        priority: CardPriority | None = None,
        deadline: str | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkboardCard | None:
        """Actualiza campos de una card existente."""
        if self._disabled:
            return None

        col = self._cards_collection(uid)
        if col is None:
            return None

        card = self.get_card(uid, card_id)
        if card is None:
            return None

        if title is not None:
            card.title = title.strip()
        if description is not None:
            card.description = description.strip()
        if status is not None:
            card.status = status
        if assignee is not None:
            card.assignee = assignee
        if parent_id is not None:
            card.parent_id = parent_id
        if priority is not None:
            card.priority = priority
        if deadline is not None:
            card.deadline = deadline
        if labels is not None:
            card.labels = labels
        if metadata is not None:
            card.metadata = metadata

        card.updated_at = self._now_iso()
        card.stale_warning = False  # Reset al actualizar

        try:
            col.document(card_id).set(card.to_dict(), merge=True)
            log.info("Card actualizada: uid=%s card=%s", uid[:8], card_id[:8])
            return card
        except Exception:
            log.exception("Error actualizando card uid=%s card=%s", uid[:8], card_id[:8])
            return None

    def move_card(self, uid: str, card_id: str, new_status: CardStatus) -> WorkboardCard | None:
        """Mueve una card a otra columna (cambio de status)."""
        return self.update_card(uid, card_id, status=new_status)

    def assign_card(self, uid: str, card_id: str, sub_agent_id: str) -> WorkboardCard | None:
        """Asigna una card a un sub-agente."""
        return self.update_card(uid, card_id, assignee=sub_agent_id)

    def delete_card(self, uid: str, card_id: str) -> bool:
        """Elimina (archiva) una card del tablero."""
        if self._disabled:
            return False

        col = self._cards_collection(uid)
        if col is None:
            return False

        try:
            # Verificar que existe
            doc = col.document(card_id).get()
            if not doc.exists:
                return False

            # Archivar: mover status a "done" en lugar de borrar físicamente
            col.document(card_id).update({
                "status": "done",
                "updated_at": self._now_iso(),
                "metadata.archived": True,
            })
            log.info("Card archivada: uid=%s card=%s", uid[:8], card_id[:8])
            return True
        except Exception:
            log.exception("Error archivando card uid=%s card=%s", uid[:8], card_id[:8])
            return False

    def get_card_tree(self, uid: str, root_card_id: str) -> dict[str, Any] | None:
        """Devuelve el árbol completo de una card y sus hijos.

        Recursivo: la card raíz + sus hijos directos + hijos de hijos.
        """
        root = self.get_card(uid, root_card_id)
        if root is None:
            return None

        def _build_tree(card: WorkboardCard) -> dict[str, Any]:
            children = self._get_children(uid, card.id)
            return {
                "card": card.to_dict(),
                "id": card.id,
                "children": [_build_tree(child) for child in children],
                "children_count": len(children),
            }

        return _build_tree(root)

    def _get_children(self, uid: str, parent_id: str) -> list[WorkboardCard]:
        """Obtiene las cards hijas directas de una card padre."""
        if self._disabled:
            return []

        col = self._cards_collection(uid)
        if col is None:
            return []

        try:
            docs = col.where("parent_id", "==", parent_id).stream()
            children = []
            for doc in docs:
                data = doc.to_dict() or {}
                card = WorkboardCard.from_dict(doc.id, data)
                children.append(card)
            return children
        except Exception:
            log.exception("Error buscando hijos de card=%s uid=%s", parent_id[:8], uid[:8])
            return []

    # ── Heartbeat ─────────────────────────────────────────

    def _check_stale(self, card: WorkboardCard) -> WorkboardCard:
        """Verifica si una card en in_progress está stale (>24h)."""
        if card.status != CardStatus.in_progress:
            card.stale_warning = False
            return card

        try:
            updated = datetime.fromisoformat(card.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            stale_threshold = datetime.now(timezone.utc) - timedelta(hours=STALE_IN_PROGRESS_HOURS)
            card.stale_warning = updated < stale_threshold
        except (ValueError, TypeError):
            card.stale_warning = False

        return card

    def check_all_stale_cards(self, uid: str) -> list[WorkboardCard]:
        """Verifica y retorna todas las cards stale del usuario."""
        in_progress = self.list_cards(uid, status_filter="in_progress")
        stale = [c for c in in_progress if c.stale_warning]

        if stale:
            log.warning(
                "Stale cards detectadas: uid=%s count=%d",
                uid[:8], len(stale),
            )

        return stale

    def get_columns(self, uid: str) -> dict[str, list[WorkboardCard]]:
        """Devuelve el tablero completo organizado por columnas."""
        all_cards = self.list_cards(uid)

        columns: dict[str, list[WorkboardCard]] = {
            col: [] for col in DEFAULT_COLUMNS
        }

        for card in all_cards:
            status_str = card.status.value
            if status_str in columns:
                columns[status_str].append(card)

        return columns


# ── Singleton ───────────────────────────────────────────

_workboard_service: WorkboardService | None = None


def get_workboard_service() -> WorkboardService:
    """Devuelve el singleton WorkboardService."""
    global _workboard_service
    if _workboard_service is None:
        from app.settings import settings
        _workboard_service = WorkboardService(
            enabled=settings.workboard_enabled,
        )
    return _workboard_service
