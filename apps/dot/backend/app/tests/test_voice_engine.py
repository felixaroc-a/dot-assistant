"""Tests para servicios de voz multi-proveedor (TTS, STT, Talk Mode).

Ejecutar:
    pytest app/tests/test_voice_engine.py -v

Cubre:
  - TTS: Gemini, Edge, ElevenLabs (mockeados)
  - STT: Gemini, Whisper (mockeados)
  - Talk Mode: máquina de estados, inicios, turnos, interrupción
"""

from __future__ import annotations

import base64
import io
import json
import sys

import httpx
import pytest
from fastapi import HTTPException

# ─── TTS Service ─────────────────────────────────────────────────────────


class TestTtsService:
    """Pruebas del servicio TTS multi-proveedor."""

    def test_tts_configured_no_providers(self, monkeypatch):
        from app.services import tts_service
        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(tts_service.settings, "elevenlabs_api_key", "", raising=False)
        assert tts_service.tts_configured() is True  # Edge siempre está disponible

    def test_tts_configured_with_gemini(self, monkeypatch):
        from app.services import tts_service
        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "test-key", raising=False)
        assert tts_service.tts_configured() is True

    def test_get_available_providers(self, monkeypatch):
        from app.services import tts_service
        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "test-key", raising=False)
        monkeypatch.setattr(tts_service.settings, "elevenlabs_api_key", "test-key", raising=False)
        providers = tts_service.get_available_tts_providers()
        names = [p["name"] for p in providers]
        assert "elevenlabs" in names
        assert "edge" in names
        assert "gemini" in names

    @pytest.mark.asyncio
    async def test_synthesize_with_gemini(self, monkeypatch):
        from app.services import tts_service

        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "test-key", raising=False)

        # Mock httpx AsyncClient
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"audioContent": base64.b64encode(b"fake_audio_data").decode()}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())

        result = await tts_service.synthesize_speech(
            text="Hola mundo", voice="es-ES-Standard-A", provider="gemini",
        )
        assert result["provider"] == "gemini"
        assert result["format"] == "mp3"
        assert result["audio_base64"]
        decoded = base64.b64decode(result["audio_base64"])
        assert decoded == b"fake_audio_data"

    @pytest.mark.asyncio
    async def test_synthesize_auto_selects_provider(self, monkeypatch):
        from app.services import tts_service

        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(tts_service.settings, "elevenlabs_api_key", "", raising=False)

        # Mock edge-tts module
        class FakeCommunicate:
            def __init__(self, *args, **kwargs):
                pass

            async def stream(self):
                yield {"type": "audio", "data": b"edge_audio_data"}

        fake_mod = type("FakeEdgeModule", (), {"Communicate": FakeCommunicate})()
        monkeypatch.setitem(sys.modules, "edge_tts", fake_mod)

        result = await tts_service.synthesize_speech(
            text="Hola mundo", voice="auto", provider="auto",
        )
        assert result["provider"] == "edge"
        assert result["format"] == "mp3"
        decoded = base64.b64decode(result["audio_base64"])
        assert decoded == b"edge_audio_data"

    @pytest.mark.asyncio
    async def test_synthesize_invalid_provider(self, monkeypatch):
        from app.services import tts_service

        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(tts_service.settings, "elevenlabs_api_key", "", raising=False)

        with pytest.raises(HTTPException) as exc:
            await tts_service.synthesize_speech(
                text="Hola", voice="auto", provider="gemini",
            )
        assert exc.value.status_code == 400
        assert "no disponible" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_synthesize_empty_text(self, monkeypatch):
        from app.services import tts_service
        from app.services.tts_service import GeminiTTSProvider

        provider = GeminiTTSProvider()
        monkeypatch.setattr(tts_service.settings, "gemini_api_key", "test-key", raising=False)

        with pytest.raises(HTTPException) as exc:
            await provider.synthesize("   ", "es-ES-Standard-A")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_gemini_provider_http_401(self, monkeypatch):
        from app.services.tts_service import GeminiTTSProvider

        monkeypatch.setattr(
            "app.services.tts_service.settings",
            type("FakeSettings", (), {"gemini_api_key": "bad-key"})(),
            raising=False,
        )

        class FakeErrorResponse:
            status_code = 401
            text = "Unauthorized"

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                return FakeErrorResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        monkeypatch.setattr(
            "app.services.tts_service.settings",
            type("FakeSettings2", (), {"gemini_api_key": "bad-key"})(),
            raising=False,
        )

        provider = GeminiTTSProvider()
        monkeypatch.setattr(
            provider, "available",
            lambda: True,
            raising=False,
        )

        with pytest.raises(HTTPException) as exc:
            await provider.synthesize("Hola", "es-ES-Standard-A")
        assert exc.value.status_code == 503


# ─── STT Service ─────────────────────────────────────────────────────────


class TestSttService:
    """Pruebas del servicio STT multi-proveedor."""

    def test_stt_configured_no_providers(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(stt_service.settings, "openai_api_key", "", raising=False)
        assert stt_service.stt_configured() is False

    def test_stt_configured_with_gemini(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
        assert stt_service.stt_configured() is True

    def test_stt_configured_with_openai(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(stt_service.settings, "openai_api_key", "test-key", raising=False)
        assert stt_service.stt_configured() is True

    def test_get_available_providers(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
        monkeypatch.setattr(stt_service.settings, "openai_api_key", "test-key", raising=False)
        providers = stt_service.get_available_stt_providers()
        names = [p["name"] for p in providers]
        assert "whisper" in names
        assert "gemini" in names

    @pytest.mark.asyncio
    async def test_transcribe_success_gemini(self, monkeypatch):
        from app.services import stt_service

        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
        monkeypatch.setattr(stt_service.settings, "gemini_model", "gemini-2.0-flash", raising=False)

        class FakeResponse:
            status_code = 200
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "hola mundo"}]}}]}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())

        text = await stt_service.transcribe_audio(b"x" * 100, "audio/webm", language="es")
        assert text == "hola mundo"

    @pytest.mark.asyncio
    async def test_transcribe_empty_marker(self, monkeypatch):
        from app.services import stt_service

        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)

        class FakeResponse:
            status_code = 200
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "(sin audio)"}]}}]}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())

        text = await stt_service.transcribe_audio(b"x" * 100, "audio/webm")
        assert text == ""

    @pytest.mark.asyncio
    async def test_transcribe_invalid_provider(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(stt_service.settings, "openai_api_key", "", raising=False)

        with pytest.raises(HTTPException) as exc:
            await stt_service.transcribe_audio(
                b"x" * 100, "audio/webm", provider="gemini",
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_transcribe_auto_no_providers(self, monkeypatch):
        from app.services import stt_service
        monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
        monkeypatch.setattr(stt_service.settings, "openai_api_key", "", raising=False)

        with pytest.raises(HTTPException) as exc:
            await stt_service.transcribe_audio(b"x" * 100, "audio/webm", provider="auto")
        assert exc.value.status_code == 503


# ─── Talk Mode Service ───────────────────────────────────────────────────


class TestTalkMode:
    """Pruebas del servicio de Talk Mode bidireccional."""

    def test_start_session_creates_state(self, monkeypatch):
        from app.services import talk_mode

        # Limpiar sesiones
        monkeypatch.setattr(talk_mode, "_sessions", {})

        result = talk_mode.start_talk_session("test-uid-1")
        assert result["state"] == "listening"
        assert result["transcript"] == ""

        session = talk_mode.get_talk_session("test-uid-1")
        assert session.state.value == "listening"
        assert session.conversation_history == []

    def test_get_session_reuses(self, monkeypatch):
        from app.services import talk_mode

        monkeypatch.setattr(talk_mode, "_sessions", {})

        s1 = talk_mode.get_talk_session("uid-x")
        s2 = talk_mode.get_talk_session("uid-x")
        assert s1 is s2

    def test_get_talk_status_idle(self, monkeypatch):
        from app.services import talk_mode

        monkeypatch.setattr(talk_mode, "_sessions", {})
        result = talk_mode.get_talk_status("uid-x")
        assert result["active"] is False
        assert result["state"] == "idle"

    @pytest.mark.asyncio
    async def test_process_talk_turn(self, monkeypatch):
        from app.services import talk_mode
        import app.services.talk_mode as tm_mod

        monkeypatch.setattr(tm_mod, "_sessions", {})

        # Mock STT que devuelve texto fijo
        async def mock_transcribe(*args, **kwargs):
            return "hola dot"
        monkeypatch.setattr(tm_mod, "transcribe_audio", mock_transcribe)

        # Mock TTS que devuelve b64 fijo
        async def mock_synthesize(*args, **kwargs):
            return {
                "audio_base64": base64.b64encode(b"fake_tts").decode(),
                "format": "mp3",
                "provider": "mock",
            }
        monkeypatch.setattr(tm_mod, "synthesize_speech", mock_synthesize)

        result = await talk_mode.process_talk_turn(
            uid="uid-test",
            audio_bytes=b"x" * 500,
            mime_type="audio/webm",
            language="es",
        )

        assert result["state"] == "idle"
        assert result["transcript"] == "hola dot"
        assert result["response_text"] == "Recibí tu mensaje: hola dot"
        assert result["audio_base64"]
        assert result["history_length"] == 2

    @pytest.mark.asyncio
    async def test_talk_turn_interruption(self, monkeypatch):
        from app.services import talk_mode
        import app.services.talk_mode as tm_mod

        monkeypatch.setattr(tm_mod, "_sessions", {})

        async def mock_transcribe(*args, **kwargs):
            return "mensaje interrumpido"
        monkeypatch.setattr(tm_mod, "transcribe_audio", mock_transcribe)

        async def mock_synthesize(*args, **kwargs):
            return {
                "audio_base64": base64.b64encode(b"fake_tts").decode(),
                "format": "mp3",
                "provider": "mock",
            }
        monkeypatch.setattr(tm_mod, "synthesize_speech", mock_synthesize)

        result = await talk_mode.process_talk_turn(
            uid="uid-int",
            audio_bytes=b"x" * 500,
            mime_type="audio/webm",
            interruption=True,
        )

        assert result["state"] == "interrupted"
        assert result["transcript"] == "mensaje interrumpido"

    def test_stop_session(self, monkeypatch):
        from app.services import talk_mode

        monkeypatch.setattr(talk_mode, "_sessions", {})

        talk_mode.start_talk_session("uid-stop")
        result = talk_mode.stop_talk_session("uid-stop")
        assert result["stopped"] is True
        assert result["total_turns"] == 0

    def test_stop_nonexistent_session(self, monkeypatch):
        from app.services import talk_mode

        monkeypatch.setattr(talk_mode, "_sessions", {})
        result = talk_mode.stop_talk_session("uid-fake")
        assert result["stopped"] is False
