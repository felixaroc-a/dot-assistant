"""Tool gmail_send para el Agent Runtime."""

from __future__ import annotations

from typing import Any

from app.application.agent.ports import ToolResult


def gmail_send_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    from app.application.whatsapp.gmail_action import execute_gmail_send

    to = str(arguments.get("to") or "").strip()
    subject = str(arguments.get("subject") or "").strip()
    body = arguments.get("body")
    if not to or "@" not in to:
        return ToolResult(
            ok=False,
            output="",
            error="Falta destinatario válido (to). Pide el email al usuario.",
        )
    if not isinstance(body, str):
        body = str(body or "")
    action: dict[str, Any] = {
        "to": to,
        "subject": subject or "(sin asunto)",
        "body": body,
    }
    body_html = arguments.get("body_html")
    if isinstance(body_html, str) and body_html.strip():
        action["body_html"] = body_html
    attachments = arguments.get("attachments")
    if isinstance(attachments, list) and attachments:
        action["attachments"] = attachments
    msg = execute_gmail_send(uid, action)
    # execute_gmail_send siempre devuelve texto humano; ok si no es mensaje de error típico
    fail_markers = (
        "necesitas conectar",
        "No pude enviar",
        "Hubo un error",
    )
    ok = not any(m.lower() in msg.lower() for m in fail_markers)
    return ToolResult(ok=ok, output=msg if ok else "", error=None if ok else msg)
