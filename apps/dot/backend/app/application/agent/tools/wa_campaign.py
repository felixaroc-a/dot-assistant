"""Tool del agente: registrar campana de WhatsApp para envio por el worker.

NO envia los mensajes directamente — eso lo hace el worker.
Registra la campana formateada en Firestore y devuelve instrucciones
para que el AutomationExecutor las procese.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.application.agent.ports import ToolResult
from app.firebase_db import get_db as get_firestore_client

log = logging.getLogger("dot.agent.tools.wa_campaign")


def send_whatsapp_campaign_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Registra una campana de WhatsApp para envio masivo por el worker.

    Recibe:
        contacts: list[str]  — numeros de WhatsApp de destino
        template: str        — plantilla de mensaje con {name} placeholders
        names: list[str]     — nombres correspondientes a contacts
        auto_id: str         — ID de la automatizacion padre

    Devuelve ToolResult con artifacts de tipo "whatsapp_campaign".
    El texto de salida contiene lineas con formato:
        to: +58... | text: mensaje personalizado
    """
    contacts: list[str] = arguments.get("contacts", []) or []
    template: str = str(arguments.get("template", "")).strip()
    names: list[str] = arguments.get("names", []) or []
    auto_id: str = str(arguments.get("auto_id", "")).strip()

    if not contacts:
        return ToolResult(
            ok=False,
            output="",
            error="La campana necesita al menos un contacto (contacts).",
        )
    if not template:
        return ToolResult(
            ok=False,
            output="",
            error="La campana necesita una plantilla de mensaje (template).",
        )
    if not auto_id:
        return ToolResult(
            ok=False,
            output="",
            error="Falta el ID de la automatizacion padre (auto_id).",
        )

    # Personalizar mensajes
    lines: list[str] = []
    campaign_messages: list[dict[str, str]] = []
    for i, contact in enumerate(contacts):
        name = names[i] if i < len(names) else ""
        personalized = template.replace("{name}", name or contact)
        lines.append(f"to: {contact.strip()} | text: {personalized.strip()}")
        campaign_messages.append({
            "to": contact.strip(),
            "text": personalized.strip(),
        })

    campaign_text = "\n".join(lines)

    # Guardar registro en Firestore para trazabilidad
    try:
        db = get_firestore_client()
        campaign_ref = (
            db.collection("users")
            .document(uid)
            .collection("automation_results")
            .document(auto_id)
            .collection("campaigns")
            .document("pending")
        )
        campaign_ref.set({
            "automation_id": auto_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "registered",
            "total": len(campaign_messages),
            "contacts": contacts,
            "messages": campaign_messages,
        })
        log.info(
            "Campana registrada: auto=%s, %d mensajes para uid=%s",
            auto_id[:12], len(campaign_messages), uid[:8],
        )
    except Exception as e:
        log.warning("Error guardando registro de campana en Firestore: %s", e)
        # No bloqueamos — el worker igual procesara el texto

    return ToolResult(
        ok=True,
        output=campaign_text,
        artifacts=[
            {
                "type": "whatsapp_campaign",
                "auto_id": auto_id,
                "total": len(campaign_messages),
                "contacts": contacts,
            }
        ],
    )
