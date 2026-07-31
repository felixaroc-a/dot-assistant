"""Tests del comando /agenda via endpoint backend."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.billing_db import get_billing_db
from app.services import calendar_service
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


def test_chat_agenda_today_returns_events(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    monkeypatch.setattr(
        "app.services.calendar_service.list_today",
        lambda _uid: [
            {
                "summary": "Reunión comercial",
                "start": "2026-06-04T09:00:00Z",
                "end": "2026-06-04T09:30:00Z",
                "html_link": "https://calendar.google.com/event/abc",
            }
        ],
    )

    resp = client.get(
        "/v1/chat/agenda/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["linked"] is True
    assert len(data["events"]) == 1
    assert data["events"][0]["summary"] == "Reunión comercial"


def test_chat_agenda_today_without_google_link(client: TestClient, monkeypatch) -> None:
    token = _get_token(client)

    def _raise_missing(_uid: str):
        raise calendar_service.MissingCalendarCredentialsError("no linked")

    monkeypatch.setattr("app.services.calendar_service.list_today", _raise_missing)

    resp = client.get(
        "/v1/chat/agenda/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["linked"] is False
    assert data["events"] == []
    assert "Configuralo desde Ajustes" in data["message"]
