"""Tests de endpoints de recordatorios de chat."""
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


class _FakeReminderService:
    def __init__(self):
        self.acked_ids: list[str] = []

    def create_reminder(self, uid: str, text: str, due_at):
        return {
            "id": "rem-123",
            "text": text,
            "due_at": due_at.isoformat(),
            "notified": False,
        }

    def list_pending_notifications(self, uid: str, limit: int = 25):
        return [
            {
                "id": "pending-1",
                "text": "Revisar contrato",
                "due_at": "2030-01-01T12:00:00+00:00",
            }
        ]

    def ack_notifications(self, uid: str, reminder_ids: list[str]):
        self.acked_ids = list(reminder_ids)
        return len(reminder_ids)


def test_create_chat_reminder(client: TestClient) -> None:
    token = _get_token(client)
    fake = _FakeReminderService()
    client.app.state.reminder_service = fake

    resp = client.post(
        "/v1/chat/reminders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "text": "Pagar suscripción",
            "due_at": "2030-01-01T12:30:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["id"] == "rem-123"
    assert "Recordatorio guardado" in data["message"]


def test_pending_and_ack_chat_reminders(client: TestClient) -> None:
    token = _get_token(client)
    fake = _FakeReminderService()
    client.app.state.reminder_service = fake

    pending = client.get(
        "/v1/chat/reminders/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pending.status_code == 200
    payload = pending.json()
    assert len(payload["reminders"]) == 1
    assert payload["reminders"][0]["id"] == "pending-1"

    ack = client.post(
        "/v1/chat/reminders/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={"ids": ["pending-1"]},
    )
    assert ack.status_code == 200
    assert ack.json()["ok"] is True
    assert fake.acked_ids == ["pending-1"]
