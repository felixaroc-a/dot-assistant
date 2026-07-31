"""Integración auth: login, refresh (rotación/reuso), logout y /me."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.auth import LoginResponse, MeResponse
from app.tests.conftest import seed_cliente

LOGIN_SHAPE_KEYS = frozenset(LoginResponse.model_fields.keys())
ME_SHAPE_KEYS = frozenset(MeResponse.model_fields.keys())


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _login(
    client: TestClient,
    db_session: Session,
    *,
    cedula: str = "1234567890",
    password: str = "test123",
    **seed_overrides,
) -> dict:
    seed_cliente(db_session, cedula=cedula, password=password, **seed_overrides)
    resp = client.post(
        "/v1/auth/login",
        json={"cedula": cedula, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestAuthLoginIntegration:
    def test_login_success_contract(self, client: TestClient, db_session: Session) -> None:
        data = _login(client, db_session)

        assert frozenset(data.keys()) == LOGIN_SHAPE_KEYS
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        assert data["cliente"]["cedula"] == "1234567890"
        assert data["cliente"]["plan"] == "mensual"

    def test_login_401_invalid_credentials(self, client: TestClient, db_session: Session) -> None:
        seed_cliente(db_session, password="realpass")

        resp = client.post(
            "/v1/auth/login",
            json={"cedula": "1234567890", "password": "wrongpass"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "credenciales_invalidas"

    def test_login_403_subscription_expired(self, client: TestClient, db_session: Session) -> None:
        """D05: suscripción vencida hace 2+ días → 403."""
        utc_today = datetime.now(timezone.utc).date()
        seed_cliente(db_session, fecha_vencimiento=utc_today - timedelta(days=2))

        resp = client.post(
            "/v1/auth/login",
            json={"cedula": "1234567890", "password": "test123"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "subscription_expired"


class TestAuthRefreshIntegration:
    def test_refresh_rotation_issues_new_tokens(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        tokens = _login(client, db_session)
        original_refresh = tokens["refresh_token"]
        original_access = tokens["access_token"]

        refresh_resp = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": original_refresh},
        )
        assert refresh_resp.status_code == 200, refresh_resp.text
        rotated = refresh_resp.json()
        assert rotated["access_token"] != original_access
        assert rotated["refresh_token"] != original_refresh
        assert rotated["expires_in"] > 0

        me_old = client.get("/me", headers=_auth_headers(original_access))
        assert me_old.status_code == 200

        me_new = client.get("/me", headers=_auth_headers(rotated["access_token"]))
        assert me_new.status_code == 200
        assert me_new.json()["uid"] == me_old.json()["uid"]

    def test_refresh_reuse_detected_and_revokes_family(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        tokens = _login(client, db_session)
        original_refresh = tokens["refresh_token"]

        first = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": original_refresh},
        )
        assert first.status_code == 200
        new_refresh = first.json()["refresh_token"]

        reuse = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": original_refresh},
        )
        assert reuse.status_code == 401
        assert "sospechosa" in reuse.json()["detail"].lower()

        after_theft = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        assert after_theft.status_code == 401


class TestAuthLogoutIntegration:
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

    def test_logout_requires_bearer(self, client: TestClient) -> None:
        resp = client.post("/v1/auth/logout", json={})
        assert resp.status_code == 401


class TestAuthMeIntegration:
    def test_me_with_valid_bearer(self, client: TestClient, db_session: Session) -> None:
        tokens = _login(client, db_session)

        resp = client.get("/me", headers=_auth_headers(tokens["access_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert frozenset(data.keys()) == ME_SHAPE_KEYS
        assert data["uid"] == tokens["cliente"]["cliente_id"]
        assert data["cedula"] == "1234567890"
        assert data["plan"] == "mensual"

    def test_me_without_bearer(self, client: TestClient) -> None:
        resp = client.get("/me")
        assert resp.status_code == 401

    def test_me_with_invalid_bearer(self, client: TestClient) -> None:
        resp = client.get("/me", headers=_auth_headers("not.a.valid.jwt"))
        assert resp.status_code == 401


class TestAuthEndToEndFlow:
    def test_full_session_lifecycle(self, client: TestClient, db_session: Session) -> None:
        tokens = _login(client, db_session)
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]

        me1 = client.get("/me", headers=_auth_headers(access))
        assert me1.status_code == 200

        rotated = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert rotated.status_code == 200
        new_access = rotated.json()["access_token"]
        new_refresh = rotated.json()["refresh_token"]

        me2 = client.get("/me", headers=_auth_headers(new_access))
        assert me2.status_code == 200
        assert me2.json()["uid"] == me1.json()["uid"]

        stale_refresh = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert stale_refresh.status_code == 401

        logout = client.post(
            "/v1/auth/logout",
            headers=_auth_headers(new_access),
            json={"refresh_token": new_refresh},
        )
        assert logout.status_code == 204

        assert client.get("/me", headers=_auth_headers(new_access)).status_code == 401
        assert (
            client.post("/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code
            == 401
        )
