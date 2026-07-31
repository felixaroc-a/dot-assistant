"""Tools profundas de Gmail — F6a."""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.gmail_deep")


def gmail_read_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee un correo completo por ID (cuerpo HTML convertido a texto)."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("id") or "").strip()
        if not msg_id:
            return ToolResult(ok=False, output="", error="Falta message_id del correo a leer.")

        result = gmail_service.read_message(uid, msg_id)
        return ToolResult(ok=True, output=str(result)[:5000] if result else "Correo no encontrado.")
    except Exception as e:
        log.warning("gmail_read_message error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def gmail_get_attachments_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Descarga adjuntos de un correo al Escritorio."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("id") or "").strip()
        if not msg_id:
            return ToolResult(ok=False, output="", error="Falta message_id del correo.")

        folder = str(arguments.get("folder") or "~/Desktop/DOT Trabajos/Gmail")
        saved = gmail_service.download_attachments(uid, msg_id, download_dir=folder)
        if not saved:
            return ToolResult(ok=True, output="Este correo no tiene adjuntos para descargar.")
        lines = [f"Guardé {len(saved)} adjunto(s):"]
        lines.extend(f"- {path}" for path in saved)
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("gmail_get_attachments error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def gmail_get_thread_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene hilo completo de conversacion por ID de hilo."""
    try:
        from app.services import gmail_service

        thread_id = str(arguments.get("thread_id") or arguments.get("id") or "").strip()
        if not thread_id:
            return ToolResult(ok=False, output="", error="Falta thread_id.")

        messages = gmail_service.get_thread(uid, thread_id)
        if not messages:
            return ToolResult(ok=True, output="Hilo vacio o no encontrado.")

        lines = [f"Hilo ({len(messages)} mensajes):"]
        for m in messages:
            lines.append(
                f"- {m.get('from','?')}: {m.get('subject','')} | {m.get('snippet','')[:120]}"
            )
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("gmail_get_thread error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def gmail_extract_contacts_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Extrae emails de remitentes recientes del usuario."""
    try:
        from collections import Counter
        from app.services import gmail_service

        messages = gmail_service.list_messages(uid, max_results=50)
        if not messages:
            return ToolResult(ok=True, output="No se encontraron correos recientes.")

        counter: Counter[str] = Counter()
        for m in messages:
            sender = m.get("from", "")
            if "@" in sender:
                counter[sender.split("<")[-1].rstrip(">") if "<" in sender else sender] += 1

        lines = ["Remitentes frecuentes de Gmail:"]
        for email, count in counter.most_common(20):
            lines.append(f"- {email}: {count} correos")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("gmail_extract_contacts error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def gmail_mark_read_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Marca un correo como leido."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("id") or "").strip()
        if not msg_id:
            return ToolResult(ok=False, output="", error="Falta message_id.")

        gmail_service.mark_read(uid, msg_id)
        return ToolResult(ok=True, output="Correo marcado como leido.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_archive_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Archiva un correo."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("id") or "").strip()
        if not msg_id:
            return ToolResult(ok=False, output="", error="Falta message_id.")

        gmail_service.archive(uid, msg_id)
        return ToolResult(ok=True, output="Correo archivado.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_trash_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Mueve un correo a la papelera."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("id") or "").strip()
        if not msg_id:
            return ToolResult(ok=False, output="", error="Falta message_id.")

        gmail_service.trash(uid, msg_id)
        return ToolResult(ok=True, output="Correo movido a papelera.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_auto_reply_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Responde automaticamente un correo con texto personalizado."""
    try:
        from app.services import gmail_service

        msg_id = str(arguments.get("message_id") or arguments.get("in_reply_to") or "").strip()
        body = str(arguments.get("body") or arguments.get("text") or "").strip()
        if not msg_id or not body:
            return ToolResult(ok=False, output="", error="Falta message_id y body.")

        attachments = arguments.get("attachments")
        att_list = attachments if isinstance(attachments, list) and attachments else None
        gmail_service.reply(uid, msg_id, body, attachments=att_list)
        if att_list:
            return ToolResult(
                ok=True,
                output=f"Respuesta enviada con {len(att_list)} adjunto(s).",
            )
        return ToolResult(ok=True, output="Respuesta enviada.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))

TOOLS = [("gmail_read_message", gmail_read_message_handler), ("gmail_get_attachments", gmail_get_attachments_handler), ("gmail_get_thread", gmail_get_thread_handler), ("gmail_extract_contacts", gmail_extract_contacts_handler), ("gmail_mark_read", gmail_mark_read_handler), ("gmail_archive", gmail_archive_handler), ("gmail_trash", gmail_trash_handler), ("gmail_auto_reply", gmail_auto_reply_handler)]

TOOL_SCHEMAS: dict[str, dict] = {
    "gmail_read_message": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "ID del correo (sale de gmail_search o gmail_list_unread)."},
        },
        "required": ["message_id"],
    },
    "gmail_get_attachments": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "ID del correo con adjuntos."},
            "folder": {
                "type": "string",
                "description": "Carpeta destino en el PC (default ~/Desktop/DOT Trabajos/Gmail). Usa ~/Desktop para el Escritorio.",
            },
        },
        "required": ["message_id"],
    },
    "gmail_get_thread": {
        "type": "object",
        "properties": {"thread_id": {"type": "string"}},
        "required": ["thread_id"],
    },
    "gmail_extract_contacts": {"type": "object", "properties": {}},
    "gmail_mark_read": {
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    "gmail_archive": {
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    "gmail_trash": {
        "type": "object",
        "properties": {"message_id": {"type": "string"}},
        "required": ["message_id"],
    },
    "gmail_auto_reply": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string"},
            "body": {"type": "string", "description": "Texto de la respuesta."},
            "attachments": {
                "type": "array",
                "description": "Adjuntos opcionales: [{filename, path}] con path sandbox (~Desktop/archivo.pdf).",
                "items": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "path": {"type": "string"},
                    },
                },
            },
        },
        "required": ["message_id", "body"],
    },
}
