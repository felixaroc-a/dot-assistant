"""Agent Runtime — orquestador único chat PC + WhatsApp (M2 / PROMPTSOTE)."""

from app.application.agent.ports import AgentResult, ToolCall, ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry
from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry

__all__ = [
    "AgentResult",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "ToolRegistry",
    "run_agent",
    "build_default_registry",
]
