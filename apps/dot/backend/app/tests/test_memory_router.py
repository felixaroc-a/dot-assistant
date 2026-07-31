"""Tests del router /v1/memory para la UI «Lo que recuerdo»."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth_deps import require_product_jwt
from app.main import app

UID = "uid-memory-ui"


@pytest.fixture
def client():
    test_client = TestClient(app)
    test_client.app.dependency_overrides[require_product_jwt] = lambda: {"sub": UID, "cliente_id": 1}
    yield test_client
    test_client.app.dependency_overrides.pop(require_product_jwt, None)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@patch("app.routers.memory.metrics.track_memory_operation")
@patch("app.routers.memory.get_memory_facts")
@patch("app.routers.memory.get_memory")
def test_get_v1_memory_overview(mock_get_memory, mock_get_facts, mock_metrics, client, auth_headers):
    mock_get_memory.return_value = "Le gusta el café."
    mock_get_facts.return_value = [
        {
            "fact_id": "fact-1",
            "type": "preference",
            "key": "bebida_favorita",
            "value": "Café con leche",
            "confidence": 0.9,
            "updated_at": None,
        }
    ]

    resp = client.get("/v1/memory", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "Le gusta el café."
    assert data["total"] == 1
    assert data["facts"][0]["fact_id"] == "fact-1"
    assert data["facts"][0]["value"] == "Café con leche"
    assert "embedding" not in data["facts"][0]
    mock_metrics.assert_called_once_with("recall")


@patch("app.routers.memory.metrics.track_memory_operation")
@patch("app.routers.memory.forget_memory_fact", return_value=True)
def test_delete_v1_memory_fact(mock_forget, mock_metrics, client, auth_headers):
    resp = client.delete("/v1/memory/facts/fact-1", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "fact_id": "fact-1"}
    mock_forget.assert_called_once_with(UID, "fact-1")
    mock_metrics.assert_called_once_with("forget")


@patch("app.routers.memory.forget_memory_fact", return_value=False)
def test_delete_v1_memory_fact_not_found(mock_forget, client, auth_headers):
    resp = client.delete("/v1/memory/facts/missing", headers=auth_headers)

    assert resp.status_code == 404
    mock_forget.assert_called_once_with(UID, "missing")
