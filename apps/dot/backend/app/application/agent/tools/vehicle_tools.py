"""Tools de vehiculos, e-commerce basico, ventas — P2."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.vehicle")


def car_maintenance_schedule_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        brand = str(arguments.get("brand") or "").strip()
        model = str(arguments.get("model") or "").strip()
        km = float(arguments.get("km") or 0)
        if not brand:
            return ToolResult(ok=False, output="", error="Falta marca del vehiculo.")
        lines = [
            f"Calendario mantenimiento {brand} {model} ({km:.0f} km):",
            "  Cada 5,000 km: Cambio aceite y filtro",
            "  Cada 10,000 km: Filtro aire, bujias",
            "  Cada 20,000 km: Filtro combustible, alineacion",
            "  Cada 40,000 km: Frenos, correa distribucion",
            "  Cada 100,000 km: Revision mayor",
            "\nUsa schedule_reminder para alertas por km o fecha."
        ]
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def car_sell_valuation_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        brand = str(arguments.get("brand") or "").strip()
        model = str(arguments.get("model") or "").strip()
        year = int(arguments.get("year") or 2020)
        km = float(arguments.get("km") or 0)
        if not brand or not model:
            return ToolResult(ok=False, output="", error="Falta marca y modelo.")
        result = route_chat(f"Estima precio de mercado para {brand} {model} {year}, {km:.0f} km en Venezuela/mercado latino. Rango de precio justo.", provider_id="deepseek", system_prompt="Tasador de vehiculos. Respuesta en espanol, precio estimado realista.")
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def car_fuel_tracker_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        liters = float(arguments.get("liters") or 0)
        km = float(arguments.get("km") or 0)
        cost = float(arguments.get("cost") or 0)
        if liters <= 0:
            return ToolResult(ok=False, output="", error="Falta litros cargados.")
        efficiency = km / liters if km > 0 else 0
        cost_per_km = cost / km if km > 0 and cost > 0 else 0
        return ToolResult(ok=True, output=f"Carga: {liters}L, {km} km recorridos. Rendimiento: {efficiency:.1f} km/L. Costo estimado: ${cost_per_km:.4f}/km.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def car_route_optimizer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        origin = str(arguments.get("origin") or "").strip()
        dest = str(arguments.get("destination") or "").strip()
        if not origin or not dest:
            return ToolResult(ok=False, output="", error="Falta origen y destino.")
        result = route_chat(f"Mejor ruta de {origin} a {dest}. Distancia aproximada, tiempo estimado, peajes si aplica. Sugiere via principal.", provider_id="deepseek", system_prompt="Rutas practicas. Breve.")
        return ToolResult(ok=True, output=result.strip()[:400])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def car_accident_protocol_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    protocol = "PROTOCOLO DE ACCIDENTE:\n1. Mantener la calma, no mover el vehiculo\n2. Verificar heridos, llamar emergencias si es necesario\n3. Tomar fotos de todos los angulos\n4. Intercambiar datos: cedula, licencia, placa, seguro\n5. Llamar al seguro\n6. No aceptar culpa ni firmar nada sin abogado\n7. Buscar testigos\n8. Acudir a transito si hay heridos o danos mayores"
    return ToolResult(ok=True, output=protocol)


def sales_crm_light_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        lead = str(arguments.get("lead") or "").strip()
        stage = str(arguments.get("stage") or "contactado").strip()
        note = str(arguments.get("note") or "").strip()
        if not lead:
            return ToolResult(ok=False, output="", error="Falta nombre del lead.")
        stages = ["nuevo", "contactado", "interesado", "negociacion", "cerrado", "perdido"]
        if stage not in stages:
            stage = "contactado"
        return ToolResult(ok=True, output=f"Lead '{lead}' -> etapa '{stage}'. Nota: {note}. Guarda este pipeline en CRM o usa contact_create para seguimiento.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def sales_generate_quote_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        client = str(arguments.get("client") or "").strip()
        items_text = str(arguments.get("items") or "").strip()
        if not client or not items_text:
            return ToolResult(ok=False, output="", error="Falta cliente e items.")
        result = route_chat(f"Cotizacion para {client}:\n{items_text}\n\nGenera PDF mental con: logo sugerido, items con precio, subtotal, IVA (16%), total, validez 15 dias, terminos.", provider_id="deepseek", system_prompt="Cotizacion profesional en espanol.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def ecom_inventory_alert_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        product = str(arguments.get("product") or "").strip()
        stock = int(arguments.get("stock") or 0)
        min_stock = int(arguments.get("min_stock") or 5)
        if not product:
            return ToolResult(ok=False, output="", error="Falta nombre del producto.")
        if stock <= min_stock:
            return ToolResult(ok=True, output=f"ALERTA: {product} solo quedan {stock} unidades (minimo: {min_stock}). Reordena ya.")
        return ToolResult(ok=True, output=f"{product}: {stock} unidades en stock. OK.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def ecom_order_fulfillment_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        order = str(arguments.get("order_id") or arguments.get("order") or "").strip()
        client = str(arguments.get("client") or "").strip()
        address = str(arguments.get("address") or "").strip()
        if not order or not client:
            return ToolResult(ok=False, output="", error="Falta order_id y client.")
        return ToolResult(ok=True, output=f"Pedido {order} para {client}. Envio a: {address}. Genera etiqueta de envio y notifica al cliente con whatsapp_send.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("car_maintenance_schedule", car_maintenance_schedule_handler),
    # ⚠️ FAKE: car_sell_valuation alucina precios de vehículos sin API de tasación real (route_chat)
    # ("car_sell_valuation", car_sell_valuation_handler),
    ("car_fuel_tracker", car_fuel_tracker_handler),
    # ⚠️ car_route_optimizer → migrado a real_apis.py (OpenRouteService + Nominatim real)
    ("car_accident_protocol", car_accident_protocol_handler),
    ("sales_crm_light", sales_crm_light_handler),
    ("sales_generate_quote", sales_generate_quote_handler),
    ("ecom_inventory_alert", ecom_inventory_alert_handler),
    ("ecom_order_fulfillment", ecom_order_fulfillment_handler),
]
