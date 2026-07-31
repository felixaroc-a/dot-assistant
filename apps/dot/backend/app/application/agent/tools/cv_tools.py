"""Tool analyze_cv — lee CV (PDF/DOCX/TXT) del PC y extrae datos estructurados.

Flujo BIBLIA C1/P1: abrir CV en sandbox → extraer hechos → responder o notificar WA.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult
from app.application.agent.tools.read_document import MIME_MAP, _guess_mime
from app.application.documents.pipeline import extract_from_text

log = logging.getLogger("dot.agent.tools.cv")

_BRIDGE_ERRORS = {
    "bridge_secret_not_configured": "El puente local no está configurado. Abre la app DOT en el PC.",
    "bridge_unreachable": "No se pudo conectar con el PC (bridge). ¿Está abierta la app DOT?",
    "bridge_unauthorized": "El puente local rechazó la autenticación.",
}


def _read_document_text(path_raw: str) -> tuple[str | None, str | None]:
    """Lee texto de PDF/DOCX/TXT vía bridge Electron."""
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    mime = _guess_mime(path_raw)
    if not mime:
        suffix = Path(path_raw).suffix or "sin extensión"
        return None, (
            f"Tipo de archivo no soportado: {suffix}. "
            "Solo PDF, DOCX y TXT son soportados para CV."
        )

    raw = execute_local_tool_via_bridge(
        "parseDocument",
        path=path_raw,
        content=mime,
    )
    if not raw.get("ok"):
        err = str(raw.get("error", "No se pudo leer el CV."))
        return None, _BRIDGE_ERRORS.get(err, err)

    text = str(raw.get("text", raw.get("content", ""))).strip()
    if not text:
        return None, (
            "El CV fue procesado pero no se encontró texto extraíble. "
            "¿Es un PDF escaneado sin texto seleccionable?"
        )
    return text, None


def _format_cv_summary(fields: dict[str, Any], filename: str) -> str:
    """Formatea campos extraídos en resumen legible en español."""
    lines = [f"Análisis del CV «{filename}»:", ""]

    name = fields.get("name")
    if name:
        lines.append(f"• Nombre: {name}")

    email = fields.get("email")
    if email:
        lines.append(f"• Email: {email}")

    phone = fields.get("phone")
    if phone:
        lines.append(f"• Teléfono: {phone}")

    summary = fields.get("summary")
    if summary:
        lines.extend(["", "Resumen:", str(summary).strip()])

    skills = fields.get("skills") or []
    if skills:
        skill_list = ", ".join(str(s) for s in skills[:15])
        extra = f" (+{len(skills) - 15} más)" if len(skills) > 15 else ""
        lines.extend(["", f"Habilidades ({len(skills)}): {skill_list}{extra}"])

    experience = fields.get("experience") or []
    if experience:
        lines.extend(["", f"Experiencia ({len(experience)} entradas):"])
        for item in experience[:5]:
            lines.append(f"  - {str(item).strip()[:200]}")
        if len(experience) > 5:
            lines.append(f"  … y {len(experience) - 5} más")

    education = fields.get("education") or []
    if education:
        lines.extend(["", f"Formación ({len(education)}):"])
        for item in education[:4]:
            lines.append(f"  - {str(item).strip()[:200]}")

    languages = fields.get("languages") or []
    if langs := [str(l).strip() for l in languages if str(l).strip()]:
        lines.extend(["", f"Idiomas: {', '.join(langs)}"])

    if len(lines) <= 2:
        preview = str(fields.get("raw_preview") or "").strip()
        if preview:
            lines.extend(["", "Vista previa del contenido:", preview[:800]])
        else:
            lines.append("No se detectaron campos estructurados; usa read_document para el texto completo.")

    return "\n".join(lines)


def analyze_cv_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee un CV (PDF/DOCX/TXT) del PC del usuario y extrae datos clave.

    Args:
        arguments:
            path (str): ruta al CV (Escritorio, Documentos, Descargas o DOT Trabajos).
            question (str, opcional): pregunta concreta sobre el CV (p. ej. «¿cuántos años de experiencia?»).
    """
    path_raw = str(arguments.get("path", "")).strip()
    if not path_raw:
        return ToolResult(
            ok=False,
            output="",
            error="analyze_cv necesita la ruta del CV (path). Ejemplo: ~/Desktop/mi_cv.pdf",
        )

    suffix = Path(path_raw).suffix.lower()
    if suffix and suffix not in MIME_MAP:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"Formato no soportado: {suffix or 'sin extensión'}. "
                "Usa PDF, DOCX o TXT."
            ),
        )

    try:
        text, read_err = _read_document_text(path_raw)
        if read_err or not text:
            return ToolResult(ok=False, output="", error=read_err or "No se pudo leer el CV.")

        result = extract_from_text(text)
        if not result.get("ok"):
            return ToolResult(
                ok=False,
                output="",
                error=str(result.get("error") or "No se pudo analizar el CV."),
            )

        fields = result.get("fields") or {}
        filename = Path(path_raw).name
        summary = _format_cv_summary(fields, filename)

        question = str(arguments.get("question") or "").strip()
        if question:
            summary += (
                f"\n\nPregunta del usuario: {question}\n"
                "Responde usando SOLO los datos extraídos arriba; no inventes información."
            )

        return ToolResult(
            ok=True,
            output=summary,
            artifacts=[{
                "type": "cv_analysis",
                "path": path_raw,
                "fields": {
                    k: fields.get(k)
                    for k in (
                        "name", "email", "phone", "summary",
                        "skills", "experience", "education", "languages",
                    )
                },
                "extraction_method": result.get("method", "heuristic"),
            }],
        )
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="Bridge de herramientas locales no disponible. Abre la app DOT.",
        )
    except Exception as e:
        log.exception("Error en analyze_cv para path=%s", path_raw[:120])
        return ToolResult(ok=False, output="", error=f"No se pudo analizar el CV: {e}")
