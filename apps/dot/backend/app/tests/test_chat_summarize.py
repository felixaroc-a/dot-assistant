"""Tests del endpoint /v1/chat/summarize."""
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


def test_chat_summarize_ok(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)
    monkeypatch.setattr(
        "app.services.provider_router.route_summarize",
        lambda content, provider_id=None, ai_provider=None: ("Resumen corto", "url", 2),
    )

    resp = client.post(
        "/v1/chat/summarize",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "https://example.com/articulo", "provider": "deepseek"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "Resumen corto"
    assert data["source_type"] == "url"
    assert data["chunks"] == 2


def test_chat_summarize_bad_request(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    def _raise_value_error(*_args, **_kwargs):
        raise ValueError("Debes proporcionar texto, URL o PDF para resumir.")

    monkeypatch.setattr("app.services.provider_router.route_summarize", _raise_value_error)

    resp = client.post(
        "/v1/chat/summarize",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": ""},
    )
    assert resp.status_code == 400
    assert "proporcionar texto" in resp.json()["detail"]


def test_chat_summarize_provider_unavailable(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    def _raise_provider_error(*_args, **_kwargs):
        raise ProviderNotAvailableError("Resumen no disponible")

    monkeypatch.setattr("app.services.provider_router.route_summarize", _raise_provider_error)

    resp = client.post(
        "/v1/chat/summarize",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "texto"},
    )
    assert resp.status_code == 503
    assert "Resumen no disponible" in resp.json()["detail"]
