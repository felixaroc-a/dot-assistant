"""Tool de generación de hojas de cálculo con gráficos (P2.3).

Permite al agente crear archivos XLSX con múltiples hojas, tablas de datos
y gráficos (barras, líneas, torta) usando openpyxl.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.document_output_service import build_document_confirmation

log = logging.getLogger("dot.agent.tools.generate_spreadsheet")


def generate_spreadsheet_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un archivo XLSX con datos y gráficos.

    Args:
        arguments:
            title (str): nombre del archivo (sin extensión)
            data_sections (list[dict]): secciones de datos, cada una con:
                - section_title (str): título de la hoja
                - headers (list[str]): encabezados de columna
                - rows (list[list]): filas de datos (str|int|float)
                - chart_type (str, opcional): "bar", "line", "pie"
                - chart_title (str, opcional): título del gráfico
    """
    title = str(arguments.get("title") or "Hoja de cálculo DOT").strip()
    data_sections = arguments.get("data_sections")

    if not data_sections or not isinstance(data_sections, list) or len(data_sections) == 0:
        return ToolResult(ok=False, output="", error="generate_spreadsheet requiere data_sections (lista de secciones)")

    # Validar estructura básica de cada sección
    for i, section in enumerate(data_sections):
        if not isinstance(section, dict):
            return ToolResult(ok=False, output="", error=f"data_sections[{i}] debe ser un dict con headers y rows")
        if not section.get("headers") or not section.get("rows"):
            return ToolResult(ok=False, output="", error=f"data_sections[{i}] requiere headers y rows")

    try:
        from app.services.document_image_service import create_xlsx_with_charts

        result = create_xlsx_with_charts(
            title=title,
            data_sections=data_sections,
        )

        if not result.get("ok"):
            return ToolResult(ok=False, output="", error=str(result.get("error", "falló")))

        xlsx_path = str(result.get("path", ""))
        filename = str(result.get("filename", "hoja.xlsx"))
        sheet_count = result.get("sheet_count", len(data_sections))
        artifacts = [{
            "type": "spreadsheet",
            "path": xlsx_path,
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "name": filename,
        }]

        return ToolResult(
            ok=True,
            output=build_document_confirmation(
                kind="xlsx",
                filename=filename,
                path=xlsx_path,
                extra_lines=[f"Hojas: {sheet_count}"],
            ),
            artifacts=artifacts,
        )
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="openpyxl no está instalado. No se pueden generar hojas de cálculo con gráficos.",
        )
    except Exception as e:
        log.exception("Error generando hoja de cálculo XLSX")
        return ToolResult(ok=False, output="", error=f"Error al generar hoja de cálculo: {e}")
