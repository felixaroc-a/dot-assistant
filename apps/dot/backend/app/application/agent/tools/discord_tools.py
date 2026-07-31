"""Tools Discord API — M6S4-A.

3 tools reales para Discord usando API v10 gratuita (Bot Token):
  - discord_send_message: enviar mensaje a un canal
  - discord_list_channels: listar canales de un servidor
  - discord_get_user: obtener info de un usuario por ID

Auth: Bearer token via DISCORD_BOT_TOKEN env var.
Sin token → "requiere configurar DISCORD_BOT_TOKEN en Ajustes".
Rate limit: Discord permite ~50 req/seg; respetamos 0.5s entre llamadas.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.discord")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 0.5) -> None:
    """Espera si es necesario para respetar rate limit de Discord."""
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
    """Retorna mensaje de error si DISCORD_BOT_TOKEN no configurado."""
    token = _env("DISCORD_BOT_TOKEN")
    if not token:
        return (
            "Discord API no configurada. Solicita al usuario que configure "
            "DISCORD_BOT_TOKEN en Ajustes (gratis en discord.com/developers/applications)."
        )
    return None


# ──────────────────────────────────────────────
#  1. discord_send_message — Enviar mensaje a un canal
# ──────────────────────────────────────────────


def discord_send_message_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un mensaje de texto a un canal de Discord usando API v10."""
    try:
        channel_id = str(arguments.get("channel_id") or "").strip()
        text = str(arguments.get("text") or "").strip()

        if not channel_id:
            return ToolResult(
                ok=False, output="",
                error="Falta channel_id (ID del canal de Discord, ej: '123456789012345678').",
            )
        if not text:
            return ToolResult(
                ok=False, output="",
                error="Falta text (contenido del mensaje, máximo 2000 caracteres).",
            )

        if len(text) > 2000:
            return ToolResult(
                ok=False, output="",
                error=f"El mensaje excede 2000 caracteres ({len(text)}/2000). Acorta el texto.",
            )

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("DISCORD_BOT_TOKEN")

        _rate_limit("discord_send_message")
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                json={"content": text},
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                msg_id = data.get("id", "?")
                return ToolResult(
                    ok=True,
                    output=(
                        f"💬 Mensaje enviado a Discord.\n"
                        f"Canal ID: {channel_id}\n"
                        f"Mensaje ID: {msg_id}\n"
                        f"Texto: {text[:200]}{'...' if len(text) > 200 else ''}\n"
                        f"Fuente: Discord API v10"
                    ),
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="DISCORD_BOT_TOKEN inválido. Verifica el token en discord.com/developers/applications.",
                )
            elif resp.status_code == 403:
                return ToolResult(
                    ok=False, output="",
                    error=f"El bot no tiene permisos para enviar mensajes al canal {channel_id}. Verifica permisos Send Messages y View Channel.",
                )
            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Canal {channel_id} no encontrado. Verifica el ID del canal.",
                )
            elif resp.status_code == 429:
                try:
                    retry_after = resp.json().get("retry_after", 1)
                except Exception:
                    retry_after = 1
                return ToolResult(
                    ok=False, output="",
                    error=f"Rate limit excedido en Discord API. Reintenta en {retry_after:.0f} segundos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al enviar mensaje a Discord ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al enviar mensaje a Discord: {e}")
    except Exception as e:
        log.exception("discord_send_message uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. discord_list_channels — Listar canales de un servidor
# ──────────────────────────────────────────────


def discord_list_channels_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los canales de un servidor (guild) de Discord usando API v10."""
    try:
        guild_id = str(arguments.get("guild_id") or "").strip()
        if not guild_id:
            return ToolResult(
                ok=False, output="",
                error="Falta guild_id (ID del servidor de Discord, ej: '123456789012345678').",
            )

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("DISCORD_BOT_TOKEN")

        _rate_limit("discord_list_channels")
        url = f"https://discord.com/api/v10/guilds/{guild_id}/channels"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                headers={"Authorization": f"Bot {token}"},
            )

            if resp.status_code == 200:
                channels = resp.json()
                if not channels:
                    return ToolResult(
                        ok=True,
                        output=f"📋 Servidor {guild_id}: sin canales accesibles para el bot.",
                    )

                # Separar por tipo de canal
                type_names: dict[int, str] = {
                    0: "📝 Texto",
                    2: "🔊 Voz",
                    4: "📂 Categoría",
                    5: "📢 Anuncios",
                    13: "🎤 Escenario",
                    15: "🧵 Foro",
                }

                text_channels = [ch for ch in channels if ch.get("type") == 0]
                voice_channels = [ch for ch in channels if ch.get("type") == 2]
                categories = [ch for ch in channels if ch.get("type") == 4]
                other = [ch for ch in channels if ch.get("type") not in (0, 2, 4)]

                lines = [f"📋 Canales del servidor {guild_id} ({len(channels)} total):\n"]

                if categories:
                    lines.append("─ Categorías ─")
                    for ch in categories:
                        lines.append(f"  📂 {ch.get('name', '?')} (ID: {ch.get('id', '?')})")

                if text_channels:
                    lines.append("\n─ Canales de texto ─")
                    for i, ch in enumerate(text_channels, 1):
                        name = ch.get("name", "?")
                        ch_id = ch.get("id", "?")
                        topic = (ch.get("topic") or "")[:80] if ch.get("topic") else ""
                        nsfw = " 🔞" if ch.get("nsfw") else ""
                        topic_str = f" — {topic}" if topic else ""
                        lines.append(f"  {i}. #{name}{nsfw}{topic_str}\n     ID: {ch_id}")

                if voice_channels:
                    lines.append("\n─ Canales de voz ─")
                    for i, ch in enumerate(voice_channels, 1):
                        name = ch.get("name", "?")
                        ch_id = ch.get("id", "?")
                        bitrate = ch.get("bitrate", 0) / 1000
                        user_limit = ch.get("user_limit", 0)
                        limit_str = f" | {int(user_limit)} usuarios" if user_limit else ""
                        lines.append(f"  {i}. 🔊 {name} ({int(bitrate)}kbps{limit_str})\n     ID: {ch_id}")

                if other:
                    lines.append("\n─ Otros ─")
                    for ch in other:
                        ch_type = type_names.get(ch.get("type"), f"Tipo {ch.get('type')}")
                        lines.append(f"  {ch_type}: {ch.get('name', '?')} (ID: {ch.get('id', '?')})")

                return ToolResult(
                    ok=True,
                    output="\n".join(lines) + "\n\nFuente: Discord API v10",
                )

            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="DISCORD_BOT_TOKEN inválido. Verifica el token en discord.com/developers/applications.",
                )
            elif resp.status_code == 403:
                return ToolResult(
                    ok=False, output="",
                    error=f"El bot no tiene acceso al servidor {guild_id}. Verifica que el bot esté invitado al servidor.",
                )
            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Servidor {guild_id} no encontrado. Verifica el ID del servidor.",
                )
            elif resp.status_code == 429:
                try:
                    retry_after = resp.json().get("retry_after", 1)
                except Exception:
                    retry_after = 1
                return ToolResult(
                    ok=False, output="",
                    error=f"Rate limit excedido en Discord API. Reintenta en {retry_after:.0f} segundos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al listar canales ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("discord_list_channels uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. discord_get_user — Obtener info de un usuario
# ──────────────────────────────────────────────


def discord_get_user_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene información de un usuario de Discord por ID usando API v10."""
    try:
        user_id = str(arguments.get("user_id") or "").strip()
        if not user_id:
            return ToolResult(
                ok=False, output="",
                error="Falta user_id (ID del usuario de Discord, ej: '123456789012345678').",
            )

        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("DISCORD_BOT_TOKEN")

        _rate_limit("discord_get_user")
        url = f"https://discord.com/api/v10/users/{user_id}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                url,
                headers={"Authorization": f"Bot {token}"},
            )

            if resp.status_code == 200:
                data = resp.json()
                username = data.get("username", "?")
                discriminator = data.get("discriminator", "0")
                display_name = data.get("global_name") or username
                avatar = data.get("avatar")
                banner = data.get("banner")
                accent_color = data.get("accent_color")
                bot = "🤖 Bot" if data.get("bot") else "👤 Usuario"
                flags = data.get("public_flags", 0)
                badge_str = _decode_user_flags(flags)

                name_tag = f"{username}#{discriminator}" if discriminator != "0" else username

                avatar_url = ""
                if avatar:
                    ext = "gif" if avatar.startswith("a_") else "png"
                    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=256"

                output = (
                    f"👤 Usuario Discord — {name_tag}\n"
                    f"Tipo: {bot}\n"
                    f"Nombre global: {display_name}\n"
                    + (f"Avatar: {avatar_url}\n" if avatar_url else "")
                    + (f"Insignias: {badge_str}\n" if badge_str else "")
                    + (f"Color de perfil: #{accent_color:06X}\n" if accent_color else "")
                    + f"ID: {user_id}\n"
                    f"Fuente: Discord API v10"
                )

                return ToolResult(ok=True, output=output)

            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="DISCORD_BOT_TOKEN inválido. Verifica el token en discord.com/developers/applications.",
                )
            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Usuario {user_id} no encontrado en Discord.",
                )
            elif resp.status_code == 429:
                try:
                    retry_after = resp.json().get("retry_after", 1)
                except Exception:
                    retry_after = 1
                return ToolResult(
                    ok=False, output="",
                    error=f"Rate limit excedido en Discord API. Reintenta en {retry_after:.0f} segundos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al consultar usuario ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red: {e}")
    except Exception as e:
        log.exception("discord_get_user uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def _decode_user_flags(flags: int) -> str:
    """Decodifica insignias (public_flags) de un usuario de Discord."""
    flag_map: dict[int, str] = {
        1: "Discord Employee",
        2: "Partnered Server Owner",
        4: "HypeSquad Events",
        8: "Bug Hunter Level 1",
        64: "House Bravery",
        128: "House Brilliance",
        256: "House Balance",
        512: "Early Supporter",
        1024: "Team User",
        16384: "Bug Hunter Level 2",
        65536: "Verified Bot Developer",
        131072: "Active Developer",
    }
    badges = [name for bit, name in sorted(flag_map.items()) if flags & bit]
    return ", ".join(badges) if badges else ""


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("discord_send_message", discord_send_message_handler),
    ("discord_list_channels", discord_list_channels_handler),
    ("discord_get_user", discord_get_user_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "discord_send_message": {
        "description": "Envía un mensaje de texto a un canal de Discord. Máximo 2000 caracteres. Requiere DISCORD_BOT_TOKEN configurado.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "ID del canal de Discord de destino (ej: '123456789012345678')",
                },
                "text": {
                    "type": "string",
                    "description": "Texto del mensaje (máximo 2000 caracteres)",
                },
            },
            "required": ["channel_id", "text"],
        },
        "category": "social",
        "capability": "B",
    },
    "discord_list_channels": {
        "description": "Lista los canales (texto, voz, categorías) de un servidor de Discord. Requiere DISCORD_BOT_TOKEN y que el bot esté en el servidor.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "guild_id": {
                    "type": "string",
                    "description": "ID del servidor (guild) de Discord (ej: '123456789012345678')",
                },
            },
            "required": ["guild_id"],
        },
        "category": "social",
        "capability": "B",
    },
    "discord_get_user": {
        "description": "Obtiene información de un usuario de Discord: nombre, avatar, insignias y más. Requiere DISCORD_BOT_TOKEN.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "ID del usuario de Discord a consultar (ej: '123456789012345678')",
                },
            },
            "required": ["user_id"],
        },
        "category": "social",
        "capability": "B",
    },
}
