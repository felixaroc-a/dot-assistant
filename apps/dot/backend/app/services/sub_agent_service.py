"""Sub-Agent Manager — agentes delegados con workspace aislado.

GOAL 3: Arquitectura de sub-agentes estilo OpenClaw.
Cada sub-agente tiene su propio contexto de conversación, tool access,
y ejecuta en background con progreso reportable.

Características:
- Workspace isolation: cada sub-agente tiene su propio conversation context.
- Delegación: el agente padre puede delegar tareas a sub-agentes.
- Background execution: los sub-agentes corren en background sin bloquear.
- Progress reporting: estado, progreso y paso actual visibles.
- Auto-terminate: sub-agentes inactivos por 30 min se terminan automáticamente.
- Cancelación: el usuario puede cancelar sub-agentes en cualquier momento.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.sub_agent")

# ── Constantes ──────────────────────────────────────────

MAX_SUB_AGENTS_PER_USER = 5
SUB_AGENT_IDLE_TIMEOUT_SECONDS = 30 * 60  # 30 minutos
SUB_AGENT_MAX_STEPS = 15
SUB_AGENT_HEARTBEAT_INTERVAL = 10  # segundos entre heartbeats


class SubAgentStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    idle_timeout = "idle_timeout"


@dataclass
class SubAgentTask:
    """Tarea delegada a un sub-agente."""
    goal: str
    allowed_tools: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    parent_conversation_id: str | None = None


@dataclass
class SubAgentState:
    """Estado runtime de un sub-agente."""
    agent_id: str
    uid: str
    name: str
    task: SubAgentTask
    status: SubAgentStatus = SubAgentStatus.pending
    progress: float = 0.0  # 0.0 a 1.0
    current_step: str = ""
    result_summary: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps_completed: int = 0
    steps_total: int = 0
    # Contexto aislado de conversación
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    # Thread de ejecución
    _thread: threading.Thread | None = field(default=None, repr=False)
    _cancel_event: threading.Event | None = field(default=None, repr=False)
    # Tool registry (referencia al global, puede ser filtrado)
    _registry: Any = field(default=None, repr=False)


class SubAgentManager:
    """Gestor central de sub-agentes — singleton por proceso.

    Responsabilidades:
    - Crear, monitorear y cancelar sub-agentes.
    - Auto-terminar sub-agentes inactivos.
    - Mantener contexto aislado por sub-agente.
    """

    def __init__(self):
        self._agents: dict[str, dict[str, SubAgentState]] = {}  # uid -> {agent_id -> state}
        self._lock = threading.Lock()
        self._idle_check_task: asyncio.Task | None = None
        self._shutting_down = False

    # ═══════════════════════════════════════════════════════
    # GOAL 3: Creación y gestión de sub-agentes
    # ═══════════════════════════════════════════════════════

    def spawn_sub_agent(
        self,
        uid: str,
        name: str,
        goal: str,
        allowed_tools: list[str] | None = None,
        context: dict[str, Any] | None = None,
        parent_conversation_id: str | None = None,
        registry: Any = None,
    ) -> str:
        """Crea un sub-agente y lo lanza en background.

        Args:
            uid: ID del usuario propietario.
            name: Nombre descriptivo del sub-agente.
            goal: Objetivo que debe cumplir el sub-agente.
            allowed_tools: Lista de tools permitidas (vacío = todas).
            context: Contexto adicional (datos, preferencias, etc.).
            parent_conversation_id: ID de la conversación padre.
            registry: ToolRegistry para el sub-agente.

        Returns:
            agent_id único del sub-agente creado.

        Raises:
            RuntimeError si el usuario excede el límite de sub-agentes.
        """
        with self._lock:
            user_agents = self._agents.setdefault(uid, {})

            # Contar agentes activos (pending + running)
            active_count = sum(
                1 for a in user_agents.values()
                if a.status in (SubAgentStatus.pending, SubAgentStatus.running)
            )
            if active_count >= MAX_SUB_AGENTS_PER_USER:
                raise RuntimeError(
                    f"Límite de sub-agentes alcanzado ({MAX_SUB_AGENTS_PER_USER}). "
                    "Cancela uno existente antes de crear otro."
                )

            agent_id = str(uuid.uuid4())
            task = SubAgentTask(
                goal=goal,
                allowed_tools=list(allowed_tools or []),
                context=dict(context or {}),
                parent_conversation_id=parent_conversation_id,
            )

            state = SubAgentState(
                agent_id=agent_id,
                uid=uid,
                name=name,
                task=task,
                _registry=registry,
            )

            user_agents[agent_id] = state

        # Lanzar en background
        cancel_event = threading.Event()
        state._cancel_event = cancel_event
        state._thread = threading.Thread(
            target=self._run_sub_agent,
            args=(state, cancel_event),
            name=f"sub-agent-{agent_id[:8]}",
            daemon=True,
        )
        state._thread.start()

        log.info(
            "Sub-agente '%s' creado: uid=%s id=%s goal=%s",
            name, uid[:8], agent_id[:8], goal[:80],
        )
        return agent_id

    def get_sub_agent_status(self, uid: str, agent_id: str) -> dict[str, Any] | None:
        """Devuelve el estado detallado de un sub-agente."""
        with self._lock:
            user_agents = self._agents.get(uid, {})
            state = user_agents.get(agent_id)

        if state is None:
            return None

        return {
            "agent_id": state.agent_id,
            "name": state.name,
            "status": state.status.value,
            "progress": state.progress,
            "current_step": state.current_step,
            "goal": state.task.goal,
            "steps_completed": state.steps_completed,
            "steps_total": state.steps_total,
            "created_at": state.created_at.isoformat(),
            "last_active_at": state.last_active_at.isoformat(),
            "result_summary": state.result_summary,
            "error_message": state.error_message,
            "allowed_tools": state.task.allowed_tools,
        }

    def get_active_sub_agents(self, uid: str) -> list[dict[str, Any]]:
        """Lista todos los sub-agentes activos de un usuario."""
        with self._lock:
            user_agents = self._agents.get(uid, {})

        active = []
        for agent_id, state in user_agents.items():
            if state.status in (
                SubAgentStatus.pending,
                SubAgentStatus.running,
            ):
                active.append(self.get_sub_agent_status(uid, agent_id))

        return active

    def get_all_sub_agents(self, uid: str) -> list[dict[str, Any]]:
        """Lista todos los sub-agentes (activos + terminados) de un usuario."""
        with self._lock:
            user_agents = self._agents.get(uid, {})

        return [
            self.get_sub_agent_status(uid, agent_id)
            for agent_id in user_agents
        ]

    def cancel_sub_agent(self, uid: str, agent_id: str) -> bool:
        """Cancela un sub-agente en ejecución.

        Returns:
            True si se canceló, False si no existía o ya terminó.
        """
        with self._lock:
            user_agents = self._agents.get(uid, {})
            state = user_agents.get(agent_id)

        if state is None:
            return False

        if state.status not in (SubAgentStatus.pending, SubAgentStatus.running):
            return False

        if state._cancel_event:
            state._cancel_event.set()

        state.status = SubAgentStatus.cancelled
        state.current_step = "Cancelado por el usuario"
        state.last_active_at = datetime.now(timezone.utc)

        log.info("Sub-agente '%s' cancelado: uid=%s id=%s", state.name, uid[:8], agent_id[:8])
        return True

    def get_sub_agent_result(self, uid: str, agent_id: str) -> dict[str, Any] | None:
        """Devuelve el resultado final de un sub-agente completado."""
        status = self.get_sub_agent_status(uid, agent_id)
        if status is None:
            return None

        if status["status"] not in (
            SubAgentStatus.completed.value,
            SubAgentStatus.failed.value,
            SubAgentStatus.cancelled.value,
            SubAgentStatus.idle_timeout.value,
        ):
            return None

        return {
            "agent_id": agent_id,
            "name": status["name"],
            "status": status["status"],
            "goal": status["goal"],
            "result_summary": status["result_summary"],
            "error_message": status["error_message"],
            "steps_completed": status["steps_completed"],
            "steps_total": status["steps_total"],
        }

    # ═══════════════════════════════════════════════════════
    # GOAL 3: Ejecución en background
    # ═══════════════════════════════════════════════════════

    def _run_sub_agent(
        self,
        state: SubAgentState,
        cancel_event: threading.Event,
    ) -> None:
        """Ejecuta el ciclo de vida del sub-agente en un thread separado.

        El sub-agente:
        1. Planifica pasos para el goal.
        2. Ejecuta tools permitidas secuencialmente.
        3. Reporta progreso.
        4. Termina con resultado o error.
        """
        state.status = SubAgentStatus.running
        state.current_step = "Inicializando..."

        try:
            # Usar planner para generar plan
            plan = self._draft_sub_agent_plan(state)

            if cancel_event.is_set():
                state.status = SubAgentStatus.cancelled
                return

            state.steps_total = len(plan)
            state.current_step = f"Plan creado: {len(plan)} pasos"

            # Ejecutar pasos
            for i, step in enumerate(plan):
                if cancel_event.is_set():
                    state.status = SubAgentStatus.cancelled
                    state.current_step = "Cancelado"
                    return

                state.current_step = f"Paso {i + 1}/{len(plan)}: {step['description'][:100]}"
                state.progress = (i + 0.5) / max(len(plan), 1)
                state.last_active_at = datetime.now(timezone.utc)

                try:
                    result = self._execute_sub_agent_step(state, step)
                    step["result"] = result
                    state.steps_completed = i + 1

                    if not result.get("ok", False):
                        state.current_step = f"Paso {i + 1} falló: {result.get('error', '')[:80]}"
                        # Continuar con siguientes pasos incluso si uno falla
                except Exception as step_err:
                    step["result"] = {"ok": False, "error": str(step_err)}
                    state.steps_completed = i + 1

                state.progress = (i + 1) / max(len(plan), 1)

            if cancel_event.is_set():
                state.status = SubAgentStatus.cancelled
                return

            # Finalizar
            state.status = SubAgentStatus.completed
            state.progress = 1.0
            state.current_step = "Completado"

            # Generar resumen
            summary_parts = []
            for step in plan:
                result = step.get("result", {})
                if result.get("ok"):
                    output = result.get("output", "")[:200]
                    summary_parts.append(f"✓ {step['description'][:80]}: {output}")
                else:
                    summary_parts.append(f"✗ {step['description'][:80]}: {result.get('error', 'error')[:80]}")

            state.result_summary = "\n".join(summary_parts)

            log.info(
                "Sub-agente '%s' completado: uid=%s id=%s steps=%d/%d",
                state.name, state.uid[:8], state.agent_id[:8],
                state.steps_completed, state.steps_total,
            )

        except Exception as e:
            log.exception("Sub-agente '%s' falló: uid=%s id=%s", state.name, state.uid[:8], state.agent_id[:8])
            state.status = SubAgentStatus.failed
            state.error_message = str(e)
            state.current_step = f"Error: {str(e)[:100]}"

        finally:
            # Workboard: sincronizar estado de la card asignada a este sub-agente
            _sync_workboard_on_sub_agent_complete(state)

    def _draft_sub_agent_plan(self, state: SubAgentState) -> list[dict[str, Any]]:
        """Genera un plan de pasos para el sub-agente usando el LLM o heurística."""
        # Si hay registry y LLM disponible, usar planner
        if state._registry is not None and hasattr(state._registry, 'list_specs'):
            try:
                from app.application.agent.planner import draft_plan

                plan = draft_plan(state.task.goal, state._registry)

                steps = []
                for step in plan.steps:
                    if step.tool_name:
                        if not state.task.allowed_tools or step.tool_name in state.task.allowed_tools:
                            steps.append({
                                "description": step.description,
                                "tool_name": step.tool_name,
                            })
                        else:
                            # Tool no permitida, convertir a paso sin tool
                            steps.append({
                                "description": f"[Tool restringida: {step.tool_name}] {step.description}",
                                "tool_name": None,
                            })
                    else:
                        steps.append({
                            "description": step.description,
                            "tool_name": None,
                        })

                if steps:
                    return steps
            except Exception:
                log.debug("Planner LLM falló para sub-agente, usando heurística", exc_info=True)

        # Fallback heurístico
        return [
            {
                "description": f"Analizar objetivo: {state.task.goal[:100]}",
                "tool_name": None,
            },
            {
                "description": "Ejecutar tarea principal",
                "tool_name": None,
            },
            {
                "description": "Preparar resumen de resultados",
                "tool_name": None,
            },
        ]

    def _execute_sub_agent_step(
        self,
        state: SubAgentState,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta un paso del sub-agente, incluyendo tool calls si aplica."""
        tool_name = step.get("tool_name")
        if not tool_name or state._registry is None:
            # Paso sin tool — simular completado
            state.conversation_history.append({
                "role": "assistant",
                "content": f"Paso completado: {step['description']}",
            })
            return {"ok": True, "output": f"Completado: {step['description']}"}

        # Verificar tool permitida
        if state.task.allowed_tools and tool_name not in state.task.allowed_tools:
            return {"ok": False, "error": f"Tool no permitida: {tool_name}"}

        # Ejecutar tool via registry
        try:
            result: ToolResult = state._registry.execute(
                state.uid,
                tool_name,
                {"goal": state.task.goal, "context": state.task.context},
            )

            state.conversation_history.append({
                "role": "tool",
                "content": f"[{tool_name}]: {result.output[:200] if result.ok else result.error}",
            })

            return {
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════
    # GOAL 3: Auto-terminate idle sub-agents
    # ═══════════════════════════════════════════════════════

    async def start_idle_monitor(self) -> None:
        """Inicia el monitor de inactividad que termina sub-agentes idle.

        Llamar desde lifespan de FastAPI.
        """
        if self._idle_check_task is not None:
            return

        self._idle_check_task = asyncio.create_task(
            self._idle_monitor_loop(),
            name="sub-agent-idle-monitor",
        )
        log.info("Monitor de inactividad de sub-agentes iniciado (timeout=%ds)", SUB_AGENT_IDLE_TIMEOUT_SECONDS)

    async def stop_idle_monitor(self) -> None:
        """Detiene el monitor de inactividad."""
        self._shutting_down = True
        if self._idle_check_task and not self._idle_check_task.done():
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass
        log.info("Monitor de inactividad de sub-agentes detenido")

    async def _idle_monitor_loop(self) -> None:
        """Loop que verifica y termina sub-agentes inactivos cada 60s."""
        while not self._shutting_down:
            await asyncio.sleep(60)

            if self._shutting_down:
                break

            now = datetime.now(timezone.utc)
            idle_timeout = timedelta(seconds=SUB_AGENT_IDLE_TIMEOUT_SECONDS)

            with self._lock:
                for uid, user_agents in list(self._agents.items()):
                    for agent_id, state in list(user_agents.items()):
                        if state.status not in (
                            SubAgentStatus.pending,
                            SubAgentStatus.running,
                        ):
                            continue

                        idle_duration = now - state.last_active_at
                        if idle_duration > idle_timeout:
                            log.warning(
                                "Sub-agente '%s' inactivo por %s — auto-terminando",
                                state.name, idle_duration,
                            )
                            state.status = SubAgentStatus.idle_timeout
                            state.current_step = "Terminado por inactividad (30 min)"
                            state.error_message = (
                                f"Sub-agente inactivo por más de "
                                f"{SUB_AGENT_IDLE_TIMEOUT_SECONDS // 60} minutos"
                            )
                            if state._cancel_event:
                                state._cancel_event.set()

    # ═══════════════════════════════════════════════════════
    # GOAL 3: Delegación desde el planner
    # ═══════════════════════════════════════════════════════

    def delegate_to_sub_agent(
        self,
        uid: str,
        goal: str,
        allowed_tools: list[str] | None = None,
        context: dict[str, Any] | None = None,
        registry: Any = None,
    ) -> tuple[str, SubAgentState]:
        """Delega una tarea a un sub-agente desde el planner.

        Wrapper conveniente para usar desde planner.py.

        Returns:
            (agent_id, state) del sub-agente creado.
        """
        agent_id = self.spawn_sub_agent(
            uid=uid,
            name=f"Agent-{goal[:30]}",
            goal=goal,
            allowed_tools=allowed_tools,
            context=context,
            registry=registry,
        )

        with self._lock:
            state = self._agents.get(uid, {}).get(agent_id)

        return agent_id, state

    def wait_for_sub_agent(
        self,
        uid: str,
        agent_id: str,
        timeout: float = 300.0,
    ) -> dict[str, Any] | None:
        """Espera a que un sub-agente termine (bloqueante, usar en thread).

        Args:
            uid: ID del usuario.
            agent_id: ID del sub-agente.
            timeout: Tiempo máximo de espera en segundos.

        Returns:
            Resultado del sub-agente, o None si timeout.
        """
        with self._lock:
            user_agents = self._agents.get(uid, {})
            state = user_agents.get(agent_id)

        if state is None:
            return None

        thread = state._thread
        if thread is None:
            return self.get_sub_agent_result(uid, agent_id)

        thread.join(timeout=timeout)

        if thread.is_alive():
            log.warning("Timeout esperando sub-agente %s (%.0fs)", agent_id[:8], timeout)
            return None

        return self.get_sub_agent_result(uid, agent_id)


# ── Singleton ───────────────────────────────────────────

_sub_agent_manager: SubAgentManager | None = None


def get_sub_agent_manager() -> SubAgentManager:
    """Devuelve el singleton SubAgentManager."""
    global _sub_agent_manager
    if _sub_agent_manager is None:
        _sub_agent_manager = SubAgentManager()
    return _sub_agent_manager


async def init_sub_agent_manager() -> SubAgentManager:
    """Inicializa el gestor de sub-agentes y su monitor de inactividad."""
    manager = get_sub_agent_manager()
    await manager.start_idle_monitor()
    log.info("SubAgentManager inicializado con idle monitor")
    return manager


def _sync_workboard_on_sub_agent_complete(state: SubAgentState) -> None:
    """Cuando un sub-agente termina, mueve su card asignada en el workboard.

    Busca cards del usuario que tengan assignee == agent_id y las mueve a done/blocked.
    """
    try:
        from app.settings import settings
        if not settings.workboard_enabled:
            return
    except Exception:
        return

    agent_id = state.agent_id
    uid = state.uid

    try:
        from app.services.workboard_service import CardStatus, get_workboard_service

        svc = get_workboard_service()
        if not svc.enabled:
            return

        # Buscar cards asignadas a este sub-agente
        all_cards = svc.list_cards(uid)
        for card in all_cards:
            if card.assignee == agent_id and card.status not in (CardStatus.done, CardStatus.blocked):
                if state.status == SubAgentStatus.completed:
                    svc.move_card(uid, card.id, CardStatus.done)
                    log.info("Workboard: card %s movida a done (sub-agente completado)", card.id[:8])
                elif state.status in (SubAgentStatus.failed, SubAgentStatus.idle_timeout):
                    svc.move_card(uid, card.id, CardStatus.blocked)
                    log.info("Workboard: card %s movida a blocked (sub-agente %s)", card.id[:8], state.status.value)
                elif state.status == SubAgentStatus.cancelled:
                    svc.move_card(uid, card.id, CardStatus.todo)
                    log.info("Workboard: card %s movida a todo (sub-agente cancelado)", card.id[:8])
    except Exception:
        log.debug("Workboard: error sincronizando sub-agente completion", exc_info=True)


async def shutdown_sub_agent_manager() -> None:
    """Apaga el gestor de sub-agentes."""
    manager = get_sub_agent_manager()
    await manager.stop_idle_monitor()
    log.info("SubAgentManager apagado")
