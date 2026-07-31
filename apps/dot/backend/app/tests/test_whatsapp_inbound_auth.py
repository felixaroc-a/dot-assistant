"""F1: inbound WhatsApp rechaza anónimos / secreto inválido."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_inbound_rejects_invalid_webhook_secret(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "whatsapp_webhook_secret", "secret-correcto")
    monkeypatch.setattr(settings, "testing", "0")

    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/v1/whatsapp/inbound",
        json={
            "from_phone": "+580000000001",
            "to_phone": "+580000000099",
            "text": "hola",
            "message_id": "f1-auth-1",
        },
        headers={"X-Webhook-Secret": "secret-malo"},
    )
    assert resp.status_code == 401


def test_inbound_rejects_missing_secret_when_configured(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "whatsapp_webhook_secret", "secret-correcto")
    monkeypatch.setattr(settings, "testing", "0")

    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/v1/whatsapp/inbound",
        json={
            "from_phone": "+580000000001",
            "to_phone": "+580000000099",
            "text": "hola",
            "message_id": "f1-auth-2",
        },
    )
    assert resp.status_code == 401


def test_send_whatsapp_message_fail_closed_without_bridge_secret(monkeypatch):
    import asyncio

    from app.settings import settings
    from app.services import whatsapp_client

    monkeypatch.setattr(settings, "whatsapp_bridge_secret", "")
    monkeypatch.setattr(settings, "testing", "0")

    ok, err = asyncio.run(whatsapp_client.send_whatsapp_message("+580000000001", "hola"))
    assert ok is False
    assert err == "bridge_secret_not_configured"
