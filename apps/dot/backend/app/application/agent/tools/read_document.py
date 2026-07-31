"""Tool C01: read_document — lee y extrae texto de PDF, DOCX y TXT.

Usa document-parser.cjs (Electron) via bridge local para extraer texto
de documentos sin que el archivo salga del PC del usuario.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.read_document")

MIME_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/plain",
    ".rtf": "application/rtf",
}


def _guess_mime(path: str) -> str | None:
    """Determina el MIME type basado en la extension del archivo."""
    suffix = Path(path).suffix.lower()
    return MIME_MAP.get(suffix)


def read_document_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae texto de un documento PDF, DOCX o TXT en el PC del usuario.

    Args:
        arguments:
            path (str): ruta absoluta del documento en el PC del usuario
                      (Desktop, Documents, Downloads o DOT Trabajos).
    """
    path_raw = str(arguments.get("path", "")).strip()
    if not path_raw:
        return ToolResult(
            ok=False,
            output="",
            error="read_document necesita la ruta del archivo (path).",
        )

    mime = _guess_mime(path_raw)
    if not mime:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"Tipo de archivo no soportado: {Path(path_raw).suffix or 'sin extensión'}. "
                "Solo PDF, DOCX y TXT son soportados."
            ),
        )

    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge(
            "parseDocument",
            path=path_raw,
            content=mime,  # pasamos MIME type como content para el bridge
        )

        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el documento."))
            human = {
                "bridge_secret_not_configured": "El puente local no está configurado. Abre la app DOT en el PC.",
                "bridge_unreachable": "No se pudo conectar con el PC (bridge). ¿Está abierta la app DOT?",
                "bridge_unauthorized": "El puente local rechazó la autenticación.",
            }.get(err, err)
            return ToolResult(ok=False, output="", error=human)

        text = str(raw.get("text", raw.get("content", "")))
        if not text.strip():
            return ToolResult(
                ok=False,
                output="",
                error="El documento fue procesado pero no se encontró texto extraíble.",
            )

        truncated = text if len(text) <= 12000 else text[:12000] + "\n\n[Texto truncado a 12,000 caracteres]"

        return ToolResult(
            ok=True,
            output=f"Contenido de {Path(path_raw).name}:\n\n{truncated}",
            artifacts=[{
                "type": "document_parsed",
                "path": path_raw,
                "mime": mime,
                "chars": len(text),
            }],
        )
    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.exception("Error en read_document para path=%s", path_raw[:120])
        return ToolResult(ok=False, output="", error=f"Error al leer el documento: {e}")
