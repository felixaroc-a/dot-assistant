"""Tools avanzadas de WhatsApp para Agent Runtime — F5 Ojos."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.whatsapp")


# ─── Lectura de mensajes ────────────────────────────────

def whatsapp_read_recent_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee los ultimos N mensajes de WhatsApp del usuario."""
    try:
        from app.application.whatsapp.inbound_service import get_message_store

        limit = min(int(arguments.get("limit") or arguments.get("max_results") or 10), 50)
        phone = str(arguments.get("phone") or arguments.get("from_phone") or "").strip() or None

        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=limit)

        if not messages:
            return ToolResult(ok=True, output="No hay mensajes recientes de WhatsApp.")

        lines = []
        for m in messages:
            direction = "→" if m.direction == "outbound" else "←"
            ts = m.timestamp or ""
            text_preview = (m.text or "")[:200]
            lines.append(
                f"{direction} [{ts[:19]}] {m.from_phone[-10:]}: {text_preview}"
            )

        return ToolResult(
            ok=True,
            output=f"Ultimos {len(messages)} mensajes WhatsApp:\n" + "\n".join(lines),
        )
    except Exception as e:
        log.warning("whatsapp_read_recent error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def whatsapp_get_thread_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene toda la conversacion con un contacto especifico."""
    try:
        from app.application.whatsapp.inbound_service import get_message_store

        phone = str(arguments.get("phone") or arguments.get("contact") or "").strip()
        if not phone:
            return ToolResult(ok=False, output="", error="Falta el numero de telefono del contacto (phone).")

        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=100)

        if not messages:
            return ToolResult(ok=True, output=f"No se encontraron mensajes con {phone}.")

        lines = [f"Conversacion con {phone} ({len(messages)} mensajes):"]
        for m in reversed(messages):
            direction = "Tú" if m.direction == "outbound" else phone[-10:]
            lines.append(f"[{m.timestamp[:19]}] {direction}: {m.text[:300]}")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("whatsapp_get_thread error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def whatsapp_search_messages_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca mensajes de WhatsApp que contengan una palabra clave."""
    try:
        from app.application.whatsapp.inbound_service import get_message_store

        query = str(arguments.get("query") or arguments.get("keyword") or "").strip().lower()
        if not query:
            return ToolResult(ok=False, output="", error="Falta la palabra clave a buscar (query).")

        limit = min(int(arguments.get("limit") or 30), 100)
        store = get_message_store()
        messages = store.list_for_uid(uid, limit=100)

        matches = [
            m for m in messages[:100]
            if query in (m.text or "").lower()
        ][:limit]

        if not matches:
            return ToolResult(ok=True, output=f"No se encontraron mensajes con '{query}'.")

        lines = [f"Mensajes con '{query}' ({len(matches)}):"]
        for m in matches:
            ctx = (m.text or "")[:200].replace("\n", " ")
            lines.append(f"[{m.timestamp[:19]}] {m.from_phone[-10:]}: {ctx}")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("whatsapp_search_messages error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── Análisis de mensajes ──────────────────────────────

def whatsapp_detect_intent_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Clasifica la intencion de un mensaje de WhatsApp usando IA."""
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or arguments.get("message") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta el texto del mensaje a analizar.")

        result = route_chat(
            f"Clasifica la intencion de este mensaje en UNA sola palabra o frase corta. "
            f"Ejemplos: confirmar_cita, consultar_precio, queja, comprar, saludar, "
            f"pedir_info, negociar, despedirse, urgente, spam.\n\n"
            f"Mensaje: {text[:500]}",
            provider_id="deepseek",
            system_prompt=(
                "Eres un clasificador de intenciones. Responde SOLO con la categoria, "
                "sin explicacion, sin puntuacion extra. Maximo 3 palabras."
            ),
        )
        intent = result.strip().replace("\n", " ")[:80]
        return ToolResult(ok=True, output=intent)
    except Exception as e:
        log.warning("whatsapp_detect_intent error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def whatsapp_extract_entities_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae entidades (nombre, fecha, monto, telefono, direccion) de un mensaje."""
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or arguments.get("message") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta el texto a analizar.")

        result = route_chat(
            f"Extrae entidades de este mensaje en JSON. Campos detectados: "
            f"nombre, fecha, hora, monto, moneda, telefono, direccion, email, "
            f"producto, cantidad. Solo incluye los que APAREZCAN en el texto.\n\n"
            f"Mensaje: {text[:800]}",
            provider_id="deepseek",
            system_prompt=(
                "Eres un extractor de entidades. Responde SOLO con JSON valido, "
                "sin markdown, sin explicacion. Campos detectados en minuscula. "
                "Si no detectas nada, responde {}."
            ),
        )
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        log.warning("whatsapp_extract_entities error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def whatsapp_summarize_thread_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un resumen de una conversacion de WhatsApp."""
    try:
        from app.application.whatsapp.inbound_service import get_message_store
        from app.services.provider_router import route_chat

        phone = str(arguments.get("phone") or arguments.get("contact") or "").strip()
        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=50) if phone else store.list_for_uid(uid, limit=30)

        if not messages:
            return ToolResult(ok=True, output="No hay mensajes para resumir.")

        thread_text = "\n".join(
            f"[{m.timestamp[:19]}] {m.from_phone[-10:]}: {m.text[:300]}"
            for m in reversed(messages)
        )

        summary = route_chat(
            f"Resume esta conversacion de WhatsApp en 2-3 frases. "
            f"Incluye: tema principal, decisiones tomadas, pendientes.\n\n{thread_text[:4000]}",
            provider_id="deepseek",
            system_prompt="Resume conversaciones en espanol, 2-3 frases, estilo ejecutivo.",
        )
        return ToolResult(ok=True, output=summary.strip()[:500])
    except Exception as e:
        log.warning("whatsapp_summarize_thread error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── Contactos ─────────────────────────────────────────

def whatsapp_list_contacts_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    """Lista contactos frecuentes de WhatsApp con conteo de mensajes."""
    try:
        from collections import Counter
        from app.application.whatsapp.inbound_service import get_message_store

        store = get_message_store()
        messages = store.list_for_uid(uid, limit=200)

        if not messages:
            return ToolResult(ok=True, output="No hay contactos de WhatsApp registrados aun.")

        counter: Counter[str] = Counter()
        last_msg: dict[str, str] = {}
        for m in messages:
            phone = m.from_phone[-10:] or m.to_phone[-10:] or "desconocido"
            counter[phone] += 1
            if phone not in last_msg:
                last_msg[phone] = (m.text or "")[:80]

        lines = ["Contactos frecuentes de WhatsApp:"]
        for phone, count in counter.most_common(15):
            preview = last_msg.get(phone, "")[:50]
            lines.append(f"- {phone}: {count} mensajes | Ult: {preview}")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("whatsapp_list_contacts error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── Envío avanzado ───────────────────────────────────

def send_whatsapp_image_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envia una imagen por WhatsApp."""
    try:
        to_raw = str(arguments.get("to") or arguments.get("phone") or "").strip()
        path = str(arguments.get("path") or arguments.get("file") or "").strip()
        caption = str(arguments.get("caption") or "").strip()

        if not to_raw:
            return ToolResult(ok=False, output="", error="Falta destinatario (to/phone).")
        if not path:
            return ToolResult(ok=False, output="", error="Falta ruta de la imagen (path/file).")

        from app.services.whatsapp_client import send_whatsapp_media

        ok, err = asyncio.run(
            send_whatsapp_media(to_raw, path, media_type="image", caption=caption)
        )
        if ok:
            return ToolResult(ok=True, output=f"Imagen enviada a {to_raw}.")
        return ToolResult(ok=False, output="", error=f"No se pudo enviar la imagen: {err}")
    except Exception as e:
        log.warning("send_whatsapp_image error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def send_whatsapp_document_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envia un documento (PDF, DOCX, etc.) por WhatsApp."""
    try:
        to_raw = str(arguments.get("to") or arguments.get("phone") or "").strip()
        path = str(arguments.get("path") or arguments.get("file") or "").strip()
        caption = str(arguments.get("caption") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="Falta ruta del documento.")

        from app.services.document_output_service import (
            format_path_for_user,
            resolve_document_path_for_send,
        )

        resolved = resolve_document_path_for_send(path)
        if resolved is None:
            return ToolResult(
                ok=False,
                output="",
                error=f"No encuentro el archivo en: {path}",
            )
        path = str(resolved)

        if not to_raw:
            from app.services.whatsapp_link import get_channel_state

            state = get_channel_state(uid)
            if not state.linked or not state.phone_number:
                return ToolResult(
                    ok=False,
                    output="",
                    error="WhatsApp no vinculado. Vinculá tu número en Configuración → WhatsApp.",
                )
            to_raw = state.phone_number

        from app.services.whatsapp_client import send_whatsapp_media

        ok, err = asyncio.run(
            send_whatsapp_media(to_raw, path, media_type="document", caption=caption)
        )
        if ok:
            display = format_path_for_user(path)
            filename = Path(path).name
            tail = to_raw[-4:] if len(to_raw) >= 4 else to_raw
            return ToolResult(
                ok=True,
                output=(
                    f"✅ Te envié el documento por WhatsApp.\n"
                    f"Archivo: {filename}\n"
                    f"Ruta: {path}\n"
                    f"Ubicación: {display}\n"
                    f"Destino: tu WhatsApp vinculado (…{tail})."
                ),
            )
        return ToolResult(ok=False, output="", error=f"No se pudo enviar el documento: {err}")
    except Exception as e:
        log.warning("send_whatsapp_document error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def notify_whatsapp_owner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envia una notificacion al WhatsApp del dueno (numero vinculado)."""
    try:
        message = str(arguments.get("message") or arguments.get("text") or "").strip()
        if not message:
            return ToolResult(ok=False, output="", error="Falta el mensaje a enviar.")

        from app.services.whatsapp_link import get_channel_state
        from app.services.whatsapp_client import send_whatsapp_message

        state = get_channel_state(uid)
        if not state.linked or not state.phone_number:
            return ToolResult(ok=False, output="", error="WhatsApp no vinculado. No se puede notificar al dueno.")

        phone = state.phone_number
        ok, err = asyncio.run(send_whatsapp_message(phone, message))
        if ok:
            return ToolResult(ok=True, output=f"Notificacion enviada al dueno ({phone[-4:]}).")
        return ToolResult(ok=False, output="", error=f"No se pudo notificar: {err}")
    except Exception as e:
        log.warning("notify_whatsapp_owner error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def notify_desktop_toast_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Muestra una notificacion nativa en el escritorio de Windows."""
    try:
        message = str(arguments.get("message") or arguments.get("text") or "").strip()
        title = str(arguments.get("title") or "DOT").strip()

        if not message:
            return ToolResult(ok=False, output="", error="Falta el mensaje.")

        from app.services.ws_manager import manager

        try:
            asyncio.run(manager.send_to_user(uid, {
                "type": "desktop_notification",
                "title": title,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            pass

        return ToolResult(ok=True, output=f"Notificacion enviada al escritorio: {message[:100]}")
    except Exception as e:
        log.warning("notify_desktop_toast error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))


def whatsapp_bulk_notify_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envia mensaje personalizado a multiples contactos de WhatsApp."""
    try:
        contacts = arguments.get("contacts") or arguments.get("phones") or []
        template = str(arguments.get("message") or arguments.get("template") or "").strip()
        names_list = arguments.get("names") or []

        if not contacts or not isinstance(contacts, list) or not template:
            return ToolResult(ok=False, output="", error="Falta contacts (lista) y message/template.")

        from app.services.whatsapp_client import send_whatsapp_message

        sent, failed = 0, 0
        errors: list[str] = []
        for i, contact in enumerate(contacts[:20]):
            name = names_list[i] if i < len(names_list) else ""
            text = template.replace("{name}", str(name))
            try:
                ok, err = asyncio.run(send_whatsapp_message(str(contact), text))
                if ok:
                    sent += 1
                else:
                    failed += 1
                    errors.append(f"{contact}: {err}")
            except Exception as e2:
                failed += 1
                errors.append(f"{contact}: {e2}")

        summary = f"Notificacion: {sent}/{len(contacts[:20])} enviados"
        if failed:
            summary += f", {failed} fallidos"
            if errors:
                summary += "\n" + "\n".join(errors[:5])
        return ToolResult(ok=True, output=summary)
    except Exception as e:
        log.warning("whatsapp_bulk_notify error: %s", e)
        return ToolResult(ok=False, output="", error=str(e))

def save_whatsapp_media_to_desktop_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Guarda el adjunto WhatsApp reciente (foto/PDF) en el Escritorio del PC."""
    try:
        from app.application.whatsapp.whatsapp_media_service import (
            build_save_confirmation_message,
            save_whatsapp_media_to_desktop,
        )

        message_id = str(arguments.get("message_id") or "").strip() or None
        dest_path = str(arguments.get("path") or arguments.get("dest") or "").strip() or None
        result = save_whatsapp_media_to_desktop(
            uid,
            message_id=message_id,
            dest_path=dest_path,
        )
        if result.ok:
            msg = result.human_message or build_save_confirmation_message(result)
            return ToolResult(ok=True, output=msg)
        err = result.error or "save_failed"
        human = {
            "no_media_cached": "No encuentro el adjunto reciente. Pídele que lo reenvíe.",
            "bridge_unreachable": "No pude guardar el archivo porque la app DOT no está abierta en tu PC.",
        }.get(err, err)
        return ToolResult(ok=False, output="", error=human)
    except Exception as e:
        log.warning("save_whatsapp_media_to_desktop error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("whatsapp_read_recent", whatsapp_read_recent_handler),
    ("whatsapp_get_thread", whatsapp_get_thread_handler),
    ("whatsapp_search_messages", whatsapp_search_messages_handler),
    ("whatsapp_list_contacts", whatsapp_list_contacts_handler),
    # ⚠️ FAKE: whatsapp_detect_intent alucina clasificación de intención sin modelo NLP real (route_chat)
    # ("whatsapp_detect_intent", whatsapp_detect_intent_handler),
    # ⚠️ FAKE: whatsapp_extract_entities alucina extracción de entidades sin NER real (route_chat)
    # ("whatsapp_extract_entities", whatsapp_extract_entities_handler),
    # ⚠️ FAKE: whatsapp_summarize_thread alucina resúmenes sin modelo de summarization real (route_chat)
    # ("whatsapp_summarize_thread", whatsapp_summarize_thread_handler),
    ("send_whatsapp_image", send_whatsapp_image_handler),
    ("send_whatsapp_document", send_whatsapp_document_handler),
    ("save_whatsapp_media_to_desktop", save_whatsapp_media_to_desktop_handler),
    ("notify_whatsapp_owner", notify_whatsapp_owner_handler),
    ("notify_desktop_toast", notify_desktop_toast_handler),
    ("whatsapp_bulk_notify", whatsapp_bulk_notify_handler),
]
