"""Tests STT voz — mock httpx; no requiere GEMINI_API_KEY real.

Tras refactor multi-proveedor, las pruebas usan stt_service directamente.
voice_service.py es un wrapper de compatibilidad.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from app.services import stt_service
from app.services import voice_service


class DummyErrorResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self._request = httpx.Request("POST", "https://example.com")

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError("Error", request=self._request, response=self)


class DummyAsyncClient:
    def __init__(self, response: DummyErrorResponse):
        self._response = response

    async def __aenter__(self) -> "DummyAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, *args, **kwargs) -> DummyErrorResponse:
        return self._response


class SuccessResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"candidates": [{"content": {"parts": [{"text": "hola mundo"}]}}]}


class RecordingAsyncClient:
    instance: "RecordingAsyncClient" | None = None

    def __init__(self, *args, **kwargs):
        RecordingAsyncClient.instance = self

    async def __aenter__(self) -> "RecordingAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url, *args, **kwargs) -> SuccessResponse:
        self.last_url = url
        self.last_kwargs = kwargs
        return SuccessResponse()


@pytest.mark.asyncio
async def test_transcribe_missing_api_key(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        await voice_service.transcribe_audio(b"x" * 100, "audio/webm")
    assert exc.value.status_code == 503
    assert "transcripción por voz" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_transcribe_success(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(stt_service.settings, "gemini_model", "gemini-2.0-flash", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)
    text = await voice_service.transcribe_audio(b"x" * 100, "audio/webm;codecs=opus", language="es")
    assert text == "hola mundo"
    client = RecordingAsyncClient.instance
    assert client is not None
    assert "gemini-2.0-flash:generateContent" in client.last_url
    assert client.last_kwargs.get("params", {}).get("key") == "test-key"


@pytest.mark.asyncio
async def test_transcribe_rate_limit(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(
            DummyErrorResponse(429, {"error": {"message": "quota"}})
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await voice_service.transcribe_audio(b"x" * 100, "audio/webm")
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_transcribe_empty_marker(monkeypatch):
    class EmptyResponse(SuccessResponse):
        def json(self) -> dict[str, object]:
            return {"candidates": [{"content": {"parts": [{"text": "(sin audio)"}]}}]}

    class EmptyClient(RecordingAsyncClient):
        async def post(self, url, *args, **kwargs) -> EmptyResponse:
            return EmptyResponse()

    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", EmptyClient)
    text = await voice_service.transcribe_audio(b"x" * 100, "audio/webm")
    assert text == ""


def test_voice_stt_configured(monkeypatch):
    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "", raising=False)
    assert voice_service.voice_stt_configured() is False
    monkeypatch.setattr(stt_service.settings, "gemini_api_key", "abc", raising=False)
    assert voice_service.voice_stt_configured() is True
