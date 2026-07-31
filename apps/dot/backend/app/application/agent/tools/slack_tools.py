"""Tools Slack API — M3S2-B.

5 tools reales para Slack usando API gratuita (Bot Token):
  - slack_send_message: enviar mensaje a canal/usuario
  - slack_list_channels: listar canales del workspace
  - slack_list_users: listar miembros del workspace
  - slack_get_channel_history: historial de mensajes de un canal
  - slack_send_upload_file: subir archivo a un canal

Auth: Bearer token via SLACK_BOT_TOKEN env var.
Sin token → "requiere configurar SLACK_BOT_TOKEN en Ajustes".
Rate limit: Tier 1 ≈ 1 req/seg; respetamos 1.2s entre llamadas.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.slack")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 1.2) -> None:
    """Espera si es necesario para respetar rate limit de Slack."""
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
    """Retorna mensaje de error si SLACK_BOT_TOKEN no configurado."""
    token = _env("SLACK_BOT_TOKEN")
    if not token:
        return (
            "Slack API no configurada. Solicita al usuario que configure "
            "SLACK_BOT_TOKEN en Ajustes (gratis en api.slack.com/apps)."
        )
    return None


# ──────────────────────────────────────────────
#  1. slack_send_message — Enviar mensaje
# ──────────────────────────────────────────────


def slack_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje a un canal o usuario de Slack usando chat.postMessage."""
    try:
        channel = str(arguments.get("channel") or "").strip()
        text = str(arguments.get("text") or "").strip()

        if not channel:
            return ToolResult(ok=False, output="", error="Falta channel (ID del canal o usuario, ej: 'C01234567' o '@U01234567').")
        if not text:
            return ToolResult(ok=False, output="", error="Falta text (contenido del mensaje).")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("SLACK_BOT_TOKEN")

        _rate_limit("slack_send_message")
        url = "https://slack.com/api/chat.postMessage"

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                json={
                    "channel": channel,
                    "text": text,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            data = resp.json()

            if data.get("ok"):
                ts = data.get("ts", "?")
                ch = data.get("channel", channel)
                return ToolResult(
                    ok=True,
                    output=(
                        f"💬 Mensaje enviado a Slack.\n"
                        f"Canal: {ch}\n"
                        f"Timestamp: {ts}\n"
                        f"Texto: {text[:200]}{'...' if len(text) > 200 else ''}\n"
                        f"Fuente: Slack API"
                    ),
                )
            else:
                err = data.get("error", "error desconocido")
                return ToolResult(
                    ok=False, output="",
                    error=f"Slack rechazó el envío: {err}. Verifica que el bot tenga permisos chat:write y esté en el canal.",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al enviar mensaje a Slack: {e}")
    except Exception as e:
        log.exception("slack_send_message uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. slack_list_channels — Listar canales
# ──────────────────────────────────────────────


def slack_list_channels_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los canales públicos del workspace de Slack usando conversations.list."""
    try:
        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("SLACK_BOT_TOKEN")
        limit = min(int(arguments.get("limit") or 20), 200)
        types = str(arguments.get("types") or "public_channel").strip()

        _rate_limit("slack_list_channels")
        url = "https://slack.com/api/conversations.list"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params={
                    "limit": limit,
                    "types": types,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

            data = resp.json()

            if data.get("ok"):
                channels = data.get("channels") or []
                if not channels:
                    return ToolResult(
                        ok=True,
                        output="📋 No se encontraron canales públicos en el workspace.",
                    )

                lines = [f"📋 Canales de Slack ({len(channels)} encontrados):\n"]
                for i, ch in enumerate(channels, 1):
                    name = ch.get("name", "?")
                    ch_id = ch.get("id", "?")
                    topic = (ch.get("topic", {}) or {}).get("value", "")
                    members = ch.get("num_members", "?")
                    is_archived = " 🗄 (archivado)" if ch.get("is_archived") else ""
                    topic_str = f" — {topic[:80]}" if topic else ""

                    lines.append(
                        f"{i}. #{name}{is_archived}{topic_str}\n"
                        f"   ID: {ch_id} | Miembros: {members}"
                    )

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Slack API",
                )
            else:
                err = data.get("error", "error desconocido")
                return ToolResult(
                    ok=False, output="",
                    error=f"Slack rechazó la consulta: {err}. Verifica que el bot tenga permiso channels:read.",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("slack_list_channels uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. slack_list_users — Listar miembros
# ──────────────────────────────────────────────


def slack_list_users_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los miembros del workspace de Slack usando users.list."""
    try:
        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("SLACK_BOT_TOKEN")
        limit = min(int(arguments.get("limit") or 20), 200)

        _rate_limit("slack_list_users")
        url = "https://slack.com/api/users.list"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params={"limit": limit},
                headers={"Authorization": f"Bearer {token}"},
            )

            data = resp.json()

            if data.get("ok"):
                members = data.get("members") or []
                if not members:
                    return ToolResult(
                        ok=True,
                        output="👥 No se encontraron miembros en el workspace.",
                    )

                # Filtrar solo usuarios humanos (no bots) si muchos
                humans = [m for m in members if not m.get("is_bot") and not m.get("deleted")]
                bots = [m for m in members if m.get("is_bot")]

                lines = [f"👥 Miembros de Slack ({len(humans)} personas, {len(bots)} bots):\n"]

                for i, u in enumerate(humans[:25], 1):
                    real_name = u.get("real_name") or u.get("name", "?")
                    display_name = u.get("profile", {}).get("display_name", "")
                    user_id = u.get("id", "?")
                    email = u.get("profile", {}).get("email", "")
                    title = u.get("profile", {}).get("title", "")
                    is_admin = " 👑" if u.get("is_admin") else ""
                    is_owner = " 🔑" if u.get("is_owner") else ""

                    name_display = f"{real_name}"
                    if display_name and display_name != real_name:
                        name_display += f" ({display_name})"

                    lines.append(
                        f"{i}. {name_display}{is_admin}{is_owner}\n"
                        f"   ID: {user_id}"
                        + (f" | {email}" if email else "")
                        + (f" | {title}" if title else "")
                    )

                if len(humans) > 25:
                    lines.append(f"\n... y {len(humans) - 25} miembros más.")

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Slack API",
                )
            else:
                err = data.get("error", "error desconocido")
                return ToolResult(
                    ok=False, output="",
                    error=f"Slack rechazó la consulta: {err}. Verifica que el bot tenga permiso users:read.",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("slack_list_users uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  4. slack_get_channel_history — Historial
# ──────────────────────────────────────────────


def slack_get_channel_history_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee el historial reciente de mensajes de un canal de Slack usando conversations.history."""
    try:
        channel = str(arguments.get("channel") or "").strip()
        if not channel:
            return ToolResult(ok=False, output="", error="Falta channel (ID del canal, ej: 'C01234567').")

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("SLACK_BOT_TOKEN")
        limit = min(int(arguments.get("limit") or 10), 100)

        _rate_limit("slack_get_channel_history")
        url = "https://slack.com/api/conversations.history"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                params={
                    "channel": channel,
                    "limit": limit,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

            data = resp.json()

            if data.get("ok"):
                messages = data.get("messages") or []
                if not messages:
                    return ToolResult(
                        ok=True,
                        output=f"📜 Canal {channel}: sin mensajes recientes.",
                    )

                # Obtener info de usuarios para mostrar nombres
                user_ids = {m.get("user", "") for m in messages if m.get("user")}
                user_names: dict[str, str] = {}
                if user_ids:
                    try:
                        _rate_limit("slack_users_info_batch", min_interval=0.5)
                        users_resp = client.get(
                            "https://slack.com/api/users.list",
                            params={"limit": 200},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if users_resp.status_code == 200:
                            users_data = users_resp.json()
                            for u in users_data.get("members") or []:
                                uid_ = u.get("id", "")
                                if uid_ in user_ids:
                                    user_names[uid_] = u.get("real_name") or u.get("name", uid_)
                    except Exception:
                        log.debug("No se pudieron resolver nombres de usuarios en historial.")

                # Revertir para mostrar más recientes primero
                messages_reversed = list(reversed(messages))

                lines = [f"📜 Historial del canal {channel} ({len(messages)} mensajes):\n"]
                for i, msg in enumerate(messages_reversed, 1):
                    ts = msg.get("ts", "?")
                    user_id = msg.get("user", "bot")
                    username = user_names.get(user_id, user_id)
                    text = (msg.get("text") or "")[:300]
                    subtype = msg.get("subtype", "")
                    if subtype:
                        text = f"[{subtype}] {text}"

                    # Formatear timestamp
                    try:
                        from datetime import datetime as dt, timezone
                        ts_float = float(ts)
                        ts_str = dt.fromtimestamp(ts_float, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        ts_str = ts

                    lines.append(f"{i}. {username} — {ts_str}\n   {text}")

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Slack API",
                )
            else:
                err = data.get("error", "error desconocido")
                if err == "channel_not_found":
                    return ToolResult(
                        ok=False, output="",
                        error=f"Canal {channel} no encontrado. Verifica el ID y que el bot tenga acceso al canal.",
                    )
                return ToolResult(
                    ok=False, output="",
                    error=f"Slack rechazó la consulta: {err}. Verifica permisos channels:history.",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("slack_get_channel_history uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  5. slack_upload_file — Subir archivo
# ──────────────────────────────────────────────


def slack_upload_file_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Sube un archivo a un canal de Slack usando files.upload. Soporta rutas locales y texto como snippet."""
    try:
        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("SLACK_BOT_TOKEN")

        # Puede subir archivo local o texto como snippet
        file_path = str(arguments.get("file_path") or "").strip()
        content = str(arguments.get("content") or "").strip()
        channels = str(arguments.get("channels") or "").strip()
        title = str(arguments.get("title") or "").strip()
        filename = str(arguments.get("filename") or "").strip()

        if not file_path and not content:
            return ToolResult(
                ok=False, output="",
                error="Falta file_path (ruta local del archivo) o content (texto para subir como snippet).",
            )

        _rate_limit("slack_upload_file")

        if file_path:
            # Subir archivo desde disco
            if not os.path.exists(file_path):
                return ToolResult(
                    ok=False, output="",
                    error=f"Archivo no encontrado: {file_path}. Verifica la ruta.",
                )

            url = "https://slack.com/api/files.upload"
            with httpx.Client(timeout=30) as client:
                files_param = {"file": (os.path.basename(file_path), open(file_path, "rb"))}
                data_params = {}
                if channels:
                    data_params["channels"] = channels
                if title:
                    data_params["title"] = title

                resp = client.post(
                    url,
                    files=files_param,
                    data=data_params,
                    headers={"Authorization": f"Bearer {token}"},
                )

                data = resp.json()

                if data.get("ok"):
                    file_info = data.get("file", {})
                    file_name = file_info.get("name", os.path.basename(file_path))
                    file_id = file_info.get("id", "?")
                    permalink = file_info.get("permalink", "")
                    size = file_info.get("size", 0)
                    size_str = f"{size / 1024:.1f} KB" if size else "?"

                    return ToolResult(
                        ok=True,
                        output=(
                            f"📎 Archivo subido a Slack.\n"
                            f"Nombre: {file_name}\n"
                            f"ID: {file_id}\n"
                            f"Tamaño: {size_str}\n"
                            + (f"Enlace: {permalink}\n" if permalink else "")
                            + (f"Canales: {channels}\n" if channels else "")
                            + f"Fuente: Slack API"
                        ),
                    )
                else:
                    err = data.get("error", "error desconocido")
                    return ToolResult(
                        ok=False, output="",
                        error=f"Slack rechazó la subida: {err}. Verifica permisos files:write.",
                    )
        else:
            # Subir contenido como snippet de texto
            url = "https://slack.com/api/files.upload"
            with httpx.Client(timeout=15) as client:
                data_params: dict[str, Any] = {
                    "content": content,
                }
                if channels:
                    data_params["channels"] = channels
                if title:
                    data_params["title"] = title
                if filename:
                    data_params["filename"] = filename
                else:
                    data_params["filename"] = "snippet.txt"
                    data_params["filetype"] = "text"

                resp = client.post(
                    url,
                    data=data_params,
                    headers={"Authorization": f"Bearer {token}"},
                )

                data = resp.json()

                if data.get("ok"):
                    file_info = data.get("file", {})
                    file_id = file_info.get("id", "?")
                    permalink = file_info.get("permalink", "")

                    return ToolResult(
                        ok=True,
                        output=(
                            f"📎 Snippet subido a Slack.\n"
                            f"ID: {file_id}\n"
                            + (f"Título: {title}\n" if title else "")
                            + (f"Enlace: {permalink}\n" if permalink else "")
                            + (f"Canales: {channels}\n" if channels else "")
                            + f"Contenido: {content[:150]}{'...' if len(content) > 150 else ''}\n"
                            + f"Fuente: Slack API"
                        ),
                    )
                else:
                    err = data.get("error", "error desconocido")
                    return ToolResult(
                        ok=False, output="",
                        error=f"Slack rechazó la subida del snippet: {err}.",
                    )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("slack_upload_file uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("slack_send_message", slack_send_message_handler),
    ("slack_list_channels", slack_list_channels_handler),
    ("slack_list_users", slack_list_users_handler),
    ("slack_get_channel_history", slack_get_channel_history_handler),
    ("slack_upload_file", slack_upload_file_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "slack_send_message": {
        "description": "Envía un mensaje a un canal o usuario de Slack. Requiere SLACK_BOT_TOKEN configurado.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "ID del canal (ej: 'C01234567') o usuario (ej: '@U01234567') de destino",
                },
                "text": {
                    "type": "string",
                    "description": "Texto del mensaje a enviar (soporta markdown básico de Slack)",
                },
            },
            "required": ["channel", "text"],
        },
        "category": "productivity",
        "capability": "B",
    },
    "slack_list_channels": {
        "description": "Lista los canales públicos del workspace de Slack. Requiere SLACK_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de canales a listar (default 20, max 200)",
                },
                "types": {
                    "type": "string",
                    "description": "Tipos de conversación: public_channel, private_channel, mpim, im (default: public_channel)",
                },
            },
        },
        "category": "productivity",
        "capability": "B",
    },
    "slack_list_users": {
        "description": "Lista los miembros del workspace de Slack (personas y bots). Requiere SLACK_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de usuarios a listar (default 20, max 200)",
                },
            },
        },
        "category": "productivity",
        "capability": "B",
    },
    "slack_get_channel_history": {
        "description": "Lee el historial reciente de mensajes de un canal de Slack. Requiere SLACK_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "ID del canal a consultar (ej: 'C01234567')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de mensajes a recuperar (default 10, max 100)",
                },
            },
            "required": ["channel"],
        },
        "category": "productivity",
        "capability": "B",
    },
    "slack_upload_file": {
        "description": "Sube un archivo o snippet de texto a un canal de Slack. Requiere SLACK_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Ruta local del archivo a subir (ej: 'C:/Users/Nordik/Desktop/reporte.pdf')",
                },
                "content": {
                    "type": "string",
                    "description": "Contenido de texto para subir como snippet (alternativa a file_path)",
                },
                "channels": {
                    "type": "string",
                    "description": "ID del canal o canales separados por coma (ej: 'C01234567,C089ABC')",
                },
                "title": {
                    "type": "string",
                    "description": "Título opcional del archivo",
                },
                "filename": {
                    "type": "string",
                    "description": "Nombre opcional para el archivo (solo para snippets de texto)",
                },
            },
        },
        "category": "productivity",
        "capability": "B",
    },
}
