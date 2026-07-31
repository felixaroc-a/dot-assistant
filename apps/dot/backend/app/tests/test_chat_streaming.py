"""Tests para streaming SSE del chat."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.tests.conftest import seed_cliente


def _get_token(client: TestClient, db_session: Session) -> str:
    seed_cliente(db_session)
    resp = client.post(
        "/v1/auth/login",
        json={
            "cedula": "1234567890",
            "password": "test123",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _extract_sse_payloads(raw: str) -> list[dict]:
    payloads: list[dict] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payloads.append(json.loads(line[6:]))
    return payloads


def test_chat_stream_emits_tokens_and_done(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    token = _get_token(client, db_session)

    def _fake_detailed(
        text: str,
        provider_id: str | None = None,
        system_prompt: str | None = None,
        include_document_action_prompt: bool = False,
        ai_provider=None,
    ):
        class _FakeResult:
            text = "Hola mundo"
            finish_reason = "stop"
            usage = None
        return _FakeResult()

    monkeypatch.setattr(
        "app.services.provider_router.route_chat_detailed",
        _fake_detailed,
    )

    response = client.post(
        "/v1/chat/send/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "saludo", "provider": "deepseek"},
    )
    assert response.status_code == 200

    payloads = _extract_sse_payloads(response.text)
    tokens = [p["token"] for p in payloads if "token" in p]
    done_events = [p for p in payloads if p.get("done") is True]

    assert len(tokens) > 0
    assert len(done_events) == 1
    assert isinstance(done_events[0].get("conversation_id"), str)
    assert done_events[0]["conversation_id"]


def test_chat_stream_emits_done_even_without_finish_reason(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    token = _get_token(client, db_session)

    def _fake_detailed(
        text: str,
        provider_id: str | None = None,
        system_prompt: str | None = None,
        include_document_action_prompt: bool = False,
        ai_provider=None,
    ):
        class _FakeResult:
            text = "tok"
            finish_reason = ""
            usage = None
        return _FakeResult()

    monkeypatch.setattr(
        "app.services.provider_router.route_chat_detailed",
        _fake_detailed,
    )

    response = client.post(
        "/v1/chat/send/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "sin finish", "provider": "deepseek"},
    )
    assert response.status_code == 200

    payloads = _extract_sse_payloads(response.text)
    done_events = [p for p in payloads if p.get("done") is True]
    assert len(done_events) == 1
