"""Servicio Microsoft 365 / Outlook — integración completa via MS Graph API.

Gestiona OAuth2 delegado (authorization code flow), operaciones de correo,
calendario y contactos para usuarios enterprise (400M+ Office 365 users).

Gate: OUTLOOK_ENABLED=true en .env.
Requiere app registration en Azure AD con permisos delegados:
  - Mail.Read, Mail.Send, Calendars.Read, Calendars.ReadWrite,
    Contacts.Read, User.Read, offline_access

Referencia:
  - https://learn.microsoft.com/en-us/graph/api/overview
  - https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.settings import settings

log = logging.getLogger("dot.outlook_service")

# ─── Constantes ────────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_BASE = "https://login.microsoftonline.com"

OUTLOOK_SCOPES = [
    "Mail.Read",
    "Mail.Send",
    "Calendars.Read",
    "Calendars.ReadWrite",
    "Contacts.Read",
    "User.Read",
    "offline_access",
]

# ─── Estado de conexión ────────────────────────────────────────────────

@dataclass
class OutlookConnectionStatus:
    linked: bool = False
    user_email: str | None = None
    user_name: str | None = None
    last_linked_at: str | None = None
    error: str | None = None


# ─── Caché de tokens (en producción usar Firestore cifrado) ────────────

# Caché simple de tokens por user_id: {user_id: {access_token, refresh_token, expires_at, scope, user_email}}
_token_cache: dict[str, dict[str, Any]] = {}

# Caché de estados OAuth pendientes (state -> {user_id, pkce_verifier, expires_at})
_pending_states: dict[str, dict[str, Any]] = {}


def _get_token(user_id: str) -> dict[str, Any] | None:
    """Obtiene el token cacheado para un usuario."""
    entry = _token_cache.get(user_id)
    if not entry:
        return None
    if entry.get("expires_at", 0) > time.time() + 60:
        return entry
    # Intentar refresh
    refresh = entry.get("refresh_token")
    if refresh:
        try:
            import asyncio
            new_tokens = asyncio.get_event_loop().run_until_complete(
                _refresh_token(refresh)
            )
            if new_tokens:
                entry.update(new_tokens)
                entry["expires_at"] = time.time() + new_tokens.get("expires_in", 3600)
                _token_cache[user_id] = entry
                return entry
        except Exception as e:
            log.warning("Token refresh failed for user %s: %s", user_id[:8], e)
    del _token_cache[user_id]
    return None


async def _refresh_token(refresh_token: str) -> dict[str, Any] | None:
    """Refresca un access token usando refresh_token."""
    if not _is_configured():
        return None

    token_url = f"{AUTH_BASE}/{settings.azure_tenant_id}/oauth2/v2.0/token"
    payload = {
        "client_id": settings.azure_client_id,
        "client_secret": settings.azure_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": " ".join(OUTLOOK_SCOPES),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data=payload)
        if resp.status_code >= 400:
            log.warning("Token refresh failed: %s", resp.text[:200])
            return None
        return resp.json()


async def _acquire_token_by_code(code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
    """Intercambia authorization code por access + refresh tokens."""
    if not _is_configured():
        raise ValueError("Outlook no configurado. Faltan AZURE_CLIENT_ID, AZURE_TENANT_ID o AZURE_CLIENT_SECRET.")

    token_url = f"{AUTH_BASE}/{settings.azure_tenant_id}/oauth2/v2.0/token"
    payload = {
        "client_id": settings.azure_client_id,
        "client_secret": settings.azure_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
        "scope": " ".join(OUTLOOK_SCOPES),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(token_url, data=payload)
        if resp.status_code >= 400:
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_data.get("error_description", resp.text[:300])
            raise RuntimeError(f"Error intercambiando código OAuth: {error_msg}")
        return resp.json()


async def _get_user_profile(access_token: str) -> dict[str, Any]:
    """Obtiene el perfil del usuario autenticado via /me."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


# ─── Configuración ─────────────────────────────────────────────────────

def _is_configured() -> bool:
    return bool(
        settings.outlook_enabled
        and settings.azure_client_id
        and settings.azure_tenant_id
        and settings.azure_client_secret
    )


def get_connection_status(user_id: str) -> OutlookConnectionStatus:
    """Retorna el estado de conexión Outlook de un usuario."""
    if not settings.outlook_enabled:
        return OutlookConnectionStatus(error="Outlook no habilitado (OUTLOOK_ENABLED=false)")
    if not _is_configured():
        return OutlookConnectionStatus(error="Outlook no configurado (faltan credenciales Azure)")

    entry = _token_cache.get(user_id)
    if entry and entry.get("expires_at", 0) > time.time():
        return OutlookConnectionStatus(
            linked=True,
            user_email=entry.get("user_email"),
            user_name=entry.get("user_name"),
            last_linked_at=entry.get("linked_at"),
        )

    return OutlookConnectionStatus(linked=False, error="No conectado. Usa /v1/outlook/auth-url para vincular.")


# ─── Flujo OAuth ────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Genera code_verifier + code_challenge para PKCE (S256)."""
    import base64
    import hashlib

    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def build_auth_url(redirect_uri: str, state: str | None = None) -> dict[str, Any]:
    """Construye la URL de autorización OAuth2 de Microsoft.

    Args:
        redirect_uri: URL de callback registrada en Azure AD
        state: Estado opcional (si no se provee, se genera uno nuevo)

    Returns:
        dict con {auth_url, state, code_verifier}
    """
    if not _is_configured():
        raise ValueError("Outlook no configurado. Faltan AZURE_CLIENT_ID, AZURE_TENANT_ID o AZURE_CLIENT_SECRET.")

    code_verifier, code_challenge = generate_pkce_pair()
    if not state:
        state = secrets.token_urlsafe(32)

    auth_params = {
        "client_id": settings.azure_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(OUTLOOK_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "response_mode": "query",
    }

    auth_url = f"{AUTH_BASE}/{settings.azure_tenant_id}/oauth2/v2.0/authorize?{urlencode(auth_params)}"

    # Guardar estado pendiente (TTL 10 minutos)
    _pending_states[state] = {
        "code_verifier": code_verifier,
        "expires_at": time.time() + 600,
    }

    return {
        "auth_url": auth_url,
        "state": state,
    }


def complete_auth_callback(code: str, state: str, redirect_uri: str, user_id: str) -> dict[str, Any]:
    """Completa el flujo OAuth: intercambia code por tokens y guarda la conexión.

    Args:
        code: Código de autorización de Microsoft
        state: Estado OAuth (debe coincidir con el generado)
        redirect_uri: URL de callback usada
        user_id: ID del usuario DOT

    Returns:
        dict con {ok, user_email, user_name}
    """
    import asyncio

    pending = _pending_states.pop(state, None)
    if not pending:
        raise ValueError("Estado OAuth inválido o expirado. Inicia el flujo de nuevo.")
    if pending["expires_at"] < time.time():
        raise ValueError("Estado OAuth expirado. Inicia el flujo de nuevo.")

    code_verifier = pending["code_verifier"]

    try:
        tokens = asyncio.get_event_loop().run_until_complete(
            _acquire_token_by_code(code, redirect_uri, code_verifier)
        )
    except Exception as e:
        log.exception("Error adquiriendo token OAuth para user %s", user_id[:8])
        raise RuntimeError(f"No se pudo completar la autenticación: {e}") from e

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")

    # Obtener perfil del usuario
    profile = asyncio.get_event_loop().run_until_complete(_get_user_profile(access_token))

    user_email = profile.get("mail") or profile.get("userPrincipalName", "desconocido")
    user_name = profile.get("displayName", user_email)

    # Guardar en caché
    _token_cache[user_id] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + tokens.get("expires_in", 3600),
        "scope": tokens.get("scope", ""),
        "user_email": user_email,
        "user_name": user_name,
        "linked_at": datetime.now(timezone.utc).isoformat(),
    }

    log.info("Outlook vinculado: user=%s email=%s", user_id[:8], user_email)
    return {
        "ok": True,
        "user_email": user_email,
        "user_name": user_name,
    }


# ─── Helpers Graph API ─────────────────────────────────────────────────

def _ensure_token(user_id: str) -> str:
    """Obtiene un access token válido para el usuario. Lanza excepción si no hay."""
    entry = _get_token(user_id)
    if not entry:
        raise PermissionError("Outlook no vinculado. Usa /v1/outlook/auth-url para conectar tu cuenta Microsoft 365.")
    return entry["access_token"]


async def _graph_get(user_id: str, endpoint: str, params: dict | None = None, timeout: int = 20) -> dict:
    """GET a MS Graph API con token delegado del usuario."""
    token = _ensure_token(user_id)
    url = f"{GRAPH_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers, params=params)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            log.warning("Graph GET %s → %d: %s", endpoint, resp.status_code, str(data)[:200])
            raise RuntimeError(f"MS Graph error {resp.status_code}: {data.get('error', {}).get('message', str(data))}")
        return data


async def _graph_post(user_id: str, endpoint: str, payload: dict, timeout: int = 20) -> dict:
    """POST a MS Graph API con token delegado del usuario."""
    token = _ensure_token(user_id)
    url = f"{GRAPH_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            log.warning("Graph POST %s → %d: %s", endpoint, resp.status_code, str(data)[:200])
            raise RuntimeError(f"MS Graph error {resp.status_code}: {data.get('error', {}).get('message', str(data))}")
        return data


# ─── EMAIL ─────────────────────────────────────────────────────────────

async def list_inbox(
    user_id: str,
    top: int = 20,
    skip: int = 0,
    folder: str = "inbox",
    order_by: str = "receivedDateTime desc",
) -> dict[str, Any]:
    """Lista correos del inbox del usuario.

    Args:
        user_id: ID del usuario DOT
        top: Número máximo de correos a retornar (1-100)
        skip: Offset para paginación
        folder: Carpeta de correo ("inbox", "sentitems", "drafts", "deleteditems")
        order_by: Ordenamiento

    Returns:
        dict con {total, emails: [{id, subject, from, received, is_read, has_attachments, preview}]}
    """
    top = max(1, min(top, 100))
    folder_id = _folder_name_to_id(folder)

    params = {
        "$top": top,
        "$skip": skip,
        "$orderby": order_by,
        "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview,importance,internetMessageId",
    }

    data = await _graph_get(
        user_id,
        f"/me/mailFolders/{folder_id}/messages",
        params=params,
    )

    emails = []
    for msg in data.get("value", []):
        sender = msg.get("from", {}).get("emailAddress", {})
        emails.append({
            "id": msg.get("id", ""),
            "subject": msg.get("subject", "(sin asunto)"),
            "from_name": sender.get("name", "Desconocido"),
            "from_email": sender.get("address", ""),
            "received": msg.get("receivedDateTime", ""),
            "is_read": msg.get("isRead", False),
            "has_attachments": msg.get("hasAttachments", False),
            "preview": (msg.get("bodyPreview", "") or "")[:200],
            "importance": msg.get("importance", "normal"),
        })

    return {
        "total": len(emails),
        "folder": folder,
        "emails": emails,
    }


async def get_message(user_id: str, message_id: str) -> dict[str, Any]:
    """Obtiene un mensaje completo por ID."""
    params = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,sentDateTime,"
                   "isRead,hasAttachments,body,bodyPreview,importance,internetMessageId,"
                   "conversationId,flag,attachments",
    }
    data = await _graph_get(user_id, f"/me/messages/{message_id}", params=params)

    sender = data.get("from", {}).get("emailAddress", {})
    to_list = data.get("toRecipients", [])
    cc_list = data.get("ccRecipients", [])

    body = data.get("body", {})
    body_content = body.get("content", "") if body.get("contentType") == "text" else body.get("content", "")

    return {
        "id": data.get("id", ""),
        "subject": data.get("subject", "(sin asunto)"),
        "from_name": sender.get("name", "Desconocido"),
        "from_email": sender.get("address", ""),
        "to": [r.get("emailAddress", {}).get("address", "") for r in to_list],
        "cc": [r.get("emailAddress", {}).get("address", "") for r in cc_list],
        "received": data.get("receivedDateTime", ""),
        "sent": data.get("sentDateTime", ""),
        "is_read": data.get("isRead", False),
        "has_attachments": data.get("hasAttachments", False),
        "body": body_content[:5000],
        "body_preview": data.get("bodyPreview", "")[:300],
        "importance": data.get("importance", "normal"),
        "conversation_id": data.get("conversationId", ""),
    }


async def search_messages(
    user_id: str,
    query: str,
    top: int = 20,
    folder: str = "inbox",
) -> dict[str, Any]:
    """Busca correos en el buzón del usuario.

    Args:
        user_id: ID del usuario DOT
        query: Término de búsqueda (soporta KQL: from:, subject:, hasAttachments:true, etc.)
        top: Máximo de resultados (1-100)
        folder: Carpeta donde buscar

    Returns:
        dict con {total, query, emails: [...]}
    """
    top = max(1, min(top, 100))
    folder_id = _folder_name_to_id(folder)

    # Usar $search para búsqueda full-text en el folder especificado
    params = {
        "$search": f'"{query}"',
        "$top": top,
        "$select": "id,subject,from,receivedDateTime,isRead,hasAttachments,bodyPreview,importance",
        "$orderby": "receivedDateTime desc",
    }

    data = await _graph_get(
        user_id,
        f"/me/mailFolders/{folder_id}/messages",
        params=params,
    )

    emails = []
    for msg in data.get("value", []):
        sender = msg.get("from", {}).get("emailAddress", {})
        emails.append({
            "id": msg.get("id", ""),
            "subject": msg.get("subject", "(sin asunto)"),
            "from_name": sender.get("name", "Desconocido"),
            "from_email": sender.get("address", ""),
            "received": msg.get("receivedDateTime", ""),
            "is_read": msg.get("isRead", False),
            "has_attachments": msg.get("hasAttachments", False),
            "preview": (msg.get("bodyPreview", "") or "")[:200],
        })

    return {
        "total": len(emails),
        "query": query,
        "folder": folder,
        "emails": emails,
    }


async def send_message(
    user_id: str,
    to: list[str],
    subject: str,
    body: str,
    body_type: str = "Text",
    cc: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Envía un correo desde la cuenta Microsoft 365 del usuario.

    Args:
        user_id: ID del usuario DOT
        to: Lista de destinatarios (emails)
        subject: Asunto del correo
        body: Cuerpo del mensaje
        body_type: "Text" o "HTML"
        cc: Lista de emails en copia
        attachments: Lista de adjuntos [{name, contentBytes (base64), contentType}]

    Returns:
        dict con {ok, message_id, sent_at}
    """
    message: dict[str, Any] = {
        "subject": subject,
        "body": {
            "contentType": body_type,
            "content": body,
        },
        "toRecipients": [{"emailAddress": {"address": addr.strip()}} for addr in to if addr.strip()],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr.strip()}} for addr in cc if addr.strip()]

    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att.get("name", f"attachment_{i}"),
                "contentType": att.get("contentType", "application/octet-stream"),
                "contentBytes": att.get("contentBytes", ""),
            }
            for i, att in enumerate(attachments)
        ]

    result = await _graph_post(user_id, "/me/sendMail", {"message": message, "saveToSentItems": True})

    return {
        "ok": True,
        "message_id": str(uuid.uuid4())[:12],
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── CALENDAR ──────────────────────────────────────────────────────────

async def list_events(
    user_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    top: int = 50,
) -> dict[str, Any]:
    """Lista eventos del calendario del usuario.

    Args:
        user_id: ID del usuario DOT
        start_date: Fecha inicio ISO (default: hoy)
        end_date: Fecha fin ISO (default: +7 días)
        top: Máximo de eventos (1-100)

    Returns:
        dict con {total, events: [...]}
    """
    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    if not end_date:
        end_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59Z")

    top = max(1, min(top, 100))

    params = {
        "startDateTime": start_date,
        "endDateTime": end_date,
        "$top": top,
        "$select": "id,subject,start,end,location,organizer,bodyPreview,importance,"
                    "isAllDay,isCancelled,sensitivity,showAs,onlineMeeting",
        "$orderby": "start/dateTime asc",
    }

    data = await _graph_get(user_id, "/me/calendarView", params=params)

    events = []
    for ev in data.get("value", []):
        start = ev.get("start", {})
        end = ev.get("end", {})
        organizer = ev.get("organizer", {}).get("emailAddress", {})
        location = ev.get("location", {}).get("displayName", "")
        online = ev.get("onlineMeeting", {}).get("joinUrl", "")

        events.append({
            "id": ev.get("id", ""),
            "subject": ev.get("subject", "(sin título)"),
            "start": f"{start.get('dateTime', '')}",
            "start_tz": start.get("timeZone", "UTC"),
            "end": f"{end.get('dateTime', '')}",
            "end_tz": end.get("timeZone", "UTC"),
            "is_all_day": ev.get("isAllDay", False),
            "location": location,
            "organizer": organizer.get("name", ""),
            "organizer_email": organizer.get("address", ""),
            "preview": (ev.get("bodyPreview", "") or "")[:200],
            "importance": ev.get("importance", "normal"),
            "is_cancelled": ev.get("isCancelled", False),
            "online_meeting_url": online,
            "show_as": ev.get("showAs", "busy"),
        })

    return {
        "total": len(events),
        "start": start_date,
        "end": end_date,
        "events": events,
    }


async def create_event(
    user_id: str,
    subject: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone: str = "America/Bogota",
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Crea un evento en el calendario del usuario.

    Args:
        user_id: ID del usuario DOT
        subject: Título del evento
        start_dt: Fecha/hora inicio (datetime)
        end_dt: Fecha/hora fin (datetime)
        timezone: Zona horaria (IANA)
        location: Ubicación opcional
        body: Descripción en texto
        attendees: Lista de emails de asistentes

    Returns:
        dict con {ok, event_id, subject, start, end}
    """
    payload: dict[str, Any] = {
        "subject": subject,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone,
        },
    }

    if location:
        payload["location"] = {"displayName": location}
    if body:
        payload["body"] = {"contentType": "text", "content": body}
    if attendees:
        payload["attendees"] = [
            {
                "emailAddress": {"address": email.strip()},
                "type": "required",
            }
            for email in attendees
            if email.strip()
        ]

    data = await _graph_post(user_id, "/me/events", payload)

    return {
        "ok": True,
        "event_id": data.get("id", ""),
        "subject": subject,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


async def get_free_slots(
    user_id: str,
    start_date: str,
    end_date: str,
    duration_minutes: int = 30,
    working_hours_start: int = 8,
    working_hours_end: int = 18,
    timezone: str = "America/Bogota",
) -> dict[str, Any]:
    """Encuentra slots libres en el calendario del usuario.

    Args:
        user_id: ID del usuario DOT
        start_date: Fecha inicio ISO
        end_date: Fecha fin ISO
        duration_minutes: Duración mínima del slot (default 30)
        working_hours_start: Hora inicio laboral (default 8)
        working_hours_end: Hora fin laboral (default 18)
        timezone: Zona horaria IANA

    Returns:
        dict con {total_slots, slots: [{start, end, duration_min}]}
    """
    # Obtener eventos en el rango (hasta 100 para ser razonable)
    params = {
        "startDateTime": start_date,
        "endDateTime": end_date,
        "$top": 100,
        "$select": "start,end,showAs,isAllDay,isCancelled",
        "$orderby": "start/dateTime asc",
    }
    data = await _graph_get(user_id, "/me/calendarView", params=params)

    # Parsear fecha inicio/fin
    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

    # Generar slots candidatos (solo en horas laborales)
    slots = []
    current = start_dt
    while current + timedelta(minutes=duration_minutes) <= end_dt:
        hour = current.hour
        if working_hours_start <= hour < working_hours_end:
            slot_end = current + timedelta(minutes=duration_minutes)
            slots.append((current, slot_end))
        current += timedelta(minutes=duration_minutes)

    # Filtrar slots ocupados
    busy_periods = []
    for ev in data.get("value", []):
        if ev.get("isCancelled", False):
            continue
        if ev.get("showAs", "busy") == "free":
            continue
        ev_start = datetime.fromisoformat(ev.get("start", {}).get("dateTime", "").replace("Z", "+00:00"))
        ev_end = datetime.fromisoformat(ev.get("end", {}).get("dateTime", "").replace("Z", "+00:00"))
        busy_periods.append((ev_start, ev_end))

    free_slots = []
    for slot_start, slot_end in slots:
        is_free = True
        for busy_start, busy_end in busy_periods:
            if slot_start < busy_end and slot_end > busy_start:
                is_free = False
                break
        if is_free:
            free_slots.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "duration_min": duration_minutes,
            })

    return {
        "total_slots": len(free_slots),
        "start": start_date,
        "end": end_date,
        "duration_minutes": duration_minutes,
        "slots": free_slots[:20],  # Limitar a 20 slots
    }


# ─── CONTACTOS ─────────────────────────────────────────────────────────

async def list_contacts(
    user_id: str,
    top: int = 50,
    query: str | None = None,
) -> dict[str, Any]:
    """Lista contactos del usuario en Microsoft 365 / Outlook.

    Args:
        user_id: ID del usuario DOT
        top: Máximo de contactos (1-200)
        query: Término de búsqueda opcional (nombre o email)

    Returns:
        dict con {total, contacts: [...]}
    """
    top = max(1, min(top, 200))
    params: dict[str, Any] = {
        "$top": top,
        "$select": "id,displayName,givenName,surname,emailAddresses,businessPhones,"
                    "mobilePhone,companyName,jobTitle,department,personalNotes",
        "$orderby": "displayName asc",
    }

    if query:
        params["$search"] = f'"{query}"'

    data = await _graph_get(user_id, "/me/contacts", params=params)

    contacts = []
    for c in data.get("value", []):
        emails = c.get("emailAddresses", [])
        contacts.append({
            "id": c.get("id", ""),
            "display_name": c.get("displayName", ""),
            "given_name": c.get("givenName", ""),
            "surname": c.get("surname", ""),
            "emails": [e.get("address", "") for e in emails],
            "business_phones": c.get("businessPhones", []),
            "mobile_phone": c.get("mobilePhone", ""),
            "company": c.get("companyName", ""),
            "job_title": c.get("jobTitle", ""),
            "department": c.get("department", ""),
            "notes": (c.get("personalNotes", "") or "")[:200],
        })

    return {
        "total": len(contacts),
        "contacts": contacts,
    }


async def get_contact(user_id: str, contact_id: str) -> dict[str, Any]:
    """Obtiene un contacto específico por ID."""
    params = {
        "$select": "id,displayName,givenName,surname,emailAddresses,businessPhones,"
                    "mobilePhone,companyName,jobTitle,department,personalNotes,"
                    "homePhones,imAddresses,homeAddress,businessAddress",
    }
    data = await _graph_get(user_id, f"/me/contacts/{contact_id}", params=params)

    emails = data.get("emailAddresses", [])
    return {
        "id": data.get("id", ""),
        "display_name": data.get("displayName", ""),
        "given_name": data.get("givenName", ""),
        "surname": data.get("surname", ""),
        "emails": [e.get("address", "") for e in emails],
        "business_phones": data.get("businessPhones", []),
        "mobile_phone": data.get("mobilePhone", ""),
        "company": data.get("companyName", ""),
        "job_title": data.get("jobTitle", ""),
        "department": data.get("department", ""),
        "notes": (data.get("personalNotes", "") or "")[:500],
    }


# ─── Helpers ───────────────────────────────────────────────────────────

def _folder_name_to_id(folder: str) -> str:
    """Convierte nombres amigables a well-known folder ids de MS Graph."""
    mapping = {
        "inbox": "inbox",
        "sentitems": "sentitems",
        "drafts": "drafts",
        "deleteditems": "deleteditems",
        "junkemail": "junkemail",
        "archive": "archive",
        "outbox": "outbox",
    }
    return mapping.get(folder.lower().replace(" ", ""), "inbox")
