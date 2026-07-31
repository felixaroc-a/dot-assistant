"""Tool web_search para el Agent Runtime (reemplaza heurística pre-inyectada)."""

from __future__ import annotations

from typing import Any

from app.application.agent.ports import ToolResult
from app.settings import settings


def web_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid  # authz a nivel runtime/endpoint
    if not settings.enable_web_search:
        return ToolResult(
            ok=False,
            output="",
            error="La búsqueda web no está habilitada en esta instalación.",
        )
    query = str(arguments.get("query") or arguments.get("q") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="web_search requiere query")
    try:
        from app.services.web_search import search_and_format_sync

        text = search_and_format_sync(query)
        if not (text or "").strip():
            return ToolResult(ok=False, output="", error="Sin resultados de búsqueda.")
        return ToolResult(ok=True, output=text.strip())
    except Exception as e:
        error_msg = str(e).lower()
        if "timeout" in error_msg or "timed out" in error_msg:
            return ToolResult(
                ok=False,
                output="",
                error="La búsqueda web tardó demasiado. Revisa tu conexión a internet e intenta de nuevo.",
            )
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude buscar en la web: {e}. Revisa tu conexión o intenta más tarde.",
        )
