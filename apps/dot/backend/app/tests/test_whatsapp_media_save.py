"""Tests B08: adjuntos WhatsApp → Escritorio."""
from __future__ import annotations

import base64

import pytest

from app.application.whatsapp.whatsapp_media_service import (
    build_save_confirmation_message,
    cache_inbound_media,
    clear_media_cache_for_tests,
    detect_save_media_intent,
    has_saveable_inbound_media,
    save_whatsapp_media_to_desktop,
    suggest_dest_relative_path,
    WhatsAppMediaSaveResult,
)
from app.domain.whatsapp.message import InboundWhatsAppMessage


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_media_cache_for_tests()
    yield
    clear_media_cache_for_tests()


def test_detect_save_media_intent_spanish():
    assert detect_save_media_intent("DOT guárdame esta foto en el Escritorio")
    assert detect_save_media_intent("guarda el pdf")
    assert not detect_save_media_intent("hola DOT cómo estás")


def test_has_saveable_inbound_media_image():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    msg = InboundWhatsAppMessage(
        message_id="img-1",
        from_phone="+580000000601",
        to_phone="+580000000602",
        text="[media]",
        timestamp="2026-07-24T12:00:00Z",
        has_image=True,
        media_mime_type="image/png",
        media_data_base64=base64.b64encode(png_bytes).decode("ascii"),
    )
    assert has_saveable_inbound_media(msg)


def test_suggest_dest_relative_path_pdf():
    path = suggest_dest_relative_path(
        mime_type="application/pdf",
        filename_hint="factura-julio.pdf",
        kind="document",
    )
    assert path.startswith("~/Desktop/")
    assert "factura-julio.pdf" in path


def test_build_save_confirmation_message_image():
    msg = build_save_confirmation_message(
        WhatsAppMediaSaveResult(ok=True, filename="foto-whatsapp.jpg", kind="image")
    )
    assert "Guardé la foto" in msg
    assert "Escritorio" in msg


def test_save_whatsapp_media_to_desktop_via_bridge(monkeypatch):
    uid = "test-wa-media-save-01"
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"y" * 100
    message = InboundWhatsAppMessage(
        message_id="img-save-1",
        from_phone="+580000000601",
        to_phone="+580000000602",
        text="guárdame esta foto",
        timestamp="2026-07-24T12:00:00Z",
        has_image=True,
        media_mime_type="image/png",
        media_data_base64=base64.b64encode(png_bytes).decode("ascii"),
    )
    cache_inbound_media(uid, message)

    captured: dict = {}

    def fake_bridge(operation, *, path="", content=None, **kwargs):
        captured["operation"] = operation
        captured["path"] = path
        captured["content"] = content
        return {"ok": True, "path": "C:/Users/x/Escritorio/foto-whatsapp.png", "bytes": len(png_bytes)}

    monkeypatch.setattr(
        "app.application.whatsapp.whatsapp_media_service.execute_local_tool_via_bridge",
        fake_bridge,
    )

    result = save_whatsapp_media_to_desktop(uid, message_id="img-save-1")
    assert result.ok is True
    assert captured["operation"] == "writeFileBytes"
    assert "foto" in captured["path"].lower() or captured["path"].startswith("~/Desktop/")
    assert "Guardé la foto" in (result.human_message or "")


def test_process_inbound_auto_saves_image_with_intent(monkeypatch):
    from app.application.whatsapp.inbound_service import get_message_store, process_inbound_message
    from app.services.whatsapp_link import clear_channel_state, update_channel_state

    uid = "test-wa-media-inbound-01"
    linked = "+580000000701"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)
    get_message_store().clear_uid(uid)

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"z" * 100

    monkeypatch.setattr(
        "app.application.whatsapp.whatsapp_media_service.execute_local_tool_via_bridge",
        lambda operation, *, path="", content=None, **kwargs: {
            "ok": True,
            "path": "C:/Users/x/Escritorio/recibo.png",
            "bytes": len(png_bytes),
        },
    )

    message = InboundWhatsAppMessage(
        message_id="img-inbound-1",
        from_phone=linked,
        to_phone=linked,
        text="DOT guárdame esta foto",
        timestamp="2026-07-24T12:05:00Z",
        is_group=True,
        group_name="DOT",
        has_image=True,
        media_mime_type="image/png",
        media_data_base64=base64.b64encode(png_bytes).decode("ascii"),
    )

    result = process_inbound_message(message)
    assert result["status"] == "ok"
    assert result["has_saveable_media"] is True
    assert result["media_auto_saved"] is True
    assert "Guardé la foto" in (result["media_save_message"] or "")

    clear_channel_state(uid)
    get_message_store().clear_uid(uid)
