"""Registro de tools — deny-by-default con políticas y auditoría.

PL06: soporte para fallback mapping entre tools (web_search → web_fetch, etc.).
PL08: tool policy enforcement (allow/deny) + audit log de ejecuciones.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.application.agent.ports import ToolHandler, ToolResult, ToolSpec

log = logging.getLogger("dot.agent.registry")


class ToolRegistry:
    """Tools conocidas. Cualquier nombre no registrado → error humano.

    PL06: soporta fallback_map para recuperación automática ante tool failures.
    PL08: enforcea tool policies (allow/deny) y registra auditoría.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._fallback_map: dict[str, str] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        name = (spec.name or "").strip()
        if not name:
            raise ValueError("ToolSpec.name vacío")
        self._specs[name] = spec
        self._handlers[name] = handler

    def unregister(self, name: str) -> bool:
        """Elimina una tool del registro. Retorna True si existía, False si no.

        Usado por PluginManager para desregistrar tools de plugins desinstalados.
        """
        name = name.strip()
        removed = False
        if name in self._specs:
            del self._specs[name]
            removed = True
        if name in self._handlers:
            del self._handlers[name]
            removed = True
        # Limpiar fallback mappings que referencien a esta tool
        self._fallback_map = {
            k: v for k, v in self._fallback_map.items() if v != name
        }
        return removed

    def set_fallback(self, from_tool: str, to_tool: str) -> None:
        """PL06: define tool alternativa si `from_tool` falla al ejecutarse."""
        from_tool = from_tool.strip()
        to_tool = to_tool.strip()
        if not from_tool or not to_tool:
            raise ValueError("set_fallback requiere tool names no vacíos")
        if from_tool == to_tool:
            raise ValueError(f"set_fallback: from_tool y to_tool no pueden ser iguales ({from_tool})")
        if not self.has(to_tool):
            log.warning("set_fallback: to_tool=%s no registrada aún; fallback no funcionará", to_tool)
        self._fallback_map[from_tool] = to_tool

    def get_fallback(self, name: str) -> str | None:
        """PL06: devuelve el nombre de la tool alternativa, o None si no hay mapeo."""
        return self._fallback_map.get(name.strip())

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def has(self, name: str) -> bool:
        return name in self._handlers

    def execute(self, uid: str, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        from app.application.agent.tool_rate_limit import allow_tool_call

        if not allow_tool_call(uid):
            return ToolResult(
                ok=False,
                output="",
                error="Demasiadas acciones seguidas. Espera un momento e inténtalo de nuevo.",
                artifacts=[],
            )

        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(
                ok=False,
                output="",
                error=f"Herramienta no disponible: {name}",
                artifacts=[],
            )

        # PL08: Tool policy enforcement — check allow/deny antes de ejecutar
        allowed, policy_reason = _check_policy(uid, name)
        if not allowed:
            log.warning(
                "Tool DENEGADA por política: uid=%s tool=%s razón=%s",
                uid[:8], name, policy_reason,
            )
            return ToolResult(
                ok=False,
                output="",
                error=policy_reason,
                artifacts=[],
            )

        # Loop-12: confirmación humana antes de acciones destructivas (chat usuario)
        confirm_ok, confirm_reason = _check_destructive_confirmation(name, arguments)
        if not confirm_ok:
            log.info(
                "Tool pendiente de confirmación: uid=%s tool=%s",
                uid[:8],
                name,
            )
            return ToolResult(
                ok=False,
                output="",
                error=confirm_reason,
                artifacts=[],
            )

        handler_args = _strip_confirm_argument(arguments)

        # Ejecutar con medición de tiempo y auditoría
        started_at = time.monotonic()
        try:
            from app.application.agent.browser_uid_context import browser_tool_uid_scope

            with browser_tool_uid_scope(uid):
                result = handler(uid, handler_args)
        except Exception as exc:  # noqa: BLE001 — fail human-readable al runtime
            result = ToolResult(
                ok=False,
                output="",
                error=f"Error al ejecutar {name}: {exc}",
                artifacts=[],
            )

        duration_ms = int((time.monotonic() - started_at) * 1000)

        # PL08: Audit log — registrar toda ejecución (success o failure)
        _log_audit(
            uid=uid,
            tool_name=name,
            arguments=arguments,
            result_ok=result.ok,
            error=result.error,
            duration_ms=duration_ms,
        )

        return result


# ---------------------------------------------------------------------------
# Helpers internos — evitan acoplar imports en __init__
# ---------------------------------------------------------------------------


def _check_destructive_confirmation(
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> tuple[bool, str]:
    try:
        from app.services.destructive_confirm_service import check_destructive_confirmation

        return check_destructive_confirmation(tool_name, arguments)
    except ImportError:
        return True, ""
    except Exception as exc:
        log.warning(
            "Error en confirmación destructiva tool=%s: %s",
            tool_name,
            exc,
        )
        return True, ""


def _strip_confirm_argument(arguments: dict[str, Any] | None) -> dict[str, Any]:
    try:
        from app.services.destructive_confirm_service import strip_confirm_argument

        return strip_confirm_argument(arguments)
    except ImportError:
        return arguments or {}


def _check_policy(uid: str, tool_name: str) -> tuple[bool, str]:
    """Verifica políticas de herramienta para uid. Retorna (allowed, reason)."""
    try:
        from app.services.tool_policy_service import check_tool_allowed

        return check_tool_allowed(uid, tool_name)
    except ImportError:
        # Si el servicio no está importable (ej. en tests sin Firestore),
        # fail open — permitir todo
        log.debug("tool_policy_service no disponible para uid=%s", uid[:8])
        return True, ""
    except Exception as exc:
        log.warning(
            "Error consultando política para uid=%s tool=%s: %s",
            uid[:8], tool_name, exc,
        )
        return True, ""


def _log_audit(
    uid: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    result_ok: bool,
    error: str | None,
    duration_ms: int,
) -> None:
    """Registra ejecución en el audit log (fire-and-forget)."""
    try:
        from app.services.tool_audit_service import log_tool_execution

        log_tool_execution(
            uid=uid,
            tool_name=tool_name,
            arguments=arguments,
            result_ok=result_ok,
            error=error,
            duration_ms=duration_ms,
        )
    except ImportError:
        log.debug("tool_audit_service no disponible para uid=%s", uid[:8])
    except Exception as exc:
        log.warning(
            "Error registrando auditoría para uid=%s tool=%s: %s",
            uid[:8], tool_name, exc,
        )
