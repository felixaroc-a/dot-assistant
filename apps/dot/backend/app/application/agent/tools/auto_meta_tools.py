"""Tools meta de automatizaciones y billing — F6."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.meta")

TOOL_SCHEMAS: dict[str, dict] = {
    "auto_create": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nombre corto de la automatización."},
            "instruction": {"type": "string", "description": "Qué debe hacer (instrucción para el agente)."},
            "schedule": {
                "type": "string",
                "description": "manual, daily:HH:MM o weekly:mon:HH:MM. Preferir create_automation para NL.",
            },
            "output_type": {"type": "string", "description": "notify o whatsapp."},
            "description": {"type": "string", "description": "Descripción breve opcional."},
        },
        "required": ["name", "instruction"],
    },
}

_FIRESTORE_UNAVAILABLE_ERRORS = ("quota exceeded", "resource_exhausted", "unavailable", "deadline exceeded", "internal")
_FIRESTORE_FALLBACK = (
    "Firestore no está disponible en este momento (límite de uso o mantenimiento). "
    "Tus automatizaciones están guardadas localmente. "
    "Se sincronizarán cuando el servicio se restablezca."
)

def _is_firestore_unavailable(error: str) -> bool:
    return any(tag in str(error).lower() for tag in _FIRESTORE_UNAVAILABLE_ERRORS)


def auto_list_active_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Lista todas las automatizaciones activas del usuario."""
    try:
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            return ToolResult(ok=True, output="Perfil no encontrado.")
        profile = doc.to_dict()
        autos = profile.get("saved_automations", [])
        if not autos:
            return ToolResult(ok=True, output="No hay automatizaciones guardadas.")
        lines = [f"Automatizaciones ({len(autos)}):"]
        for a in autos:
            status = "ACTIVA" if a.get("active") else "PAUSADA"
            schedule = a.get("schedule", "manual")
            lines.append(f"  [{status}] {a.get('name','?')} | schedule={schedule} | integration={a.get('integration_id','ia')}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_pause_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Pausa una automatizacion por ID o nombre."""
    try:
        query = str(arguments.get("id") or arguments.get("name") or "").strip().lower()
        if not query:
            return ToolResult(ok=False, output="", error="Falta id o name de la automatizacion.")
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        profile = doc.to_dict() if doc.exists else {}
        autos = profile.get("saved_automations", [])
        found = None
        for a in autos:
            if a.get("id") == query or query in a.get("name", "").lower():
                found = a
                break
        if not found:
            return ToolResult(ok=False, output="", error=f"Automatizacion '{query}' no encontrada.")
        found["active"] = False
        db.collection("users").document(uid).set({"saved_automations": autos}, merge=True)
        return ToolResult(ok=True, output=f"Automatizacion '{found.get('name')}' pausada.")
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_resume_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Reanuda una automatizacion pausada."""
    try:
        query = str(arguments.get("id") or arguments.get("name") or "").strip().lower()
        if not query:
            return ToolResult(ok=False, output="", error="Falta id o name.")
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        profile = doc.to_dict() if doc.exists else {}
        autos = profile.get("saved_automations", [])
        found = None
        for a in autos:
            if a.get("id") == query or query in a.get("name", "").lower():
                found = a
                break
        if not found:
            return ToolResult(ok=False, output="", error=f"Automatizacion '{query}' no encontrada.")
        found["active"] = True
        db.collection("users").document(uid).set({"saved_automations": autos}, merge=True)
        return ToolResult(ok=True, output=f"Automatizacion '{found.get('name')}' reanudada.")
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_get_stats_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Estadisticas de automatizaciones."""
    try:
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        excs = db.collection("users").document(uid).collection("automation_executions").limit(100).stream()
        total = 0
        results = []
        for exc in excs:
            d = exc.to_dict()
            total += 1
            results.append(d.get("result", "")[:50])
        doc = db.collection("users").document(uid).get()
        profile = doc.to_dict() if doc.exists else {}
        auto_count = len(profile.get("saved_automations", []))
        active = sum(1 for a in profile.get("saved_automations", []) if a.get("active"))
        return ToolResult(ok=True, output=f"Stats: {auto_count} autos ({active} activas), {total} ejecuciones recientes.")
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_clone_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Clona una automatizacion existente con otro nombre."""
    try:
        query = str(arguments.get("id") or arguments.get("name") or "").strip().lower()
        new_name = str(arguments.get("new_name") or "").strip()
        if not query or not new_name:
            return ToolResult(ok=False, output="", error="Falta id/name de la original y new_name.")
        import uuid
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        autos = (doc.to_dict() or {}).get("saved_automations", [])
        for a in autos:
            if a.get("id") == query or query in a.get("name", "").lower():
                clone = dict(a)
                clone["id"] = uuid.uuid4().hex[:12]
                clone["name"] = new_name
                clone["active"] = False
                autos.append(clone)
                db.collection("users").document(uid).set({"saved_automations": autos}, merge=True)
                return ToolResult(ok=True, output=f"Automatizacion clonada como '{new_name}' (pausada).")
        return ToolResult(ok=False, output="", error=f"No encontrada: {query}")
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_suggest_improvement_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Sugiere mejora de instruccion usando IA."""
    try:
        query = str(arguments.get("id") or arguments.get("name") or "").strip().lower()
        if not query:
            return ToolResult(ok=False, output="", error="Falta id/name.")
        from app.firebase_db import get_db as get_firestore_client
        from app.services.provider_router import route_chat
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        autos = (doc.to_dict() or {}).get("saved_automations", [])
        found = None
        for a in autos:
            if a.get("id") == query or query in a.get("name", "").lower():
                found = a
                break
        if not found:
            return ToolResult(ok=False, output="", error=f"No encontrada: {query}")
        suggestion = route_chat(
            f"Mejora esta instruccion de automatizacion para que sea mas clara y efectiva. "
            f"Sugiere cambios concretos.\n\nInstruccion actual: {found.get('instruction','')}",
            provider_id="deepseek",
            system_prompt="Sugiere mejoras concretas. Se breve y practico."
        )
        return ToolResult(ok=True, output=suggestion.strip()[:600])
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def auto_create_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea una automatización desde chat (P2). Args: name, instruction, schedule (manual|daily:HH:MM|weekly:day:HH:MM), output_type opcional."""
    try:
        import uuid

        name = str(arguments.get("name") or "").strip()
        instruction = str(arguments.get("instruction") or "").strip()
        schedule = str(arguments.get("schedule") or "manual").strip() or "manual"
        output_type = str(arguments.get("output_type") or "notify").strip() or "notify"
        description = str(arguments.get("description") or "").strip()
        if not name or not instruction:
            return ToolResult(
                ok=False,
                output="",
                error="Faltan name e instruction. Ejemplo: name='Briefing mañana', instruction='...', schedule='daily:09:00'.",
            )
        from app.firebase_db import get_db as get_firestore_client

        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        profile = doc.to_dict() if doc.exists else {}
        autos = list(profile.get("saved_automations") or [])
        if not isinstance(autos, list):
            autos = []
        auto_id = uuid.uuid4().hex[:12]
        new_auto = {
            "id": auto_id,
            "name": name[:120],
            "instruction": instruction[:4000],
            "integration_id": "third-option",
            "schedule": schedule,
            "output_type": output_type,
            "description": description[:500] or name[:120],
            "active": True,
            "source": "chat",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        autos.append(new_auto)
        db.collection("users").document(uid).set({"saved_automations": autos}, merge=True)
        try:
            from app.services.automation_scheduler import get_scheduler

            sch = get_scheduler()
            if sch is not None:
                sch.reload_user_automations(uid)
        except Exception as e:
            log.debug("Scheduler no rehidratado tras auto_create: %s", e)
        return ToolResult(
            ok=True,
            output=(
                f"Automatización creada y ACTIVA.\n"
                f"id={auto_id}\nname={name}\nschedule={schedule}\n"
                f"Se ejecutará sola según la programación (o ▶ si es manual)."
            ),
        )
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def billing_payment_link_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera instrucciones de pago."""
    try:
        amount = float(arguments.get("amount") or 0)
        concept = str(arguments.get("concept") or "Pago").strip()
        method = str(arguments.get("method") or "pago_movil").strip().lower()
        if amount <= 0:
            return ToolResult(ok=False, output="", error="Falta amount mayor a 0.")
        methods = {
            "pago_movil": "PagoMóvil",
            "zelle": "Zelle",
            "paypal": "PayPal",
            "transferencia": "Transferencia bancaria",
            "binance": "Binance Pay",
        }
        label = methods.get(method, method.upper())
        return ToolResult(ok=True, output=f"Solicitud de pago por {label}: {amount:.2f} USD por {concept}. Instrucciones de pago pendientes por configurar.")
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


def billing_collection_sequence_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera secuencia de cobranza."""
    try:
        from app.services.provider_router import route_chat
        client_name = str(arguments.get("client") or arguments.get("name") or "Cliente").strip()
        debt_amount = str(arguments.get("amount") or "").strip()
        days = int(arguments.get("days_overdue") or 7)
        result = route_chat(
            f"Genera 5 mensajes de cobranza para {client_name}, deuda de {debt_amount}, {days} dias vencida. "
            f"Tono escalando de amable a firme. Mensajes para WhatsApp, max 300 chars cada uno.",
            provider_id="deepseek",
            system_prompt="Mensajes de cobranza profesionales en espanol. Breve."
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        if _is_firestore_unavailable(str(e)):
            return ToolResult(ok=True, output="(Firestore no disponible. Datos locales activos.)")
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("auto_create", auto_create_handler),
    ("auto_list_active", auto_list_active_handler),
    ("auto_pause", auto_pause_handler),
    ("auto_resume", auto_resume_handler),
    ("auto_get_stats", auto_get_stats_handler),
    ("auto_clone", auto_clone_handler),
    # ⚠️ FAKE: auto_suggest_improvement alucina mejoras de automatización sin análisis real (route_chat)
    # ("auto_suggest_improvement", auto_suggest_improvement_handler),
    ("billing_payment_link", billing_payment_link_handler),
    # ⚠️ FAKE: billing_collection_sequence alucina mensajes de cobranza sin plantillas reales (route_chat)
    # ("billing_collection_sequence", billing_collection_sequence_handler),
]
