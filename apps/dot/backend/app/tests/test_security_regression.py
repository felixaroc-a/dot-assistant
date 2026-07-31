"""Red anti-regresión de seguridad (auditoría §7): contratos API críticos."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.chat_models import ConversationORM, MessageORM
from app.main import CORS_ALLOW_METHODS
from app.schemas.profile import UserProfileResponse
from app.tests.conftest import seed_cliente

PROFILE_SHAPE_KEYS = frozenset(UserProfileResponse.model_fields.keys())


def _cors_allowed_methods() -> frozenset[str]:
    return frozenset(m.upper() for m in CORS_ALLOW_METHODS)


def _login(
    client: TestClient,
    db_session: Session,
    **overrides,
) -> dict:
    cedula = overrides.pop("cedula", None) or f"10{uuid4().hex[:8]}"
    seed_cliente(db_session, cedula=cedula, **overrides)
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": cedula, "password": "test123"},
    )
    assert resp.status_code == 200
    return resp.json()


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


class TestProfileShape:
    def test_get_profile_response_shape(
        self,
        client: TestClient,
        db_session: Session,
        monkeypatch,
    ) -> None:
        tokens = _login(client, db_session)
        uid = tokens["cliente"]["cliente_id"]

        def _fake_profile(user_id: str) -> dict:
            assert user_id == uid
            return {
                "display_name": "Ana DOT",
                "channel_id": "ch-1",
                "ai_provider_id": "deepseek",
                "integrations": ["gmail"],
                "automation_summary": "Resumen",
                "onboarding_completed": True,
                "saved_automations": [
                    {
                        "id": "auto-1",
                        "name": "Inbox",
                        "integrationId": "gmail",
                        "instruction": "Revisar correo",
                    }
                ],
                "pending_automation_results": {"has_new": False},
            }

        monkeypatch.setattr(
            "app.repositories.profile_repository.get_user_profile",
            _fake_profile,
        )

        resp = client.get("/users/me/profile", headers=_auth_headers(tokens["access_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert frozenset(data.keys()) == PROFILE_SHAPE_KEYS
        assert data["display_name"] == "Ana DOT"
        assert data["integrations"] == ["gmail"]
        auto = data["saved_automations"][0]
        assert auto["integration_id"] == "gmail"
        assert "integrationId" not in auto
        assert "outputType" not in auto

    def test_get_profile_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/users/me/profile")
        assert resp.status_code == 401


class TestAuthRefreshLogout:
    def test_logout_revokes_access_and_refresh(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        tokens = _login(client, db_session)
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]

        logout = client.post(
            "/v1/auth/logout",
            headers=_auth_headers(access),
            json={"refresh_token": refresh},
        )
        assert logout.status_code == 204

        me = client.get("/me", headers=_auth_headers(access))
        assert me.status_code == 401

        refresh_resp = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert refresh_resp.status_code == 401

    def test_logout_without_refresh_still_revokes_access(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        tokens = _login(client, db_session)
        access = tokens["access_token"]

        logout = client.post(
            "/v1/auth/logout",
            headers=_auth_headers(access),
            json={},
        )
        assert logout.status_code == 204

        me = client.get("/me", headers=_auth_headers(access))
        assert me.status_code == 401


class TestPendriveLink:
    def test_link_pendrive_then_login_with_serial(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        tokens = _login(client, db_session)
        cedula = tokens["cliente"]["cedula"]
        serial = "NEW-USB-SERIAL-9999"

        link = client.post(
            "/v1/pendrive/link",
            headers=_auth_headers(tokens["access_token"]),
            json={"serial": serial},
        )
        assert link.status_code == 200, link.text
        body = link.json()
        assert body["ok"] is True

        login = client.post(
            "/v1/auth/login",
            json={
                "cedula": cedula,
                "password": "test123",
                "hardware_serial": serial,
            },
        )
        assert login.status_code == 200

    def test_link_pendrive_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/v1/pendrive/link", json={"serial": "X"})
        assert resp.status_code == 401


class TestCorsMethods:
    def test_preflight_exposes_configured_methods(self, client: TestClient) -> None:
        expected = _cors_allowed_methods()
        resp = client.options(
            "/me",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        exposed = {m.strip().upper() for m in allowed.split(",") if m.strip()}
        assert expected.issubset(exposed)

    def test_preflight_rejects_method_outside_allowlist(self, client: TestClient) -> None:
        resp = client.options(
            "/me",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "TRACE",
            },
        )
        # Starlette rechaza métodos fuera de allow_methods con 400 (sin exponer TRACE).
        assert resp.status_code == 400


class TestChatOwnership:
    def _seed_conversation(
        self,
        db_session: Session,
        cliente_id: UUID,
        title: str = "Privada",
    ) -> UUID:
        conv_id = uuid4()
        conv = ConversationORM(
            id=conv_id,
            cliente_id=cliente_id,
            title=title,
            provider="deepseek",
        )
        db_session.add(conv)
        db_session.add(
            MessageORM(
                conversation_id=conv_id,
                role="user",
                content="mensaje privado",
            )
        )
        db_session.commit()
        return conv_id

    def test_chat_list_scoped_to_authenticated_user(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        owner = seed_cliente(db_session, cedula=f"11{uuid4().hex[:8]}")
        other = seed_cliente(db_session, cedula=f"22{uuid4().hex[:8]}")

        owner_conv = self._seed_conversation(db_session, owner.id, "Mía")
        self._seed_conversation(db_session, other.id, "Ajena")

        login = client.post(
            "/v1/auth/login",
            json={"cedula": owner.cedula, "password": "test123"},
        )
        token = login.json()["access_token"]

        resp = client.get("/v1/chat", headers=_auth_headers(token))
        assert resp.status_code == 200
        ids = {c["id"] for c in resp.json()["conversations"]}
        assert str(owner_conv) in ids
        assert len(ids) == 1

    def test_chat_history_denies_foreign_conversation(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        owner = seed_cliente(db_session, cedula=f"33{uuid4().hex[:8]}")
        other = seed_cliente(db_session, cedula=f"44{uuid4().hex[:8]}")

        foreign_conv = self._seed_conversation(db_session, other.id)

        login = client.post(
            "/v1/auth/login",
            json={"cedula": owner.cedula, "password": "test123"},
        )
        token = login.json()["access_token"]

        resp = client.get(
            f"/v1/chat/{foreign_conv}/history",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 403
        assert "acceso" in resp.json()["detail"].lower()

    def test_chat_history_allows_owner(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        owner = seed_cliente(db_session, cedula=f"55{uuid4().hex[:8]}")
        own_conv = self._seed_conversation(db_session, owner.id)

        login = client.post(
            "/v1/auth/login",
            json={"cedula": owner.cedula, "password": "test123"},
        )
        token = login.json()["access_token"]

        resp = client.get(
            f"/v1/chat/{own_conv}/history",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 1
