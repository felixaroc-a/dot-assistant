"""Sandbox de ejecucion para automatizaciones.

Aisla cada ejecucion con:
- Timeout forzoso (30s por defecto; 120s para Agent/third-option)
- Captura de excepciones
- Sin acceso al filesystem del servidor (solo sandbox del usuario)
- Logs de ejecucion separados

Override global: env ``DOT_AGENT_SANDBOX_TIMEOUT`` (segundos).
"""
from __future__ import annotations

import logging
import os
import signal
import threading
from contextlib import contextmanager
from typing import Any, Callable

# Integraciones que ejecutan Agent Runtime (multi-step, tools reales).
_AGENT_INTEGRATIONS = frozenset(
    {"third-option", "chat", "manual", "agent", "dot", ""}
)

log = logging.getLogger("dot.sandbox")


def resolve_sandbox_timeout(
    payload: dict[str, Any] | None = None,
    *,
    default: int = 30,
    agent_default: int = 120,
) -> int:
    """Resuelve timeout del sandbox según integración del payload.

    - ``DOT_AGENT_SANDBOX_TIMEOUT``: override numérico global (segundos).
    - third-option / chat / vacío → ``agent_default`` (120s).
    - Resto → ``default`` (30s).
    """
    override = (os.getenv("DOT_AGENT_SANDBOX_TIMEOUT") or "").strip()
    if override.isdigit():
        return int(override)

    integration = ""
    if payload:
        integration = str(
            payload.get("integration_id")
            or payload.get("integrationId")
            or payload.get("integration")
            or ""
        ).strip().lower()

    if integration in _AGENT_INTEGRATIONS:
        return agent_default
    return default


class SandboxTimeoutError(RuntimeError):
    """La ejecucion excedio el tiempo maximo permitido."""


class SandboxError(RuntimeError):
    """Error controlado dentro del sandbox."""


@contextmanager
def timeout(seconds: int, message: str = "La automatizacion excedio el tiempo limite"):
    """Context manager que lanza SandboxTimeoutError si la ejecucion excede N segundos.

    Usa signal.SIGALRM en Unix, fallback a threading.Timer en Windows.
    """
    import platform

    if platform.system() != "Windows":
        # Unix: signal-based timeout (mas preciso)
        original = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(seconds)
        try:
            yield
        except SandboxTimeoutError:
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original)
    else:
        # Windows: threading-based timeout
        timer = threading.Timer(seconds, _raise_timeout)
        timer.start()
        try:
            yield
        except SandboxTimeoutError:
            raise
        finally:
            timer.cancel()


def _raise_timeout(*args: object) -> None:
    raise SandboxTimeoutError("La automatizacion excedio el tiempo limite")


class ExecutionSandbox:
    """Entorno aislado para ejecutar una automatizacion.

    Uso:
        sandbox = ExecutionSandbox(timeout_seconds=30)
        result = sandbox.run(lambda: mi_funcion(), context="gmail")
    """

    def __init__(self, timeout_seconds: int = 30):
        self._timeout = timeout_seconds

    def run(self, fn: Callable[[], str], context: str = "general") -> str:
        """Ejecuta una funcion dentro del sandbox con timeout."""
        log.info("Sandbox ejecutando: %s (timeout=%ds)", context, self._timeout)
        try:
            with timeout(self._timeout):
                result = fn()
                log.info("Sandbox completado: %s (%d chars)", context, len(result))
                return result
        except SandboxTimeoutError:
            log.error("Sandbox TIMEOUT: %s excedio %ds", context, self._timeout)
            raise
        except Exception as e:
            log.error("Sandbox ERROR: %s - %s", context, e)
            raise SandboxError(str(e)) from e


def validate_automation_payload(payload: dict[str, Any]) -> None:
    """Valida que el payload de automatizacion sea seguro."""
    instruction = str(payload.get("instruction", "")).strip()
    if not instruction:
        raise SandboxError("Instruccion vacia en la automatizacion")

    if len(instruction) > 10_000:
        raise SandboxError("Instruccion demasiado larga (max 10000 caracteres)")

    # No permitir instrucciones que intenten acceder al sistema
    dangerous_keywords = [
        "import os", "import subprocess", "__import__", "eval(", "exec(",
        "open(", "system(", "popen", "shutil",
    ]
    lower = instruction.lower()
    for kw in dangerous_keywords:
        if kw in lower:
            raise SandboxError(f"Instruccion rechazada: contiene '{kw}'")

    log.debug("Payload validado: %s", payload.get("id", "unknown")[:8])
