"""Tests de envío outbound de notas de voz WhatsApp (TTS → PTT)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.application.agent.tools.gaps_tools import whatsapp_send_voice_note_handler
from app.application.whatsapp.voice_outbound_service import (
    WHATSAPP_TTS_UNAVAILABLE_PREFIX,
    send_whatsapp_voice_note_outbound,
)


@pytest.mark.asyncio
async def test_voice_note_sends_real_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(text: str, voice: str = "auto", provider: str = "auto"):
        assert text == "Hola por voz"
        return {"audio_base64": "aGVsbG8=", "format": "mp3", "provider": "edge"}

    monkeypatch.setattr(
        "app.services.tts_service.synthesize_speech",
        fake_synthesize,
    )
    monkeypatch.setattr(
        "app.application.whatsapp.voice_outbound_service.execute_local_tool_via_bridge",
        lambda *args, **kwargs: {"ok": True, "path": "~/Desktop/nota-voz-dot-1.mp3"},
    )

    sent: dict[str, str] = {}

    async def fake_send_voice(to: str, path: str):
        sent["to"] = to
        sent["path"] = path
        return True, "msg_voice_1"

    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_voice_note",
        fake_send_voice,
    )

    ok, err, mode = await send_whatsapp_voice_note_outbound("+584141234567", "Hola por voz")
    assert ok is True
    assert err is None
    assert mode == "voice"
    assert sent["to"] == "+584141234567"
    assert sent["path"].endswith(".mp3")


@pytest.mark.asyncio
async def test_voice_note_tts_unavailable_falls_back_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_synthesize(*args, **kwargs):
        raise HTTPException(status_code=503, detail="Edge TTS no disponible")

    monkeypatch.setattr(
        "app.services.tts_service.synthesize_speech",
        fake_synthesize,
    )

    sent: dict[str, str] = {}

    async def fake_send_text(to: str, text: str):
        sent["to"] = to
        sent["text"] = text
        return True, "msg_text_1"

    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        fake_send_text,
    )

    ok, err, mode = await send_whatsapp_voice_note_outbound("+584141234567", "Mensaje importante")
    assert ok is True
    assert err is None
    assert mode == "text_fallback"
    assert sent["text"].startswith(WHATSAPP_TTS_UNAVAILABLE_PREFIX)
    assert "Mensaje importante" in sent["text"]


def test_whatsapp_send_voice_note_handler_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.application.whatsapp.voice_outbound_service.send_whatsapp_voice_note_sync",
        lambda to, message: (True, None, "voice"),
    )
    result = whatsapp_send_voice_note_handler("uid-1", {"to": "+584141234567", "message": "Hola"})
    assert result.ok is True
    assert "Nota de voz enviada" in result.output


def test_whatsapp_send_voice_note_handler_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.application.whatsapp.voice_outbound_service.send_whatsapp_voice_note_sync",
        lambda to, message: (True, None, "text_fallback"),
    )
    result = whatsapp_send_voice_note_handler("uid-1", {"to": "+584141234567", "message": "Hola"})
    assert result.ok is True
    assert "texto" in result.output.lower()
