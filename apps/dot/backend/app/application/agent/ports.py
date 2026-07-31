"""Puertos del Agent Runtime (hexagonal): specs de tools y resultados."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """Descripción de una tool registrable (deny-by-default vía registry)."""

    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: str | None = None
    duration_ms: int = 0
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    """Salida canónica de run_agent."""

    final_text: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    model_usage: dict[str, Any] | None = None
    model_name: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    # Cada artifact: {"type": "document", "path": "C:/...", "mime": "application/pdf"}
    #               {"type": "image", "path": "C:/...", "mime": "image/png"}
    #               {"type": "whatsapp_sent", "to": "+58...", "text": "..."}


class ToolHandler(Protocol):
    def __call__(self, uid: str, arguments: dict[str, Any]) -> ToolResult: ...


# Callable inyectable para tests / adapters (evita acoplar DeepSeek en el loop).
ModelTurnFn = Callable[..., Any]
