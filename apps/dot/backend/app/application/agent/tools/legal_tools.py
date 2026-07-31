"""Tools legales y de tramites — P1."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.legal")


def legal_contract_generator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        tipo = str(arguments.get("type") or "alquiler").strip()
        partes = str(arguments.get("parties") or "").strip()
        terms = str(arguments.get("terms") or "").strip()
        result = route_chat(f"Genera contrato de {tipo}. Partes: {partes}. Terminos clave: {terms}. Incluye clausulas estandar de Venezuela. Usa lenguaje legal claro.", provider_id="deepseek", system_prompt="Abogado generando contrato en espanol. Profesional, claro, con clausulas estandar. Incluye disclaimer: NO es asesoria legal, revisar con abogado.")
        return ToolResult(ok=True, output=result.strip()[:2000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def legal_nd_generator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        partes = str(arguments.get("parties") or "").strip()
        result = route_chat(f"Genera acuerdo de confidencialidad (NDA). Partes: {partes}. Incluye duracion, alcance, penalizacion.", provider_id="deepseek", system_prompt="NDA en espanol. Profesional. Incluye disclaimer.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def legal_document_translator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        from app.services.provider_router import route_chat
        path = str(arguments.get("path") or "").strip()
        to_lang = str(arguments.get("to") or "ingles").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path del documento.")
        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error: {raw.get('error')}")
        text = str(raw.get("content", ""))[:3000]
        result = route_chat(f"Traduce este documento a {to_lang} manteniendo formato y tono:\n\n{text}", provider_id="deepseek", system_prompt=f"Traduccion profesional a {to_lang}.")
        return ToolResult(ok=True, output=result.strip()[:3000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def legal_rent_receipt_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        arrendador = str(arguments.get("landlord") or "").strip()
        inquilino = str(arguments.get("tenant") or "").strip()
        monto = str(arguments.get("amount") or "").strip()
        mes = str(arguments.get("month") or "").strip()
        if not arrendador or not inquilino or not monto:
            return ToolResult(ok=False, output="", error="Falta landlord, tenant y amount.")
        from datetime import datetime
        receipt = f"RECIBO DE ALQUILER\n{'='*40}\nFecha: {datetime.now().strftime('%d/%m/%Y')}\nArrendador: {arrendador}\nInquilino: {inquilino}\nMes: {mes or datetime.now().strftime('%B %Y')}\nMonto: {monto}\nConcepto: Alquiler mensual\n{'='*40}\nFirma arrendador: ____________"
        return ToolResult(ok=True, output=receipt)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def legal_demand_letter_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        situation = str(arguments.get("situation") or "").strip()
        recipient = str(arguments.get("recipient") or "").strip()
        if not situation:
            return ToolResult(ok=False, output="", error="Falta situacion.")
        result = route_chat(f"Redacta carta de reclamo formal para {recipient}. Situacion: {situation}. Tono firme pero profesional. Incluye plazo de respuesta.", provider_id="deepseek", system_prompt="Carta legal en espanol. Profesional. Incluye disclaimer.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def legal_gov_appointment_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        tramite = str(arguments.get("tramite") or "pasaporte").strip()
        from app.services.provider_router import route_chat
        result = route_chat(f"Pasos para solicitar cita de {tramite} en Venezuela (SAIME u organismo correspondiente). Requisitos, costo, tiempo estimado.", provider_id="deepseek", system_prompt="Guia de tramites Venezuela. Practico, actualizado si es posible.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("legal_contract_generator", legal_contract_generator_handler),
    ("legal_nd_generator", legal_nd_generator_handler),
    ("legal_document_translator", legal_document_translator_handler),
    ("legal_rent_receipt", legal_rent_receipt_handler),
    ("legal_demand_letter", legal_demand_letter_handler),
    ("legal_gov_appointment", legal_gov_appointment_handler),
]
