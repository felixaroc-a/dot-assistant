"""Envio masivo de mensajes WhatsApp via bridge local con rate limiting.

Usado por el worker para ejecutar campanas de WhatsApp generadas por
automatizaciones con output_type: "whatsapp_campaign".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.settings import settings

log = logging.getLogger("dot.worker.whatsapp_sender")

# Rate limiting: max 5 mensajes/segundo para no disparar anti-spam
_MAX_RPS = 5
_BURST_SIZE = 5


def _bridge_url() -> str:
    return (settings.whatsapp_bridge_url or "http://127.0.0.1:18790").rstrip("/")


def _bridge_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret = settings.whatsapp_bridge_secret.strip()
    if secret:
        headers["X-Bridge-Secret"] = secret
    return headers


class MessageRateLimiter:
    """Controla la tasa de envio de mensajes (token bucket simple)."""

    def __init__(self, max_rps: int = _MAX_RPS, burst: int = _BURST_SIZE):
        self._max_rps = max_rps
        self._burst = burst
        self._tokens = burst
        self._last_refill = asyncio.get_event_loop().time()

    async def acquire(self) -> None:
        """Espera hasta que haya un token disponible."""
        loop = asyncio.get_event_loop()
        while self._tokens <= 0:
            now = loop.time()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._max_rps)
            self._last_refill = now
            if self._tokens <= 0:
                wait = 1.0 / self._max_rps
                await asyncio.sleep(wait)
        self._tokens -= 1


async def _send_one(
    client: httpx.AsyncClient,
    to: str,
    text: str,
    limiter: MessageRateLimiter,
) -> dict[str, Any]:
    """Envia un mensaje individual respetando rate limiting."""
    await limiter.acquire()

    payload = {"to": to.strip(), "text": text.strip()}
    try:
        resp = await client.post(
            f"{_bridge_url()}/v1/send",
            json=payload,
            headers=_bridge_headers(),
        )
        if resp.status_code == 401:
            return {"to": to, "ok": False, "error": "bridge_unauthorized"}
        if resp.status_code == 503:
            return {"to": to, "ok": False, "error": "bridge_secret_not_configured"}
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        message_id = data.get("message_id") if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get("ok") is False:
            return {"to": to, "ok": False, "error": str(data.get("error") or "bridge_send_failed")}
        return {"to": to, "ok": True, "message_id": str(message_id) if message_id else None}
    except httpx.ConnectError:
        log.error("Bridge WhatsApp no disponible en %s", _bridge_url())
        return {"to": to, "ok": False, "error": "bridge_unreachable"}
    except Exception as e:
        log.error("Error enviando a %s: %s", to, e)
        return {"to": to, "ok": False, "error": str(e)}


async def send_bulk_messages(
    uid: str,
    auto_id: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Envia multiples mensajes de WhatsApp con rate limiting.

    Cada message dict debe tener:
        to: str   — numero de telefono o JID
        text: str — contenido del mensaje

    Retorna:
        {
            sent: int,
            failed: int,
            total: int,
            details: list[dict],
            executed_at: str  # ISO timestamp
        }
    """
    if not messages:
        return {"sent": 0, "failed": 0, "total": 0, "details": [], "executed_at": datetime.now(timezone.utc).isoformat()}

    # Validar secreto del bridge
    secret = settings.whatsapp_bridge_secret.strip()
    if not secret and settings.testing.strip() != "1":
        log.error("WHATSAPP_BRIDGE_SECRET vacio — campana %s rechazada (fail-closed)", auto_id)
        return {
            "sent": 0,
            "failed": len(messages),
            "total": len(messages),
            "details": [{"to": m.get("to", "?"), "ok": False, "error": "bridge_secret_not_configured"} for m in messages],
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    limiter = MessageRateLimiter()

    async with httpx.AsyncClient(timeout=20.0) as client:
        tasks = [_send_one(client, m["to"], m["text"], limiter) for m in messages]
        details = await asyncio.gather(*tasks)

    sent = sum(1 for d in details if d.get("ok"))
    failed = sum(1 for d in details if not d.get("ok"))

    log.info(
        "Campana %s completada: %d/%d enviados, %d fallidos (uid=%s)",
        auto_id[:12], sent, len(messages), failed, uid[:8],
    )

    return {
        "sent": sent,
        "failed": failed,
        "total": len(messages),
        "details": details,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def send_bulk_messages_sync(
    uid: str,
    auto_id: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Wrapper sincrono para usar desde codigo no-async (ej: sandbox)."""
    return asyncio.run(send_bulk_messages(uid, auto_id, messages))
