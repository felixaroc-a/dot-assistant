"""Shim legacy: trailing JSON local_tool / create_document / gmail → texto humano."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.agent.tools.local_files import execute_local_tool_via_bridge
from app.application.whatsapp.gmail_action import apply_gmail_send_if_present
from app.application.whatsapp.local_tool_parse import (
    extract_first_json_object,
    format_tool_result_for_wa,
    parse_local_tool_action,
    strip_local_tool_json,
)

log = logging.getLogger("dot.agent.legacy_shim")

_CREATE_DOC_TRAILING = re.compile(
    r"\{[\s\S]*\"action\"\s*:\s*\"create_document\"[\s\S]*\}\s*$",
    re.IGNORECASE,
)


def parse_create_document_action(text: str) -> dict[str, Any] | None:
    data = extract_first_json_object(text)
    if not data:
        return None
    if str(data.get("action") or "").lower() != "create_document":
        return None
    title = str(data.get("title") or "").strip() or "documento-dot"
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    ext = str(data.get("type") or "txt").strip().lower().replace(".", "")
    if ext not in {"txt", "md", "csv"}:
        ext = "txt"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title)[:80]
    return {
        "path": f"~/Desktop/{safe}.{ext}",
        "content": content,
        "title": title,
    }


def _human_from_create_document(doc: dict[str, Any], tool_result: dict[str, Any]) -> str:
    body = str(doc.get("content") or "").strip()
    # Mostrar resumen al usuario (sin JSON); acotar
    preview = body if len(body) <= 2500 else body[:2500] + "…"
    if tool_result.get("ok"):
        path = tool_result.get("path") or doc.get("path")
        return (
            f"{preview}\n\n"
            f"Archivo guardado en tu Escritorio:\n{path}"
        )
    err = tool_result.get("error") or "error"
    return (
        f"{preview}\n\n"
        f"No pude guardar el archivo en el Escritorio ({err}). "
        "¿Está abierta la app DOT?"
    )


def finalize_assistant_tools(uid: str, assistant_text: str) -> str:
    """Si hay acción legacy, ejecuta y sustituye por mensaje humano. Si no, texto intacto."""
    text = (assistant_text or "").strip()
    if not text:
        return assistant_text or ""

    tool_action = parse_local_tool_action(text)
    if tool_action:
        log.info(
            "legacy_shim local_tool op=%s uid=%s",
            tool_action["operation"],
            uid[:8] if uid else "?",
        )
        tool_result = execute_local_tool_via_bridge(
            tool_action["operation"],
            path=tool_action.get("path") or "",
            content=tool_action.get("content"),
        )
        spoken = strip_local_tool_json(text)
        tool_msg = format_tool_result_for_wa(tool_action["operation"], tool_result)
        if spoken and spoken != text and "local_tool" not in spoken:
            return f"{spoken}\n\n{tool_msg}".strip()
        return tool_msg

    doc = parse_create_document_action(text)
    if doc:
        log.info(
            "legacy_shim create_document→writeFile title=%s uid=%s",
            doc["title"][:40],
            uid[:8] if uid else "?",
        )
        tool_result = execute_local_tool_via_bridge(
            "writeFile",
            path=doc["path"],
            content=doc["content"],
        )
        return _human_from_create_document(doc, tool_result)

    return apply_gmail_send_if_present(uid, text)
