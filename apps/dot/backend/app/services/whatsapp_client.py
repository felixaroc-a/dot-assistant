"""Cliente para enviar mensajes WhatsApp via bridge local de Electron."""
from __future__ import annotations

import logging

import httpx

from app.settings import settings

log = logging.getLogger("dot.whatsapp_client")


def _bridge_url() -> str:
    return (settings.whatsapp_bridge_url or "http://127.0.0.1:18790").rstrip("/")


def _bridge_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret = settings.whatsapp_bridge_secret.strip()
    if secret:
        headers["X-Bridge-Secret"] = secret
    return headers


async def send_whatsapp_message(to: str, text: str) -> tuple[bool, str | None]:
    """
    Envía un mensaje de WhatsApp a través del bridge local de Electron/OpenClaw.

    Returns:
        (success, message_id_or_error)
    """
    secret = settings.whatsapp_bridge_secret.strip()
    if not secret and settings.testing.strip() != "1":
        log.error("WHATSAPP_BRIDGE_SECRET vacío — outbound rechazado (fail-closed)")
        return False, "bridge_secret_not_configured"

    payload = {"to": to.strip(), "text": text.strip()}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{_bridge_url()}/v1/send",
                json=payload,
                headers=_bridge_headers(),
            )
            if resp.status_code == 401:
                log.warning("Bridge WhatsApp rechazó el secreto local")
                return False, "bridge_unauthorized"
            if resp.status_code == 503:
                return False, "bridge_secret_not_configured"
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            message_id = data.get("message_id") if isinstance(data, dict) else None
            if isinstance(data, dict) and data.get("ok") is False:
                return False, str(data.get("error") or "bridge_send_failed")
            return True, str(message_id) if message_id else None
    except httpx.ConnectError:
        log.error("Bridge WhatsApp no disponible en %s", _bridge_url())
        return False, "bridge_unreachable"
    except Exception as e:
        log.error("Error enviando mensaje WhatsApp a %s: %s", to, e)
        return False, str(e)


async def send_whatsapp_voice_note(to: str, path: str) -> tuple[bool, str | None]:
    """
    Envía nota de voz (PTT) por WhatsApp vía bridge local (Baileys).

    Returns:
        (success, message_id_or_error)
    """
    return await send_whatsapp_media(to, path, media_type="voice")


async def send_whatsapp_media(
    to: str,
    path: str,
    *,
    media_type: str = "document",
    caption: str = "",
) -> tuple[bool, str | None]:
    """
    Envía imagen o documento por WhatsApp vía bridge local (Baileys).

    Returns:
        (success, message_id_or_error)
    """
    secret = settings.whatsapp_bridge_secret.strip()
    if not secret and settings.testing.strip() != "1":
        log.error("WHATSAPP_BRIDGE_SECRET vacío — outbound media rechazado (fail-closed)")
        return False, "bridge_secret_not_configured"

    payload = {
        "to": to.strip(),
        "path": path.strip(),
        "media_type": media_type.strip().lower(),
        "caption": caption.strip(),
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{_bridge_url()}/v1/send-media",
                json=payload,
                headers=_bridge_headers(),
            )
            if resp.status_code == 401:
                log.warning("Bridge WhatsApp rechazó el secreto local (media)")
                return False, "bridge_unauthorized"
            if resp.status_code == 503:
                return False, "bridge_secret_not_configured"
            if resp.status_code == 400:
                data = resp.json() if resp.content else {}
                err = data.get("error") if isinstance(data, dict) else None
                return False, str(err or "invalid_media_request")
            if resp.status_code == 501:
                return False, "media_send_not_supported"
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            message_id = data.get("message_id") if isinstance(data, dict) else None
            if isinstance(data, dict) and data.get("ok") is False:
                return False, str(data.get("error") or "bridge_send_media_failed")
            return True, str(message_id) if message_id else None
    except httpx.ConnectError:
        log.error("Bridge WhatsApp no disponible en %s (media)", _bridge_url())
        return False, "bridge_unreachable"
    except Exception as e:
        log.error("Error enviando media WhatsApp a %s path=%s: %s", to, path, e)
        return False, str(e)
