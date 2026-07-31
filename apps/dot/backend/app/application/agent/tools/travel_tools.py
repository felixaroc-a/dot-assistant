"""Tools de viajes y turismo — P1."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.travel")


def travel_full_planner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        dest = str(arguments.get("destination") or "").strip()
        days = int(arguments.get("days") or 5)
        budget = str(arguments.get("budget") or "moderado").strip()
        if not dest:
            return ToolResult(ok=False, output="", error="Falta destino.")
        result = route_chat(f"Plan de viaje a {dest} por {days} dias, presupuesto {budget}. Incluye itinerario dia por dia, hoteles sugeridos, transporte, comidas tipicas, actividades imperdibles.", provider_id="deepseek", system_prompt="Guia de viaje en espanol. Practica, realista, con datos utiles.")
        return ToolResult(ok=True, output=result.strip()[:2000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_visa_checker_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        nationality = str(arguments.get("nationality") or "venezolano").strip()
        dest = str(arguments.get("destination") or "").strip()
        if not dest:
            return ToolResult(ok=False, output="", error="Falta pais destino.")
        result = route_chat(f"Requisitos de visa para {nationality} viajando a {dest}. Tipo de visa, costo, tiempo de tramite, documentos necesarios.", provider_id="deepseek", system_prompt="Informacion de visados en espanol. Practica y actualizada si es posible.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_packing_list_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        dest = str(arguments.get("destination") or "").strip()
        days = int(arguments.get("days") or 5)
        season = str(arguments.get("season") or "verano").strip()
        result = f"Checklist de equipaje para {dest} ({days} dias, {season}):\n"
        items = ["Pasaporte/ID", "Tarjeta de embarque", "Dinero/tarjetas", "Celular + cargador", "Medicinas personales", "Ropa interior ({days}+2)", "Camisas/blusas ({days})", "Pantalones/shorts ({days//2})", "Zapatos comodos x2", "Chaqueta/abrigo" if season != "verano" else "Protector solar"]
        result += "\n".join(f"- {i}" for i in items)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_local_guide_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        city = str(arguments.get("city") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta ciudad.")
        result = route_chat(f"Guia local de {city}: transporte publico, zonas seguras/inseguras, comidas tipicas, frases utiles, costumbres, propinas, estafas comunes a evitar.", provider_id="deepseek", system_prompt="Guia local practica en espanol. Consejos de viajero.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_budget_tracker_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        budget = float(arguments.get("budget") or 1000)
        spent = float(arguments.get("spent") or 0)
        category = str(arguments.get("category") or "").strip()
        note = str(arguments.get("note") or "").strip()
        remaining = budget - spent
        pct = round(spent / budget * 100, 1) if budget > 0 else 0
        bar = "[" + "#" * int(pct // 5) + "." * (20 - int(pct // 5)) + "]"
        msg = f"Presupuesto viaje: ${spent:.0f}/${budget:.0f} ({pct}%) {bar}\nRestante: ${remaining:.0f}"
        if spent > budget:
            msg += "\nALERTA: Presupuesto excedido."
        return ToolResult(ok=True, output=msg)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_itinerary_share_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        itinerary = str(arguments.get("itinerary") or arguments.get("text") or "").strip()
        if not itinerary:
            return ToolResult(ok=False, output="", error="Falta itinerario.")
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path = "~/Desktop/Itinerario_de_viaje.txt"
        execute_local_tool_via_bridge("writeFile", path=path, content=itinerary)
        return ToolResult(ok=True, output=f"Itinerario guardado. Compartelo por WhatsApp: {path}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def travel_currency_optimizer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        amount = float(arguments.get("amount") or 100)
        from_cur = str(arguments.get("from") or "USD").upper()
        to_cur = str(arguments.get("to") or "VES").upper()
        result = route_chat(f"Convierte {amount} {from_cur} a {to_cur}. Sugiere si conviene cambiar en efectivo, banco o tarjeta. Tasa de referencia actual.", provider_id="deepseek", system_prompt="Consejo de cambio de divisas. Practico.")
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("travel_full_planner", travel_full_planner_handler),
    ("travel_visa_checker", travel_visa_checker_handler),
    ("travel_packing_list", travel_packing_list_handler),
    ("travel_local_guide", travel_local_guide_handler),
    ("travel_budget_tracker", travel_budget_tracker_handler),
    ("travel_itinerary_share", travel_itinerary_share_handler),
    ("travel_currency_optimizer", travel_currency_optimizer_handler),
]
