"""Tools Telegram Bot API — M3S3-B.

5 tools reales para Telegram usando Bot API gratuita e ilimitada:
  - telegram_send_message: enviar mensaje de texto
  - telegram_get_updates: recibir mensajes recientes del bot
  - telegram_send_photo: enviar foto (por ruta local o URL)
  - telegram_get_chat_info: obtener info de un chat
  - telegram_send_document: enviar documento/archivo

Auth: TELEGRAM_BOT_TOKEN env var. API gratuita sin rate limits estrictos.
Sin token → "requiere configurar TELEGRAM_BOT_TOKEN en Ajustes".
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.telegram")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 0.5) -> None:
    """Espera si es necesario para respetar rate (Telegram tolera ~30 msg/seg por chat)."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


def _check_token() -> str | None:
    """Retorna mensaje de error si TELEGRAM_BOT_TOKEN no configurado."""
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return (
            "Telegram Bot API no configurada. Solicita al usuario que configure "
            "TELEGRAM_BOT_TOKEN en Ajustes (gratis creando un bot con @BotFather en Telegram)."
        )
    return None


def _base_url(token: str) -> str:
    """URL base de la API de Telegram."""
    return f"https://api.telegram.org/bot{token}"


# ──────────────────────────────────────────────
#  1. telegram_send_message — Enviar mensaje
# ──────────────────────────────────────────────


def telegram_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje de texto a un chat de Telegram usando sendMessage."""
    try:
        chat_id = str(arguments.get("chat_id") or "").strip()
        text = str(arguments.get("text") or "").strip()

        if not chat_id:
            return ToolResult(ok=False, output="", error="Falta chat_id (ID del chat o canal, ej: '123456789' o '@mi_canal').")
        if not text:
            return ToolResult(ok=False, output="", error="Falta text (contenido del mensaje).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("TELEGRAM_BOT_TOKEN")

        # Telegram no tiene límite de caracteres estrictos, pero truncamos a 4096 (límite de mensaje)
        if len(text) > 4096:
            text = text[:4090] + "..."

        _rate_limit("telegram_send_message")

        parse_mode = str(arguments.get("parse_mode") or "").strip()
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode in ("HTML", "MarkdownV2", "Markdown"):
            body["parse_mode"] = parse_mode

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_base_url(token)}/sendMessage",
                json=body,
            )

            data = resp.json()

            if data.get("ok"):
                msg = data.get("result", {})
                msg_id = msg.get("message_id", "?")
                chat = msg.get("chat", {})
                chat_name = chat.get("title") or chat.get("first_name", chat_id)

                return ToolResult(
                    ok=True,
                    output=(
                        f"✈️ Mensaje enviado a Telegram.\n"
                        f"Chat: {chat_name} ({chat_id})\n"
                        f"Message ID: {msg_id}\n"
                        f"Texto: {text[:200]}{'...' if len(text) > 200 else ''}\n"
                        f"Fuente: Telegram Bot API"
                    ),
                )
            else:
                err_desc = data.get("description", "error desconocido")
                if "chat not found" in str(err_desc).lower():
                    return ToolResult(
                        ok=False, output="",
                        error=f"Chat {chat_id} no encontrado. El usuario debe iniciar una conversación con el bot primero (@tu_bot).",
                    )
                return ToolResult(
                    ok=False, output="",
                    error=f"Telegram rechazó el envío: {err_desc}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al enviar mensaje a Telegram: {e}")
    except Exception as e:
        log.exception("telegram_send_message uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. telegram_get_updates — Recibir mensajes
# ──────────────────────────────────────────────


def telegram_get_updates_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene los mensajes recientes recibidos por el bot de Telegram usando getUpdates."""
    try:
        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("TELEGRAM_BOT_TOKEN")
        limit = min(int(arguments.get("limit") or 10), 100)

        _rate_limit("telegram_get_updates")

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_base_url(token)}/getUpdates",
                params={
                    "limit": limit,
                    "timeout": 0,  # long polling desactivado para respuesta inmediata
                },
            )

            data = resp.json()

            if data.get("ok"):
                updates = data.get("result") or []

                if not updates:
                    return ToolResult(
                        ok=True,
                        output="📬 Telegram: sin mensajes recientes en el bot.",
                    )

                lines = [f"📬 Mensajes recientes de Telegram ({len(updates)} encontrados):\n"]

                for i, update in enumerate(updates, 1):
                    msg = update.get("message") or update.get("channel_post") or {}
                    update_id = update.get("update_id", "?")
                    msg_id = msg.get("message_id", "?")
                    msg_date = msg.get("date", 0)
                    chat = msg.get("chat", {})
                    from_user = msg.get("from", {})

                    chat_name = chat.get("title") or chat.get("first_name", "?")
                    chat_type = chat.get("type", "?")
                    username = from_user.get("username") or from_user.get("first_name", "?")
                    text = (msg.get("text") or msg.get("caption") or "[sin texto]")[:300]

                    # Formatear timestamp
                    try:
                        from datetime import datetime as dt, timezone
                        ts_str = dt.fromtimestamp(msg_date, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        ts_str = str(msg_date)

                    # Detectar tipo de contenido
                    content_type = "📝"
                    if msg.get("photo"):
                        content_type = "🖼"
                    elif msg.get("document"):
                        content_type = "📎"
                    elif msg.get("video"):
                        content_type = "🎬"
                    elif msg.get("voice"):
                        content_type = "🎤"
                    elif msg.get("sticker"):
                        content_type = "🏷"
                    elif msg.get("location"):
                        content_type = "📍"

                    lines.append(
                        f"{i}. {content_type} {username} → {chat_name} ({chat_type})\n"
                        f"   {ts_str} — Update #{update_id}\n"
                        f"   {text}"
                    )

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Telegram Bot API",
                )
            else:
                err_desc = data.get("description", "error desconocido")
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al obtener mensajes de Telegram: {err_desc}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("telegram_get_updates uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. telegram_send_photo — Enviar foto
# ──────────────────────────────────────────────


def telegram_send_photo_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía una foto a un chat de Telegram. Soporta archivo local o URL pública."""
    try:
        chat_id = str(arguments.get("chat_id") or "").strip()
        photo = str(arguments.get("photo") or "").strip()
        caption = str(arguments.get("caption") or "").strip()

        if not chat_id:
            return ToolResult(ok=False, output="", error="Falta chat_id (ID del chat destino).")
        if not photo:
            return ToolResult(ok=False, output="", error="Falta photo (ruta local del archivo o URL pública de la imagen).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("TELEGRAM_BOT_TOKEN")

        _rate_limit("telegram_send_photo")

        url = f"{_base_url(token)}/sendPhoto"

        with httpx.Client(timeout=30) as client:
            if photo.startswith("http://") or photo.startswith("https://"):
                # Enviar por URL
                body: dict[str, Any] = {
                    "chat_id": chat_id,
                    "photo": photo,
                }
                if caption:
                    body["caption"] = caption[:1024]

                resp = client.post(url, json=body)
            else:
                # Enviar archivo local
                if not os.path.exists(photo):
                    return ToolResult(
                        ok=False, output="",
                        error=f"Archivo no encontrado: {photo}. Verifica la ruta.",
                    )

                files_param = {"photo": (os.path.basename(photo), open(photo, "rb"), "image/*")}
                data_params: dict[str, Any] = {"chat_id": chat_id}
                if caption:
                    data_params["caption"] = caption[:1024]

                resp = client.post(url, files=files_param, data=data_params)

            data = resp.json()

            if data.get("ok"):
                msg = data.get("result", {})
                msg_id = msg.get("message_id", "?")
                photo_info = msg.get("photo", [])
                dimensions = ""
                if photo_info and len(photo_info) > 0:
                    largest = photo_info[-1]
                    dimensions = f"{largest.get('width', '?')}x{largest.get('height', '?')}"

                return ToolResult(
                    ok=True,
                    output=(
                        f"🖼 Foto enviada a Telegram.\n"
                        f"Chat ID: {chat_id}\n"
                        f"Message ID: {msg_id}\n"
                        + (f"Dimensiones: {dimensions}\n" if dimensions else "")
                        + (f"Caption: {caption[:100]}\n" if caption else "")
                        + f"Fuente: Telegram Bot API"
                    ),
                )
            else:
                err_desc = data.get("description", "error desconocido")
                if "chat not found" in str(err_desc).lower():
                    return ToolResult(
                        ok=False, output="",
                        error=f"Chat {chat_id} no encontrado. El usuario debe iniciar conversación con el bot primero.",
                    )
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al enviar foto: {err_desc}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("telegram_send_photo uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  4. telegram_get_chat_info — Info del chat
# ──────────────────────────────────────────────


def telegram_get_chat_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene información de un chat de Telegram: nombre, tipo, miembros, descripción."""
    try:
        chat_id = str(arguments.get("chat_id") or "").strip()
        if not chat_id:
            return ToolResult(ok=False, output="", error="Falta chat_id (ID del chat, canal o grupo a consultar).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("TELEGRAM_BOT_TOKEN")

        _rate_limit("telegram_get_chat_info")

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_base_url(token)}/getChat",
                params={"chat_id": chat_id},
            )

            data = resp.json()

            if data.get("ok"):
                chat = data.get("result", {})

                chat_type = chat.get("type", "?")
                chat_title = chat.get("title") or ""
                chat_username = chat.get("username", "")
                first_name = chat.get("first_name", "")
                last_name = chat.get("last_name", "")
                description = (chat.get("description") or "")[:300]
                invite_link = chat.get("invite_link", "")
                member_count = chat.get("member_count", 0)

                # Emoji según tipo
                type_emoji = {
                    "private": "👤",
                    "group": "👥",
                    "supergroup": "👥",
                    "channel": "📢",
                }.get(chat_type, "💬")

                # Nombre para mostrar
                if chat_title:
                    display_name = chat_title
                elif first_name:
                    display_name = f"{first_name} {last_name}".strip()
                else:
                    display_name = chat_id

                output = (
                    f"{type_emoji} Chat de Telegram — {display_name}\n"
                    f"Tipo: {chat_type}\n"
                    f"ID: {chat.get('id', chat_id)}\n"
                )
                if chat_username:
                    output += f"Username: @{chat_username}\n"
                if description:
                    output += f"Descripción: {description}\n"
                if member_count:
                    output += f"Miembros: {member_count}\n"
                if invite_link:
                    output += f"Invite: {invite_link}\n"

                output += "Fuente: Telegram Bot API"

                return ToolResult(ok=True, output=output)

            else:
                err_desc = data.get("description", "error desconocido")
                if "chat not found" in str(err_desc).lower():
                    return ToolResult(
                        ok=False, output="",
                        error=f"Chat {chat_id} no encontrado. Asegúrate de que el bot sea miembro del chat/grupo/canal.",
                    )
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al obtener info del chat: {err_desc}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("telegram_get_chat_info uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  5. telegram_send_document — Enviar documento
# ──────────────────────────────────────────────


def telegram_send_document_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un documento/archivo a un chat de Telegram (PDF, DOCX, ZIP, etc.). Soporta archivo local o URL."""
    try:
        chat_id = str(arguments.get("chat_id") or "").strip()
        document = str(arguments.get("document") or "").strip()
        caption = str(arguments.get("caption") or "").strip()
        filename = str(arguments.get("filename") or "").strip()

        if not chat_id:
            return ToolResult(ok=False, output="", error="Falta chat_id (ID del chat destino).")
        if not document:
            return ToolResult(ok=False, output="", error="Falta document (ruta local del archivo o URL pública).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("TELEGRAM_BOT_TOKEN")

        _rate_limit("telegram_send_document")

        url = f"{_base_url(token)}/sendDocument"

        with httpx.Client(timeout=60) as client:
            if document.startswith("http://") or document.startswith("https://"):
                # Enviar por URL
                body: dict[str, Any] = {
                    "chat_id": chat_id,
                    "document": document,
                }
                if caption:
                    body["caption"] = caption[:1024]
                if filename:
                    body["filename"] = filename

                resp = client.post(url, json=body)
            else:
                # Enviar archivo local
                if not os.path.exists(document):
                    return ToolResult(
                        ok=False, output="",
                        error=f"Archivo no encontrado: {document}. Verifica la ruta.",
                    )

                # Verificar tamaño (Telegram límite: 50 MB para bots)
                size_mb = os.path.getsize(document) / (1024 * 1024)
                if size_mb > 50:
                    return ToolResult(
                        ok=False, output="",
                        error=f"Archivo demasiado grande ({size_mb:.1f} MB). Telegram permite máximo 50 MB para bots.",
                    )

                display_filename = filename or os.path.basename(document)
                files_param = {"document": (display_filename, open(document, "rb"))}
                data_params: dict[str, Any] = {"chat_id": chat_id}
                if caption:
                    data_params["caption"] = caption[:1024]

                resp = client.post(url, files=files_param, data=data_params)

            data = resp.json()

            if data.get("ok"):
                msg = data.get("result", {})
                msg_id = msg.get("message_id", "?")
                doc_info = msg.get("document", {})
                doc_name = doc_info.get("file_name", filename or os.path.basename(document) if not document.startswith("http") else "documento")
                doc_size = doc_info.get("file_size", 0)
                size_str = f"{doc_size / 1024:.1f} KB" if doc_size else "?"

                return ToolResult(
                    ok=True,
                    output=(
                        f"📎 Documento enviado a Telegram.\n"
                        f"Chat ID: {chat_id}\n"
                        f"Message ID: {msg_id}\n"
                        f"Archivo: {doc_name}\n"
                        f"Tamaño: {size_str}\n"
                        + (f"Caption: {caption[:100]}\n" if caption else "")
                        + f"Fuente: Telegram Bot API"
                    ),
                )
            else:
                err_desc = data.get("description", "error desconocido")
                if "chat not found" in str(err_desc).lower():
                    return ToolResult(
                        ok=False, output="",
                        error=f"Chat {chat_id} no encontrado. El usuario debe iniciar conversación con el bot primero.",
                    )
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al enviar documento: {err_desc}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("telegram_send_document uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("telegram_send_message", telegram_send_message_handler),
    ("telegram_get_updates", telegram_get_updates_handler),
    ("telegram_send_photo", telegram_send_photo_handler),
    ("telegram_get_chat_info", telegram_get_chat_info_handler),
    ("telegram_send_document", telegram_send_document_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "telegram_send_message": {
        "description": "Envía un mensaje de texto a un chat o canal de Telegram. Requiere TELEGRAM_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "ID del chat destino (número, @username del canal, o ID de grupo)",
                },
                "text": {
                    "type": "string",
                    "description": "Texto del mensaje (máximo 4096 caracteres)",
                },
                "parse_mode": {
                    "type": "string",
                    "enum": ["HTML", "MarkdownV2", "Markdown"],
                    "description": "Formato del mensaje (opcional): HTML, MarkdownV2 o Markdown",
                },
            },
            "required": ["chat_id", "text"],
        },
        "category": "social",
        "capability": "B",
    },
    "telegram_get_updates": {
        "description": "Obtiene los mensajes recientes recibidos por el bot de Telegram. Útil para monitorear conversaciones.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de mensajes a recuperar (default 10, max 100)",
                },
            },
        },
        "category": "social",
        "capability": "B",
    },
    "telegram_send_photo": {
        "description": "Envía una foto a un chat de Telegram. Soporta archivo local (ruta) o URL pública de la imagen.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "ID del chat destino",
                },
                "photo": {
                    "type": "string",
                    "description": "Ruta local del archivo de imagen o URL pública (jpg, png, gif, webp)",
                },
                "caption": {
                    "type": "string",
                    "description": "Texto opcional que acompaña la foto (máximo 1024 caracteres)",
                },
            },
            "required": ["chat_id", "photo"],
        },
        "category": "social",
        "capability": "B",
    },
    "telegram_get_chat_info": {
        "description": "Obtiene información de un chat, grupo o canal de Telegram: nombre, tipo, miembros, descripción.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "ID del chat a consultar (número, @username, o ID de grupo/canal)",
                },
            },
            "required": ["chat_id"],
        },
        "category": "social",
        "capability": "B",
    },
    "telegram_send_document": {
        "description": "Envía un documento/archivo a un chat de Telegram (PDF, DOCX, ZIP, etc.). Máximo 50 MB para bots.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "ID del chat destino",
                },
                "document": {
                    "type": "string",
                    "description": "Ruta local del archivo o URL pública del documento",
                },
                "caption": {
                    "type": "string",
                    "description": "Texto opcional que acompaña el documento (máximo 1024 caracteres)",
                },
                "filename": {
                    "type": "string",
                    "description": "Nombre personalizado para el archivo (opcional, solo para archivos locales)",
                },
            },
            "required": ["chat_id", "document"],
        },
        "category": "social",
        "capability": "B",
    },
}
