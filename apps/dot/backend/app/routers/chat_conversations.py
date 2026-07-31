"""Chat: historial, listado, agenda, recordatorios, traducir, resumir, conversaciones.

B01: Multi-chat — endpoints CRUD de conversaciones con channel, soft-delete
y paginación de mensajes.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import claims_uid, require_product_jwt
from app.firebase_db import FIRESTORE_AVAILABLE
from app.billing_db import get_billing_db
from app.dependencies.limiter import limiter
from app.deps.ai_provider import get_ai_provider
from app.settings import settings
from app.services.ai_provider import AIProvider
from app.services.chat_crypto import decrypt_message
from app.services.chat_persistence import (
    load_recent_history,
    list_user_conversations,
    create_conversation,
    rename_conversation,
    delete_conversation,
    auto_title_conversation,
    list_archived_conversations,
    unarchive_conversation,
    search_conversation_messages,
    conversation_title_from_user_text,
)
from app.routers.chat_utils import (
    AgendaEventResponse,
    AgendaTodayResponse,
    ReminderCreateRequest,
    ReminderCreateResponse,
    ReminderPendingItem,
    ReminderPendingResponse,
    ReminderAckRequest,
    TranslateRequest,
    TranslateResponse,
    SummarizeRequest,
    SummarizeResponse,
    RenameConversationRequest,
    CreateConversationRequest,
    ConversationResponse,
)

log = logging.getLogger("dot.chat")

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.get("/agenda/today", response_model=AgendaTodayResponse)
def chat_agenda_today(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    uid = str(claims.get("sub") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido.")

    from app.services import calendar_service

    try:
        events = calendar_service.list_today(uid)
    except calendar_service.MissingCalendarCredentialsError:
        return AgendaTodayResponse(
            linked=False,
            events=[],
            message="Google Calendar no esta vinculado. Configuralo desde Ajustes para usar /agenda.",
        )
    except calendar_service.CalendarIntegrationError:
        log.warning("Agenda error por credenciales para uid=%s", uid, exc_info=True)
        return AgendaTodayResponse(
            linked=False,
            events=[],
            message="No se pudo consultar Google Calendar. Revisa la vinculacion OAuth y vuelve a intentar.",
        )
    except Exception:
        log.exception("Error inesperado consultando /agenda para uid=%s", uid)
        return AgendaTodayResponse(
            linked=False,
            events=[],
            message="No se pudo consultar tu agenda en este momento.",
        )

    if not events:
        return AgendaTodayResponse(
            linked=True,
            events=[],
            message=calendar_service.render_today_agenda(events),
        )

    parsed = [
        AgendaEventResponse(
            summary=str(item.get("summary") or "(sin titulo)"),
            start=str(item.get("start")) if item.get("start") else None,
            end=str(item.get("end")) if item.get("end") else None,
            html_link=str(item.get("html_link")) if item.get("html_link") else None,
        )
        for item in events
    ]
    return AgendaTodayResponse(
        linked=True,
        events=parsed,
        message=f"Tienes {len(parsed)} evento(s) para hoy:\n\n{calendar_service.render_today_agenda(events)}",
    )


def _require_reminder_service(request: Request):
    service = getattr(request.app.state, "reminder_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Servicio de recordatorios no disponible.",
        )
    return service


@router.post("/reminders", response_model=ReminderCreateResponse)
@limiter.limit("10/minute")
def create_chat_reminder(
    request: Request,
    body: ReminderCreateRequest,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_reminder_service(request)
    try:
        created = service.create_reminder(uid, body.text, body.due_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error creando recordatorio para uid=%s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="No se pudo crear el recordatorio.") from exc

    due_at = str(created.get("due_at", ""))
    return ReminderCreateResponse(
        ok=True,
        id=str(created.get("id", "")),
        due_at=due_at,
        message=f"Recordatorio guardado para {due_at}. Te avisare en la app cuando venza.",
    )


@router.get("/reminders/pending", response_model=ReminderPendingResponse)
def list_pending_chat_reminders(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("list_pending_chat_reminders: Firestore no disponible, retornando vacio")
        return ReminderPendingResponse(reminders=[])
    service = _require_reminder_service(request)
    try:
        reminders = service.list_pending_notifications(uid, limit=25)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error listando recordatorios pendientes para uid=%s: %s", uid, exc)
        raise HTTPException(
            status_code=500,
            detail="No se pudieron cargar los recordatorios pendientes.",
        ) from exc

    return ReminderPendingResponse(
        reminders=[
            ReminderPendingItem(
                id=str(item.get("id", "")),
                text=str(item.get("text", "")),
                due_at=str(item.get("due_at", "")),
            )
            for item in reminders
            if str(item.get("id", "")).strip() and str(item.get("text", "")).strip()
        ]
    )


@router.post("/reminders/ack")
@limiter.limit("10/minute")
def ack_chat_reminders(
    request: Request,
    body: ReminderAckRequest,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_reminder_service(request)
    try:
        count = service.ack_notifications(uid, body.ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error confirmando recordatorios para uid=%s: %s", uid, exc)
        raise HTTPException(
            status_code=500,
            detail="No se pudieron confirmar los recordatorios.",
        ) from exc
    return {"ok": True, "acked": count}


@router.post("/translate", response_model=TranslateResponse)
@limiter.limit("10/minute")
def chat_translate(
    request: Request,
    body: TranslateRequest,
    claims: dict = Depends(require_product_jwt),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    uid = claims_uid(claims)
    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido.")

    from app.services.provider_router import ProviderNotAvailableError, route_translate

    try:
        translated_text, provider_used, target_lang = route_translate(
            text=body.text,
            target_lang=body.target_lang,
            provider_id=body.provider or settings.default_chat_provider or "deepseek",
            ai_provider=ai_provider,
        )
        return TranslateResponse(
            translated_text=translated_text,
            provider=provider_used,
            target_lang=target_lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error traduciendo texto para uid=%s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="No se pudo completar la traduccion.") from exc


@router.post("/summarize", response_model=SummarizeResponse)
@limiter.limit("10/minute")
def chat_summarize(
    request: Request,
    body: SummarizeRequest,
    claims: dict = Depends(require_product_jwt),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    uid = claims_uid(claims)
    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido.")

    from app.services.provider_router import ProviderNotAvailableError, route_summarize

    try:
        summary, source_type, chunks = route_summarize(
            content=body.content,
            provider_id=body.provider or settings.default_chat_provider or "deepseek",
            ai_provider=ai_provider,
        )
        return SummarizeResponse(
            summary=summary,
            source_type=source_type,
            chunks=chunks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error resumiendo contenido para uid=%s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="No se pudo completar el resumen.") from exc


# ══════════════════════════════════════════════════════════════════
# B01: Endpoints de conversaciones (Multi-chat)
# ══════════════════════════════════════════════════════════════════


@router.get("/conversations/{conversation_id}/history")
def chat_history(
    request: Request,
    conversation_id: str,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=200, description="Mensajes por página"),
):
    """Obtiene historial paginado de conversación desde BD (B01)."""
    uid = claims_uid(claims)

    offset = (page - 1) * page_size
    messages, total = load_recent_history(db, uid, conversation_id, limit=page_size, offset=offset)

    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "text": decrypt_message(m.content),
                "createdAt": m.created_at.isoformat() if m.created_at else "",
                "status": "sent",
            }
            for m in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/conversations")
def chat_list_conversations(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    q: str | None = Query(None, max_length=200, description="Filtrar por título o contenido"),
    include_archived: bool = Query(False, description="Incluir conversaciones archivadas"),
    search_messages: bool = Query(False, description="Buscar también en contenido de mensajes"),
):
    """Lista conversaciones del usuario (B01)."""
    uid = claims_uid(claims)

    if include_archived:
        convs = list_archived_conversations(
            db, uid, query=q, search_messages=search_messages
        )
    else:
        convs = list_user_conversations(
            db, uid, query=q, include_archived=include_archived, search_messages=search_messages
        )

    return {
        "conversations": [
            {
                "id": str(c.id),
                "title": c.title,
                "provider": c.provider,
                "channel": c.channel or "pc",
                "message_count": c.message_count or 0,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
                "archived": c.archived_at is not None,
            }
            for c in convs
        ],
    }


@router.post("/conversations", response_model=ConversationResponse)
def chat_create_conversation(
    request: Request,
    body: CreateConversationRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Crea una conversación vacía (B01)."""
    uid = claims_uid(claims)
    channel = body.channel or "pc"
    if channel not in ("pc", "whatsapp"):
        raise HTTPException(status_code=400, detail="Canal inválido. Usa 'pc' o 'whatsapp'.")
    conv = create_conversation(db, uid, title=body.title, channel=channel)
    return ConversationResponse(
        id=str(conv.id),
        title=conv.title,
        provider=conv.provider,
        channel=conv.channel or "pc",
        message_count=conv.message_count or 0,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        archived=False,
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
def chat_rename_conversation(
    request: Request,
    conversation_id: str,
    body: RenameConversationRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Renombra una conversación existente (B01)."""
    uid = claims_uid(claims)
    conv = rename_conversation(db, uid, conversation_id, body.title.strip())
    return ConversationResponse(
        id=str(conv.id),
        title=conv.title,
        provider=conv.provider,
        channel=conv.channel or "pc",
        message_count=conv.message_count or 0,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        archived=conv.archived_at is not None,
    )


@router.delete("/conversations/{conversation_id}")
def chat_delete_conversation(
    request: Request,
    conversation_id: str,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Soft-delete: archiva conversación, preserva mensajes (B01)."""
    uid = claims_uid(claims)
    delete_conversation(db, uid, conversation_id)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════
# CH07: Auto-titulado LLM de conversaciones
# ══════════════════════════════════════════════════════════════════


class AutoTitleRequest(BaseModel):
    user_text: str = Field(..., min_length=1, max_length=4000)


@router.post("/conversations/{conversation_id}/auto-title")
def chat_auto_title(
    request: Request,
    conversation_id: str,
    body: AutoTitleRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    """Genera un título para la conversación usando IA (CH07)."""
    uid = claims_uid(claims)
    user_text = body.user_text.strip()

    try:
        # Prompt mejorado: título en español, max 6 palabras, sin comillas
        title = ai_provider.simple_chat(
            user_message=user_text,
            system_prompt=(
                "Eres un asistente que genera títulos cortos en español. "
                "Analiza el siguiente mensaje y crea un título descriptivo de "
                "máximo 6 palabras. Responde ÚNICA y EXCLUSIVAMENTE con el título. "
                "No uses comillas, puntos, signos de puntuación ni nada más. "
                "Solo el título en español, máximo 6 palabras."
            ),
        )
        # Limpiar respuesta: quitar comillas, puntuación, saltos de línea
        title = title.strip().strip('"\'').strip()
        # Quitar puntos, signos de exclamación/interrogación al final
        title = title.rstrip('.!?;:,-')
        # Tomar solo la primera línea si el LLM devolvió multi-línea
        title = title.split('\n')[0].strip()

        if not title or len(title) < 2:
            title = conversation_title_from_user_text(user_text)[:100]
        else:
            # Truncar a 6 palabras máximo
            words = title.split()
            if len(words) > 6:
                title = ' '.join(words[:6]) + '…'
        title = title[:200]
    except Exception:
        log.warning("Auto-title LLM falló para conv=%s, usando fallback", conversation_id)
        title = conversation_title_from_user_text(user_text)[:100]

    conv = auto_title_conversation(db, uid, conversation_id, title)
    return {
        "id": str(conv.id),
        "title": conv.title,
    }


# ══════════════════════════════════════════════════════════════════
# CH06: Búsqueda en contenido de mensajes
# ══════════════════════════════════════════════════════════════════


@router.get("/conversations/search/messages")
def chat_search_messages(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    q: str = Query(..., min_length=2, max_length=200, description="Texto a buscar en mensajes"),
):
    """Busca en el contenido de mensajes descifrados (CH06)."""
    uid = claims_uid(claims)
    results = search_conversation_messages(db, uid, q)
    return {"results": results, "query": q}


# ══════════════════════════════════════════════════════════════════
# CH04b: Restaurar conversación archivada
# ══════════════════════════════════════════════════════════════════


@router.post("/conversations/{conversation_id}/unarchive")
def chat_unarchive_conversation(
    request: Request,
    conversation_id: str,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Restaura una conversación archivada (CH04b)."""
    uid = claims_uid(claims)
    conv = unarchive_conversation(db, uid, conversation_id)
    return {
        "id": str(conv.id),
        "title": conv.title,
        "ok": True,
    }


# ─── Compatibilidad con rutas legacy ────────────────────────────


@router.get("")
def chat_list_legacy(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    q: str | None = Query(None, max_length=200, description="Filtrar por título (ILIKE)"),
):
    """Lista conversaciones del usuario (compatibilidad legacy)."""
    uid = claims_uid(claims)

    convs = list_user_conversations(db, uid, query=q)

    return {
        "conversations": [
            {
                "id": str(c.id),
                "title": c.title,
                "provider": c.provider,
                "channel": c.channel or "pc",
                "message_count": c.message_count or 0,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
                "archived": c.archived_at is not None,
            }
            for c in convs
        ],
    }


@router.post("", response_model=ConversationResponse)
def chat_create_conversation_legacy(
    request: Request,
    body: CreateConversationRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Crea una conversación vacía (compatibilidad legacy)."""
    uid = claims_uid(claims)
    channel = body.channel or "pc"
    if channel not in ("pc", "whatsapp"):
        raise HTTPException(status_code=400, detail="Canal inválido. Usa 'pc' o 'whatsapp'.")
    conv = create_conversation(db, uid, title=body.title, channel=channel)
    return ConversationResponse(
        id=str(conv.id),
        title=conv.title,
        provider=conv.provider,
        channel=conv.channel or "pc",
        message_count=conv.message_count or 0,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        archived=False,
    )


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def chat_rename_conversation_legacy(
    request: Request,
    conversation_id: str,
    body: RenameConversationRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Renombra una conversación existente (compatibilidad legacy)."""
    uid = claims_uid(claims)
    conv = rename_conversation(db, uid, conversation_id, body.title.strip())
    return ConversationResponse(
        id=str(conv.id),
        title=conv.title,
        provider=conv.provider,
        channel=conv.channel or "pc",
        message_count=conv.message_count or 0,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        archived=conv.archived_at is not None,
    )


@router.delete("/{conversation_id}")
def chat_delete_conversation_legacy(
    request: Request,
    conversation_id: str,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Soft-delete: archiva conversación, preserva mensajes (compatibilidad legacy)."""
    uid = claims_uid(claims)
    delete_conversation(db, uid, conversation_id)
    return {"ok": True}


@router.get("/{conversation_id}/history")
def chat_history_legacy(
    request: Request,
    conversation_id: str,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Obtiene historial de conversación desde BD (compatibilidad legacy)."""
    uid = claims_uid(claims)

    offset = (page - 1) * page_size
    messages, total = load_recent_history(db, uid, conversation_id, limit=page_size, offset=offset)

    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "text": decrypt_message(m.content),
                "createdAt": m.created_at.isoformat() if m.created_at else "",
                "status": "sent",
            }
            for m in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
