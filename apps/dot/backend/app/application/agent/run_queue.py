"""Cola in-process para serializar run_agent por sesión (AgentRunQueue).

FREE-T04b: usa threading.Lock/Semaphore a propósito — run_agent es sync y se invoca
desde endpoints sync o vía asyncio.to_thread en SSE; migrar la cola a asyncio requeriría
reescribir runtime + cancel cooperativo. No convertir a ThreadPoolExecutor ad-hoc aquí.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Literal, TypeVar

T = TypeVar("T")

# Máximo de runs concurrentes entre todas las sesiones.
MAX_CONCURRENT = 4

RunMode = Literal["followup", "interrupt"]

_global_sem = threading.Semaphore(MAX_CONCURRENT)
_lanes_guard = threading.Lock()
_lanes: dict[str, "SessionLane"] = {}


class AgentRunSuperseded(RuntimeError):
    """Un run en cola fue descartado por mode=interrupt."""


class AgentRunCancelled(RuntimeError):
    """El run activo fue cancelado por un interrupt posterior."""


class SessionLane:
    """Un run activo por lane; los demás esperan en cola FIFO."""

    def __init__(self) -> None:
        self._run_lock = threading.Lock()
        self._meta = threading.Lock()
        self._generation = 0
        self._cancel_event: threading.Event | None = None

    def request_cancel(self) -> None:
        with self._meta:
            if self._cancel_event is not None:
                self._cancel_event.set()

    def run(self, fn: Callable[[threading.Event], T], *, mode: RunMode = "followup") -> T:
        with self._meta:
            if mode == "interrupt":
                # Descarta runs en cola que aún no empezaron + señal al activo.
                self._generation += 1
                if self._cancel_event is not None:
                    self._cancel_event.set()
            ticket = self._generation

        with _global_sem:
            with self._run_lock:
                with self._meta:
                    if ticket != self._generation:
                        raise AgentRunSuperseded(
                            "Run descartado: llegó otro con mode=interrupt"
                        )
                    cancel_event = threading.Event()
                    self._cancel_event = cancel_event
                try:
                    return fn(cancel_event)
                finally:
                    with self._meta:
                        if self._cancel_event is cancel_event:
                            self._cancel_event = None


def _get_lane(session_key: str) -> SessionLane:
    with _lanes_guard:
        lane = _lanes.get(session_key)
        if lane is None:
            lane = SessionLane()
            _lanes[session_key] = lane
        return lane


def enqueue_agent_run(
    session_key: str,
    fn: Callable[..., T],
    *,
    mode: RunMode = "followup",
) -> T:
    """Encola y ejecuta fn serializado por session_key (sync, apto para FastAPI).

    - followup (default): espera turno si el lane está ocupado.
    - interrupt: descarta runs en cola pendientes y cancela el activo (cooperativo).

    `fn` puede aceptar 0 args o 1 arg (`cancel_event: threading.Event`).
    """
    import inspect

    def _invoke(cancel_event: threading.Event) -> T:
        try:
            sig = inspect.signature(fn)
            if any(p.name == "cancel_event" for p in sig.parameters.values()):
                return fn(cancel_event=cancel_event)  # type: ignore[misc]
        except (TypeError, ValueError):
            pass
        return fn()  # type: ignore[call-arg]

    lane = _get_lane(session_key)
    return lane.run(_invoke, mode=mode)


def reset_run_queue_for_tests() -> None:
    """Solo tests: limpia lanes in-process."""
    with _lanes_guard:
        _lanes.clear()
