"""Goal Tree Service — Descomposición jerárquica de objetivos.

Cada goal se descompone recursivamente en sub-goals usando LLM o heurística.
Las hojas del árbol pueden asignarse a sub-agentes para ejecución paralela.

Persistencia: Firestore users/{uid}/workboard/goals/{goal_id}

Integración con SubAgentManager: spawn agent per leaf goal.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.firebase_db import get_db

log = logging.getLogger("dot.goal_tree_service")


class GoalStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


@dataclass
class GoalNode:
    id: str
    description: str
    parent_id: str | None = None
    status: GoalStatus = GoalStatus.pending
    agent_assigned: str | None = None  # sub_agent_id
    result: str | None = None
    priority: int = 0  # orden entre hermanos
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "agent_assigned": self.agent_assigned,
            "result": self.result,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalNode":
        status_raw = data.get("status", "pending")
        try:
            status = GoalStatus(status_raw)
        except ValueError:
            status = GoalStatus.pending

        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            parent_id=data.get("parent_id"),
            status=status,
            agent_assigned=data.get("agent_assigned"),
            result=data.get("result"),
            priority=data.get("priority", 0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )


_DECOMPOSE_SYSTEM_PROMPT = """Eres un planificador estratégico. Descompone el objetivo dado en sub-objetivos concretos y accionables.

Devuelve SOLO JSON válido (sin markdown):
{
  "sub_goals": [
    {"description": "sub-objetivo 1", "priority": 0},
    {"description": "sub-objetivo 2", "priority": 1}
  ]
}

Reglas:
- Entre 2 y 5 sub-objetivos.
- Cada sub-objetivo debe ser concreto y accionable.
- priority: 0 = mayor prioridad.
- Si el objetivo ya es atómico (no se puede dividir más), devuelve sub_goals vacío [].
- Descripciones en español, claras y breves."""


class GoalTreeService:
    """Gestor de árboles de objetivos con descomposición recursiva.

    Persistencia: Firestore users/{uid}/workboard/goals/{goal_id}.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @property
    def _disabled(self) -> bool:
        return not self.enabled

    def _goals_collection(self, uid: str):
        db = get_db()
        if db is None:
            return None
        return (
            db.collection("users")
            .document(uid)
            .collection("workboard")
            .document("_goals")
            .collection("goals")
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Descomposición ────────────────────────────────────

    def decompose_goal(
        self,
        uid: str,
        goal_text: str,
        max_depth: int = 3,
        use_llm: bool = True,
    ) -> GoalNode | None:
        """Descompone un objetivo en árbol de sub-objetivos recursivamente.

        Args:
            uid: ID del usuario.
            goal_text: Texto del objetivo a descomponer.
            max_depth: Profundidad máxima del árbol (default 3).
            use_llm: Usar LLM para la descomposición (si está disponible).
        """
        if self._disabled:
            return None

        col = self._goals_collection(uid)
        if col is None:
            log.warning("Firestore no disponible para goal tree uid=%s", uid[:8])
            return None

        # Crear nodo raíz
        root = self._create_goal_node(uid, goal_text, parent_id=None)

        # Descomposición recursiva
        self._decompose_recursive(uid, root, depth=1, max_depth=max_depth, use_llm=use_llm)

        return root

    def _decompose_recursive(
        self,
        uid: str,
        node: GoalNode,
        depth: int,
        max_depth: int,
        use_llm: bool,
    ) -> None:
        """Descompone recursivamente un nodo en sub-objetivos."""
        if depth > max_depth:
            return

        sub_goals = self._get_sub_goals(node.description, use_llm)
        if not sub_goals:
            return  # Nodo hoja (atómico)

        for i, sub_desc in enumerate(sub_goals):
            child = self._create_goal_node(
                uid,
                sub_desc["description"],
                parent_id=node.id,
                priority=sub_desc.get("priority", i),
            )
            # Recursión
            self._decompose_recursive(uid, child, depth + 1, max_depth, use_llm)

    def _get_sub_goals(
        self,
        goal_text: str,
        use_llm: bool,
    ) -> list[dict[str, Any]]:
        """Obtiene sub-objetivos para un goal, vía LLM o heurística."""
        if use_llm:
            try:
                from app.services.provider_router import route_chat

                raw = route_chat(
                    goal_text,
                    provider_id="deepseek",
                    system_prompt=_DECOMPOSE_SYSTEM_PROMPT,
                    include_document_action_prompt=False,
                )
                result = self._parse_decompose_response(raw)
                if result is not None:
                    return result
            except Exception:
                log.debug("LLM decompose falló, usando heurística", exc_info=True)

        return self._decompose_heuristic(goal_text)

    def _parse_decompose_response(self, raw: str) -> list[dict[str, Any]] | None:
        """Parsea la respuesta JSON del LLM."""
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        sub_goals = data.get("sub_goals", [])
        if not isinstance(sub_goals, list):
            return None

        result = []
        for i, item in enumerate(sub_goals):
            if isinstance(item, str):
                result.append({"description": item.strip(), "priority": i})
            elif isinstance(item, dict):
                desc = str(item.get("description", "")).strip()
                if desc:
                    result.append({
                        "description": desc,
                        "priority": item.get("priority", i),
                    })

        return result if result else None

    def _decompose_heuristic(self, goal_text: str) -> list[dict[str, Any]]:
        """Descomposición heurística basada en palabras clave."""
        goal_lower = goal_text.lower()

        # Patrones comunes de descomposición
        patterns = [
            (["analizar", "investigar", "estudiar"], [
                "Recopilar información relevante",
                "Analizar datos y patrones",
                "Preparar informe de hallazgos",
            ]),
            (["crear", "construir", "desarrollar", "implementar"], [
                "Definir requisitos y alcance",
                "Diseñar solución",
                "Implementar funcionalidad",
                "Probar y validar",
            ]),
            (["planificar", "organizar", "coordinar"], [
                "Definir objetivos específicos",
                "Establecer cronograma",
                "Asignar recursos necesarios",
                "Ejecutar plan",
            ]),
            (["comparar", "evaluar", "revisar", "auditar"], [
                "Identificar criterios de evaluación",
                "Recopilar datos comparativos",
                "Analizar diferencias",
                "Emitir recomendación",
            ]),
            (["resumir", "sintetizar", "extraer"], [
                "Identificar puntos clave",
                "Organizar información",
                "Redactar resumen",
            ]),
        ]

        for keywords, steps in patterns:
            if any(kw in goal_lower for kw in keywords):
                return [{"description": s, "priority": i} for i, s in enumerate(steps)]

        # Fallback genérico
        if len(goal_text.split()) > 10:
            return [
                {"description": f"Analizar: {goal_text[:80]}", "priority": 0},
                {"description": "Ejecutar tarea principal", "priority": 1},
                {"description": "Verificar resultados", "priority": 2},
                {"description": "Preparar resumen final", "priority": 3},
            ]

        # Goal muy corto — probablemente atómico
        return []

    def _create_goal_node(
        self,
        uid: str,
        description: str,
        parent_id: str | None = None,
        priority: int = 0,
    ) -> GoalNode:
        """Crea y persiste un nodo de goal en Firestore."""
        col = self._goals_collection(uid)
        now = self._now_iso()

        node = GoalNode(
            id=str(uuid.uuid4()),
            description=description.strip(),
            parent_id=parent_id,
            priority=priority,
            created_at=now,
            updated_at=now,
        )

        if col is not None:
            try:
                col.document(node.id).set(node.to_dict())
            except Exception:
                log.exception("Error persistiendo goal node uid=%s", uid[:8])

        return node

    # ── Consulta de árbol ─────────────────────────────────

    def get_goal_tree(self, uid: str, root_goal_id: str) -> dict[str, Any] | None:
        """Devuelve el árbol completo desde un goal raíz."""
        col = self._goals_collection(uid)
        if col is None:
            return None

        root_doc = col.document(root_goal_id).get()
        if not root_doc.exists:
            return None

        root_data = root_doc.to_dict() or {}
        root = GoalNode.from_dict(root_data)

        return self._build_goal_tree(uid, root)

    def _build_goal_tree(self, uid: str, node: GoalNode) -> dict[str, Any]:
        """Construye recursivamente el árbol de goals."""
        children = self._get_child_goals(uid, node.id)
        children_trees = [self._build_goal_tree(uid, child) for child in children]

        return {
            "id": node.id,
            "description": node.description,
            "status": node.status.value,
            "agent_assigned": node.agent_assigned,
            "result": node.result,
            "priority": node.priority,
            "parent_id": node.parent_id,
            "children": children_trees,
            "children_count": len(children_trees),
            "created_at": node.created_at,
            "updated_at": node.updated_at,
        }

    def _get_child_goals(self, uid: str, parent_id: str) -> list[GoalNode]:
        """Obtiene los goals hijos de un goal padre."""
        col = self._goals_collection(uid)
        if col is None:
            return []

        try:
            docs = col.where("parent_id", "==", parent_id).stream()
            children = []
            for doc in docs:
                data = doc.to_dict() or {}
                children.append(GoalNode.from_dict(data))
            # Ordenar por prioridad
            children.sort(key=lambda c: c.priority)
            return children
        except Exception:
            log.exception("Error buscando hijos de goal=%s uid=%s", parent_id[:8], uid[:8])
            return []

    # ── Gestión de estado ─────────────────────────────────

    def mark_complete(self, uid: str, goal_id: str) -> GoalNode | None:
        """Marca un goal como completado. Auto-completa el padre si todos los hijos están done."""
        col = self._goals_collection(uid)
        if col is None:
            return None

        doc = col.document(goal_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        node = GoalNode.from_dict(data)

        node.status = GoalStatus.completed
        node.updated_at = self._now_iso()

        try:
            col.document(goal_id).set(node.to_dict(), merge=True)
            log.info("Goal completado: uid=%s goal=%s", uid[:8], goal_id[:8])
        except Exception:
            log.exception("Error marcando goal como completado uid=%s", uid[:8])
            return node

        # Auto-completar padre si todos los hijos están completados
        if node.parent_id:
            self._auto_complete_parent(uid, node.parent_id)

        return node

    def _auto_complete_parent(self, uid: str, parent_id: str) -> None:
        """Si todos los hijos están completados, marca el padre como completado."""
        children = self._get_child_goals(uid, parent_id)
        if not children:
            return

        all_done = all(c.status == GoalStatus.completed for c in children)
        if all_done:
            self._set_goal_status(uid, parent_id, GoalStatus.completed)
            log.info("Goal padre auto-completado: uid=%s goal=%s", uid[:8], parent_id[:8])

            # Recursión hacia arriba
            col = self._goals_collection(uid)
            if col:
                parent_doc = col.document(parent_id).get()
                if parent_doc.exists:
                    parent_data = parent_doc.to_dict() or {}
                    grandparent_id = parent_data.get("parent_id")
                    if grandparent_id:
                        self._auto_complete_parent(uid, grandparent_id)

    def _set_goal_status(self, uid: str, goal_id: str, status: GoalStatus) -> bool:
        """Actualiza el estado de un goal."""
        col = self._goals_collection(uid)
        if col is None:
            return False

        try:
            col.document(goal_id).set({
                "status": status.value,
                "updated_at": self._now_iso(),
            }, merge=True)
            return True
        except Exception:
            return False

    def set_goal_status(
        self,
        uid: str,
        goal_id: str,
        status: GoalStatus,
        result: str | None = None,
    ) -> GoalNode | None:
        """Actualiza el estado y resultado de un goal."""
        col = self._goals_collection(uid)
        if col is None:
            return None

        doc = col.document(goal_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        node = GoalNode.from_dict(data)
        node.status = status
        node.updated_at = self._now_iso()
        if result is not None:
            node.result = result

        try:
            col.document(goal_id).set(node.to_dict(), merge=True)
            log.info("Goal status actualizado: uid=%s goal=%s status=%s", uid[:8], goal_id[:8], status.value)
        except Exception:
            log.exception("Error actualizando goal status uid=%s", uid[:8])

        return node

    def get_leaf_goals(self, uid: str, root_goal_id: str) -> list[GoalNode]:
        """Obtiene todos los goals hoja (sin hijos) de un árbol."""
        leaves: list[GoalNode] = []

        def _collect_leaves(node_id: str) -> None:
            col = self._goals_collection(uid)
            if col is None:
                return

            doc = col.document(node_id).get()
            if not doc.exists:
                return

            data = doc.to_dict() or {}
            node = GoalNode.from_dict(data)

            children = self._get_child_goals(uid, node_id)
            if not children:
                leaves.append(node)
            else:
                for child in children:
                    _collect_leaves(child.id)

        _collect_leaves(root_goal_id)
        return leaves

    # ── Ejecución con sub-agentes ─────────────────────────

    def execute_leaf_goals(
        self,
        uid: str,
        root_goal_id: str,
        allowed_tools: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Ejecuta todos los goals hoja de un árbol usando sub-agentes.

        Cada goal hoja se asigna a un sub-agente independiente.
        Los resultados se recolectan y los goals se marcan como completados.

        Returns:
            Lista de resultados: [{goal_id, agent_id, status, result}, ...]
        """
        from app.services.sub_agent_service import get_sub_agent_manager

        leaves = self.get_leaf_goals(uid, root_goal_id)
        if not leaves:
            log.warning("No hay goals hoja para ejecutar uid=%s root=%s", uid[:8], root_goal_id[:8])
            return []

        manager = get_sub_agent_manager()

        # Filtrar solo pending
        pending_leaves = [l for l in leaves if l.status == GoalStatus.pending]
        if not pending_leaves:
            return []

        # Obtener registry para los sub-agentes
        from app.application.agent.tools import build_default_registry
        from app.settings import settings

        registry = build_default_registry(
            include_web_search=bool(settings.enable_web_search)
        )

        results: list[dict[str, Any]] = []
        spawned: dict[str, GoalNode] = {}

        # Lanzar sub-agentes en paralelo
        for leaf in pending_leaves:
            try:
                agent_id = manager.spawn_sub_agent(
                    uid=uid,
                    name=f"Goal-{leaf.description[:30]}",
                    goal=leaf.description,
                    allowed_tools=allowed_tools or [],
                    context={"goal_id": leaf.id, "root_goal_id": root_goal_id},
                    registry=registry,
                )
                leaf.agent_assigned = agent_id
                leaf.status = GoalStatus.in_progress
                self._update_goal_node(uid, leaf)
                spawned[agent_id] = leaf
                log.info("Goal hoja delegado a sub-agente: goal=%s agent=%s", leaf.id[:8], agent_id[:8])
            except RuntimeError:
                log.warning("Límite de sub-agentes alcanzado para goal=%s", leaf.id[:8])
                results.append({
                    "goal_id": leaf.id,
                    "agent_id": None,
                    "status": "failed",
                    "result": "Límite de sub-agentes alcanzado",
                })

        # Esperar resultados
        for agent_id, leaf in spawned.items():
            result = manager.wait_for_sub_agent(uid, agent_id, timeout=600.0)
            if result is None:
                leaf.status = GoalStatus.failed
                leaf.result = f"Sub-agente {agent_id[:8]} no respondió a tiempo"
                self._update_goal_node(uid, leaf)
                results.append({
                    "goal_id": leaf.id,
                    "agent_id": agent_id,
                    "status": "failed",
                    "result": leaf.result,
                })
                continue

            if result["status"] == "completed":
                leaf.status = GoalStatus.completed
                leaf.result = result.get("result_summary", "Completado")
                self._update_goal_node(uid, leaf)
                # Auto-completar padre
                if leaf.parent_id:
                    self._auto_complete_parent(uid, leaf.parent_id)
            elif result["status"] in ("failed", "cancelled", "idle_timeout"):
                leaf.status = GoalStatus.failed
                leaf.result = result.get("error_message", result["status"])
                self._update_goal_node(uid, leaf)

            results.append({
                "goal_id": leaf.id,
                "agent_id": agent_id,
                "status": result["status"],
                "result": leaf.result,
            })

        return results

    def _update_goal_node(self, uid: str, node: GoalNode) -> None:
        """Persiste un nodo de goal en Firestore."""
        col = self._goals_collection(uid)
        if col is None:
            return
        try:
            col.document(node.id).set(node.to_dict(), merge=True)
        except Exception:
            log.exception("Error actualizando goal node uid=%s goal=%s", uid[:8], node.id[:8])


# ── Singleton ───────────────────────────────────────────

_goal_tree_service: GoalTreeService | None = None


def get_goal_tree_service() -> GoalTreeService:
    """Devuelve el singleton GoalTreeService."""
    global _goal_tree_service
    if _goal_tree_service is None:
        from app.settings import settings
        _goal_tree_service = GoalTreeService(
            enabled=settings.workboard_enabled,
        )
    return _goal_tree_service
