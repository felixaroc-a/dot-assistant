"""Tools Signal Bridge — CANAL 1/3: Mensajería Signal via signal-cli.

Tools para Agent Runtime que permiten al agente enviar mensajes por Signal.

Auth: SIGNAL_PHONE_NUMBER + signal-cli en PATH.
Gate: SIGNAL_ENABLED=true en .env.
Sin token/config → "requiere configurar Signal en Ajustes".
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.signal")

# ─── Helpers ──────────────────────────────────────────────────────────

def _check_enabled() -> str | None:
    """Retorna mensaje de error si Signal no está habilitado/configurado."""
    if not settings.signal_enabled:
        return "Canal Signal deshabilitado. El usuario debe activar SIGNAL_ENABLED=true en Ajustes."

    phone = (os.getenv("SIGNAL_PHONE_NUMBER") or "").strip()
    if not phone:
        return (
            "Signal no configurado. Solicita al usuario que configure "
            "SIGNAL_PHONE_NUMBER en Ajustes y asegúrese de tener signal-cli instalado "
            "(gratis en https://github.com/AsamK/signal-cli)."
        )
    return None


# ─── Handlers ──────────────────────────────────────────────────────────

def signal_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje de Signal al número indicado.

    Args:
        to: Número de teléfono en formato internacional (+584241234567)
        text: Contenido del mensaje de texto

    Returns:
        ToolResult con confirmación o error
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    to = str(arguments.get("to") or arguments.get("phone") or "").strip()
    text = str(arguments.get("text") or arguments.get("message") or "").strip()

    if not to:
        return ToolResult(ok=False, output="", error="Falta el número de destino (to).")
    if not text:
        return ToolResult(ok=False, output="", error="Falta el contenido del mensaje (text).")

    try:
        from app.services.signal_service import send_signal_message as _send

        result = _send(phone=to, text=text)
        if result["ok"]:
            return ToolResult(
                ok=True,
                output=f"Mensaje Signal enviado a {to[-8:]}: \"{text[:100]}\" (id={result['message_id']}).",
            )
        return ToolResult(ok=False, output="", error=f"Error enviando Signal: {result['error']}")
    except Exception as e:
        log.warning("signal_send_message error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def signal_check_status_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica el estado del canal Signal (linked, phone, configurado).

    Returns:
        ToolResult con resumen del estado del canal
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=True, output=f"Canal Signal: {error_msg}")

    phone = (os.getenv("SIGNAL_PHONE_NUMBER") or "").strip()
    cli = settings.signal_cli_path or "signal-cli"

    return ToolResult(
        ok=True,
        output=(
            f"Canal Signal configurado:\n"
            f"- Número: {phone[-8:]}\n"
            f"- CLI: {cli}\n"
            f"- Estado: operativo (skeleton)"
        ),
    )


def signal_read_recent_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee mensajes recientes de Signal. Skeleton — requiere implementación completa
    con signal-cli receive o dbus.

    Args:
        limit: Máximo de mensajes a recuperar (default 10)
        phone: Filtrar por número de teléfono (opcional)

    Returns:
        ToolResult con lista de mensajes o indicación de skeleton
    """
    error_msg = _check_enabled()
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    limit = min(int(arguments.get("limit") or 10), 50)

    return ToolResult(
        ok=True,
        output=(
            f"Lectura de mensajes Signal (skeleton): "
            f"La recepción de mensajes Signal requiere signal-cli en modo dbus. "
            f"Actualmente solo está implementado el envío. "
            f"Se solicitaron {limit} mensajes."
        ),
    )


# ─── Registro ──────────────────────────────────────────────────────────

TOOLS = [
    ("signal_send_message", signal_send_message_handler),
    ("signal_check_status", signal_check_status_handler),
    ("signal_read_recent", signal_read_recent_handler),
]
