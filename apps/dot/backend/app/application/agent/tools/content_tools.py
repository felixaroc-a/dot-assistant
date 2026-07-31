"""Tools de comunicacion avanzada y newsletters — F6."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.comm")


def comm_email_campaign_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        subject = str(arguments.get("subject") or "Oferta especial").strip()
        audience = str(arguments.get("audience") or "").strip()
        goal = str(arguments.get("goal") or "conversion").strip()
        result = route_chat(
            f"Genera copy para campana de email. Asunto: {subject}. Audiencia: {audience}. Objetivo: {goal}. Incluye subject line alternativo, cuerpo y CTA.",
            provider_id="deepseek",
            system_prompt="Copywriter profesional. Email en espanol, persuasivo, con CTA claro."
        )
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_newsletter_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "Actualizacion mensual").strip()
        sections = int(arguments.get("sections") or 3)
        result = route_chat(
            f"Genera newsletter sobre {topic} con {sections} secciones. Incluye titular, introduccion, secciones con subtitulos y cierre con CTA.",
            provider_id="deepseek",
            system_prompt="Newsletter profesional en espanol. Estructura: titulo, intro, secciones, CTA."
        )
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_signature_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        name = str(arguments.get("name") or "").strip()
        title = str(arguments.get("title") or "").strip()
        company = str(arguments.get("company") or "").strip()
        phone = str(arguments.get("phone") or "").strip()
        email = str(arguments.get("email") or "").strip()
        result = route_chat(
            f"Genera firma de email profesional para: {name}, {title}, {company}. Telefono: {phone}, Email: {email}. Solo texto, sin HTML.",
            provider_id="deepseek",
            system_prompt="Firma de email profesional. Solo texto, elegante, en espanol."
        )
        return ToolResult(ok=True, output=result.strip()[:400])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def comm_auto_responder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        message = str(arguments.get("message") or "Estoy fuera de la oficina. Respondere a la brevedad.").strip()
        active_str = str(arguments.get("active") or "true").strip().lower()
        active = active_str in ("true", "1", "si", "yes")

        config = {
            "message": message,
            "active": active,
            "updated_at": __import__("datetime").datetime.now().isoformat(),
        }
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        import json
        path = str(Path("~/Desktop/DOT Trabajos/auto_reply_config.json").expanduser())
        execute_local_tool_via_bridge("writeFile", path=path, content=json.dumps(config, indent=2))
        status = "activado" if active else "desactivado"
        return ToolResult(ok=True, output=f"Auto-respondedor {status}: {message[:100]}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def content_blog_outline_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        if not topic:
            return ToolResult(ok=False, output="", error="Falta topic del articulo.")
        result = route_chat(
            f"Genera esquema de articulo de blog sobre: {topic}. Incluye titulo SEO, subtitulos (H2), bullet points por seccion y meta description.",
            provider_id="deepseek",
            system_prompt="Esquema de blog en espanol. SEO-friendly, estructurado."
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def content_generate_ideas_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "marketing digital").strip()
        count = min(int(arguments.get("count") or 10), 20)
        result = route_chat(
            f"Genera {count} ideas de contenido creativas sobre: {topic}. Una idea por linea, breves y accionables.",
            provider_id="deepseek",
            system_prompt="Ideas de contenido creativas en espanol. 1 linea por idea."
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def content_extract_keywords_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta texto.")
        result = route_chat(
            f"Extrae las 10 keywords SEO mas relevantes de este texto. Una por linea:\n\n{text[:2000]}",
            provider_id="deepseek",
            system_prompt="Keywords SEO en espanol. Solo lista, 1 por linea."
        )
        return ToolResult(ok=True, output=result.strip()[:400])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def content_script_video_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        duration = int(arguments.get("seconds") or 60)
        platform = str(arguments.get("platform") or "TikTok").strip()
        if not topic:
            return ToolResult(ok=False, output="", error="Falta topic.")
        result = route_chat(
            f"Guion para video de {platform} de ~{duration}s sobre: {topic}. Incluye hook (3s), desarrollo y CTA.",
            provider_id="deepseek",
            system_prompt=f"Guion para {platform} en espanol. Con hook inicial fuerte y CTA."
        )
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def content_translate_localize_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        text = str(arguments.get("text") or "").strip()
        to = str(arguments.get("to") or "es").strip()
        region = str(arguments.get("region") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta texto.")
        prompt = f"Traduce y adapta culturalmente este texto a {to}"
        if region: prompt += f" ({region})"
        result = route_chat(f"{prompt}:\n\n{text[:2000]}", provider_id="deepseek", system_prompt=f"Traduccion + localizacion a {to}. Solo el texto traducido.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("comm_email_campaign", comm_email_campaign_handler),
    ("comm_create_newsletter", comm_newsletter_handler),
    ("comm_create_signature", comm_signature_handler),
    ("comm_auto_responder", comm_auto_responder_handler),
    ("content_blog_outline", content_blog_outline_handler),
    ("content_generate_ideas", content_generate_ideas_handler),
    ("content_extract_keywords", content_extract_keywords_handler),
    ("content_script_video", content_script_video_handler),
    ("content_translate_localize", content_translate_localize_handler),
]
