"""Router para integración Microsoft 365 / Outlook via MS Graph API.

Consumido por el frontend Electron para gestionar correo, calendario y
contactos de la cuenta Microsoft 365 del usuario.

Gate: OUTLOOK_ENABLED=true habilita todos los endpoints.
Requiere app registration en Azure AD con permisos delegados:
  - Mail.Read, Mail.Send, Calendars.Read, Calendars.ReadWrite,
    Contacts.Read, User.Read, offline_access

Endpoints:
- GET  /v1/outlook/status        → estado de conexión
- GET  /v1/outlook/auth-url      → URL de autorización OAuth
- POST /v1/outlook/callback      → callback OAuth (intercambia code)
- GET  /v1/outlook/emails        → listar correos
- GET  /v1/outlook/emails/{id}   → leer correo
- GET  /v1/outlook/emails/search → buscar correos
- POST /v1/outlook/emails/send   → enviar correo
- GET  /v1/outlook/calendar      → listar eventos
- POST /v1/outlook/calendar/events → crear evento
- GET  /v1/outlook/calendar/free-slots → slots libres
- GET  /v1/outlook/contacts      → listar contactos
- GET  /v1/outlook/contacts/{id} → ver contacto
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter
from app.services.outlook_service import (
    build_auth_url,
    complete_auth_callback,
    get_connection_status,
    list_inbox,
    get_message,
    search_messages,
    send_message,
    list_events,
    create_event,
    get_free_slots,
    list_contacts,
    get_contact,
)
from app.settings import settings

log = logging.getLogger("dot.outlook_router")

router = APIRouter(prefix="/v1/outlook", tags=["outlook"])


# ─── Schemas ──────────────────────────────────────────────────────────

class OutlookStatusResponse(BaseModel):
    enabled: bool = False
    linked: bool = False
    user_email: str | None = None
    user_name: str | None = None
    last_linked_at: str | None = None
    error: str | None = None


class AuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class CallbackInput(BaseModel):
    code: str = Field(..., description="Código de autorización de Microsoft")
    state: str = Field(..., description="Estado OAuth (debe coincidir)")
    redirect_uri: str = Field(
        default="http://127.0.0.1:8000/v1/outlook/callback",
        description="URL de callback usada en el flujo",
    )


class CallbackResponse(BaseModel):
    ok: bool
    user_email: str | None = None
    user_name: str | None = None


class SendEmailInput(BaseModel):
    to: list[str] = Field(..., min_length=1, description="Lista de destinatarios")
    subject: str = Field(..., min_length=1, max_length=998, description="Asunto del correo")
    body: str = Field(..., min_length=1, description="Cuerpo del mensaje")
    body_type: str = Field(default="Text", pattern="^(Text|HTML)$", description="Tipo de cuerpo")
    cc: list[str] | None = Field(default=None, description="Emails en copia")
    attachments: list[dict] | None = Field(default=None, description="Adjuntos [{name, contentBytes, contentType}]")


class SendEmailResponse(BaseModel):
    ok: bool
    message_id: str
    sent_at: str


class CreateEventInput(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500, description="Título del evento")
    start_dt: str = Field(..., description="Fecha/hora inicio ISO 8601")
    end_dt: str = Field(..., description="Fecha/hora fin ISO 8601")
    timezone: str = Field(default="America/Bogota", description="Zona horaria IANA")
    location: str | None = Field(default=None, description="Ubicación")
    body: str | None = Field(default=None, description="Descripción")
    attendees: list[str] | None = Field(default=None, description="Emails de asistentes")


class CreateEventResponse(BaseModel):
    ok: bool
    event_id: str
    subject: str
    start: str
    end: str


# ─── Gate helper ───────────────────────────────────────────────────────

def _check_enabled():
    """Lanza 404 si Outlook no está habilitado."""
    if not settings.outlook_enabled:
        raise HTTPException(status_code=404, detail="Integración Outlook no habilitada (OUTLOOK_ENABLED=false)")


def _get_uid(claims: dict[str, object]) -> str:
    return claims_uid(claims)


# ─── Status ────────────────────────────────────────────────────────────

@router.get("/status", response_model=OutlookStatusResponse)
async def outlook_status(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Estado actual de la conexión Outlook del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)
    status = get_connection_status(user_id)
    return OutlookStatusResponse(
        enabled=settings.outlook_enabled,
        linked=status.linked,
        user_email=status.user_email,
        user_name=status.user_name,
        last_linked_at=status.last_linked_at,
        error=status.error,
    )


# ─── OAuth ─────────────────────────────────────────────────────────────

@router.get("/auth-url", response_model=AuthUrlResponse)
@limiter.limit("10/minute")
async def outlook_auth_url(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
    redirect_uri: str = Query(default="http://127.0.0.1:8000/v1/outlook/callback"),
):
    """Genera la URL de autorización OAuth2 de Microsoft para vincular la cuenta.

    El usuario debe abrir esta URL en su navegador, iniciar sesión con su cuenta
    Microsoft 365 y autorizar los permisos solicitados. Microsoft redirigirá al
    callback con un código de autorización.
    """
    _check_enabled()
    result = build_auth_url(redirect_uri)
    return AuthUrlResponse(auth_url=result["auth_url"], state=result["state"])


@router.post("/callback", response_model=CallbackResponse)
@limiter.limit("10/minute")
async def outlook_callback(
    request: Request,
    body: CallbackInput,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Callback OAuth: intercambia el código de autorización por tokens.

    Este endpoint completa el flujo OAuth2. El frontend debe llamarlo después
    de que Microsoft redirija al usuario de vuelta con ?code=...&state=...
    """
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = complete_auth_callback(
            code=body.code,
            state=body.state,
            redirect_uri=body.redirect_uri,
            user_id=user_id,
        )
        return CallbackResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Emails ────────────────────────────────────────────────────────────

@router.get("/emails")
@limiter.limit("30/minute")
async def outlook_list_emails(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
    top: int = Query(default=20, ge=1, le=100, description="Cantidad de correos"),
    skip: int = Query(default=0, ge=0, description="Offset para paginación"),
    folder: str = Query(default="inbox", description="Carpeta: inbox, sentitems, drafts, deleteditems"),
    order_by: str = Query(default="receivedDateTime desc", description="Ordenamiento"),
):
    """Lista los correos recientes de la bandeja del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await list_inbox(
            user_id=user_id,
            top=top,
            skip=skip,
            folder=folder,
            order_by=order_by,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/emails/search")
@limiter.limit("30/minute")
async def outlook_search_emails(
    request: Request,
    q: str = Query(..., min_length=1, description="Término de búsqueda (KQL)"),
    claims: dict[str, object] = Depends(require_product_jwt),
    top: int = Query(default=20, ge=1, le=100),
    folder: str = Query(default="inbox"),
):
    """Busca correos en el buzón del usuario usando KQL."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await search_messages(
            user_id=user_id,
            query=q,
            top=top,
            folder=folder,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/emails/{message_id}")
@limiter.limit("60/minute")
async def outlook_get_email(
    request: Request,
    message_id: str,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Obtiene un correo completo por ID."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await get_message(user_id=user_id, message_id=message_id)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/emails/send", response_model=SendEmailResponse)
@limiter.limit("10/minute")
async def outlook_send_email(
    request: Request,
    body: SendEmailInput,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Envía un correo desde la cuenta Microsoft 365 del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await send_message(
            user_id=user_id,
            to=body.to,
            subject=body.subject,
            body=body.body,
            body_type=body.body_type,
            cc=body.cc,
            attachments=body.attachments,
        )
        return SendEmailResponse(**result)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Calendar ──────────────────────────────────────────────────────────

@router.get("/calendar")
@limiter.limit("30/minute")
async def outlook_list_events(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
    start: str | None = Query(default=None, description="Fecha inicio ISO"),
    end: str | None = Query(default=None, description="Fecha fin ISO"),
    top: int = Query(default=50, ge=1, le=100),
):
    """Lista eventos del calendario Microsoft 365 del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await list_events(
            user_id=user_id,
            start_date=start,
            end_date=end,
            top=top,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/calendar/events", response_model=CreateEventResponse)
@limiter.limit("20/minute")
async def outlook_create_event(
    request: Request,
    body: CreateEventInput,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Crea un evento en el calendario Microsoft 365 del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        start_dt = datetime.fromisoformat(body.start_dt)
        end_dt = datetime.fromisoformat(body.end_dt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Formato de fecha inválido: {e}")

    try:
        result = await create_event(
            user_id=user_id,
            subject=body.subject,
            start_dt=start_dt,
            end_dt=end_dt,
            timezone=body.timezone,
            location=body.location,
            body=body.body,
            attendees=body.attendees,
        )
        return CreateEventResponse(**result)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/calendar/free-slots")
@limiter.limit("30/minute")
async def outlook_free_slots(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
    start: str = Query(..., description="Fecha inicio ISO"),
    end: str = Query(..., description="Fecha fin ISO"),
    duration: int = Query(default=30, ge=15, le=480, description="Duración mínima en minutos"),
    work_start: int = Query(default=8, ge=0, le=23, description="Hora inicio laboral"),
    work_end: int = Query(default=18, ge=1, le=24, description="Hora fin laboral"),
    timezone: str = Query(default="America/Bogota"),
):
    """Encuentra slots libres en el calendario del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await get_free_slots(
            user_id=user_id,
            start_date=start,
            end_date=end,
            duration_minutes=duration,
            working_hours_start=work_start,
            working_hours_end=work_end,
            timezone=timezone,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Contacts ──────────────────────────────────────────────────────────

@router.get("/contacts")
@limiter.limit("30/minute")
async def outlook_list_contacts(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
    top: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, description="Buscar por nombre o email"),
):
    """Lista los contactos de Microsoft 365 / Outlook del usuario."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await list_contacts(
            user_id=user_id,
            top=top,
            query=q,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/contacts/{contact_id}")
@limiter.limit("60/minute")
async def outlook_get_contact(
    request: Request,
    contact_id: str,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Obtiene un contacto específico por ID."""
    _check_enabled()
    user_id = _get_uid(claims)

    try:
        result = await get_contact(user_id=user_id, contact_id=contact_id)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
