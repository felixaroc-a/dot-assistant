"""Servicio LINE Messaging — skeleton con LINE Messaging API.

Gestiona el estado del canal LINE y el envío de mensajes via LINE Messaging API v2.
Gate: LINE_ENABLED=true en .env.
Requiere LINE_CHANNEL_ACCESS_TOKEN y LINE_CHANNEL_SECRET de LINE Developers Console.

Referencia: https://developers.line.biz/en/reference/messaging-api/
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.settings import settings

log = logging.getLogger("dot.line_service")


# ─── Estado del canal ─────────────────────────────────────────────────

@dataclass
class LineChannelStatus:
    linked: bool = False
    bot_name: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


def get_line_channel_state() -> LineChannelStatus:
    """Obtiene el estado actual del canal LINE."""
    enabled = bool(settings.line_enabled)
    token = settings.line_channel_access_token

    return LineChannelStatus(
        linked=enabled and bool(token),
        bot_name=None,
        last_linked_at=None,
        last_heartbeat_at=None,
        last_error_at=None,
        error=None if (enabled and token) else "LINE no configurado (falta LINE_CHANNEL_ACCESS_TOKEN)",
    )


def update_line_channel_state(
    *, linked: bool, bot_name: str | None = None, error: str | None = None
) -> None:
    """Actualiza el estado del canal LINE. Skeleton — en producción usa Firestore."""
    log.info("line_channel_state_update linked=%s bot=%s error=%s", linked, bot_name, error)


def record_line_channel_event(
    *, event: str, bot_name: str | None = None, error: str | None = None, metadata: dict | None = None
) -> None:
    """Registra un evento operacional del canal LINE. Skeleton."""
    log.info("line_channel_event event=%s bot=%s error=%s meta=%s", event, bot_name, error, metadata)


# ─── Webhook ───────────────────────────────────────────────────────────

def _verify_line_signature(body: bytes, signature: str) -> bool:
    """Verifica la firma del webhook de LINE usando HMAC-SHA256."""
    secret = (settings.line_channel_secret or "").encode("utf-8")
    if not secret:
        log.warning("line_webhook: LINE_CHANNEL_SECRET no configurado, omitiendo verificación")
        return True

    expected = hmac.new(secret, body, hashlib.sha256).digest()
    expected_b64 = expected.hex()
    return hmac.compare_digest(expected_b64, signature)


def process_line_webhook(body: bytes, signature: str) -> dict:
    """Procesa eventos del webhook de LINE.

    Verifica firma, parsea eventos y los registra. Skeleton — en producción
    enrutaría a auto-reply o inbound service.

    Returns:
        dict con {ok, events_processed, error}
    """
    if not _verify_line_signature(body, signature):
        return {"ok": False, "error": "Firma webhook inválida"}

    try:
        data = json.loads(body)
        events = data.get("events", [])
        for event in events:
            event_type = event.get("type", "unknown")
            source = event.get("source", {})
            user_id = source.get("userId", "unknown")
            log.info("line_webhook_event type=%s user=%s", event_type, user_id[:12])

        return {"ok": True, "events_processed": len(events)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Body JSON inválido: {e}"}
    except Exception as e:
        log.exception("line_webhook error")
        return {"ok": False, "error": str(e)}


# ─── Envío de mensajes ────────────────────────────────────────────────

LINE_API_BASE = "https://api.line.me/v2"


def _line_headers() -> dict[str, str]:
    """Headers de autenticación para LINE Messaging API."""
    token = settings.line_channel_access_token
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN no configurado")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _line_post(endpoint: str, payload: dict, timeout: int = 20) -> dict:
    """POST genérico a LINE Messaging API."""
    url = f"{LINE_API_BASE}{endpoint}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_line_headers(), json=payload)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            log.warning("line_api error %d %s: %s", resp.status_code, endpoint, data)
        return {"status": resp.status_code, "data": data}


def send_line_push_message(
    user_id: str | None = None,
    user_ids: list[str] | None = None,
    text: str = "",
    notification_disabled: bool = False,
) -> dict:
    """Envía mensaje push (a un usuario) o multicast (a varios) via LINE.

    Args:
        user_id: ID de usuario LINE para push individual
        user_ids: Lista de IDs para multicast (>1 usa multicast)
        text: Contenido del mensaje
        notification_disabled: Si true, no notifica al usuario

    Returns:
        dict con {ok, message_id, error}
    """
    import asyncio

    if not settings.line_enabled:
        return {"ok": False, "message_id": None, "error": "Canal LINE deshabilitado (LINE_ENABLED=false)"}

    if not settings.line_channel_access_token:
        return {"ok": False, "message_id": None, "error": "LINE_CHANNEL_ACCESS_TOKEN no configurado"}

    messages = [{"type": "text", "text": text}]

    try:
        if user_ids and len(user_ids) > 1:
            payload = {"to": user_ids, "messages": messages}
            endpoint = "/bot/message/multicast"
        elif user_id:
            payload = {"to": user_id, "messages": messages}
            if notification_disabled:
                payload["notificationDisabled"] = True
            endpoint = "/bot/message/push"
        else:
            return {"ok": False, "message_id": None, "error": "Se requiere user_id o user_ids"}

        result = asyncio.run(_line_post(endpoint, payload))
        status = result.get("status", 500)
        ok = 200 <= status < 300
        msg_id = str(uuid.uuid4())[:12] if ok else None

        if ok:
            log.info("line_send ok endpoint=%s status=%d", endpoint, status)
        else:
            log.warning("line_send fail status=%d data=%s", status, result.get("data"))

        return {
            "ok": ok,
            "message_id": msg_id,
            "error": None if ok else f"LINE API error {status}: {result.get('data')}",
        }
    except Exception as e:
        log.warning("line_send exception: %s", e)
        return {"ok": False, "message_id": None, "error": str(e)}
