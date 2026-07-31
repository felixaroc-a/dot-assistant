"""Servicio de contexto de usuario para inyectar en el prompt del chat."""
from __future__ import annotations

import logging

from app.firebase_db import get_db as get_firestore_client

log = logging.getLogger("dot.user_context_service")

MAX_AUTOMATIONS_IN_CONTEXT = 10
MAX_EXECUTIONS = 5
MAX_DESCRIPTION_LENGTH = 200


def _get_user_profile(uid: str) -> dict:
    """Obtiene el perfil del usuario desde Firestore."""
    try:
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        if doc.exists:
            return doc.to_dict() or {}
    except Exception as e:
        log.warning("Error obteniendo perfil para contexto uid=%s: %s", uid[:8], e)
    return {}


def _get_recent_executions(uid: str) -> list[dict]:
    """Obtiene las últimas N ejecuciones de automatizaciones."""
    try:
        db = get_firestore_client()
        docs = (
            db.collection("users")
            .document(uid)
            .collection("automation_executions")
            .order_by("executed_at", direction="DESCENDING")
            .limit(MAX_EXECUTIONS)
            .stream()
        )
        return [
            {
                "automation_id": d.to_dict().get("automation_id", ""),
                "executed_at": d.to_dict().get("executed_at", ""),
                "result": (d.to_dict().get("result", "") or "")[:MAX_DESCRIPTION_LENGTH],
                "output_type": d.to_dict().get("output_type", "chat"),
            }
            for d in docs
        ]
    except Exception as e:
        log.warning("Error obteniendo ejecuciones recientes uid=%s: %s", uid[:8], e)
    return []


def _get_integrations_info(profile: dict) -> str:
    """Serializa las integraciones activas del usuario."""
    integrations = profile.get("integrations", [])
    if not integrations or not isinstance(integrations, list):
        return "Ninguna integración configurada."
    parts: list[str] = []
    for integration in integrations:
        sid = str(integration).strip()
        if sid == "gmail":
            parts.append("Gmail (correo electrónico)")
        elif sid == "google-calendar":
            parts.append("Google Calendar (agenda)")
        elif sid == "third-option":
            parts.append("Automatización personalizada (IA)")
        else:
            parts.append(sid)
    return ", ".join(parts) if parts else "Ninguna integración configurada."


def _get_channel_info(profile: dict) -> str:
    """Serializa el canal de mensajería configurado."""
    channel = profile.get("channel_id", "")
    if channel == "whatsapp":
        return "WhatsApp vinculado"
    elif channel:
        return f"Canal: {channel}"
    return "Ningún canal de mensajería configurado."


def build_user_context_block(uid: str) -> str:
    """T-ML-010: Serializa automatizaciones + últimas 5 ejecuciones + integraciones.

    Returns:
        Bloque de texto plano para inyectar en el system prompt del chat.
    """
    profile = _get_user_profile(uid)
    automations_raw = profile.get("saved_automations", [])
    if not isinstance(automations_raw, list):
        automations_raw = []

    active_autos = [a for a in automations_raw if isinstance(a, dict) and a.get("active")]

    lines: list[str] = []
    lines.append("=== CONTEXTO DEL USUARIO ===")

    # Integraciones y canal
    lines.append(f"Integraciones activas: {_get_integrations_info(profile)}")
    lines.append(f"Mensajería: {_get_channel_info(profile)}")

    # Automatizaciones activas
    if active_autos:
        lines.append(f"\nAutomatizaciones activas ({len(active_autos)}):")
        for auto in active_autos[:MAX_AUTOMATIONS_IN_CONTEXT]:
            name = auto.get("name", "Sin nombre")
            integration = auto.get("integration_id") or auto.get("integrationId") or ""
            instruction = (auto.get("instruction") or "")[:120]
            description = auto.get("description")
            schedule = auto.get("schedule", "manual")
            desc_part = f" — {description[:100]}" if description else ""
            lines.append(
                f"  - [{name}]({integration}) "
                f"Programación: {schedule}. "
                f"Instrucción: {instruction[:80]}{desc_part}"
            )
    else:
        lines.append("\nNo tiene automatizaciones activas configuradas.")

    # Últimas ejecuciones
    executions = _get_recent_executions(uid)
    if executions:
        lines.append(f"\nÚltimas {len(executions)} ejecuciones:")
        for ex in executions:
            aid = ex.get("automation_id", "?")[:8]
            ts = ex.get("executed_at", "") or ""
            preview = (ex.get("result", "") or "")[:80].replace("\n", " ")
            lines.append(f"  - [{aid}] {ts}: {preview}")
    else:
        lines.append("\nSin ejecuciones recientes.")

    # Bloque de memoria del usuario (prosa + hechos atómicos — FREE-M05)
    try:
        from app.services.memory_service import (
            format_memory_facts_for_prompt,
            get_memory,
            get_memory_facts,
            rank_memory_facts_for_prompt,
        )

        memory = get_memory(uid)
        top_facts = rank_memory_facts_for_prompt(get_memory_facts(uid))
        facts_text = format_memory_facts_for_prompt(top_facts)

        if (memory and isinstance(memory, str) and memory.strip()) or facts_text:
            lines.append("\n=== MEMORIA DEL USUARIO ===")
            lines.append(
                "Información que el usuario ha compartido en conversaciones anteriores "
                "y que puedes usar para personalizar tus respuestas:"
            )
            if memory and isinstance(memory, str) and memory.strip():
                lines.append(memory.strip())
            if facts_text:
                lines.append("\nHechos confirmados (memoria atómica):")
                lines.append(facts_text)
            lines.append("=== FIN MEMORIA ===")
        elif memory and isinstance(memory, dict):
            # Compatibilidad con formato antiguo (facts/preferences)
            if memory.get("facts") or memory.get("preferences"):
                lines.append("\n=== MEMORIA DEL USUARIO ===")
                lines.append(
                    "El usuario ha compartido la siguiente información sobre sí mismo "
                    "en conversaciones anteriores:"
                )
                if memory.get("facts"):
                    for fact in memory["facts"]:
                        lines.append(f"- {fact}")
                if memory.get("preferences"):
                    lines.append("\nPreferencias del usuario:")
                    for pref in memory["preferences"]:
                        lines.append(f"- {pref}")
                lines.append("=== FIN MEMORIA ===")
    except Exception:
        log.warning("Error obteniendo memoria para uid=%s", uid[:8], exc_info=True)

    lines.append("=== FIN CONTEXTO ===")
    return "\n".join(lines)
