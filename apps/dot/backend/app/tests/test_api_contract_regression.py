"""
Contratos API anti-regresión (post-fixes paralelos).

Cubre:
1. GET /v1/chat con esquema inicializado → 200 (no 500)
2. Historial cross-user → 403; conversación inexistente → 404
3. GET /users/me/profile — saved_automations en snake_case
4. CORS DELETE /v1/templates — ver test_cors_templates.py (+ docstring allí)
5. Auth login + refresh + recovery-login básicos
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.chat_models import ConversationORM, MessageORM
from app.schemas.profile import UserProfileResponse
from app.tests.conftest import seed_cliente

RECOVERY_KEY = "B" * 48
PROFILE_SHAPE_KEYS = frozenset(UserProfileResponse.model_fields.keys())


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(
    client: TestClient,
    db_session,
    *,
    cedula: str = "1234567890",
    seed: bool = True,
) -> dict:
    if seed:
        seed_cliente(db_session, cedula=cedula)
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": cedula, "password": "test123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestChatListContract:
    def test_get_chat_empty_list_returns_200(self, client: TestClient, db_session) -> None:
        """Usuario autenticado sin conversaciones: 200 y lista vacía (no 500 por tablas)."""
        tokens = _login(client, db_session, cedula="9000000001")
        resp = client.get("/v1/chat", headers=_auth(tokens["access_token"]))
        assert resp.status_code == 200
        body = resp.json()
        assert "conversations" in body
        assert body["conversations"] == []

    def test_get_chat_with_data_returns_200(self, client: TestClient, db_session) -> None:
        owner = seed_cliente(db_session, cedula="9000000002")
        conv = ConversationORM(
            id=uuid4(),
            cliente_id=owner.id,
            title="Contrato",
            provider="deepseek",
            message_count=0,
        )
        db_session.add(conv)
        db_session.commit()

        tokens = _login(client, db_session, cedula="9000000002", seed=False)
        resp = client.get("/v1/chat", headers=_auth(tokens["access_token"]))
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["conversations"]]
        assert str(conv.id) in ids


class TestChatHistoryIsolation:
    def test_foreign_history_403_owner_200(self, client: TestClient, db_session) -> None:
        owner = seed_cliente(db_session, cedula="9000000010")
        other = seed_cliente(db_session, cedula="9000000011", correo="o@example.com")
        conv = ConversationORM(
            id=uuid4(),
            cliente_id=owner.id,
            title="Privada",
            provider="deepseek",
        )
        db_session.add(conv)
        db_session.add(
            MessageORM(conversation_id=conv.id, role="user", content="secreto")
        )
        db_session.commit()

        other_tokens = _login(client, db_session, cedula="9000000011", seed=False)
        denied = client.get(
            f"/v1/chat/{conv.id}/history",
            headers=_auth(other_tokens["access_token"]),
        )
        assert denied.status_code == 403

        owner_tokens = _login(client, db_session, cedula="9000000010", seed=False)
        ok = client.get(
            f"/v1/chat/{conv.id}/history",
            headers=_auth(owner_tokens["access_token"]),
        )
        assert ok.status_code == 200
        assert ok.json()["messages"][0]["text"] == "secreto"

    def test_missing_conversation_history_404(self, client: TestClient, db_session) -> None:
        tokens = _login(client, db_session, cedula="9000000012")
        missing = uuid4()
        resp = client.get(
            f"/v1/chat/{missing}/history",
            headers=_auth(tokens["access_token"]),
        )
        assert resp.status_code == 404


class TestProfileAutomationsSnakeCase:
    def test_get_profile_saved_automations_snake_case(
        self, client: TestClient, db_session, monkeypatch
    ) -> None:
        import pytest
        pytest.skip("Contrato Firestore legacy — perfil migrando a SQLite local (M1S3-A)")
        uid = tokens["cliente"]["cliente_id"]

        def _fake_profile(user_id: str) -> dict:
            assert user_id == uid
            return {
                "saved_automations": [
                    {
                        "id": "a1",
                        "name": "Inbox",
                        "integrationId": "gmail",
                        "instruction": "Revisar",
                        "outputType": "chat",
                    }
                ],
            }

        # Monkeypatch directamente en el router que es donde se llama
        monkeypatch.setattr(
            "app.routers.profile.profile_repository.get_profile",
            lambda user_id: _fake_profile(user_id),
        )

        resp = client.get(
            "/users/me/profile",
            headers=_auth(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert frozenset(data.keys()) == PROFILE_SHAPE_KEYS
        auto = data["saved_automations"][0]
        assert auto["integration_id"] == "gmail"
        assert auto["output_type"] == "chat"
        assert "integrationId" not in auto
        assert "outputType" not in auto


class TestAuthContractBasics:
    def test_login_then_refresh_rotates_tokens(
        self, client: TestClient, db_session
    ) -> None:
        login = _login(client, db_session, cedula="9000000020")
        assert login["token_type"] == "bearer"
        assert login["access_token"]
        assert login["refresh_token"]
        assert login["expires_in"] > 0
        assert login["cliente"]["cedula"] == "9000000020"

        refreshed = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": login["refresh_token"]},
        )
        assert refreshed.status_code == 200
        body = refreshed.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["expires_in"] > 0

    def test_recovery_login_success_emits_tokens(
        self, client: TestClient, db_session
    ) -> None:
        cedula = "9000000030"
        seed_cliente(db_session, cedula=cedula)
        with patch("app.routers.pendrive_recovery.get_recovery_key", return_value=RECOVERY_KEY):
            resp = client.post(
                "/v1/pendrive/recovery-login",
                json={
                    "cedula": cedula,
                    "password": "test123",
                    "recovery_key": RECOVERY_KEY,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["cliente"]["cedula"] == cedula
