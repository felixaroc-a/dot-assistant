from __future__ import annotations

import json

import pytest
import httpx
from fastapi import HTTPException

from google.api_core import exceptions as google_exceptions
from google.auth.exceptions import DefaultCredentialsError

from app.services import vision_service, vision_vertex_service
from app.services.vision_service import GEMINI_BASE_URL


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


class RecordingSuccessResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "candidates": [
                {"content": {"parts": [{"text": "resultado"}]}}
            ]
        }


class RecordingAsyncClient:
    instance: "RecordingAsyncClient" | None = None

    def __init__(self, *args, **kwargs):
        RecordingAsyncClient.instance = self

    async def __aenter__(self) -> "RecordingAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url, *args, **kwargs) -> RecordingSuccessResponse:
        self.last_url = url
        self.last_kwargs = kwargs
        return RecordingSuccessResponse()


@pytest.mark.asyncio
async def test_analyze_image_rate_limit(monkeypatch):
    monkeypatch.setattr(vision_service.settings, "gemini_provider", "api_key", raising=False)
    monkeypatch.setattr(vision_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(
            DummyErrorResponse(429, {"error": {"message": "rate limit"}})
        ),
    )

    with pytest.raises(HTTPException) as excinfo:
        await vision_service.analyze_image(b"abc", "image/jpeg", prompt="Prueba")

    assert excinfo.value.status_code == 429
    assert "Gemini limitó" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_analyze_image_forbidden_message(monkeypatch):
    monkeypatch.setattr(vision_service.settings, "gemini_provider", "api_key", raising=False)
    monkeypatch.setattr(vision_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(
            DummyErrorResponse(
                403,
                {"error": {"message": "clave restringida a modelo X"}},
            ),
        ),
    )

    with pytest.raises(HTTPException) as excinfo:
        await vision_service.analyze_image(b"abc", "image/jpeg", prompt="Prueba")

    detail = str(excinfo.value.detail)
    assert "API key sin permiso" in detail
    assert "Google Cloud Console" in detail
    assert "clave restringida a modelo X" in detail


@pytest.mark.asyncio
async def test_analyze_image_uses_override_model(monkeypatch):
    monkeypatch.setattr(vision_service.settings, "gemini_provider", "api_key", raising=False)
    monkeypatch.setattr(vision_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(vision_service.settings, "gemini_model", "gemini-custom-model", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)

    result = await vision_service.analyze_image(b"abc", "image/png", prompt="Prueba modelo")

    assert result == "resultado"
    assert RecordingAsyncClient.instance is not None
    assert RecordingAsyncClient.instance.last_url == (
        f"{GEMINI_BASE_URL}/gemini-custom-model:generateContent"
    )
    assert RecordingAsyncClient.instance.last_kwargs["params"] == {"key": "test-key"}


@pytest.mark.asyncio
async def test_analyze_image_vertex_provider(monkeypatch):
    monkeypatch.setattr(vision_service.settings, "gemini_provider", "vertex", raising=False)
    monkeypatch.setattr(vision_service.settings, "google_cloud_project", "proj", raising=False)
    monkeypatch.setattr(vision_service.settings, "google_cloud_location", "us-central1", raising=False)
    monkeypatch.setattr(vision_service.settings, "gemini_vertex_model", "gemini-vertex", raising=False)

    captured: dict[str, object] = {}

    def fake_vertex(image_bytes, mime_type, prompt, project, location, model_name):
        captured.update(
            {
                "image_bytes": image_bytes,
                "mime_type": mime_type,
                "prompt": prompt,
                "project": project,
                "location": location,
                "model_name": model_name,
            }
        )
        return "vertex-result"

    monkeypatch.setattr(vision_service, "analyze_image_vertex", fake_vertex)
    async def fake_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(vision_service, "run_in_threadpool", fake_run_in_threadpool)

    result = await vision_service.analyze_image(b"bytes", "image/png", prompt="descr")

    assert result == "vertex-result"
    assert captured["project"] == "proj"
    assert captured["mime_type"] == "image/png"
    assert captured["model_name"] == "gemini-vertex"


def test_vertex_service_requires_project():
    with pytest.raises(HTTPException) as excinfo:
        vision_vertex_service.analyze_image(
            b"bytes",
            "image/png",
            "prompt",
            project="",
            location="us-central1",
            model_name="gemini-test",
        )

    assert excinfo.value.status_code == 503


def test_vertex_service_returns_text(monkeypatch):
    class DummyVertexModule:
        def init(self, project, location):
            self.last_init = (project, location)

    class DummyPart:
        last_call: tuple[bytes, str] | None = None

        @classmethod
        def from_data(cls, data: bytes, mime_type: str):
            cls.last_call = (data, mime_type)
            return {"data": data, "mime_type": mime_type}

    class DummyResponse:
        def __init__(self, text: str):
            self.text = text

    class DummyModel:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def generate_content(self, parts):
            return DummyResponse("ap robado")

    def fake_load():
        return DummyVertexModule(), DummyModel, DummyPart

    monkeypatch.setattr(vision_vertex_service, "_load_vertex_modules", fake_load)

    result = vision_vertex_service.analyze_image(
        b"bytes",
        "image/png",
        "prompt",
        project="proj",
        location="us-central1",
        model_name="gemini-test",
    )

    assert result == "ap robado"
    assert DummyPart.last_call == (b"bytes", "image/png")


def test_vertex_service_permission_denied(monkeypatch):
    class DummyVertexModule:
        def init(self, project, location):
            return None

    class DummyPart:
        @classmethod
        def from_data(cls, data: bytes, mime_type: str):
            return {"data": data, "mime_type": mime_type}

    class DummyModel:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def generate_content(self, parts):
            raise google_exceptions.PermissionDenied("rechazado")

    def fake_load():
        return DummyVertexModule(), DummyModel, DummyPart

    monkeypatch.setattr(vision_vertex_service, "_load_vertex_modules", fake_load)

    with pytest.raises(HTTPException) as excinfo:
        vision_vertex_service.analyze_image(
            b"bytes",
            "image/png",
            "prompt",
            project="proj",
            location="us-central1",
            model_name="gemini-test",
        )

    assert excinfo.value.status_code == 403
    assert "Vertex AI rechazó" in str(excinfo.value.detail)


def test_vertex_service_credentials_error(monkeypatch):
    class DummyVertexModule:
        def init(self, project, location):
            raise DefaultCredentialsError("no creds")

    class DummyPart:
        @classmethod
        def from_data(cls, data: bytes, mime_type: str):
            return {"data": data, "mime_type": mime_type}

    class DummyModel:
        def __init__(self, model_name: str):
            pass

        def generate_content(self, parts):
            return None

    def fake_load():
        return DummyVertexModule(), DummyModel, DummyPart

    monkeypatch.setattr(vision_vertex_service, "_load_vertex_modules", fake_load)

    with pytest.raises(HTTPException) as excinfo:
        vision_vertex_service.analyze_image(
            b"bytes",
            "image/jpeg",
            "prompt",
            project="proj",
            location="us-central1",
            model_name="gemini-test",
        )

    assert excinfo.value.status_code == 503
    assert "Credenciales" in str(excinfo.value.detail)
