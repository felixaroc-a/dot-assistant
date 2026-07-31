"""Pruebas del estado de canal WhatsApp (Fase 4)."""
from __future__ import annotations

from app.services.whatsapp_link import (
    clear_channel_state,
    get_channel_state,
    record_channel_event,
    update_channel_state,
)


def test_whatsapp_event_flow_connect_link_disconnect():
    uid = "test-wa-user-01"
    clear_channel_state(uid)

    connecting = record_channel_event(uid, "connecting")
    assert connecting.status == "connecting"
    assert connecting.linked is False
    assert connecting.reconnect_required is False
    assert connecting.reconnect_attempts == 1

    qr_ready = record_channel_event(uid, "qr_ready")
    assert qr_ready.status == "connecting"
    assert qr_ready.reconnect_required is False
    assert qr_ready.error is None
    assert qr_ready.last_qr_at is not None

    linked = record_channel_event(uid, "linked", phone_number="+584141234567")
    assert linked.status == "linked"
    assert linked.linked is True
    assert linked.reconnect_required is False
    assert linked.reconnect_attempts == 0
    assert linked.phone_number == "+584141234567"
    assert linked.last_linked_at is not None

    disconnected = record_channel_event(
        uid,
        "disconnected",
        error="Sesion cerrada por el usuario",
    )
    assert disconnected.status == "disconnected"
    assert disconnected.linked is False
    assert disconnected.reconnect_required is True
    assert disconnected.error == "Sesion cerrada por el usuario"
    assert disconnected.last_disconnected_at is not None


def test_reconnecting_preserves_linked_session():
    """A3: blip de red no debe mentir linked=false ni forzar QR."""
    uid = "test-wa-user-reconnect-01"
    clear_channel_state(uid)

    linked = record_channel_event(uid, "linked", phone_number="+584149998877")
    assert linked.linked is True
    assert linked.status == "linked"

    reconnecting = record_channel_event(
        uid,
        "reconnecting",
        error="worker_exit_1",
    )
    assert reconnecting.linked is True
    assert reconnecting.status == "connecting"
    assert reconnecting.reconnect_required is False
    assert reconnecting.reconnect_attempts == 1
    assert reconnecting.phone_number == "+584149998877"
    assert reconnecting.error == "worker_exit_1"

    recovered = record_channel_event(uid, "heartbeat")
    assert recovered.linked is True
    assert recovered.status == "linked"

    clear_channel_state(uid)


def test_update_channel_state_sets_linked_and_error_metadata():
    uid = "test-wa-user-02"
    clear_channel_state(uid)

    linked = update_channel_state(uid, linked=True, phone_number="584140001111")
    assert linked.status == "linked"
    assert linked.linked is True
    assert linked.phone_number == "+584140001111"
    assert linked.error is None

    with_error = update_channel_state(uid, linked=False, error="conexion_inestable")
    assert with_error.status == "connecting"
    assert with_error.linked is False
    assert with_error.error == "conexion_inestable"
    assert with_error.last_error_at is not None

    clear_channel_state(uid)
    empty = get_channel_state(uid)
    assert empty.status == "disconnected"
    assert empty.linked is False
