"""Tools LINE Messaging — CANAL 2/3: Mensajería LINE via Messaging API.

Tools para Agent Runtime que permiten al agente enviar mensajes por LINE.

Auth: LINE_CHANNEL_ACCESS_TOKEN + LINE_CHANNEL_SECRET de LINE Developers Console.
Gate: LINE_ENABLED=true en .env.
Sin token → "requiere configurar LINE en Ajustes".

Referencia: https://developers.line.biz/en/docs/messaging-api/
"""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.line")

# ─── Helpers ──────────────────────────────────────────────────────────

def _check_enabled() -> str | None:
    """Retorna mensaje de error si LINE no está habilitado/configurado."""
    if not settings.line_enabled:
        return "Canal LINE deshabilitado. El usuario debe activar LINE_ENABLED=true en Ajustes."

    token = settings.line_channel_access_token
    if not token:
        return (
            "LINE no configurado. Solicita al usuario que configure "
            "LINE_CHANNEL_ACCESS_TOKEN y LINE_CHANNEL_SECRET en Ajustes "
            "(gratis en https://developers.line.biz/console/)."
        )
    return None


# ─── Handlers ──────────────────────────────────────────────────────────

def line_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje de LINE a un usuario.

    Args:
        user_id: ID de usuario LINE del destinatario
        text: Contenido del mensaje

    Returns:
        ToolResult con confirmación o error
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    user_id = str(arguments.get("user_id") or arguments.get("to") or "").strip()
    text = str(arguments.get("text") or arguments.get("message") or "").strip()

    if not user_id:
        return ToolResult(ok=False, output="", error="Falta el user_id de LINE del destinatario.")
    if not text:
        return ToolResult(ok=False, output="", error="Falta el contenido del mensaje (text).")

    try:
        from app.services.line_service import send_line_push_message as _send

        result = _send(user_id=user_id, text=text)
        if result["ok"]:
            return ToolResult(
                ok=True,
                output=f"Mensaje LINE enviado a {user_id[:12]}: \"{text[:100]}\" (id={result['message_id']}).",
            )
        return ToolResult(ok=False, output="", error=f"Error enviando LINE: {result['error']}")
    except Exception as e:
        log.warning("line_send_message error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def line_check_status_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica el estado del canal LINE (linked, bot configurado).

    Returns:
        ToolResult con resumen del estado del canal
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=True, output=f"Canal LINE: {error_msg}")

    return ToolResult(
        ok=True,
        output=(
            "Canal LINE configurado:\n"
            "- API: LINE Messaging API v2\n"
            "- Autenticación: Bearer token configurado\n"
            "- Estado: operativo (skeleton)"
        ),
    )


# ─── Registro ──────────────────────────────────────────────────────────

TOOLS = [
    ("line_send_message", line_send_message_handler),
    ("line_check_status", line_check_status_handler),
]
