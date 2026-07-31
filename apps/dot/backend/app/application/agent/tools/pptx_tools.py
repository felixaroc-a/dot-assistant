"""Tool de lectura y generación de presentaciones PowerPoint (.pptx).

Permite al agente leer presentaciones existentes (pptx_read) y
generar nuevas presentaciones con texto, imágenes y gráficos (pptx_generate).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.document_output_service import build_document_confirmation

log = logging.getLogger("dot.agent.tools.pptx")


def pptx_read_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee una presentación .pptx y extrae slides.

    Args:
        arguments:
            file_path (str): ruta absoluta al archivo .pptx
    """
    file_path = str(arguments.get("file_path", "")).strip()
    if not file_path:
        return ToolResult(
            ok=False,
            output="",
            error="pptx_read necesita file_path (ruta al archivo .pptx).",
        )

    try:
        from app.services.pptx_service import read_pptx

        result = read_pptx(file_path)

        if not result.get("ok"):
            return ToolResult(
                ok=False,
                output="",
                error=str(result.get("error", "No se pudo leer la presentación.")),
            )

        slides = result.get("slides", [])
        output_lines = [
            f"Presentación: {result.get('filename')}",
            f"Slides: {result.get('slide_count')}",
            "",
        ]
        for i, slide in enumerate(slides, 1):
            output_lines.append(f"--- Slide {i} ---")
            title = slide.get("title", "")
            if title:
                output_lines.append(f"Título: {title}")
            content = slide.get("content", "")
            if content:
                output_lines.append(f"Contenido: {content}")
            notes = slide.get("notes", "")
            if notes:
                output_lines.append(f"Notas: {notes}")
            img_count = slide.get("images_count", 0)
            if img_count > 0:
                output_lines.append(f"Imágenes: {img_count}")
            output_lines.append("")

        return ToolResult(
            ok=True,
            output="\n".join(output_lines),
            artifacts=[{
                "type": "pptx_read",
                "path": file_path,
                "filename": result.get("filename"),
                "slide_count": result.get("slide_count"),
                "slides": slides,
            }],
        )
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="python-pptx no está instalado. No se pueden leer presentaciones PPTX.",
        )
    except Exception as e:
        log.exception("Error leyendo PPTX: %s", file_path)
        return ToolResult(ok=False, output="", error=f"Error al leer presentación: {e}")


def pptx_generate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera una presentación .pptx a partir de datos estructurados.

    Args:
        arguments:
            title (str): nombre de la presentación
            slides_json (str): JSON string con array de slides. Cada slide:
                - title (str): título de la slide
                - content (str): contenido textual
                - image_urls (list[str], opcional): rutas de imágenes
                - chart_data (dict, opcional): {type, categories, series, title}
                - notes (str, opcional): notas del orador
            template (str, opcional): "default" (único por ahora)
            folder (str, opcional): subcarpeta en DOT Trabajos
    """
    title = str(arguments.get("title") or "Presentación DOT").strip()
    slides_raw = arguments.get("slides_json")

    if slides_raw is None:
        return ToolResult(
            ok=False,
            output="",
            error="pptx_generate requiere slides_json (array JSON de slides).",
        )

    # slides_json puede venir como string o ya parseado como lista
    if isinstance(slides_raw, str):
        try:
            slides_data = json.loads(slides_raw)
        except json.JSONDecodeError as e:
            return ToolResult(
                ok=False,
                output="",
                error=f"slides_json no es JSON válido: {e}",
            )
    elif isinstance(slides_raw, list):
        slides_data = slides_raw
    else:
        return ToolResult(
            ok=False,
            output="",
            error="slides_json debe ser un string JSON o una lista de slides.",
        )

    if not slides_data or not isinstance(slides_data, list):
        return ToolResult(
            ok=False,
            output="",
            error="slides_json está vacío. Se necesita al menos una slide.",
        )

    template = str(arguments.get("template", "default")).strip() or "default"
    folder = arguments.get("folder")
    if folder is not None:
        folder = str(folder).strip() or None

    try:
        from app.services.pptx_service import generate_pptx

        result = generate_pptx(
            title=title,
            slides_data=slides_data,
            template=template,
            folder=folder,
        )

        if not result.get("ok"):
            return ToolResult(
                ok=False,
                output="",
                error=str(result.get("error", "Error al generar presentación.")),
            )

        pptx_path = str(result.get("path", ""))
        filename = str(result.get("filename", "presentacion.pptx"))
        slide_count = result.get("slide_count", 0)
        artifacts = [{
            "type": "pptx",
            "path": pptx_path,
            "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "name": filename,
        }]

        return ToolResult(
            ok=True,
            output=build_document_confirmation(
                kind="pptx",
                filename=filename,
                path=pptx_path,
                extra_lines=[f"Diapositivas: {slide_count}"],
            ),
            artifacts=artifacts,
        )
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="python-pptx no está instalado. No se pueden generar presentaciones PPTX.",
        )
    except Exception as e:
        log.exception("Error generando PPTX: %s", title)
        return ToolResult(ok=False, output="", error=f"Error al generar presentación: {e}")
