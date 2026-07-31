"""Tests del endpoint /v1/chat/translate."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.billing_db import get_billing_db
from app.services.provider_router import ProviderNotAvailableError
from app.tests.conftest import seed_cliente


def _get_token(client: TestClient) -> str:
    session = next(get_billing_db())
    seed_cliente(session)
    session.close()
    resp = client.post(
        "/v1/auth/login",
        json={
            "cedula": "1234567890",
            "password": "test123",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_chat_translate_ok(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)
    monkeypatch.setattr(
        "app.services.provider_router.route_translate",
        lambda text, target_lang, provider_id=None, ai_provider=None: (
            "Hello world",
            "google_translate",
            "en",
        ),
    )

    resp = client.post(
        "/v1/chat/translate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "text": "Hola mundo",
            "target_lang": "inglés",
            "provider": "deepseek",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["translated_text"] == "Hello world"
    assert data["provider"] == "google_translate"
    assert data["target_lang"] == "en"


def test_chat_translate_bad_request(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    def _raise_value_error(*_args, **_kwargs):
        raise ValueError("Debes indicar el idioma destino.")

    monkeypatch.setattr("app.services.provider_router.route_translate", _raise_value_error)

    resp = client.post(
        "/v1/chat/translate",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Hola", "target_lang": ""},
    )
    assert resp.status_code == 400
    assert "idioma destino" in resp.json()["detail"]


def test_chat_translate_unavailable_provider(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    def _raise_provider_error(*_args, **_kwargs):
        raise ProviderNotAvailableError("Traducción no disponible")

    monkeypatch.setattr("app.services.provider_router.route_translate", _raise_provider_error)

    resp = client.post(
        "/v1/chat/translate",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Hola", "target_lang": "en"},
    )
    assert resp.status_code == 503
    assert "Traducción no disponible" in resp.json()["detail"]
