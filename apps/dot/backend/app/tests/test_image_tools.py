"""Tests de generate_image agent tool."""
from __future__ import annotations

import base64
from decimal import Decimal
from uuid import uuid4

import pytest

from app.application.agent.tools import image_tools
from app.billing_models import UsageTokenORM
from app.services.image_gen_vertex_service import GeneratedImage
from app.services.image_generation_service import IMAGE_GENERATION_UNAVAILABLE_MESSAGE
from app.settings import settings
from app.tests.conftest import seed_cliente


@pytest.fixture(autouse=True)
def _image_tool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_image_generation", True, raising=False)
    monkeypatch.setattr(settings, "enable_new_integration", False, raising=False)
    monkeypatch.setattr(settings, "google_cloud_project", "test-project", raising=False)
    monkeypatch.setattr(settings, "imagen_vertex_model", "imagen-3.0-generate-002", raising=False)
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", False, raising=False)


def test_generate_image_tool_success(db_session, monkeypatch) -> None:
    cliente = seed_cliente(db_session)
    fake_png = base64.b64encode(b"fake-image").decode("ascii")

    def fake_generate_images(*args, **kwargs):
        return [
            GeneratedImage(
                mime_type="image/png",
                data_base64=fake_png,
                width=1024,
                height=1024,
            )
        ]

    monkeypatch.setattr(image_tools, "generate_images", fake_generate_images)

    result = image_tools.generate_image_handler(
        str(cliente.id),
        {"prompt": "genera una imagen de un gato"},
    )

    assert result.ok is True
    assert "gato" in result.output
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["type"] == "image"
    assert result.artifacts[0]["data"] == fake_png


def test_generate_image_tool_unavailable_without_project(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_cloud_project", "", raising=False)

    result = image_tools.generate_image_handler(uuid4().hex, {"prompt": "un perro"})

    assert result.ok is False
    assert result.error == IMAGE_GENERATION_UNAVAILABLE_MESSAGE


def test_generate_image_tool_usage_limit(db_session, monkeypatch) -> None:
    cliente = seed_cliente(db_session)
    monkeypatch.setattr(settings, "ai_usage_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ai_usage_monthly_limit_usd", 0.01, raising=False)
    db_session.add(
        UsageTokenORM(
            cliente_id=cliente.id,
            modelo="deepseek-chat",
            costo_total=Decimal("0.02"),
            operation="chat",
        )
    )
    db_session.commit()

    result = image_tools.generate_image_handler(
        str(cliente.id),
        {"prompt": "un paisaje"},
    )

    assert result.ok is False
    assert "límite de IA" in (result.error or "").lower()
