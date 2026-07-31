"""Factory del ToolRegistry canonico — DOT Agent Runtime.

~177 tools (32 route_chat fakes purgadas en FASE 1.2).
Registro automatico via TOOLS export.
"""

from __future__ import annotations

import importlib
import logging

from app.application.agent.ports import ToolSpec
from app.application.agent.registry import ToolRegistry

log = logging.getLogger("dot.agent.registry")


_MODULES = [
    # F3.1: sandbox de ejecución de código Python (Docker + subprocess fallback)
    "app.application.agent.tools.code_execution",
    "app.application.agent.tools.calendar",
    "app.application.agent.tools.gmail_read",
    "app.application.agent.tools.schedule_reminder",
    "app.application.agent.tools.cron_tools",
    "app.application.agent.tools.automation_tools",
    "app.application.agent.tools.whatsapp_tools",
    "app.application.agent.tools.gmail_deep",
    "app.application.agent.tools.calendar_advanced",
    "app.application.agent.tools.file_advanced",
    "app.application.agent.tools.web_tools",
    "app.application.agent.tools.data_tools",
    "app.application.agent.tools.system_tools",
    "app.application.agent.tools.document_tools",
    "app.application.agent.tools.extra_tools",
    "app.application.agent.tools.business_tools",
    "app.application.agent.tools.life_tools",
    "app.application.agent.tools.crm_tools",
    "app.application.agent.tools.entertainment_tools",
    "app.application.agent.tools.auto_meta_tools",
    "app.application.agent.tools.productivity_tools",
    "app.application.agent.tools.content_tools",
    "app.application.agent.tools.monitor_tools",
    # "app.application.agent.tools.education_tools",     # PASO 6: 100% fake, eliminado del registry
    "app.application.agent.tools.legal_tools",
    "app.application.agent.tools.travel_tools",
    "app.application.agent.tools.home_tools",
    "app.application.agent.tools.misc_tools",
    "app.application.agent.tools.vehicle_tools",
    "app.application.agent.tools.gaps_tools",
    "app.application.agent.tools.browser_tools",
    # M2S2-B: Twitter/X API v2 — tools sociales reales
    "app.application.agent.tools.twitter_tools",
    # M2S3-A: MercadoLibre API — 5 tools de e-commerce
    "app.application.agent.tools.mercadolibre_tools",
    # M2S3-B: Google Drive API — 5 tools de almacenamiento cloud
    "app.application.agent.tools.gdrive_tools",
    # M3S2-A: 10 scrapers CDP reales — vuelos, hoteles, Amazon, LinkedIn, noticias, clima, crypto, dólar, recetas, reseñas
    "app.application.agent.tools.scraper_tools",
    # M3S2-B: Slack API — 5 tools de mensajería empresarial
    "app.application.agent.tools.slack_tools",
    # M3S3-A: Notion API — 5 tools de productividad y bases de conocimiento
    "app.application.agent.tools.notion_tools",
    # M3S3-B: Telegram Bot API — 5 tools de mensajería social
    "app.application.agent.tools.telegram_tools",
    # M6S4-A: Discord API — 3 tools de mensajería social/community
    "app.application.agent.tools.discord_tools",
    # M6S4-A: GitHub API — 3 tools de desarrollo (search, user info, issues)
    "app.application.agent.tools.github_tools",
    # M6S5-A: Signal Bridge — 3 tools de mensajería cifrada
    "app.application.agent.tools.signal_tools",
    # M6S5-B: LINE Messaging — 2 tools de mensajería asiática
    "app.application.agent.tools.line_tools",
    # M6S5-C: Microsoft Teams — 2 tools de mensajería empresarial
    "app.application.agent.tools.teams_tools",
    # M7S2-A: Microsoft 365 / Outlook — 7 tools de correo, calendario y contactos
    "app.application.agent.tools.outlook_tools",
    # M1S3-B: APIs reales — registrado al final para sobrescribir handlers fake
    "app.application.agent.tools.real_apis",
]


def build_default_registry(*, include_web_search: bool = True) -> ToolRegistry:
    """Registra todas las tools. 83+ manos para cubrir 95% de casos."""
    reg = ToolRegistry()

    # ─── Tools legacy / fase 1 ──────────────────────────
    _register_core(reg, include_web_search)

    # ─── Tools nuevas via TOOLS export ──────────────────
    for module_name in _MODULES:
        try:
            mod = importlib.import_module(module_name)
            tools = getattr(mod, "TOOLS", [])
            schemas = getattr(mod, "TOOL_SCHEMAS", {})
            tool_specs = getattr(mod, "TOOL_SPECS", {})
            for tool_name, handler in tools:
                spec_meta = tool_specs.get(tool_name, {})
                spec = ToolSpec(
                    name=tool_name,
                    description=(
                        spec_meta.get("description")
                        or getattr(handler, "__doc__", "")
                        or tool_name.replace("_", " ").title()
                    ),
                    parameters_schema=schemas.get(
                        tool_name,
                        spec_meta.get("parameters_schema")
                        or {"type": "object", "properties": {}},
                    ),
                )
                reg.register(spec, handler)
            if tools:
                log.debug("Registered %d tools from %s", len(tools), module_name.split(".")[-1])
        except Exception as e:
            log.warning("Could not load tools from %s: %s", module_name, e)

    # PL06: fallback mappings — tool alternatives for automatic recovery on failure
    reg.set_fallback("web_search", "web_fetch_page")
    reg.set_fallback("browser_navigate", "web_fetch_page")
    reg.set_fallback("calendar_list_today", "web_search")

    return reg


def _register_core(reg: ToolRegistry, include_web_search: bool) -> None:
    """Tools core: gmail_send, archivos, download, wa_send, web_search."""
    from app.application.agent.tools.gmail_send import gmail_send_handler
    from app.application.agent.tools.local_files import (
        download_url_to_desktop_handler,
        make_local_file_handler,
    )
    from app.application.agent.tools.wa_send import send_whatsapp_message_handler
    from app.application.agent.tools.wa_campaign import send_whatsapp_campaign_handler
    from app.application.agent.tools.web_search import web_search_handler
    from app.application.agent.tools.file_search import file_search_handler
    from app.application.agent.tools.generate_document import generate_document_handler
    from app.application.agent.tools.generate_spreadsheet import generate_spreadsheet_handler
    from app.application.agent.tools.read_document import read_document_handler
    from app.application.agent.tools.read_spreadsheet import read_spreadsheet_handler
    from app.application.agent.tools.cv_tools import analyze_cv_handler
    from app.application.agent.tools.pptx_tools import pptx_read_handler, pptx_generate_handler
    from app.application.agent.tools.image_tools import generate_image_handler
    from app.application.agent.tools.text_tools import summarize_handler, translate_handler

    reg.register(
        ToolSpec(
            name="gmail_send",
            description="Envia un correo con Gmail del usuario (OAuth vinculado). Requiere confirm:true tras confirmación del usuario.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "body_html": {"type": "string", "description": "Cuerpo HTML opcional."},
                    "confirm": {
                        "type": "boolean",
                        "description": "true solo tras confirmación explícita del usuario.",
                    },
                    "attachments": {
                        "type": "array",
                        "description": "Adjuntos opcionales (filename + content_base64 o path sandbox).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_base64": {"type": "string"},
                                "path": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["to", "body"],
            },
        ),
        gmail_send_handler,
    )

    _confirm_prop = {
        "confirm": {
            "type": "boolean",
            "description": "true solo tras confirmación explícita del usuario en chat.",
        }
    }

    for op, desc in (
        ("readFile", "Lee un archivo de texto. Rutas absolutas o ~/Desktop, ~/Documents, ~/Downloads, DOT."),
        ("writeFile", "Escribe un archivo de texto (path + content). Pide confirmación si sobrescribe."),
        ("listFiles", "Lista archivos en una carpeta."),
        ("deleteFile", "Elimina un archivo (no directorios). Requiere confirm:true tras confirmación del usuario."),
    ):
        schema: dict = {"type": "object", "properties": {"path": {"type": "string"}, **_confirm_prop}}
        if op == "writeFile":
            schema["properties"]["content"] = {"type": "string"}
            schema["properties"]["overwrite"] = {
                "type": "boolean",
                "description": "true si reemplazas un archivo existente.",
            }
            schema["required"] = ["path", "content"]
        elif op != "listFiles":
            schema["required"] = ["path"]
        if op == "readFile":
            schema["properties"].pop("confirm", None)
        if op == "listFiles":
            schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        reg.register(ToolSpec(name=op, description=desc, parameters_schema=schema), make_local_file_handler(op))

    reg.register(
        ToolSpec(name="download_url_to_desktop", description="Descarga un archivo desde URL http/https al Escritorio.", parameters_schema={"type": "object", "properties": {"url": {"type": "string"}, "path": {"type": "string"}}, "required": ["url"]}),
        download_url_to_desktop_handler,
    )

    reg.register(
        ToolSpec(name="send_whatsapp_message", description="Envia un mensaje de WhatsApp. Requiere confirm:true tras confirmación del usuario.", parameters_schema={"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}, "confirm": {"type": "boolean"}}, "required": ["to", "text"]}),
        send_whatsapp_message_handler,
    )

    reg.register(
        ToolSpec(name="send_whatsapp_campaign", description="Registra campana de WhatsApp para envio masivo. Requiere confirm:true.", parameters_schema={"type": "object", "properties": {"contacts": {"type": "array", "items": {"type": "string"}}, "template": {"type": "string"}, "names": {"type": "array", "items": {"type": "string"}}, "auto_id": {"type": "string"}, "confirm": {"type": "boolean"}}, "required": ["contacts", "template", "auto_id"]}),
        send_whatsapp_campaign_handler,
    )

    if include_web_search:
        reg.register(ToolSpec(name="web_search", description="Busca informacion actualizada en internet.", parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}), web_search_handler)

    reg.register(ToolSpec(name="file_search", description="Busca archivos en el PC por nombre o patron.", parameters_schema={"type": "object", "properties": {"query": {"type": "string"}, "contentPattern": {"type": "string"}, "searchRoot": {"type": "string"}}, "required": ["query"]}), file_search_handler)
    reg.register(ToolSpec(name="generate_document", description="Genera documento DOCX con texto e imagenes.", parameters_schema={"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}, "image_paths": {"type": "array", "items": {"type": "string"}}, "folder": {"type": "string"}}, "required": ["title", "content"]}), generate_document_handler)
    reg.register(ToolSpec(name="generate_spreadsheet", description="Genera hoja de calculo XLSX con datos y graficos.", parameters_schema={"type": "object", "properties": {"title": {"type": "string"}, "data_sections": {"type": "array"}}, "required": ["title", "data_sections"]}), generate_spreadsheet_handler)
    reg.register(ToolSpec(name="read_document", description="Lee PDF, DOCX o TXT en el PC del usuario.", parameters_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}), read_document_handler)
    reg.register(
        ToolSpec(
            name="read_spreadsheet",
            description=(
                "Lee y analiza Excel (.xlsx/.xls) del PC: hojas, columnas, muestra de filas "
                "y estadísticas básicas. Usar cuando pidan analizar/revisar un Excel."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta al Excel, p. ej. ~/Desktop/ventas.xlsx"},
                    "sheet": {"type": "string", "description": "Nombre de hoja opcional (si omites, resume todas)."},
                    "sample_rows": {"type": "integer", "description": "Filas de muestra por hoja (default 5)."},
                    "export_csv": {
                        "type": "boolean",
                        "description": "Si true, exporta CSV para encadenar con data_summary_stats u otras data_*.",
                    },
                },
                "required": ["path"],
            },
        ),
        read_spreadsheet_handler,
    )
    reg.register(
        ToolSpec(
            name="translate",
            description=(
                "Traduce texto al idioma indicado. Usa con texto pegado o tras read_document. "
                "También acepta path para leer PDF/DOCX/TXT antes de traducir."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto a traducir (o salida de read_document)."},
                    "target_lang": {
                        "type": "string",
                        "description": "Idioma destino: inglés, en, francés, portugués, etc.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta opcional ~/Desktop/archivo.pdf si no pasas text.",
                    },
                },
                "required": ["target_lang"],
            },
        ),
        translate_handler,
    )
    reg.register(
        ToolSpec(
            name="summarize",
            description=(
                "Resume texto, URL o documento local. Usa tras read_document o con texto pegado. "
                "Style opcional: breve, ejecutivo, bullets, academico."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto a resumir (idealmente de read_document)."},
                    "path": {
                        "type": "string",
                        "description": "Ruta opcional ~/Desktop/archivo.pdf si no pasas text.",
                    },
                    "style": {
                        "type": "string",
                        "description": "Estilo: breve (default), ejecutivo, bullets, academico.",
                    },
                },
            },
        ),
        summarize_handler,
    )
    reg.register(
        ToolSpec(
            name="analyze_cv",
            description=(
                "Analiza un CV (PDF/DOCX/TXT) del PC: nombre, contacto, habilidades, "
                "experiencia y formación. Usar antes de responder preguntas sobre currículums."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta al CV, p. ej. ~/Desktop/mi_cv.pdf"},
                    "question": {"type": "string", "description": "Pregunta opcional sobre el CV."},
                },
                "required": ["path"],
            },
        ),
        analyze_cv_handler,
    )
    reg.register(ToolSpec(name="pptx_read", description="Lee una presentacion PowerPoint .pptx y extrae slides.", parameters_schema={"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}), pptx_read_handler)
    reg.register(ToolSpec(name="pptx_generate", description="Genera presentacion PowerPoint .pptx con texto, imagenes y graficos.", parameters_schema={"type": "object", "properties": {"title": {"type": "string"}, "slides_json": {"type": "string"}, "template": {"type": "string"}, "folder": {"type": "string"}}, "required": ["title", "slides_json"]}), pptx_generate_handler)
    reg.register(
        ToolSpec(
            name="generate_image",
            description="Genera una imagen desde una descripcion de texto (Vertex Imagen).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Descripcion de la imagen a generar."},
                    "count": {"type": "integer", "description": "Numero de imagenes (1-4)."},
                    "aspect_ratio": {"type": "string", "description": "Relacion de aspecto, ej. 1:1 o 16:9."},
                    "resolution": {"type": "string", "description": "Resolucion, ej. 1024x1024."},
                },
                "required": ["prompt"],
            },
        ),
        generate_image_handler,
    )
