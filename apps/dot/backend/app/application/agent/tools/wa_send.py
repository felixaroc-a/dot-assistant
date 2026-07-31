"""Tool opcional: enviar WhatsApp desde chat PC (intención clara)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.infrastructure.whatsapp.phone_resolver import to_e164

log = logging.getLogger("dot.agent.tools.wa_send")


def send_whatsapp_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    to_raw = str(arguments.get("to") or arguments.get("phone") or "").strip()
    text = str(arguments.get("text") or arguments.get("message") or "").strip()
    if not to_raw:
        return ToolResult(
            ok=False,
            output="",
            error="Falta destinatario (to: teléfono o JID de grupo).",
        )
    if not text:
        return ToolResult(ok=False, output="", error="Falta el texto del mensaje.")

    # Grupos / LIDs ya vienen con @ — no tocar.
    if "@" in to_raw:
        to = to_raw
    else:
        to = to_e164(to_raw) or to_raw
        if not to.startswith("+"):
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Número inválido o incompleto: «{to_raw}». "
                    "Usa formato local VE (0412…) o internacional (+58…)."
                ),
            )

    try:
        from app.services.whatsapp_client import send_whatsapp_message

        ok, err = asyncio.run(send_whatsapp_message(to, text))
        if ok:
            return ToolResult(ok=True, output=f"Mensaje WhatsApp enviado a {to}.")
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude enviar por WhatsApp: {err or 'error'}",
        )
    except Exception as e:
        log.warning("wa_send falló: %s", e)
        return ToolResult(
            ok=False,
            output="",
            error="No pude enviar el WhatsApp ahora. ¿Está vinculado y el bridge abierto?",
        )
