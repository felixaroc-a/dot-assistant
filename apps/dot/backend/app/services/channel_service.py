"""Servicio unificado de canales multi-mensajería para DOT.

Centraliza el envío y recepción de mensajes a través de múltiples canales:
- WhatsApp (Baileys bridge)
- Signal (signal-cli bridge)
- Telegram (Bot API)
- Discord (Bot API)

Todos los canales usan el mismo cerebro de chat DOT para procesar mensajes.
Permite broadcast multi-canal y enrutamiento unificado.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("dot.channels")

AVAILABLE_CHANNELS: list[str] = []


class ChannelType(str, Enum):
    whatsapp = "whatsapp"
    signal = "signal"
    telegram = "telegram"
    discord = "discord"


@dataclass
class ChannelMessage:
    """Mensaje unificado a través de cualquier canal."""
    channel: str
    from_user: str
    to_user: str = ""
    text: str = ""
    timestamp: str = ""
    message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_audio: bool = False
    media_url: str | None = None
    media_mime_type: str | None = None


def get_available_channels() -> list[dict[str, Any]]:
    """Devuelve los canales disponibles con su estado."""
    from app.settings import settings

    channels = []

    # WhatsApp
    channels.append({
        "id": "whatsapp",
        "name": "WhatsApp",
        "icon": "whatsapp",
        "enabled": bool(settings.whatsapp_enabled),
        "status": "configured" if settings.whatsapp_enabled else "disabled",
        "features": ["text", "voice", "images", "groups"],
    })

    # Signal
    channels.append({
        "id": "signal",
        "name": "Signal",
        "icon": "signal",
        "enabled": bool(settings.signal_enabled),
        "status": "configured" if settings.signal_enabled else "disabled",
        "features": ["text", "images"],
    })

    # Telegram
    telegram_configured = bool((settings.telegram_bot_token or "").strip())
    channels.append({
        "id": "telegram",
        "name": "Telegram",
        "icon": "telegram",
        "enabled": telegram_configured,
        "status": "configured" if telegram_configured else "disabled",
        "features": ["text", "voice", "images", "groups", "channels"],
    })

    # Discord
    discord_configured = bool((settings.discord_bot_token or "").strip())
    channels.append({
        "id": "discord",
        "name": "Discord",
        "icon": "discord",
        "enabled": discord_configured,
        "status": "configured" if discord_configured else "disabled",
        "features": ["text", "voice", "images", "servers"],
    })

    return channels


async def send_message(
    channel: str,
    to: str,
    text: str,
    *,
    attachments: list[str] | None = None,
    uid: str = "",
) -> dict[str, Any]:
    """Envía un mensaje a través de cualquier canal disponible.

    Args:
        channel: Canal a usar ("whatsapp", "signal", "telegram", "discord").
        to: Destinatario (teléfono, chat_id, channel_id, etc.).
        text: Texto del mensaje.
        attachments: Archivos adjuntos (rutas locales).
        uid: ID del usuario propietario.

    Returns:
        {"ok": bool, "message_id": str, "error": str}
    """
    if channel == "whatsapp":
        return await _send_whatsapp(to, text)
    elif channel == "signal":
        return await _send_signal(to, text, attachments)
    elif channel == "telegram":
        return await _send_telegram(to, text, attachments)
    elif channel == "discord":
        return await _send_discord(to, text, attachments)
    else:
        return {"ok": False, "error": f"Canal no soportado: {channel}"}


async def broadcast_message(
    channels: list[str],
    to: str,
    text: str,
    *,
    attachments: list[str] | None = None,
    uid: str = "",
) -> dict[str, Any]:
    """Envía el mismo mensaje a múltiples canales simultáneamente.

    Returns:
        {"ok": bool, "results": {channel: {ok, message_id, error}}}
    """

    tasks = {
        ch: send_message(ch, to, text, attachments=attachments, uid=uid)
        for ch in channels
    }

    results = {}
    for ch, task in tasks.items():
        try:
            results[ch] = await task
        except Exception as e:
            results[ch] = {"ok": False, "error": str(e)}

    all_ok = all(r.get("ok") for r in results.values())

    return {
        "ok": all_ok,
        "results": results,
    }


async def process_inbound(channel: str, message: ChannelMessage) -> dict[str, Any]:
    """Procesa un mensaje entrante de cualquier canal con el cerebro DOT.

    Enruta a través del mismo pipeline de chat que WhatsApp y el chat PC.
    """
    from app.services.chat_context import build_system_prompt
    from app.services.provider_router import route_chat_detailed

    try:
        system_prompt = build_system_prompt(message.from_user, message.text)
        channel_hint = _channel_response_hint(channel)
        full_prompt = system_prompt + channel_hint

        result = route_chat_detailed(
            message.text,
            "deepseek",
            full_prompt,
            include_document_action_prompt=False,
        )

        return {
            "ok": True,
            "channel": channel,
            "response": result.content.strip(),
            "model": result.model,
        }
    except Exception as e:
        log.exception("Error procesando mensaje %s", channel)
        return {"ok": False, "error": str(e)}


def _channel_response_hint(channel: str) -> str:
    """Devuelve hint de formato según el canal."""
    hints = {
        "whatsapp": "\n\n[Canal: WhatsApp] Responde en texto corto para móvil (≤500 caracteres). Sin markdown.",
        "signal": "\n\n[Canal: Signal] Responde en texto claro y privado. Sin markdown extenso.",
        "telegram": "\n\n[Canal: Telegram] Puedes usar formato markdown básico (**negrita**, *cursiva*).",
        "discord": "\n\n[Canal: Discord] Responde en estilo conversacional. Puedes usar emojis y formato Discord.",
    }
    return hints.get(channel, "")


# ─── Canales individuales ────────────────────────────────────────────


async def _send_whatsapp(to: str, text: str) -> dict[str, Any]:
    """Envía mensaje por WhatsApp via Baileys bridge."""
    try:
        from app.services.whatsapp_client import send_whatsapp_message
        ok, result = await send_whatsapp_message(to, text)
        return {"ok": ok, "message_id": result, "error": None if ok else result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _send_signal(to: str, text: str, attachments: list[str] | None = None) -> dict[str, Any]:
    """Envía mensaje por Signal via signal-cli."""
    try:
        from app.services.signal_service import send_signal_message
        result = send_signal_message(phone=to, text=text, attachments=attachments)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _send_telegram(to: str, text: str, attachments: list[str] | None = None) -> dict[str, Any]:
    """Envía mensaje por Telegram Bot API."""
    from app.settings import settings

    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN no configurado"}

    import httpx

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": to,
        "text": text[:4096],
        "parse_mode": "Markdown",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("ok"):
                message_id = str(data["result"]["message_id"])
                return {"ok": True, "message_id": message_id}
            else:
                return {"ok": False, "error": data.get("description", "Error Telegram")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _send_discord(to: str, text: str, attachments: list[str] | None = None) -> dict[str, Any]:
    """Envía mensaje por Discord Bot API.

    'to' debe ser un channel_id de Discord.
    """
    from app.settings import settings

    token = (settings.discord_bot_token or "").strip()
    if not token:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN no configurado"}

    import httpx

    url = f"https://discord.com/api/v10/channels/{to}/messages"
    payload = {"content": text[:2000]}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "message_id": data["id"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
