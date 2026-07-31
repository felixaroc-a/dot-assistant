"""Confirmación humana antes de acciones destructivas (BIBLIA §19 P5, Loop-12).

En chat de usuario, tools irreversibles exigen confirmación explícita:
el agente pregunta en español y solo ejecuta con confirm=true en arguments.

Automatizaciones con mandato explícito del usuario omiten este gate vía contexto.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

CONFIRM_PARAM = "confirm"

# Canales con mandato previo (automatización/cron) — no re-preguntar cada paso.
_MANDATE_BYPASS_CHANNELS = frozenset({"automation", "worker", "cron", "composite"})

_execution_channel: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "destructive_confirm_channel",
    default=None,
)


def set_destructive_confirm_channel(channel: str | None) -> contextvars.Token:
    """Marca el canal de ejecución actual (p. ej. chat PC vs automatización)."""
    return _execution_channel.set(channel)


def reset_destructive_confirm_channel(token: contextvars.Token) -> None:
    _execution_channel.reset(token)


def _mandate_bypass_active() -> bool:
    ch = (_execution_channel.get() or "").strip().lower()
    return ch in _MANDATE_BYPASS_CHANNELS


# Tools que siempre requieren confirm en chat de usuario.
_ALWAYS_CONFIRM: dict[str, str] = {
    "deleteFile": "eliminar el archivo «{path}»",
    "calendar_delete_event": "eliminar el evento de calendario",
    "gmail_send": "enviar el correo a «{to}»",
    "gmail_auto_reply": "responder al correo",
    "gmail_archive": "archivar el correo",
    "gmail_trash": "mover el correo a la papelera",
    "send_whatsapp_message": "enviar el mensaje de WhatsApp a «{to}»",
    "send_whatsapp_document": "enviar el documento por WhatsApp a «{to}»",
    "notify_whatsapp_owner": "enviarte un mensaje por WhatsApp",
    "send_whatsapp_campaign": "enviar una campaña masiva de WhatsApp a {count} contacto(s)",
    "outlook_send_email": "enviar el correo de Outlook a «{to}»",
    "slack_send_message": "enviar un mensaje de Slack",
    "telegram_send_message": "enviar un mensaje de Telegram",
    "discord_send_message": "enviar un mensaje de Discord",
    "teams_send_message": "enviar un mensaje de Teams",
    "signal_send_message": "enviar un mensaje de Signal",
    "line_send_message": "enviar un mensaje de LINE",
    "gmail_schedule_send": "programar el envío de un correo",
    "whatsapp_send_voice_note": "enviar una nota de voz por WhatsApp",
    "exec": "ejecutar un comando en el sistema",
}

_OVERWRITE_TOOLS = frozenset({"writeFile", "writeFileBytes"})


def _is_confirmed(arguments: dict[str, Any] | None) -> bool:
    if not arguments:
        return False
    val = arguments.get(CONFIRM_PARAM)
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes", "si", "sí"}:
        return True
    return False


def _format_action_summary(tool_name: str, arguments: dict[str, Any]) -> str:
    template = _ALWAYS_CONFIRM.get(tool_name, tool_name.replace("_", " "))
    contacts = arguments.get("contacts")
    count = len(contacts) if isinstance(contacts, list) else 0
    try:
        return template.format(
            path=str(arguments.get("path") or "?"),
            to=str(arguments.get("to") or arguments.get("phone") or "?"),
            subject=str(arguments.get("subject") or "(sin asunto)"),
            count=count,
        )
    except (KeyError, ValueError):
        return template


def _is_mass_email(arguments: dict[str, Any]) -> bool:
    to = arguments.get("to") or arguments.get("recipients")
    if isinstance(to, list):
        return len(to) > 1
    if isinstance(to, str):
        return any(sep in to for sep in (",", ";"))
    return False


def _target_file_exists(path: str) -> bool:
    path = (path or "").strip()
    if not path:
        return False
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        return bool(raw.get("ok"))
    except Exception:
        return False


def requires_destructive_confirmation(tool_name: str, arguments: dict[str, Any] | None) -> bool:
    """True si la tool necesita confirmación explícita del usuario."""
    if _mandate_bypass_active():
        return False
    args = arguments or {}
    name = (tool_name or "").strip()

    if name in _ALWAYS_CONFIRM:
        return True
    if name in ("gmail_send", "outlook_send_email") and _is_mass_email(args):
        return True
    if name in _OVERWRITE_TOOLS:
        path = str(args.get("path") or "").strip()
        if args.get("overwrite") is True:
            return True
        return bool(path) and _target_file_exists(path)
    return False


def check_destructive_confirmation(
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Verifica confirmación. Retorna (allowed, mensaje_error)."""
    if not requires_destructive_confirmation(tool_name, arguments):
        return True, ""
    if _is_confirmed(arguments):
        return True, ""

    args = arguments or {}
    name = (tool_name or "").strip()
    if name in _OVERWRITE_TOOLS:
        path = str(args.get("path") or "?")
        action = f"sobrescribir el archivo «{path}»"
    else:
        action = _format_action_summary(name, args)

    return (
        False,
        (
            f"CONFIRMACIÓN REQUERIDA: Antes de {action}, pregunta al usuario en español "
            f"claro si está seguro (p. ej. «¿Seguro que quieres {action}?»). "
            f"No ejecutes hasta que responda afirmativamente. "
            f"Luego vuelve a llamar {name} con confirm: true."
        ),
    )


def strip_confirm_argument(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Quita confirm de arguments antes de pasarlos al handler."""
    if not arguments:
        return {}
    cleaned = dict(arguments)
    cleaned.pop(CONFIRM_PARAM, None)
    return cleaned


@contextmanager
def destructive_confirm_scope(channel: str | None) -> Iterator[None]:
    """Establece canal de confirmación destructiva y restaura al salir."""
    ch = (channel or "").strip().lower()
    mapped = ch if ch in _MANDATE_BYPASS_CHANNELS else "user"
    token = set_destructive_confirm_channel(mapped)
    try:
        yield
    finally:
        reset_destructive_confirm_channel(token)


def list_destructive_tools() -> dict[str, list[str]]:
    """Inventario para auditoría / documentación."""
    return {
        "always_confirm": sorted(_ALWAYS_CONFIRM.keys()),
        "overwrite_when_exists": sorted(_OVERWRITE_TOOLS),
        "mass_email": ["gmail_send", "outlook_send_email"],
    }
