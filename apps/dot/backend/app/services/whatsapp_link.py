"""Servicio de vinculacion WhatsApp para el cliente DOT.

Separa estrictamente:
- Canal WhatsApp cliente (DOT): para conversar con IA desde el movil.
- Bot de cobranzas (Chatbot-Cobro): recordatorios de pago, operacion interna.

Proposito:
- Gestionar estado del canal (vinculado/no vinculado/error).
- Proporcionar endpoints para que Electron genere QR y verifique estado.
- Monitorear reconexion ante desconexiones.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.infrastructure.whatsapp.phone_resolver import to_e164

log = logging.getLogger("dot.whatsapp_link")

WHATSAPP_CHANNEL_ID = "whatsapp"
ChannelLifecycleStatus = Literal["disconnected", "connecting", "linked"]
ChannelEventName = Literal[
    "connecting",
    "qr_ready",
    "linked",
    "heartbeat",
    "disconnected",
    "error",
    "reconnecting",
]


@dataclass
class WhatsAppChannelState:
    status: ChannelLifecycleStatus = "disconnected"
    linked: bool = False
    phone_number: str | None = None
    channel_name: str | None = None
    last_linked_at: str | None = None
    last_disconnected_at: str | None = None
    last_qr_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    reconnect_required: bool = False
    reconnect_attempts: int = 0
    error: str | None = None


# Fallback en memoria cuando Firestore no esta disponible
_channel_states: dict[str, WhatsAppChannelState] = {}


def _get_firestore_ref(user_id: str):
    """Construye referencia al documento de estado del canal en Firestore."""
    from app.firebase_db import get_db

    db = get_db()
    return (
        db.collection("users")
        .document(user_id)
        .collection("whatsapp_channel")
        .document("data")
    )


def _state_to_dict(state: WhatsAppChannelState) -> dict:
    return {
        "status": state.status,
        "linked": state.linked,
        "phone_number": state.phone_number,
        "channel_name": state.channel_name,
        "last_linked_at": state.last_linked_at,
        "last_disconnected_at": state.last_disconnected_at,
        "last_qr_at": state.last_qr_at,
        "last_heartbeat_at": state.last_heartbeat_at,
        "last_error_at": state.last_error_at,
        "reconnect_required": state.reconnect_required,
        "reconnect_attempts": state.reconnect_attempts,
        "error": state.error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _dict_to_state(data: dict) -> WhatsAppChannelState:
    status = str(data.get("status") or "disconnected").strip().lower()
    if status not in {"disconnected", "connecting", "linked"}:
        status = "disconnected"

    return WhatsAppChannelState(
        status=status,  # type: ignore[arg-type]
        linked=data.get("linked", False),
        phone_number=data.get("phone_number"),
        channel_name=data.get("channel_name"),
        last_linked_at=data.get("last_linked_at"),
        last_disconnected_at=data.get("last_disconnected_at"),
        last_qr_at=data.get("last_qr_at"),
        last_heartbeat_at=data.get("last_heartbeat_at"),
        last_error_at=data.get("last_error_at"),
        reconnect_required=bool(data.get("reconnect_required", False)),
        reconnect_attempts=int(data.get("reconnect_attempts", 0) or 0),
        error=data.get("error"),
    )


def get_channel_state(user_id: str) -> WhatsAppChannelState:
    """Obtiene el estado del canal WhatsApp para un usuario.

    Lee desde Firestore en users/{uid}/whatsapp_channel/data.
    Si Firestore no esta disponible, cae al dict en memoria como fallback.
    """
    try:
        ref = _get_firestore_ref(user_id)
        snap = ref.get()
        if snap.exists:
            return _dict_to_state(snap.to_dict() or {})
    except RuntimeError:
        log.warning("Firestore no disponible, usando fallback en memoria para get_channel_state")
    except Exception:
        log.exception("Error inesperado leyendo estado de WhatsApp de Firestore")
    return _channel_states.get(user_id, WhatsAppChannelState())


def update_channel_state(
    user_id: str,
    linked: bool | None = None,
    phone_number: str | None = None,
    channel_name: str | None = None,
    error: str | None = None,
) -> WhatsAppChannelState:
    """Actualiza el estado del canal WhatsApp.

    Persiste en Firestore en users/{uid}/whatsapp_channel/data con merge=True.
    Si Firestore falla, guarda en el dict en memoria como fallback.
    """
    state = get_channel_state(user_id)
    now = datetime.now(timezone.utc).isoformat()

    if linked is not None:
        state.linked = linked
        if linked:
            state.status = "linked"
            state.last_linked_at = now
            state.reconnect_required = False
            state.reconnect_attempts = 0
            state.error = None
        else:
            state.status = "disconnected"
            state.last_disconnected_at = now
            state.reconnect_required = True
    if phone_number is not None:
        state.phone_number = to_e164(phone_number) or phone_number
    if channel_name is not None:
        state.channel_name = channel_name
    if error is not None:
        state.error = error
        state.last_error_at = now
        if not state.linked and state.status == "disconnected":
            state.status = "connecting"
            state.reconnect_required = True

    # Persistir en Firestore
    try:
        ref = _get_firestore_ref(user_id)
        ref.set(_state_to_dict(state), merge=True)
    except RuntimeError:
        log.warning("Firestore no disponible, guardando solo en memoria para update_channel_state")
    except Exception:
        log.exception("Error inesperado escribiendo estado de WhatsApp en Firestore")

    # Mantener el fallback en memoria actualizado
    _channel_states[user_id] = state

    log.info(
        "WhatsApp channel state updated for user %s: linked=%s phone=%s",
        user_id,
        state.linked,
        state.phone_number,
    )
    return state


def record_channel_event(
    user_id: str,
    event: ChannelEventName,
    *,
    phone_number: str | None = None,
    channel_name: str | None = None,
    error: str | None = None,
) -> WhatsAppChannelState:
    """Registra un evento operacional del canal para monitoreo/reconexion."""
    state = get_channel_state(user_id)
    now = datetime.now(timezone.utc).isoformat()

    if event == "connecting":
        # Flujo QR / login fresco: aún no hay sesión válida.
        state.status = "connecting"
        state.linked = False
        state.reconnect_required = False
        state.reconnect_attempts += 1
        state.error = None
    elif event == "reconnecting":
        # Blip de red / reinicio daemon: conservar sesión vinculada (creds locales).
        # Antes: linked=False mentía "desvinculado" y forzaba QR (rompe A2/A3).
        state.status = "connecting"
        state.reconnect_required = False
        state.reconnect_attempts += 1
        if error is not None:
            state.error = error
            state.last_error_at = now
        else:
            state.error = None
    elif event == "qr_ready":
        state.status = "connecting"
        state.reconnect_required = False
        state.error = None
        state.last_qr_at = now
    elif event == "linked":
        state.status = "linked"
        state.linked = True
        state.reconnect_required = False
        state.reconnect_attempts = 0
        state.error = None
        state.last_linked_at = now
    elif event == "heartbeat":
        state.last_heartbeat_at = now
        if state.linked:
            state.status = "linked"
        elif state.status == "disconnected":
            state.status = "connecting"
    elif event == "disconnected":
        state.status = "disconnected"
        state.linked = False
        state.reconnect_required = True
        state.last_disconnected_at = now
        if error:
            state.error = error
            state.last_error_at = now
    elif event == "error":
        state.last_error_at = now
        state.error = error or "error_no_detallado"
        if not state.linked:
            state.status = "connecting"
            state.reconnect_required = True
    else:
        raise ValueError(f"Evento de canal no soportado: {event}")

    if phone_number is not None:
        state.phone_number = to_e164(phone_number) or phone_number
    if channel_name is not None:
        state.channel_name = channel_name

    try:
        ref = _get_firestore_ref(user_id)
        ref.set(_state_to_dict(state), merge=True)
    except RuntimeError:
        log.warning("Firestore no disponible, guardando evento de canal solo en memoria")
    except Exception:
        log.exception("Error guardando evento de canal en Firestore")

    _channel_states[user_id] = state
    log.info("Evento WhatsApp registrado para uid=%s: event=%s status=%s", user_id, event, state.status)
    return state


def clear_channel_state(user_id: str) -> None:
    """Limpia el estado del canal (logout/desconexion).

    Elimina el documento en Firestore. Si falla, limpia solo la memoria.
    """
    try:
        ref = _get_firestore_ref(user_id)
        ref.delete()
    except RuntimeError:
        log.warning("Firestore no disponible, limpiando solo memoria para clear_channel_state")
    except Exception:
        log.exception("Error inesperado limpiando estado de WhatsApp en Firestore")

    _channel_states.pop(user_id, None)
    log.info("WhatsApp channel state cleared for user %s", user_id)
