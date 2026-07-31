"""Tool de generación de documentos con imágenes incrustadas (P2.2).

Permite al agente crear documentos DOCX con texto e imágenes,
orquestando el flujo: generar imagen → guardar → referenciar en documento.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.document_output_service import build_document_confirmation

log = logging.getLogger("dot.agent.tools.generate_document")


def generate_document_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un documento DOCX con texto e imágenes incrustadas.

    Args:
        arguments:
            title (str): nombre del documento
            content (str): contenido markdown/texto. Usa [IMAGE:0], [IMAGE:1] para referenciar imágenes
            image_paths (list[str], opcional): rutas absolutas de imágenes a incrustar
            folder (str, opcional): subcarpeta dentro de DOT Trabajos
    """
    title = str(arguments.get("title") or "Documento DOT").strip()
    content = str(arguments.get("content") or "")
    if not content.strip():
        return ToolResult(ok=False, output="", error="generate_document requiere content")

    image_paths = arguments.get("image_paths")
    if image_paths is not None:
        if not isinstance(image_paths, list):
            return ToolResult(ok=False, output="", error="image_paths debe ser una lista de rutas")
        image_paths = [str(p) for p in image_paths if isinstance(p, str) and p.strip()]
    else:
        image_paths = []

    folder = arguments.get("folder")
    if folder is not None:
        folder = str(folder).strip() or None

    try:
        from app.services.document_image_service import create_docx_with_images

        result = create_docx_with_images(
            title=title,
            content=content,
            image_paths=image_paths if image_paths else None,
            folder=folder,
        )

        if not result.get("ok"):
            return ToolResult(ok=False, output="", error=str(result.get("error", "falló")))

        docx_path = str(result.get("path", ""))
        filename = str(result.get("filename", "documento.docx"))
        artifacts = [{
            "type": "document",
            "path": docx_path,
            "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "name": filename,
        }]

        return ToolResult(
            ok=True,
            output=build_document_confirmation(
                kind="docx",
                filename=filename,
                path=docx_path,
                extra_lines=[f"Imágenes incrustadas: {result.get('image_count', 0)}"],
            ),
            artifacts=artifacts,
        )
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="python-docx no está instalado. No se pueden generar documentos DOCX.",
        )
    except Exception as e:
        log.exception("Error generando documento DOCX")
        return ToolResult(ok=False, output="", error=f"Error al generar documento: {e}")
