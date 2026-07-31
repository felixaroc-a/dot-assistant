"""Tools de lectura de Gmail para el Agent Runtime.

gmail_list_unread, gmail_search, gmail_summarize_unread.
gmail_send ya existe en gmail_send.py.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.gmail_read")


def _build_message_lines(messages: list[dict], max_items: int = 15) -> str:
    if not messages:
        return "No se encontraron correos."
    lines = []
    for m in messages[:max_items]:
        subject = m.get("subject", "(sin asunto)")
        sender = m.get("from", "?")
        date = m.get("date", "")
        snippet = m.get("snippet", "")[:100]
        msg_id = m.get("id", "")
        line = f"- {subject} | De: {sender}"
        if msg_id:
            line += f" | ID: {msg_id}"
        if date:
            line += f" | {date}"
        if snippet:
            line += f"\n  {snippet}"
        lines.append(line)
    return "\n".join(lines)


def gmail_list_unread_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista correos no leídos de Gmail."""
    try:
        from app.services import gmail_service

        max_results = int(arguments.get("max_results") or 20)
        messages = gmail_service.list_unread(uid, max_results=min(max_results, 40))
        output = _build_message_lines(messages)
        return ToolResult(
            ok=True,
            output=f"Correos no leídos ({len(messages)}):\n{output}",
        )
    except Exception as e:
        log.warning("gmail_list_unread error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude leer Gmail: {e}. ¿Está vinculado Google?",
        )


def gmail_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca correos en Gmail por query."""
    try:
        from app.services import gmail_service

        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False,
                output="",
                error="Falta la consulta de búsqueda (query).",
            )

        max_results = int(arguments.get("max_results") or 20)
        messages = gmail_service.search_messages(
            uid, query=query, max_results=min(max_results, 40),
        )
        output = _build_message_lines(messages)
        return ToolResult(
            ok=True,
            output=f"Resultados para «{query}» ({len(messages)}):\n{output}",
        )
    except Exception as e:
        log.warning("gmail_search error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude buscar en Gmail: {e}.",
        )


def gmail_summarize_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un resumen de correos no leídos de Gmail."""
    try:
        from app.services import gmail_service

        max_results = int(arguments.get("max_results") or 10)
        summary = gmail_service.summarize_unread(uid, max_results=min(max_results, 20))
        return ToolResult(
            ok=True,
            output=summary,
        )
    except Exception as e:
        log.warning("gmail_summarize error uid=%s: %s", uid[:8], e)
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude resumir correos: {e}.",
        )
TOOLS = [('gmail_list_unread', gmail_list_unread_handler), ('gmail_search', gmail_search_handler), ('gmail_summarize_unread', gmail_summarize_handler)]
