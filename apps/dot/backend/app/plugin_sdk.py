"""Plugin SDK para Nordik-IA — decorador @plugin_tool y utilidades.

Permite a terceros crear herramientas que se auto-registran en ToolRegistry
sin tocar el core de DOT. Inspirado en OpenClaw's ClawHub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PluginToolMeta:
    """Metadatos de una tool de plugin, adjuntados via @plugin_tool."""

    name: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Any] | None = None


def plugin_tool(
    name: str,
    description: str = "",
    parameters_schema: dict[str, Any] | None = None,
) -> Callable:
    """Decorador que marca una función como tool de plugin.

    Uso:
        @plugin_tool("mi_tool", "Descripción de la tool", {
            "type": "object",
            "properties": {"param": {"type": "string"}},
            "required": ["param"]
        })
        def mi_tool_handler(uid: str, arguments: dict[str, Any]):
            ...

    La función decorada queda anotada con `_plugin_tool_meta` para que
    PluginManager la descubra y registre automáticamente.
    """
    schema = parameters_schema or {
        "type": "object",
        "properties": {},
    }

    def decorator(func: Callable) -> Callable:
        meta = PluginToolMeta(
            name=name,
            description=description or (func.__doc__ or "").strip(),
            parameters_schema=schema,
            handler=func,
        )
        func._plugin_tool_meta = meta  # type: ignore[attr-defined]
        return func

    return decorator


def discover_plugin_tools(module) -> list[PluginToolMeta]:
    """Descubre todas las funciones decoradas con @plugin_tool en un módulo."""
    tools: list[PluginToolMeta] = []
    for attr_name in dir(module):
        attr = getattr(module, attr_name, None)
        if callable(attr) and hasattr(attr, "_plugin_tool_meta"):
            meta: PluginToolMeta = attr._plugin_tool_meta  # type: ignore[attr-defined]
            meta.handler = attr
            tools.append(meta)
    return tools
