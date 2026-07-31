"""Servicio Microsoft Teams — skeleton con MS Graph API.

Gestiona el estado del canal Teams y el envío de mensajes via Microsoft Graph.
Gate: TEAMS_ENABLED=true en .env.
Requiere app registration en Azure AD con permisos:
  - Chat.ReadWrite, ChannelMessage.Send, TeamsActivity.Send

Referencia:
  - https://learn.microsoft.com/en-us/graph/api/chat-sendmessage
  - https://learn.microsoft.com/en-us/graph/api/channel-post-messages
  - https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.settings import settings

log = logging.getLogger("dot.teams_service")


# ─── Estado del canal ─────────────────────────────────────────────────

@dataclass
class TeamsChannelStatus:
    linked: bool = False
    app_name: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


def get_teams_channel_state() -> TeamsChannelStatus:
    """Obtiene el estado actual del canal Teams."""
    enabled = bool(settings.teams_enabled)
    configured = bool(settings.teams_tenant_id and settings.teams_client_id and settings.teams_client_secret)

    return TeamsChannelStatus(
        linked=enabled and configured,
        app_name=None,
        last_linked_at=None,
        last_heartbeat_at=None,
        last_error_at=None,
        error=None if (enabled and configured) else "Teams no configurado (falta TEAMS_TENANT_ID, TEAMS_CLIENT_ID o TEAMS_CLIENT_SECRET)",
    )


def update_teams_channel_state(
    *, linked: bool, app_name: str | None = None, error: str | None = None
) -> None:
    """Actualiza el estado del canal Teams. Skeleton — en producción usa Firestore."""
    log.info("teams_channel_state_update linked=%s app=%s error=%s", linked, app_name, error)


def record_teams_channel_event(
    *, event: str, app_name: str | None = None, error: str | None = None, metadata: dict | None = None
) -> None:
    """Registra un evento operacional del canal Teams. Skeleton."""
    log.info("teams_channel_event event=%s app=%s error=%s meta=%s", event, app_name, error, metadata)


# ─── Autenticación MS Graph ───────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Caché simple del token (en producción usar Redis + refresh)
_access_token_cache: dict[str, Any] = {}


async def _get_graph_token() -> str:
    """Obtiene token OAuth2 para MS Graph usando client_credentials.

    Flujo: POST /{tenant_id}/oauth2/v2.0/token
    Scope: https://graph.microsoft.com/.default
    """
    import time

    cache_key = "token"
    cached = _access_token_cache.get(cache_key)
    if cached and cached.get("expires_at", 0) > time.time() + 60:
        return cached["access_token"]

    tenant_id = settings.teams_tenant_id
    client_id = settings.teams_client_id
    client_secret = settings.teams_client_secret

    if not all([tenant_id, client_id, client_secret]):
        raise ValueError("TEAMS_TENANT_ID, TEAMS_CLIENT_ID, y TEAMS_CLIENT_SECRET requeridos")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"MS Graph auth error {resp.status_code}: {resp.text}")

        data = resp.json()
        access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)

        _access_token_cache[cache_key] = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }
        return access_token


def _graph_headers(token: str) -> dict[str, str]:
    """Headers para MS Graph API."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _graph_post(endpoint: str, payload: dict, timeout: int = 20) -> dict:
    """POST genérico a MS Graph API."""

    try:
        token = await _get_graph_token()
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log.warning("teams_graph_auth error: %s", e)
        return {"ok": False, "error": f"Error autenticando con MS Graph: {e}"}

    url = f"{GRAPH_BASE}{endpoint}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_graph_headers(token), json=payload)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            log.warning("teams_graph error %d %s: %s", resp.status_code, endpoint, data)
        return {"status": resp.status_code, "data": data}


# ─── Webhook ───────────────────────────────────────────────────────────

def process_teams_webhook(body: bytes) -> dict:
    """Procesa notificaciones de cambio de MS Graph.

    Microsoft Graph envía notificaciones cuando hay mensajes nuevos en chats suscritos.
    Cada notificación incluye resource (ej. /chats/{id}/messages/{id}) y changeType.

    Returns:
        dict con {ok, processed, error}
    """
    try:
        data = json.loads(body)
        notifications = data.get("value", [])
        for notification in notifications:
            change_type = notification.get("changeType", "unknown")
            resource = notification.get("resource", "unknown")
            log.info("teams_webhook change=%s resource=%s", change_type, resource)

        return {"ok": True, "processed": len(notifications)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Body JSON inválido: {e}"}
    except Exception as e:
        log.exception("teams_webhook error")
        return {"ok": False, "error": str(e)}


# ─── Envío de mensajes ────────────────────────────────────────────────

def send_teams_message(
    chat_id: str | None = None,
    team_id: str | None = None,
    channel_id: str | None = None,
    text: str = "",
    importance: str | None = None,
) -> dict:
    """Envía un mensaje via Microsoft Teams (MS Graph API).

    Args:
        chat_id: ID del chat 1:1 o grupo (ej. 19:xxx@thread.v2)
        team_id: ID del team (GUID) — requerido si se envía a canal
        channel_id: ID del canal — requerido si se envía a canal
        text: Contenido del mensaje (soporta HTML básico: <p>, <b>, <i>, <a>)
        importance: "low", "normal", o "high"

    Returns:
        dict con {ok, message_id, error}
    """
    import asyncio

    if not settings.teams_enabled:
        return {"ok": False, "message_id": None, "error": "Canal Teams deshabilitado (TEAMS_ENABLED=false)"}

    if not all([settings.teams_tenant_id, settings.teams_client_id, settings.teams_client_secret]):
        return {"ok": False, "message_id": None, "error": "Teams no configurado (tenant_id, client_id, client_secret requeridos)"}

    # Construir el body del mensaje
    body_content = {
        "contentType": "html",
        "content": f"<p>{text}</p>",
    }
    payload: dict[str, Any] = {"body": body_content}
    if importance and importance in ("low", "normal", "high"):
        payload["importance"] = importance

    try:
        if chat_id:
            endpoint = f"/chats/{chat_id}/messages"
        elif team_id and channel_id:
            endpoint = f"/teams/{team_id}/channels/{channel_id}/messages"
        else:
            return {"ok": False, "message_id": None, "error": "Se requiere chat_id o team_id+channel_id"}

        result = asyncio.run(_graph_post(endpoint, payload))
        status = result.get("status", 500)
        ok = 200 <= status < 300
        msg_id = str(uuid.uuid4())[:12] if ok else None

        if ok:
            graph_id = result.get("data", {}).get("id", "")
            log.info("teams_send ok endpoint=%s graph_id=%s", endpoint, graph_id)
        else:
            log.warning("teams_send fail status=%d data=%s", status, result.get("data"))

        return {
            "ok": ok,
            "message_id": msg_id,
            "error": None if ok else f"MS Graph error {status}: {result.get('data')}",
        }
    except Exception as e:
        log.warning("teams_send exception: %s", e)
        return {"ok": False, "message_id": None, "error": str(e)}
