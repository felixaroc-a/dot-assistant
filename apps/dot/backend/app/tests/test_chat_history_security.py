"""Tests de listado/historial de chat: esquema y ownership por cliente."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.chat_models import ConversationORM, MessageORM
from app.tests.conftest import seed_cliente


def _login(client: TestClient, cedula: str, password: str = "test123") -> str:
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": cedula, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_chat_list_ok_with_schema(client: TestClient, db_session: Session) -> None:
    """GET /v1/chat no debe fallar por tablas chat_* ausentes."""
    owner = seed_cliente(db_session, cedula="1111111111")
    conv = ConversationORM(
        id=uuid4(),
        cliente_id=owner.id,
        title="Hola",
        provider="deepseek",
        message_count=1,
    )
    db_session.add(conv)
    db_session.commit()
    conv_id = conv.id

    token = _login(client, "1111111111")
    resp = client.get(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "conversations" in data
    assert len(data["conversations"]) == 1
    assert data["conversations"][0]["id"] == str(conv_id)


def test_chat_history_denied_for_other_user(
    client: TestClient,
    db_session: Session,
) -> None:
    """Historial de conversación ajena debe devolver 403."""
    owner = seed_cliente(db_session, cedula="2222222222")
    seed_cliente(
        db_session,
        cedula="3333333333",
        correo="other@example.com",
    )
    conv = ConversationORM(
        id=uuid4(),
        cliente_id=owner.id,
        title="Privada",
        provider="deepseek",
    )
    db_session.add(conv)
    db_session.add(
        MessageORM(
            conversation_id=conv.id,
            role="user",
            content="secreto",
        )
    )
    db_session.commit()
    conv_id = conv.id

    other_token = _login(client, "3333333333")
    resp = client.get(
        f"/v1/chat/{conv_id}/history",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403
    assert "acceso" in resp.json()["detail"].lower()

    owner_token = _login(client, "2222222222")
    ok = client.get(
        f"/v1/chat/{conv_id}/history",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert ok.status_code == 200
    assert len(ok.json()["messages"]) == 1
    assert ok.json()["messages"][0]["text"] == "secreto"


def test_chat_history_not_found(client: TestClient, db_session: Session) -> None:
    seed_cliente(db_session, cedula="4444444444")

    token = _login(client, "4444444444")
    missing_id = uuid4()
    resp = client.get(
        f"/v1/chat/{missing_id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
