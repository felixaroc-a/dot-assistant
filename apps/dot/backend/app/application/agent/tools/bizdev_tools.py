"""Tools de desarrollo de negocios — P1-P2."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.bizdev")


def biz_business_plan_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        idea = str(arguments.get("idea") or "").strip()
        if not idea:
            return ToolResult(ok=False, output="", error="Falta idea de negocio.")
        result = route_chat(f"Plan de negocio para: {idea}. Incluye: resumen ejecutivo, mercado, competencia, marketing, operaciones, equipo, finanzas basicas, proyecciones 3 anios.", provider_id="deepseek", system_prompt="Business plan writer en espanol. Profesional y realista.")
        return ToolResult(ok=True, output=result.strip()[:2000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_market_research_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        industry = str(arguments.get("industry") or "").strip()
        country = str(arguments.get("country") or "").strip()
        if not industry:
            return ToolResult(ok=False, output="", error="Falta industria.")
        prompt = f"Investigacion de mercado: industria {industry}"
        if country: prompt += f" en {country}"
        result = route_chat(prompt + ". Tamano de mercado, crecimiento, players principales, tendencias, barreras de entrada.", provider_id="deepseek", system_prompt="Market researcher. Datos y analisis en espanol.")
        return ToolResult(ok=True, output=result.strip()[:1200])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_pitch_deck_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        startup = str(arguments.get("startup") or "").strip()
        if not startup:
            return ToolResult(ok=False, output="", error="Falta nombre/descripcion del startup.")
        result = route_chat(f"Pitch deck de 12 slides para {startup}: problema, solucion, mercado, producto, traccion, modelo de negocio, competencia, equipo, finanzas, metricas, ask, vision.", provider_id="deepseek", system_prompt="Pitch deck writer. Contenido por slide, listo para disenar.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_competitor_matrix_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        competitors = str(arguments.get("competitors") or "").strip()
        if not competitors:
            return ToolResult(ok=False, output="", error="Falta lista de competidores.")
        result = route_chat(f"Matriz competitiva para: {competitors}. Compara: precio, calidad, servicio, mercado, fortalezas, debilidades, diferenciacion.", provider_id="deepseek", system_prompt="Competitive analyst. Matriz en espanol.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_swot_analysis_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        business = str(arguments.get("business") or "").strip()
        if not business:
            return ToolResult(ok=False, output="", error="Falta negocio/proyecto.")
        result = route_chat(f"Analisis FODA para: {business}. 5+ items por cuadrante. Estrategias FO, DO, FA, DA. Plan de accion.", provider_id="deepseek", system_prompt="SWOT analyst. Estructurado y accionable.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_pricing_strategy_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        product = str(arguments.get("product") or "").strip()
        cost = float(arguments.get("cost") or 0)
        if not product or cost <= 0:
            return ToolResult(ok=False, output="", error="Falta producto y costo.")
        result = route_chat(f"Estrategia de precio para {product}, costo ${cost:.2f}. 3 opciones: penetracion, premium, paquete. Precio sugerido, margen, proyeccion de ingresos.", provider_id="deepseek", system_prompt="Pricing strategist. Datos concretos.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_customer_persona_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        business = str(arguments.get("business") or "").strip()
        if not business:
            return ToolResult(ok=False, output="", error="Falta descripcion del negocio.")
        result = route_chat(f"Genera 3 buyer personas detalladas para {business}. Demografia, dolores, objetivos, objeciones, canales, mensaje clave.", provider_id="deepseek", system_prompt="Buyer persona creator. Detallado y util.")
        return ToolResult(ok=True, output=result.strip()[:1200])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def biz_supplier_finder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        product = str(arguments.get("product") or "").strip()
        if not product:
            return ToolResult(ok=False, output="", error="Falta producto a buscar proveedores.")
        result = route_chat(f"Encuentra 5 proveedores mayoristas de {product}. Compara precio minimo, cantidad minima, tiempo de entrega, ubicacion. Sugiere como contactarlos.", provider_id="deepseek", system_prompt="Procurement specialist. Informacion practica.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ⚠️ MÓDULO 100% FAKE — tools solo generan texto con LLM, no ejecutan acciones reales. Deshabilitado hasta migrar a APIs reales.
TOOLS = [
    # ("biz_business_plan", biz_business_plan_handler),
    # ("biz_market_research", biz_market_research_handler),
    # ("biz_pitch_deck", biz_pitch_deck_handler),
    # ("biz_competitor_matrix", biz_competitor_matrix_handler),
    # ("biz_swot_analysis", biz_swot_analysis_handler),
    # ("biz_pricing_strategy", biz_pricing_strategy_handler),
    # ("biz_customer_persona", biz_customer_persona_handler),
    # ("biz_supplier_finder", biz_supplier_finder_handler),
]
