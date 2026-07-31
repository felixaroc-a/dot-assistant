"""Tools de eventos, facturacion profunda, migracion, logistica — P1-P2."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.event_bill")


# ─── Eventos ───────────────────────────────────────────

def event_rsvp_manager_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        event = str(arguments.get("event") or "Evento").strip()
        guests = arguments.get("guests") or []
        if isinstance(guests, str):
            guests = [g.strip() for g in guests.split(",")]
        if not guests:
            return ToolResult(ok=False, output="", error="Falta lista de invitados.")
        lines = [f"RSVP para: {event}"]
        for g in guests:
            lines.append(f"  - {g}: pendiente")
        lines.append(f"\n{len(guests)} invitados. Usa whatsapp_bulk_notify para invitaciones y schedule_reminder para recordatorios.")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def event_wedding_planner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        budget = str(arguments.get("budget") or "").strip()
        guests = int(arguments.get("guests") or 50)
        result = route_chat(f"Checklist de boda para {guests} invitados, presupuesto {budget}. Timeline 12 meses antes: anillos, vestido, locacion, catering, fotografia, musica, invitaciones, luna de miel.", provider_id="deepseek", system_prompt="Wedding planner en espanol. Checklist practico.")
        return ToolResult(ok=True, output=result.strip()[:1200])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def event_gift_suggester_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        relation = str(arguments.get("relation") or "amigo").strip()
        budget = str(arguments.get("budget") or "moderado").strip()
        age = int(arguments.get("age") or 30)
        result = route_chat(f"Sugiere 10 regalos para {relation}, {age} anios, presupuesto {budget}. Ideas originales, no genericas. Incluye opcion experiencia.", provider_id="deepseek", system_prompt="Ideas de regalo creativas en espanol.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Billing profundo ──────────────────────────────────

def billing_account_statement_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        client = str(arguments.get("client") or "Cliente").strip()
        invoices = arguments.get("invoices") or "factura1:100,factura2:200"
        if isinstance(invoices, str):
            invoices = [i.strip() for i in invoices.split(",")]
        lines = [f"ESTADO DE CUENTA - {client}", "=" * 40]
        total = 0
        for inv in invoices:
            parts = inv.split(":") if ":" in inv else [inv, "0"]
            name = parts[0].strip()
            try:
                amt = float(parts[1].strip().replace(",", "."))
                total += amt
                lines.append(f"  {name}: ${amt:.2f}")
            except ValueError:
                lines.append(f"  {name}: pendiente")
        lines.append(f"{'=' * 40}\n  TOTAL: ${total:.2f}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def billing_payment_plan_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        total = float(arguments.get("total") or 1000)
        months = int(arguments.get("months") or 6)
        interest = float(arguments.get("interest") or 0)
        monthly = total / months
        if interest > 0:
            monthly = total * (interest / 100) / (1 - (1 + interest / 100) ** -months)
        lines = [f"Plan de pago: ${total:.2f} en {months} cuotas"]
        for i in range(1, months + 1):
            lines.append(f"  Cuota {i}: ${monthly:.2f}")
        lines.append(f"  Total a pagar: ${monthly * months:.2f}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Migracion ─────────────────────────────────────────

def migration_path_finder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        nationality = str(arguments.get("nationality") or "").strip()
        profession = str(arguments.get("profession") or "").strip()
        if not nationality:
            return ToolResult(ok=False, output="", error="Falta nacionalidad.")
        result = route_chat(f"Compara 5 paises para emigrar siendo {nationality}, profesion {profession}. Evalua: visa posible, tiempo, costo, calidad de vida, mercado laboral.", provider_id="deepseek", system_prompt="Guia de emigracion en espanol. Datos realistas.")
        return ToolResult(ok=True, output=result.strip()[:1200])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def migration_cost_calculator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        dest = str(arguments.get("destination") or "").strip()
        people = int(arguments.get("people") or 1)
        if not dest:
            return ToolResult(ok=False, output="", error="Falta destino.")
        items = [("Pasajes", 800), ("Visa/tramites", 300), ("Alquiler 3 meses", 1500), ("Comida 3 meses", 900), ("Transporte", 200), ("Seguro medico", 300), ("Imprevistos", 500)]
        total = sum(amt for _, amt in items) * people
        lines = [f"Costo estimado para emigrar a {dest} ({people} persona(s)):", "=" * 40]
        for name, amt in items:
            lines.append(f"  {name}: ${amt * people}")
        lines.append(f"{'=' * 40}\n  TOTAL ESTIMADO: ${total}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def migration_document_checklist_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        dest = str(arguments.get("destination") or "").strip()
        if not dest:
            return ToolResult(ok=False, output="", error="Falta destino.")
        docs = ["Pasaporte vigente (+6 meses)", "Fotos tamano pasaporte", "Acta de nacimiento apostillada", "Antecedentes penales apostillados", "Titulo profesional apostillado", "Estados bancarios", "Carta de empleo/pension", "Seguro medico internacional", "Reserva de vuelo", "Reserva de alojamiento"]
        lines = [f"Checklist de documentos para {dest}:"]
        lines.extend(f"  - {d}" for d in docs)
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Logistica ─────────────────────────────────────────

def logistics_cost_calculator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        origin = str(arguments.get("origin") or "").strip()
        dest = str(arguments.get("destination") or "").strip()
        weight = float(arguments.get("weight_kg") or 1)
        if not origin or not dest:
            return ToolResult(ok=False, output="", error="Falta origen y destino.")
        base = weight * 5
        estimates = {"Domesa": base * 1.0, "MRW": base * 1.1, "Zoom": base * 0.95, "Tealca": base * 1.05}
        lines = [f"Cotizacion envio {origin} -> {dest} ({weight}kg):"]
        for carrier, cost in estimates.items():
            lines.append(f"  {carrier}: ${cost:.2f} aprox.")
        lines.append("\nPrecios estimados. Confirmar con la empresa.")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def logistics_route_planner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        stops = arguments.get("stops") or []
        if isinstance(stops, str):
            stops = [s.strip() for s in stops.split(",")]
        if not stops or len(stops) < 2:
            return ToolResult(ok=False, output="", error="Falta lista de paradas (al menos 2).")
        from app.services.provider_router import route_chat
        route_text = " -> ".join(stops[:5])
        result = route_chat(f"Optimiza esta ruta de entregas: {route_text}. Sugiere orden optimo y tiempo estimado.", provider_id="deepseek", system_prompt="Rutas optimizadas. Breve.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Oficina ───────────────────────────────────────────

def office_meeting_minutes_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "Reunion").strip()
        notes = str(arguments.get("notes") or "").strip()
        if not notes:
            return ToolResult(ok=False, output="", error="Falta notas de la reunion.")
        result = route_chat(f"Genera minuta profesional: {topic}\n\nNotas: {notes}\n\nEstructura: asistentes, agenda, decisiones, tareas (responsable + deadline), proximos pasos.", provider_id="deepseek", system_prompt="Minuta profesional en espanol. Estructura clara y accionable.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def office_proposal_writer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        client = str(arguments.get("client") or "").strip()
        service = str(arguments.get("service") or "").strip()
        budget = str(arguments.get("budget") or "").strip()
        if not client or not service:
            return ToolResult(ok=False, output="", error="Falta cliente y servicio.")
        result = route_chat(f"Propuesta comercial para {client}: {service}, presupuesto {budget}. Incluye: entendimiento del problema, metodologia, timeline, equipo, presupuesto detallado, casos similares.", provider_id="deepseek", system_prompt="Propuesta comercial profesional en espanol.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("event_rsvp_manager", event_rsvp_manager_handler),
    # ⚠️ FAKE: event_wedding_planner alucina checklists de boda sin API real (route_chat)
    # ("event_wedding_planner", event_wedding_planner_handler),
    # ⚠️ FAKE: event_gift_suggester alucina sugerencias de regalos sin API real (route_chat)
    # ("event_gift_suggester", event_gift_suggester_handler),
    ("billing_account_statement", billing_account_statement_handler),
    ("billing_payment_plan", billing_payment_plan_handler),
    # ⚠️ FAKE: migration_path_finder alucina opciones de migración sin datos reales (route_chat)
    # ("migration_path_finder", migration_path_finder_handler),
    ("migration_cost_calculator", migration_cost_calculator_handler),
    ("migration_document_checklist", migration_document_checklist_handler),
    ("logistics_cost_calculator", logistics_cost_calculator_handler),
    # ⚠️ FAKE: logistics_route_planner alucina rutas sin API de mapas real (route_chat)
    # ("logistics_route_planner", logistics_route_planner_handler),
    ("office_meeting_minutes", office_meeting_minutes_handler),
    # ⚠️ FAKE: office_proposal_writer alucina propuestas sin API real (route_chat)
    # ("office_proposal_writer", office_proposal_writer_handler),
]
