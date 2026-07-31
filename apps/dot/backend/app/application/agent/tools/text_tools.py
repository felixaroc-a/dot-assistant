"""Tools translate y summarize — traducción y resumen de primer nivel.

Usa provider_router (Google Translate + DeepSeek / SummarizerService con chunking).
Encadenables tras read_document o con texto pegado por el usuario.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.text")

_READ_DOC_PREFIX = re.compile(r"^Contenido de .+?:\s*\n+", re.DOTALL)

_STYLE_INSTRUCTIONS: dict[str, str] = {
    "breve": "",
    "ejecutivo": (
        "Formatea el resumen como informe ejecutivo con viñetas de ideas clave."
    ),
    "bullets": "Formatea el resumen como lista numerada de puntos clave.",
    "puntos": "Formatea el resumen como lista numerada de puntos clave.",
    "academico": (
        "Resume preservando rigor y estructura académica, con terminología precisa."
    ),
}


def _normalize_document_text(text: str) -> str:
    """Quita el encabezado estándar de read_document si está presente."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    match = _READ_DOC_PREFIX.match(cleaned)
    if match:
        return cleaned[match.end() :].strip()
    return cleaned


def _resolve_text(uid: str, arguments: dict[str, Any]) -> tuple[str | None, ToolResult | None]:
    """Resuelve texto desde argumentos o leyendo un documento local."""
    raw_text = str(
        arguments.get("text")
        or arguments.get("content")
        or arguments.get("source")
        or ""
    ).strip()
    path = str(arguments.get("path") or "").strip()

    if raw_text:
        return _normalize_document_text(raw_text), None

    if not path:
        return None, ToolResult(
            ok=False,
            output="",
            error=(
                "Indica el texto a procesar (text) o la ruta del documento (path). "
                "Tras read_document, pasa el contenido en text."
            ),
        )

    from app.application.agent.tools.read_document import read_document_handler

    read_result = read_document_handler(uid, {"path": path})
    if not read_result.ok:
        return None, read_result

    normalized = _normalize_document_text(read_result.output)
    if not normalized:
        return None, ToolResult(
            ok=False,
            output="",
            error="El documento no tiene texto extraíble para procesar.",
        )
    return normalized, None


def translate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Traduce texto al idioma indicado (Google Translate o DeepSeek).

    Args:
        arguments:
            text (str): texto a traducir (o salida de read_document).
            target_lang (str): idioma destino — p. ej. inglés, en, francés, pt.
            path (str, opcional): lee PDF/DOCX/TXT del PC si no hay text.
    """
    try:
        from app.services.provider_router import ProviderNotAvailableError, route_translate

        text, err_result = _resolve_text(uid, arguments)
        if err_result is not None:
            return err_result

        target_lang = str(
            arguments.get("target_lang")
            or arguments.get("to")
            or arguments.get("target")
            or ""
        ).strip()
        if not target_lang:
            return ToolResult(
                ok=False,
                output="",
                error="Indica el idioma destino (target_lang), por ejemplo: inglés, en, francés.",
            )

        translated, provider, resolved_lang = route_translate(text or "", target_lang)
        if not translated.strip():
            return ToolResult(
                ok=False,
                output="",
                error="La traducción quedó vacía. Intenta con un texto más corto.",
            )

        return ToolResult(
            ok=True,
            output=translated.strip(),
            artifacts=[
                {
                    "type": "translation",
                    "provider": provider,
                    "target_lang": resolved_lang,
                    "chars": len(text or ""),
                }
            ],
        )
    except ValueError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    except ProviderNotAvailableError as exc:
        return ToolResult(
            ok=False,
            output="",
            error=(
                "Traducción no disponible ahora. "
                "Configura GOOGLE_TRANSLATE_API_KEY o DEEPSEEK_API_KEY en el servidor."
            ),
        )
    except Exception as exc:
        log.exception("translate error uid=%s: %s", uid[:8], exc)
        return ToolResult(ok=False, output="", error=f"No pude traducir el texto: {exc}")


def summarize_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Resume texto, URL o documento local con chunking automático.

    Args:
        arguments:
            text (str): texto a resumir (idealmente salida de read_document).
            path (str, opcional): ruta PDF/DOCX/TXT si no hay text.
            style (str, opcional): breve | ejecutivo | bullets | academico.
    """
    try:
        from app.services.provider_router import (
            ProviderNotAvailableError,
            SUMMARY_SYSTEM_PROMPT,
            route_chat,
            route_summarize,
        )

        text, err_result = _resolve_text(uid, arguments)
        if err_result is not None:
            return err_result

        style = str(arguments.get("style") or "breve").strip().lower()
        style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["breve"])

        if style_instruction:
            from app.services.summarizer_service import SummarizerService

            def summarize_fn(prompt: str) -> str:
                styled = f"{style_instruction}\n\n{prompt}"
                return route_chat(
                    styled,
                    None,
                    SUMMARY_SYSTEM_PROMPT,
                    include_document_action_prompt=False,
                )

            result = SummarizerService().summarize(text or "", summarize_fn)
            summary = str(result.get("summary") or "").strip()
            source_type = str(result.get("source_type") or "text")
            chunks = int(result.get("chunks") or 1)
        else:
            summary, source_type, chunks = route_summarize(text or "")

        if not summary:
            return ToolResult(
                ok=False,
                output="",
                error="No pude generar el resumen. Prueba con un texto más corto.",
            )

        return ToolResult(
            ok=True,
            output=summary,
            artifacts=[
                {
                    "type": "summary",
                    "style": style,
                    "source_type": source_type,
                    "chunks": chunks,
                    "chars": len(text or ""),
                }
            ],
        )
    except ValueError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    except ProviderNotAvailableError as exc:
        return ToolResult(
            ok=False,
            output="",
            error="Resumen no disponible: el servicio de IA no está configurado.",
        )
    except RuntimeError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    except Exception as exc:
        log.exception("summarize error uid=%s: %s", uid[:8], exc)
        return ToolResult(ok=False, output="", error=f"No pude resumir el texto: {exc}")
