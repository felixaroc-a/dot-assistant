"""Tests del router POST /v1/images/generate."""
from __future__ import annotations

import base64
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.billing_models import UsageTokenORM
from app.routers import images as images_router
from app.services.image_gen_vertex_service import GeneratedImage
from app.settings import settings
from app.tests.conftest import seed_cliente


def _get_token(client: TestClient, db_session: Session) -> str:
    seed_cliente(db_session)
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": "1234567890", "password": "test123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(autouse=True)
def _image_gen_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_image_generation", True, raising=False)
    monkeypatch.setattr(settings, "enable_new_integration", False, raising=False)
    monkeypatch.setattr(settings, "google_cloud_project", "test-project", raising=False)
    monkeypatch.setattr(settings, "imagen_vertex_model", "imagen-3.0-generate-002", raising=False)
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", False, raising=False)


def _mock_vertex(monkeypatch: pytest.MonkeyPatch, count: int = 1) -> None:
    fake_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    class FakeImage:
        def save(self, buffer, format: str = "PNG") -> None:
            buffer.write(fake_png)

    def fake_generate_images(*args, **kwargs):
        number = kwargs.get("count") or kwargs.get("number_of_images") or 1
        return [
            GeneratedImage(
                mime_type="image/png",
                data_base64=base64.b64encode(fake_png).decode("ascii"),
                width=1024,
                height=1024,
            )
            for _ in range(number)
        ]

    monkeypatch.setattr(images_router, "generate_images", fake_generate_images)


def test_images_generate_success(client: TestClient, db_session: Session, monkeypatch) -> None:
    _mock_vertex(monkeypatch, count=1)
    token = _get_token(client, db_session)
    resp = client.post(
        "/v1/images/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "genera una imagen de un gato astronauta"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["prompt_used"] == "un gato astronauta"
    assert len(data["images"]) == 1
    assert data["images"][0]["mime_type"] == "image/png"
    assert data["usage"]["model"] == "imagen-3.0-generate-002"


def test_images_generate_invalid_prompt(client: TestClient, db_session: Session, monkeypatch) -> None:
    _mock_vertex(monkeypatch)
    token = _get_token(client, db_session)
    resp = client.post(
        "/v1/images/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "   "},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_prompt"


def test_images_generate_usage_limit_402(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    _mock_vertex(monkeypatch)
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ai_usage_monthly_limit_usd", 0.01, raising=False)

    cliente = seed_cliente(db_session)
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente.id,
            modelo="deepseek-chat",
            costo_total=Decimal("0.02"),
            operation="chat",
        )
    )
    db_session.commit()

    login = client.post(
        "/v1/auth/login",
        json={"cedula": "1234567890", "password": "test123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    resp = client.post(
        "/v1/images/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "un paisaje montañoso"},
    )
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "ai_usage_limit_exceeded"


def test_images_generate_disabled_returns_503(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "enable_image_generation", False, raising=False)
    token = _get_token(client, db_session)
    resp = client.post(
        "/v1/images/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "un atardecer"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "image_generation_unavailable"
