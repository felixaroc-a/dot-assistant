"""Envio de alertas de seguridad via webhook (Discord/Slack)."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("dot_billing.webhook")

DEFAULT_WEBHOOK_URL = os.environ.get("SECURITY_WEBHOOK_URL", "").strip()


def send_alert(
    title: str,
    message: str,
    level: str = "warning",
    webhook_url: str = "",
) -> None:
    """Envia alerta a Discord/Slack via webhook."""
    url = webhook_url or DEFAULT_WEBHOOK_URL
    if not url:
        log.debug(
            "SECURITY_WEBHOOK_URL no configurada, alerta solo en log: %s: %s",
            title,
            message,
        )
        return

    if "discord" in url or "discordapp" in url:
        payload = {"content": f"**[{level.upper()}] {title}**\n{message}"}
    else:
        payload = {"text": f"[{level.upper()}] {title}\n{message}"}

    try:
        httpx.post(url, json=payload, timeout=10)
        log.info("Alerta enviada: %s", title)
    except Exception as e:
        log.warning("No se pudo enviar alerta webhook: %s", e)
