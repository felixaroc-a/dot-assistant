"""Tool de búsqueda de archivos en el PC del usuario (P2.1).

Permite al agente buscar archivos por nombre o contenido en Desktop,
Documents y Downloads del usuario vía el bridge local de Electron.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.application.agent.tools.local_files import (
    _format_local_output,
    execute_local_tool_via_bridge,
)

log = logging.getLogger("dot.agent.tools.file_search")


def file_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca archivos en el PC vía bridge Electron.

    Args:
        arguments:
            query (str): nombre o patrón de archivo a buscar
            contentPattern (str, opcional): texto dentro del archivo
            searchRoot (str, opcional): "desktop"|"documents"|"downloads"|"all" (default: "all")
    """
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="file_search requiere query")

    content_pattern = arguments.get("contentPattern")
    if content_pattern is not None:
        content_pattern = str(content_pattern).strip() or None

    search_root = str(arguments.get("searchRoot") or "all").strip()

    from app.settings import settings

    raw = execute_local_tool_via_bridge(
        "searchFiles",
        query=query,
        content_pattern=content_pattern,
        search_root=search_root,
        scope="full" if settings.full_disk_access_enabled else None,
    )

    ok = bool(raw.get("ok"))
    if ok:
        results = raw.get("results") or []
        count = raw.get("count", len(results) if isinstance(results, list) else 0)
        artifacts = []
        for r in (results if isinstance(results, list) else []):
            if isinstance(r, dict) and r.get("path"):
                ext = str(r.get("extension") or "").lower()
                mime_map = {
                    ".pdf": "application/pdf",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".txt": "text/plain",
                    ".csv": "text/csv",
                    ".md": "text/markdown",
                }
                mime = mime_map.get(ext, "application/octet-stream")
                artifacts.append({
                    "type": "document",
                    "path": r["path"],
                    "mime": mime,
                    "name": r.get("name", ""),
                })
        return ToolResult(
            ok=True,
            output=f"Búsqueda completada: {count} archivo(s) encontrado(s).\n{_format_local_output('searchFiles', raw)}",
            artifacts=artifacts if artifacts else [],
        )
    err = str(raw.get("error") or "falló la búsqueda")
    human = {
        "bridge_secret_not_configured": "El puente local no está configurado. Abre la app DOT en el PC.",
        "bridge_unreachable": "No pude llegar al PC (bridge). ¿Está abierta la app DOT?",
        "bridge_unauthorized": "El puente local rechazó la autenticación.",
    }.get(err, err)
    return ToolResult(ok=False, output="", error=human)
