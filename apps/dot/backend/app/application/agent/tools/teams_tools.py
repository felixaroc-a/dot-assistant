"""Tools Microsoft Teams — CANAL 3/3: Mensajería Teams via MS Graph API.

Tools para Agent Runtime que permiten al agente enviar mensajes por Microsoft Teams.

Auth: TEAMS_TENANT_ID + TEAMS_CLIENT_ID + TEAMS_CLIENT_SECRET (Azure AD app).
Gate: TEAMS_ENABLED=true en .env.
Sin config → "requiere configurar Teams en Ajustes".

Referencia: https://learn.microsoft.com/en-us/graph/teams-concept-overview
"""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.teams")

# ─── Helpers ──────────────────────────────────────────────────────────

def _check_enabled() -> str | None:
    """Retorna mensaje de error si Teams no está habilitado/configurado."""
    if not settings.teams_enabled:
        return "Canal Teams deshabilitado. El usuario debe activar TEAMS_ENABLED=true en Ajustes."

    missing = []
    if not settings.teams_tenant_id:
        missing.append("TEAMS_TENANT_ID")
    if not settings.teams_client_id:
        missing.append("TEAMS_CLIENT_ID")
    if not settings.teams_client_secret:
        missing.append("TEAMS_CLIENT_SECRET")

    if missing:
        return (
            f"Microsoft Teams no configurado. Faltan: {', '.join(missing)}. "
            "Solicita al usuario que configure las credenciales en Ajustes "
            "(requiere registrar una app en Azure AD: portal.azure.com → App Registrations)."
        )
    return None


# ─── Handlers ──────────────────────────────────────────────────────────

def teams_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje a Microsoft Teams (chat 1:1 o canal).

    Args:
        chat_id: ID del chat de Teams (opcional, ej. 19:xxx@thread.v2)
        team_id: ID del team (opcional, si se envía a canal)
        channel_id: ID del canal (opcional, requiere team_id)
        text: Contenido del mensaje

    Se requiere chat_id O (team_id + channel_id).

    Returns:
        ToolResult con confirmación o error
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    chat_id = str(arguments.get("chat_id") or "").strip() or None
    team_id = str(arguments.get("team_id") or "").strip() or None
    channel_id = str(arguments.get("channel_id") or "").strip() or None
    text = str(arguments.get("text") or arguments.get("message") or "").strip()

    if not chat_id and not (team_id and channel_id):
        return ToolResult(
            ok=False, output="",
            error="Se requiere chat_id (chat directo) o team_id+channel_id (canal).",
        )
    if not text:
        return ToolResult(ok=False, output="", error="Falta el contenido del mensaje (text).")

    try:
        from app.services.teams_service import send_teams_message as _send

        result = _send(
            chat_id=chat_id,
            team_id=team_id,
            channel_id=channel_id,
            text=text,
        )
        if result["ok"]:
            target = chat_id or f"{team_id}/{channel_id}"
            return ToolResult(
                ok=True,
                output=f"Mensaje Teams enviado a {target[:40]}: \"{text[:100]}\" (id={result['message_id']}).",
            )
        return ToolResult(ok=False, output="", error=f"Error enviando Teams: {result['error']}")
    except Exception as e:
        log.warning("teams_send_message error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def teams_check_status_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica el estado del canal Microsoft Teams (linked, app configurada).

    Returns:
        ToolResult con resumen del estado del canal
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=True, output=f"Canal Teams: {error_msg}")

    return ToolResult(
        ok=True,
        output=(
            "Canal Microsoft Teams configurado:\n"
            "- API: MS Graph API v1.0\n"
            "- Autenticación: OAuth2 client_credentials\n"
            "- Tenant: configurado\n"
            "- Estado: operativo (skeleton)"
        ),
    )


# ─── Registro ──────────────────────────────────────────────────────────

TOOLS = [
    ("teams_send_message", teams_send_message_handler),
    ("teams_check_status", teams_check_status_handler),
]
