"""Tests de resultados pendientes de automatizaciones."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.billing_db import get_billing_db
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


def test_get_pending_results_payload(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)
    monkeypatch.setattr(
        "app.routers.automations.get_user_profile",
        lambda _uid: {
            "pending_automation_results": {
                "has_new": True,
                "last_auto_id": "auto-99",
                "last_auto_name": "Reporte diario",
                "last_executed_at": "2030-01-01T10:00:00Z",
                "last_result_preview": "Ventas hoy: 25",
            }
        },
    )

    resp = client.get(
        "/v1/automations/results/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_new"] is True
    assert data["last_auto_id"] == "auto-99"
    assert data["last_auto_name"] == "Reporte diario"
    assert data["last_result_preview"] == "Ventas hoy: 25"


def test_ack_pending_results_clears_scheduler(client: TestClient) -> None:
    token = _get_token(client)
    captured: dict[str, str] = {}

    class _FakeScheduler:
        def clear_pending_results(self, uid: str) -> None:
            captured["uid"] = uid

    client.app.state.auto_scheduler = _FakeScheduler()

    resp = client.post(
        "/v1/automations/results/ack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "uid" in captured
