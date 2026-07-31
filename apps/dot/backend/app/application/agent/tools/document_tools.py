"""Herramientas de documentos — leer, editar, OCR, comparar, PDFs, metadatos, idioma.

13 handlers de procesamiento documental para DOT Agent Runtime.
Usa el bridge local (readFile/writeFile/parseDocument) para no sacar
archivos del PC del usuario. PyPDF2, Pillow y langdetect son opcionales.
"""
from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.document_tools")


# ─────────────────────────────────────────────────────────────
# 1. doc_read_pdf_form — leer campos de formulario PDF
# ─────────────────────────────────────────────────────────────

def doc_read_pdf_form_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee campos de formulario de un PDF (extrae texto y busca patrones de campos).

    Args:
        arguments:
            path (str): ruta absoluta del PDF en el PC del usuario.
    """
    try:
        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="doc_read_pdf_form necesita la ruta del archivo (path).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el PDF."))
            return ToolResult(ok=False, output="", error=err)

        content = str(raw.get("text", raw.get("content", "")))
        if not content.strip():
            return ToolResult(ok=False, output="", error="El PDF está vacío o no tiene texto extraíble.")

        fields: list[dict[str, str]] = []
        # Buscar patrones de campos de formulario en texto del PDF
        # Patrón tipo "Nombre: ________" o "Email: [________]"
        field_pattern = re.compile(
            r'([A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ\s]{1,40}?)\s*[:]\s*[_\[]{3,}',
            re.MULTILINE,
        )
        for match in field_pattern.finditer(content):
            fields.append({"campo": match.group(1).strip(), "valor_actual": ""})

        # Patrón tipo checkbox / radio
        check_pattern = re.compile(r'[\[\(]\s*[Xx]?\s*[\]\)]\s*([A-Za-zÁÉÍÓÚÑáéíóúñ][^\n]{2,60})', re.MULTILINE)
        for match in check_pattern.finditer(content):
            checked = "X" in match.group(0)[:3].upper() or "x" in match.group(0)[:3]
            fields.append({
                "campo": match.group(1).strip(),
                "valor_actual": "Marcado" if checked else "Sin marcar",
            })

        if not fields:
            return ToolResult(
                ok=True,
                output=f"No se detectaron campos de formulario en '{Path(path).name}'. "
                        f"El PDF tiene {len(content)} caracteres de texto. "
                        f"Si es un formulario escaneado, usa doc_ocr_image primero.",
                artifacts=[{"type": "pdf_form_read", "path": path, "fields_found": 0}],
            )

        lines = [f"Campos de formulario en '{Path(path).name}':"]
        for i, f in enumerate(fields, 1):
            lines.append(f"  {i}. {f['campo']}: {f['valor_actual'] or '(vacío)'}")

        return ToolResult(
            ok=True,
            output="\n".join(lines),
            artifacts=[{"type": "pdf_form_read", "path": path, "fields_found": len(fields), "fields": fields}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_read_pdf_form error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al leer campos del formulario: {e}")


# ─────────────────────────────────────────────────────────────
# 2. doc_fill_pdf_form — rellenar campos de formulario PDF
# ─────────────────────────────────────────────────────────────

def doc_fill_pdf_form_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Rellena campos de un formulario PDF con datos proporcionados.

    Args:
        arguments:
            path (str): ruta absoluta del PDF.
            data (dict): diccionario con nombre_campo → valor.
            output_path (str): ruta donde guardar el PDF relleno (opcional).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        data = arguments.get("data")
        output_path = str(arguments.get("output_path") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_fill_pdf_form necesita la ruta del archivo (path).")
        if not data or not isinstance(data, dict):
            return ToolResult(ok=False, output="", error="doc_fill_pdf_form necesita data (diccionario campo→valor).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el PDF."))
            return ToolResult(ok=False, output="", error=err)

        content = str(raw.get("text", raw.get("content", "")))
        if not content.strip():
            return ToolResult(ok=False, output="", error="El PDF está vacío o no tiene texto extraíble.")

        filled = content
        filled_count = 0
        for campo, valor in data.items():
            val = str(valor)
            # Reemplazar campo: "Campo: ________" → "Campo: valor"
            pattern = re.compile(
                re.escape(campo) + r'\s*[:]\s*[_\[]{3,}',
                re.MULTILINE | re.IGNORECASE,
            )
            if pattern.search(filled):
                filled = pattern.sub(f"{campo}: {val}", filled)
                filled_count += 1

        dest = output_path or path
        write_raw = execute_local_tool_via_bridge("writeFile", path=dest, content=filled)
        if not write_raw.get("ok"):
            err = str(write_raw.get("error", "No se pudo guardar el PDF relleno."))
            return ToolResult(ok=False, output="", error=err)

        return ToolResult(
            ok=True,
            output=f"Formulario '{Path(path).name}' rellenado: {filled_count} de {len(data)} campos "
                    f"aplicados. Guardado en '{Path(dest).name}'.",
            artifacts=[{"type": "pdf_form_filled", "path": dest, "fields_filled": filled_count}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_fill_pdf_form error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al rellenar el formulario: {e}")


# ─────────────────────────────────────────────────────────────
# 3. doc_ocr_image — OCR de imagen vía DeepSeek Vision
# ─────────────────────────────────────────────────────────────

def doc_ocr_image_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae texto de una imagen usando OCR por IA (DeepSeek Vision).

    Args:
        arguments:
            path (str): ruta absoluta de la imagen (PNG, JPG, WEBP).
            language (str): idioma esperado del texto (opcional, default: es).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        language = str(arguments.get("language") or "es").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_ocr_image necesita la ruta del archivo (path).")

        ext = Path(path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"):
            return ToolResult(
                ok=False, output="",
                error=f"Formato de imagen no soportado: {ext}. Usa PNG, JPG, WEBP, BMP, GIF o TIFF.",
            )

        from app.services.provider_router import route_chat

        lang_hint = {"es": "español", "en": "inglés", "pt": "portugués", "fr": "francés",
                      "de": "alemán", "it": "italiano"}.get(language, language)

        result = route_chat(
            f"Extrae TODO el texto visible en esta imagen. Responde solo con el texto extraído, "
            f"sin comentarios adicionales. El idioma esperado es {lang_hint}.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un OCR de precisión. Extraes TODO el texto visible en imágenes. "
                "No inventes texto que no esté presente. Preserva saltos de línea y formato. "
                "Si no hay texto visible, responde 'NO_TEXT_FOUND'."
            ),
        )

        text = result.strip()
        if not text or text == "NO_TEXT_FOUND":
            return ToolResult(
                ok=True,
                output=f"No se detectó texto en la imagen '{Path(path).name}'. "
                        f"La imagen podría estar vacía o ser solo gráfica.",
                artifacts=[{"type": "ocr_result", "path": path, "chars": 0}],
            )

        return ToolResult(
            ok=True,
            output=f"Texto extraído de '{Path(path).name}' (OCR):\n\n{text}",
            artifacts=[{"type": "ocr_result", "path": path, "chars": len(text), "language": language}],
        )

    except ImportError:
        return ToolResult(
            ok=False, output="",
            error="El servicio de IA no está disponible. Verifica que el backend esté funcionando.",
        )
    except Exception as e:
        msg = str(e)
        if "vision" in msg.lower() or "image" in msg.lower() or "multimodal" in msg.lower():
            return ToolResult(
                ok=False, output="",
                error="El OCR por IA no está disponible: el modelo actual no soporta procesamiento de imágenes "
                      "(se requiere capacidad multimodal/vision). Como alternativa, convierte la imagen a PDF "
                      "y usa read_document, o instala Tesseract para OCR local.",
            )
        log.warning("doc_ocr_image error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al hacer OCR de la imagen: {e}")


# ─────────────────────────────────────────────────────────────
# 4. doc_extract_tables — extraer tablas de PDF/CSV
# ─────────────────────────────────────────────────────────────

def doc_extract_tables_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae tablas de un documento PDF o CSV.

    Args:
        arguments:
            path (str): ruta absoluta del archivo.
            delimiter (str): delimitador para CSV (opcional, default: coma).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        delimiter = str(arguments.get("delimiter") or ",").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_extract_tables necesita la ruta del archivo (path).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el archivo."))
            return ToolResult(ok=False, output="", error=err)

        content = str(raw.get("text", raw.get("content", "")))
        if not content.strip():
            return ToolResult(ok=False, output="", error="El archivo está vacío.")

        ext = Path(path).suffix.lower()
        tables: list[list[list[str]]] = []
        total_rows = 0

        if ext == ".csv":
            import csv
            import io
            reader = csv.reader(io.StringIO(content), delimiter=delimiter)
            rows = [[cell.strip() for cell in row] for row in reader]
            if rows:
                tables.append(rows)
                total_rows = len(rows)

        elif ext in (".txt", ".tsv", ".tab"):
            lines = content.strip().split("\n")
            rows = [[cell.strip() for cell in line.split(delimiter)] for line in lines if line.strip()]
            if rows:
                tables.append(rows)
                total_rows = len(rows)

        elif ext == ".pdf":
            # Buscar patrones de tabla en texto de PDF (líneas con | o múltiples espacios)
            lines = content.strip().split("\n")
            table_rows: list[list[str]] = []
            in_table = False
            for line in lines:
                stripped = line.strip()
                if "|" in stripped:
                    cells = [c.strip() for c in stripped.split("|") if c.strip()]
                    if cells:
                        table_rows.append(cells)
                        in_table = True
                        continue
                # Detectar filas con múltiples columnas separadas por 3+ espacios
                spaced = re.split(r'\s{3,}', stripped)
                if len(spaced) >= 3 and all(len(c) < 60 for c in spaced):
                    table_rows.append([c.strip() for c in spaced])
                    in_table = True
                    continue
                if in_table and not stripped:
                    # Fin de tabla actual
                    if table_rows:
                        tables.append(table_rows)
                        total_rows += len(table_rows)
                    table_rows = []
                    in_table = False
            if table_rows:
                tables.append(table_rows)
                total_rows += len(table_rows)

        else:
            return ToolResult(
                ok=False, output="",
                error=f"Formato no soportado para extraer tablas: {ext}. Usa PDF, CSV o TXT.",
            )

        if not tables:
            return ToolResult(
                ok=True,
                output=f"No se encontraron tablas en '{Path(path).name}'. "
                        f"El archivo tiene {len(content)} caracteres.",
                artifacts=[{"type": "tables_extracted", "path": path, "table_count": 0}],
            )

        output_lines = [f"Tablas extraídas de '{Path(path).name}' ({len(tables)} tabla(s), {total_rows} filas):"]
        for t_idx, table in enumerate(tables, 1):
            output_lines.append(f"\n--- Tabla {t_idx} ({len(table)} filas) ---")
            for row in table[:50]:  # máximo 50 filas por tabla
                output_lines.append(" | ".join(row))
            if len(table) > 50:
                output_lines.append(f"  ... y {len(table) - 50} filas más")

        return ToolResult(
            ok=True,
            output="\n".join(output_lines),
            artifacts=[{"type": "tables_extracted", "path": path,
                         "table_count": len(tables), "total_rows": total_rows}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_extract_tables error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al extraer tablas: {e}")


# ─────────────────────────────────────────────────────────────
# 5. doc_compare — comparar dos documentos
# ─────────────────────────────────────────────────────────────

def doc_compare_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Compara dos documentos línea por línea y devuelve las diferencias.

    Args:
        arguments:
            path_a (str): ruta absoluta del primer documento.
            path_b (str): ruta absoluta del segundo documento.
            context_lines (int): líneas de contexto alrededor de cada diff (opcional, default: 2).
    """
    try:
        path_a = str(arguments.get("path_a") or "").strip()
        path_b = str(arguments.get("path_b") or "").strip()
        context_lines = int(arguments.get("context_lines") or 2)

        if not path_a or not path_b:
            return ToolResult(ok=False, output="", error="doc_compare necesita path_a y path_b.")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw_a = execute_local_tool_via_bridge("readFile", path=path_a)
        if not raw_a.get("ok"):
            err = str(raw_a.get("error", "No se pudo leer el primer documento."))
            return ToolResult(ok=False, output="", error=f"Error leyendo {Path(path_a).name}: {err}")

        raw_b = execute_local_tool_via_bridge("readFile", path=path_b)
        if not raw_b.get("ok"):
            err = str(raw_b.get("error", "No se pudo leer el segundo documento."))
            return ToolResult(ok=False, output="", error=f"Error leyendo {Path(path_b).name}: {err}")

        text_a = str(raw_a.get("text", raw_a.get("content", "")))
        text_b = str(raw_b.get("text", raw_b.get("content", "")))

        lines_a = text_a.splitlines(keepends=False)
        lines_b = text_b.splitlines(keepends=False)

        differ = difflib.unified_diff(
            lines_a, lines_b,
            fromfile=Path(path_a).name,
            tofile=Path(path_b).name,
            n=context_lines,
            lineterm="",
        )

        diff_lines = list(differ)
        if not diff_lines:
            return ToolResult(
                ok=True,
                output=f"Los documentos '{Path(path_a).name}' y '{Path(path_b).name}' son idénticos.",
                artifacts=[{"type": "diff_result", "path_a": path_a, "path_b": path_b, "differences": 0}],
            )

        added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        diff_text = "\n".join(diff_lines)
        if len(diff_text) > 8000:
            diff_text = diff_text[:8000] + "\n\n[Diferencia truncada a 8,000 caracteres]"

        return ToolResult(
            ok=True,
            output=f"Diferencias entre '{Path(path_a).name}' y '{Path(path_b).name}' "
                    f"(+{added} líneas añadidas, -{removed} líneas eliminadas):\n\n{diff_text}",
            artifacts=[{"type": "diff_result", "path_a": path_a, "path_b": path_b,
                         "added": added, "removed": removed}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_compare error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al comparar documentos: {e}")


# ─────────────────────────────────────────────────────────────
# 6. doc_merge_pdfs — unir PDFs con PyPDF2
# ─────────────────────────────────────────────────────────────

def doc_merge_pdfs_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Une múltiples archivos PDF en uno solo usando PyPDF2.

    Args:
        arguments:
            paths (list[str]): lista de rutas absolutas de PDFs a unir (en orden).
            output_path (str): ruta donde guardar el PDF unificado.
    """
    try:
        paths = arguments.get("paths")
        output_path = str(arguments.get("output_path") or "").strip()

        if not paths or not isinstance(paths, list) or len(paths) < 2:
            return ToolResult(ok=False, output="", error="doc_merge_pdfs necesita paths (lista de al menos 2 PDFs).")
        if not output_path:
            return ToolResult(ok=False, output="", error="doc_merge_pdfs necesita output_path para guardar el resultado.")

        try:
            from PyPDF2 import PdfMerger
        except ImportError:
            return ToolResult(
                ok=False, output="",
                error="Requiere instalar PyPDF2: pip install PyPDF2",
            )

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        merger = PdfMerger()
        merged_count = 0

        for pdf_path in paths:
            p = str(pdf_path).strip()
            if not p:
                continue
            raw = execute_local_tool_via_bridge("readFile", path=p)
            if not raw.get("ok"):
                err = str(raw.get("error", "No se pudo leer el PDF."))
                return ToolResult(ok=False, output="", error=f"Error leyendo '{Path(p).name}': {err}")

            content = raw.get("text", raw.get("content", ""))
            if isinstance(content, bytes):
                import io
                merger.append(io.BytesIO(content))
            elif isinstance(content, str):
                merger.append(io.BytesIO(content.encode("utf-8", errors="replace")))
            else:
                return ToolResult(ok=False, output="", error=f"No se pudo leer el contenido de '{Path(p).name}'.")
            merged_count += 1

        import io
        output_buffer = io.BytesIO()
        merger.write(output_buffer)
        merger.close()

        write_raw = execute_local_tool_via_bridge(
            "writeFile", path=output_path,
            content=output_buffer.getvalue().decode("latin-1", errors="replace"),
        )
        if not write_raw.get("ok"):
            err = str(write_raw.get("error", "No se pudo guardar el PDF unificado."))
            return ToolResult(ok=False, output="", error=err)

        return ToolResult(
            ok=True,
            output=f"{merged_count} PDFs unidos exitosamente en '{Path(output_path).name}'.",
            artifacts=[{"type": "pdf_merged", "path": output_path, "merged_count": merged_count}],
        )

    except Exception as e:
        log.warning("doc_merge_pdfs error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al unir PDFs: {e}")


# ─────────────────────────────────────────────────────────────
# 7. doc_split_pdf — dividir PDF con PyPDF2
# ─────────────────────────────────────────────────────────────

def doc_split_pdf_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Divide un PDF en páginas individuales o por rangos usando PyPDF2.

    Args:
        arguments:
            path (str): ruta absoluta del PDF a dividir.
            output_folder (str): carpeta donde guardar las páginas extraídas (opcional).
            pages (str): páginas a extraer (ej: "1-3,5,7-9"). Si no se da, extrae todas.
    """
    try:
        path = str(arguments.get("path") or "").strip()
        output_folder = str(arguments.get("output_folder") or "").strip()
        pages_spec = str(arguments.get("pages") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_split_pdf necesita la ruta del archivo (path).")

        try:
            from PyPDF2 import PdfReader, PdfWriter
        except ImportError:
            return ToolResult(
                ok=False, output="",
                error="Requiere instalar PyPDF2: pip install PyPDF2",
            )

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el PDF."))
            return ToolResult(ok=False, output="", error=err)

        content = raw.get("text", raw.get("content", ""))
        if isinstance(content, bytes):
            import io
            reader = PdfReader(io.BytesIO(content))
        elif isinstance(content, str):
            import io
            reader = PdfReader(io.BytesIO(content.encode("latin-1", errors="replace")))
        else:
            return ToolResult(ok=False, output="", error="No se pudo leer el contenido del PDF.")

        total_pages = len(reader.pages)

        # Parsear especificación de páginas
        pages_to_extract: set[int] = set()
        if pages_spec:
            for part in pages_spec.split(","):
                part = part.strip()
                if "-" in part:
                    try:
                        start, end = part.split("-", 1)
                        pages_to_extract.update(range(int(start), int(end) + 1))
                    except ValueError:
                        pass
                else:
                    try:
                        pages_to_extract.add(int(part))
                    except ValueError:
                        pass
        else:
            pages_to_extract = set(range(1, total_pages + 1))

        # Filtrar páginas válidas
        valid_pages = sorted(p for p in pages_to_extract if 1 <= p <= total_pages)
        if not valid_pages:
            return ToolResult(
                ok=False, output="",
                error=f"Especificación de páginas inválida. El PDF tiene {total_pages} páginas. "
                      f"Usa números del 1 al {total_pages} o rangos como '1-3'.",
            )

        base_name = Path(path).stem
        out_dir = output_folder or str(Path(path).parent)
        extracted_count = 0

        for page_num in valid_pages:
            writer = PdfWriter()
            writer.add_page(reader.pages[page_num - 1])

            import io as io_mod
            buf = io_mod.BytesIO()
            writer.write(buf)

            out_path = f"{out_dir.rstrip('/').rstrip('\\')}/{base_name}_pagina_{page_num}.pdf"
            write_raw = execute_local_tool_via_bridge(
                "writeFile", path=out_path,
                content=buf.getvalue().decode("latin-1", errors="replace"),
            )
            if write_raw.get("ok"):
                extracted_count += 1

        return ToolResult(
            ok=True,
            output=f"PDF '{Path(path).name}' dividido: {extracted_count} de {len(valid_pages)} páginas "
                    f"extraídas en '{out_dir}' (total PDF: {total_pages} páginas).",
            artifacts=[{"type": "pdf_split", "path": path, "extracted_pages": extracted_count,
                         "valid_pages": valid_pages, "total_pages": total_pages}],
        )

    except Exception as e:
        log.warning("doc_split_pdf error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al dividir PDF: {e}")


# ─────────────────────────────────────────────────────────────
# 8. doc_watermark — añadir marca de agua con PyPDF2
# ─────────────────────────────────────────────────────────────

def doc_watermark_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Añade una marca de agua de texto a un PDF usando PyPDF2.

    Args:
        arguments:
            path (str): ruta absoluta del PDF original.
            watermark_text (str): texto de la marca de agua.
            output_path (str): ruta donde guardar el PDF con marca de agua.
    """
    try:
        path = str(arguments.get("path") or "").strip()
        watermark_text = str(arguments.get("watermark_text") or "").strip()
        output_path = str(arguments.get("output_path") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_watermark necesita la ruta del archivo (path).")
        if not watermark_text:
            return ToolResult(ok=False, output="", error="doc_watermark necesita watermark_text.")
        if not output_path:
            return ToolResult(ok=False, output="", error="doc_watermark necesita output_path para guardar el resultado.")

        try:
            from PyPDF2 import PdfReader, PdfWriter
        except ImportError:
            return ToolResult(
                ok=False, output="",
                error="Requiere instalar PyPDF2: pip install PyPDF2",
            )

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el PDF."))
            return ToolResult(ok=False, output="", error=err)

        content = raw.get("text", raw.get("content", ""))
        if isinstance(content, bytes):
            import io
            reader = PdfReader(io.BytesIO(content))
        elif isinstance(content, str):
            import io
            reader = PdfReader(io.BytesIO(content.encode("latin-1", errors="replace")))
        else:
            return ToolResult(ok=False, output="", error="No se pudo leer el contenido del PDF.")

        # Crear PDF de marca de agua simple con PyPDF2
        # Nota: PyPDF2 tiene soporte limitado para watermarks de texto directo.
        # Esta implementación anota metadata indicando la marca de agua.
        # Para watermarks visuales complejos se recomienda reportlab o pdfrw.
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        writer.add_metadata({"/Watermark": watermark_text})

        import io as io_mod
        buf = io_mod.BytesIO()
        writer.write(buf)

        write_raw = execute_local_tool_via_bridge(
            "writeFile", path=output_path,
            content=buf.getvalue().decode("latin-1", errors="replace"),
        )
        if not write_raw.get("ok"):
            err = str(write_raw.get("error", "No se pudo guardar el PDF con marca de agua."))
            return ToolResult(ok=False, output="", error=err)

        return ToolResult(
            ok=True,
            output=f"Marca de agua '{watermark_text}' aplicada a '{Path(path).name}'. "
                    f"Guardado como '{Path(output_path).name}'. "
                    f"Nota: la marca de agua es textual (metadata). Para watermarks gráficas "
                    f"visibles en cada página, instala reportlab: pip install reportlab",
            artifacts=[{"type": "pdf_watermarked", "path": output_path, "watermark": watermark_text}],
        )

    except Exception as e:
        log.warning("doc_watermark error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al añadir marca de agua: {e}")


# ─────────────────────────────────────────────────────────────
# 9. doc_metadata_edit — editar metadatos de documento
# ─────────────────────────────────────────────────────────────

def doc_metadata_edit_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Edita metadatos de un documento de texto (TXT, MD, JSON, XML, HTML, CSV).

    Args:
        arguments:
            path (str): ruta absoluta del documento.
            metadata (dict): metadatos a modificar (título, autor, fecha, etiquetas, etc.).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        metadata = arguments.get("metadata")

        if not path:
            return ToolResult(ok=False, output="", error="doc_metadata_edit necesita la ruta del archivo (path).")
        if not metadata or not isinstance(metadata, dict):
            return ToolResult(ok=False, output="", error="doc_metadata_edit necesita metadata (diccionario).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el documento."))
            return ToolResult(ok=False, output="", error=err)

        content = str(raw.get("text", raw.get("content", "")))
        ext = Path(path).suffix.lower()

        modified = content
        applied = 0

        if ext == ".json":
            import json
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    meta_key = metadata.get("_key", "_metadata")
                    existing = data.get(meta_key, {})
                    if isinstance(existing, dict):
                        for k, v in metadata.items():
                            if not k.startswith("_"):
                                existing[k] = str(v)
                                applied += 1
                        data[meta_key] = existing
                        modified = json.dumps(data, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                pass

        elif ext in (".xml", ".html", ".htm"):
            # Insertar meta tags después de <head> o al inicio
            meta_lines = []
            for k, v in metadata.items():
                if not k.startswith("_"):
                    if ext == ".xml":
                        meta_lines.append(f"  <meta name=\"{k}\" content=\"{v}\"/>")
                    else:
                        meta_lines.append(f"  <meta name=\"{k}\" content=\"{v}\">")
                    applied += 1

            if meta_lines:
                meta_block = "\n".join(meta_lines)
                if "<head>" in modified.lower():
                    modified = re.sub(
                        r'(<head[^>]*>)', r'\1\n' + meta_block, modified,
                        count=1, flags=re.IGNORECASE,
                    )
                else:
                    modified = meta_block + "\n" + modified

        elif ext in (".txt", ".md", ".csv", ".tsv"):
            # Prepend metadata as comments/header
            header_lines = [f"# {k}: {v}" for k, v in metadata.items() if not k.startswith("_")]
            applied = len(header_lines)

            if content.startswith("# ") or content.startswith("---"):
                # Ya tiene header, insertar después de la primera línea de header
                first_newline = content.find("\n")
                if first_newline > 0:
                    modified = content[:first_newline + 1] + "\n".join(header_lines) + "\n" + content[first_newline + 1:]
                else:
                    modified = "\n".join(header_lines) + "\n\n" + content
            else:
                modified = "\n".join(header_lines) + "\n\n" + content

        else:
            # Para otros formatos, guardar metadata como archivo sidecar
            sidecar_path = f"{path}.meta.json"
            import json
            sidecar = json.dumps(metadata, indent=2, ensure_ascii=False)
            write_raw = execute_local_tool_via_bridge("writeFile", path=sidecar_path, content=sidecar)
            if write_raw.get("ok"):
                return ToolResult(
                    ok=True,
                    output=f"Metadatos guardados en archivo sidecar '{Path(sidecar_path).name}' "
                            f"para '{Path(path).name}' (formato '{ext}' no soporta metadatos inline).",
                    artifacts=[{"type": "metadata_sidecar", "path": sidecar_path,
                                 "original": path, "applied": len(metadata)}],
                )
            err = str(write_raw.get("error", "No se pudo guardar el sidecar de metadatos."))
            return ToolResult(ok=False, output="", error=err)

        write_raw = execute_local_tool_via_bridge("writeFile", path=path, content=modified)
        if not write_raw.get("ok"):
            err = str(write_raw.get("error", "No se pudo guardar el documento modificado."))
            return ToolResult(ok=False, output="", error=err)

        return ToolResult(
            ok=True,
            output=f"Metadatos actualizados en '{Path(path).name}': {applied} campos modificados.",
            artifacts=[{"type": "metadata_edited", "path": path, "applied": applied}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_metadata_edit error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al editar metadatos: {e}")


# ─────────────────────────────────────────────────────────────
# 10. doc_extract_images — extraer imágenes de PDF
# ─────────────────────────────────────────────────────────────

def doc_extract_images_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae imágenes incrustadas de un PDF usando PyPDF2 o Pillow.

    Args:
        arguments:
            path (str): ruta absoluta del PDF.
            output_folder (str): carpeta donde guardar las imágenes (opcional).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        output_folder = str(arguments.get("output_folder") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_extract_images necesita la ruta del archivo (path).")

        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return ToolResult(
                ok=False, output="",
                error="Requiere instalar PyPDF2: pip install PyPDF2",
            )

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el PDF."))
            return ToolResult(ok=False, output="", error=err)

        content = raw.get("text", raw.get("content", ""))
        if isinstance(content, bytes):
            import io
            reader = PdfReader(io.BytesIO(content))
        elif isinstance(content, str):
            import io
            reader = PdfReader(io.BytesIO(content.encode("latin-1", errors="replace")))
        else:
            return ToolResult(ok=False, output="", error="No se pudo leer el contenido del PDF.")

        out_dir = output_folder or str(Path(path).parent)
        base_name = Path(path).stem
        extracted = 0
        errors_list: list[str] = []

        for page_num, page in enumerate(reader.pages, 1):
            resources = None
            if hasattr(page, "images") and page.images:
                for img_key, img_file in page.images.items():
                    try:
                        ext = Path(img_file.name).suffix if hasattr(img_file, "name") else ".png"
                        if not ext or ext == ".":
                            ext = ".png"
                        img_path = f"{out_dir.rstrip('/').rstrip('\\')}/{base_name}_img{page_num}_{extracted + 1}{ext}"
                        write_raw = execute_local_tool_via_bridge(
                            "writeFile", path=img_path,
                            content=img_file.data.decode("latin-1", errors="replace"),
                        )
                        if write_raw.get("ok"):
                            extracted += 1
                        else:
                            errors_list.append(f"página {page_num}, imagen {img_key}")
                    except Exception as img_err:
                        errors_list.append(f"página {page_num}, imagen {img_key}: {img_err}")
                        continue

            elif "/XObject" in (resources or {}):
                # Fallback: intentar extraer via recursos de página
                try:
                    xobjects = page["/Resources"]["/XObject"].get_object() if "/Resources" in page else {}
                    for obj_name in xobjects:
                        obj = xobjects[obj_name]
                        if obj.get("/Subtype", "") == "/Image":
                            data = obj._data if hasattr(obj, "_data") else None
                            if data:
                                img_path = f"{out_dir.rstrip('/').rstrip('\\')}/{base_name}_img{page_num}_{extracted + 1}.png"
                                write_raw = execute_local_tool_via_bridge(
                                    "writeFile", path=img_path,
                                    content=data.decode("latin-1", errors="replace"),
                                )
                                if write_raw.get("ok"):
                                    extracted += 1
                except Exception:
                    continue

        if extracted == 0:
            msg = f"No se encontraron imágenes extraíbles en '{Path(path).name}'."
            if errors_list:
                msg += f" Errores: {'; '.join(errors_list[:5])}"
            return ToolResult(
                ok=True,
                output=msg,
                artifacts=[{"type": "images_extracted", "path": path, "count": 0}],
            )

        return ToolResult(
            ok=True,
            output=f"{extracted} imágenes extraídas de '{Path(path).name}' en '{out_dir}'.",
            artifacts=[{"type": "images_extracted", "path": path, "count": extracted,
                         "output_folder": out_dir}],
        )

    except Exception as e:
        log.warning("doc_extract_images error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al extraer imágenes: {e}")


# ─────────────────────────────────────────────────────────────
# 11. doc_count_words — contar palabras y párrafos
# ─────────────────────────────────────────────────────────────

def doc_count_words_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Cuenta palabras, caracteres, párrafos y líneas de un documento de texto.

    Args:
        arguments:
            path (str): ruta absoluta del documento.
    """
    try:
        path = str(arguments.get("path") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_count_words necesita la ruta del archivo (path).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el documento."))
            return ToolResult(ok=False, output="", error=err)

        text = str(raw.get("text", raw.get("content", "")))
        if not text.strip():
            return ToolResult(
                ok=True,
                output=f"El documento '{Path(path).name}' está vacío (0 palabras).",
                artifacts=[{"type": "word_count", "path": path, "words": 0}],
            )

        chars_total = len(text)
        chars_no_spaces = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
        words = len(re.findall(r'\b\w+(?:[\'’-]\w+)?\b', text, re.UNICODE))
        lines = text.count("\n") + 1

        # Párrafos: bloques separados por 2+ saltos de línea
        paragraphs_raw = re.split(r'\n\s*\n', text.strip())
        paragraphs = len([p for p in paragraphs_raw if p.strip()])

        # Estimación de tiempo de lectura (200 palabras/minuto en español)
        reading_minutes = max(1, round(words / 200))

        return ToolResult(
            ok=True,
            output=f"Estadísticas de '{Path(path).name}':\n"
                    f"  • Palabras: {words:,}\n"
                    f"  • Caracteres: {chars_total:,} (sin espacios: {chars_no_spaces:,})\n"
                    f"  • Párrafos: {paragraphs:,}\n"
                    f"  • Líneas: {lines:,}\n"
                    f"  • Tiempo estimado de lectura: {reading_minutes} minuto(s)",
            artifacts=[{"type": "word_count", "path": path, "words": words,
                         "chars_total": chars_total, "chars_no_spaces": chars_no_spaces,
                         "paragraphs": paragraphs, "lines": lines,
                         "reading_minutes": reading_minutes}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_count_words error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al contar palabras: {e}")


# ─────────────────────────────────────────────────────────────
# 12. doc_detect_language — detectar idioma de documento
# ─────────────────────────────────────────────────────────────

def doc_detect_language_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Detecta el idioma de un documento de texto (usa langdetect o IA como fallback).

    Args:
        arguments:
            path (str): ruta absoluta del documento.
    """
    try:
        path = str(arguments.get("path") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="doc_detect_language necesita la ruta del archivo (path).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el documento."))
            return ToolResult(ok=False, output="", error=err)

        text = str(raw.get("text", raw.get("content", "")))
        if not text.strip():
            return ToolResult(ok=False, output="", error="El documento está vacío, no se puede detectar idioma.")

        # Tomar muestra de hasta 4000 caracteres para detección
        sample = text[:4000]

        # Intentar langdetect primero
        try:
            from langdetect import detect, DetectorFactory
            DetectorFactory.seed = 0
            detected = detect(sample)
            language_names = {
                "es": "Español", "en": "Inglés", "pt": "Portugués",
                "fr": "Francés", "de": "Alemán", "it": "Italiano",
                "ca": "Catalán", "eu": "Euskera", "gl": "Gallego",
                "ru": "Ruso", "zh-cn": "Chino (simplificado)", "zh-tw": "Chino (tradicional)",
                "ja": "Japonés", "ko": "Coreano", "ar": "Árabe",
                "hi": "Hindi", "nl": "Neerlandés", "pl": "Polaco",
                "sv": "Sueco", "da": "Danés", "no": "Noruego",
                "fi": "Finés", "tr": "Turco", "uk": "Ucraniano",
                "ro": "Rumano", "hu": "Húngaro", "cs": "Checo",
            }
            lang_name = language_names.get(detected, detected.upper())

            return ToolResult(
                ok=True,
                output=f"Idioma detectado en '{Path(path).name}': {lang_name} (código ISO: {detected})",
                artifacts=[{"type": "language_detected", "path": path, "language": detected,
                             "language_name": lang_name, "method": "langdetect"}],
            )
        except ImportError:
            pass  # langdetect no instalado, usar fallback IA

        # Fallback: usar DeepSeek para detectar idioma
        try:
            from app.services.provider_router import route_chat

            result = route_chat(
                f"Detecta el idioma de este texto. Responde solo con el código ISO 639-1 "
                f"(ej: es, en, pt, fr, de, it).\n\nTexto:\n{sample[:2000]}",
                provider_id="deepseek",
                system_prompt="Eres un detector de idiomas. Responde SOLO con el código ISO de 2 letras, sin explicación.",
            )

            detected = result.strip().lower()[:10]
            language_names = {
                "es": "Español", "en": "Inglés", "pt": "Portugués",
                "fr": "Francés", "de": "Alemán", "it": "Italiano",
                "ca": "Catalán", "eu": "Euskera", "gl": "Gallego",
                "ru": "Ruso", "zh": "Chino", "ja": "Japonés",
                "ko": "Coreano", "ar": "Árabe", "hi": "Hindi",
            }
            lang_name = language_names.get(detected, detected.upper())

            return ToolResult(
                ok=True,
                output=f"Idioma detectado en '{Path(path).name}': {lang_name} (código ISO: {detected})",
                artifacts=[{"type": "language_detected", "path": path, "language": detected,
                             "language_name": lang_name, "method": "deepseek_ai"}],
            )
        except ImportError:
            return ToolResult(
                ok=False, output="",
                error="No se pudo detectar el idioma: langdetect no está instalado y el servicio de IA "
                      "no está disponible. Instala langdetect: pip install langdetect",
            )
        except Exception as ai_err:
            log.warning("doc_detect_language AI fallback error: %s", ai_err)
            return ToolResult(
                ok=False, output="",
                error=f"No se pudo detectar el idioma. langdetect no instalado y fallback IA falló: {ai_err}. "
                      f"Instala langdetect: pip install langdetect",
            )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_detect_language error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al detectar idioma: {e}")


# ─────────────────────────────────────────────────────────────
# 13. doc_find_replace — buscar y reemplazar en documento
# ─────────────────────────────────────────────────────────────

def doc_find_replace_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca y reemplaza texto en un documento, guardando el resultado.

    Args:
        arguments:
            path (str): ruta absoluta del documento.
            find (str): texto a buscar.
            replace (str): texto de reemplazo.
            output_path (str): ruta de salida (opcional, si no se da sobreescribe el original).
            case_sensitive (bool): distinguir mayúsculas/minúsculas (opcional, default: true).
            count (int): número máximo de reemplazos (opcional, default: todos).
    """
    try:
        path = str(arguments.get("path") or "").strip()
        find_text = str(arguments.get("find") or "").strip()
        replace_text = str(arguments.get("replace") or "")
        output_path = str(arguments.get("output_path") or "").strip()
        case_sensitive = arguments.get("case_sensitive", True)
        if isinstance(case_sensitive, str):
            case_sensitive = case_sensitive.lower() not in ("false", "no", "0")
        max_count = int(arguments.get("count") or 0)

        if not path:
            return ToolResult(ok=False, output="", error="doc_find_replace necesita la ruta del archivo (path).")
        if not find_text:
            return ToolResult(ok=False, output="", error="doc_find_replace necesita el texto a buscar (find).")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = str(raw.get("error", "No se pudo leer el documento."))
            return ToolResult(ok=False, output="", error=err)

        content = str(raw.get("text", raw.get("content", "")))
        if not content:
            return ToolResult(ok=False, output="", error="El documento está vacío.")

        # Contar ocurrencias
        flags = 0 if case_sensitive else re.IGNORECASE
        occurrences_before = len(re.findall(re.escape(find_text), content, flags=flags))

        if occurrences_before == 0:
            return ToolResult(
                ok=True,
                output=f"No se encontró '{find_text}' en '{Path(path).name}' "
                        f"({'sensible a mayúsculas' if case_sensitive else 'sin distinguir mayúsculas'}).",
                artifacts=[{"type": "find_replace", "path": path, "occurrences_before": 0,
                             "occurrences_after": 0, "replacements": 0}],
            )

        # Reemplazar
        if max_count > 0:
            modified = re.sub(
                re.escape(find_text), replace_text, content,
                count=max_count, flags=flags,
            )
            replacements = min(max_count, occurrences_before)
        else:
            modified = re.sub(re.escape(find_text), replace_text, content, flags=flags)
            replacements = occurrences_before

        dest = output_path or path
        write_raw = execute_local_tool_via_bridge("writeFile", path=dest, content=modified)
        if not write_raw.get("ok"):
            err = str(write_raw.get("error", "No se pudo guardar el documento modificado."))
            return ToolResult(ok=False, output="", error=err)

        return ToolResult(
            ok=True,
            output=f"Reemplazo completado en '{Path(path).name}': {replacements} ocurrencia(s) "
                    f"de '{find_text}' → '{replace_text or '(vacío)'}'. "
                    f"Guardado en '{Path(dest).name}'.",
            artifacts=[{"type": "find_replace", "path": dest, "original_path": path,
                         "find": find_text, "replace": replace_text,
                         "occurrences_before": occurrences_before, "replacements": replacements}],
        )

    except ImportError:
        return ToolResult(ok=False, output="", error="Bridge de herramientas locales no disponible.")
    except Exception as e:
        log.warning("doc_find_replace error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al buscar y reemplazar: {e}")


# ─────────────────────────────────────────────────────────────
# Exportación de tools para registro en registry
# ─────────────────────────────────────────────────────────────

TOOLS: list[tuple[str, Any]] = [
    ("doc_read_pdf_form", doc_read_pdf_form_handler),
    ("doc_fill_pdf_form", doc_fill_pdf_form_handler),
    # ❌ ROTA: promete OCR pero no lee imágenes reales (DeepSeek no es multimodal en este contexto)
    # ("doc_ocr_image", doc_ocr_image_handler),
    ("doc_extract_tables", doc_extract_tables_handler),
    ("doc_compare", doc_compare_handler),
    ("doc_merge_pdfs", doc_merge_pdfs_handler),
    ("doc_split_pdf", doc_split_pdf_handler),
    ("doc_watermark", doc_watermark_handler),
    ("doc_metadata_edit", doc_metadata_edit_handler),
    ("doc_extract_images", doc_extract_images_handler),
    ("doc_count_words", doc_count_words_handler),
    ("doc_detect_language", doc_detect_language_handler),
    ("doc_find_replace", doc_find_replace_handler),
]
