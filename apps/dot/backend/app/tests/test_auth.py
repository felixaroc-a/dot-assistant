"""Tests de autenticacion (login, refresh, token expirado)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.billing_db import get_billing_db
from dot_billing.hardware_token import hash_hardware_token

from app.tests.conftest import seed_cliente


class TestLogin:
    def test_login_success(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session)
        session.close()

        resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["expires_in"] > 0
        assert data["cliente"]["cedula"] == "1234567890"
        assert data["cliente"]["plan"] == "mensual"

    def test_login_invalid_credentials(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session, password="realpass")
        session.close()

        resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "wrongpass",
        })
        assert resp.status_code == 401
        assert any(w in resp.json()["detail"] for w in ["credenciales", "acceso", "sesión"])

    def test_login_nonexistent_user(self, client) -> None:
        resp = client.post("/v1/auth/login", json={
            "cedula": "0000000000",
            "password": "test123",
        })
        assert resp.status_code == 401
        assert any(w in resp.json()["detail"] for w in ["credenciales", "acceso", "sesión"])

    def test_login_with_pendrive_success(self, client) -> None:
        serial = "PENDRIVE-TEST-1234"
        session = next(get_billing_db())
        seed_cliente(session, hardware_token_hash=hash_hardware_token(serial))
        session.close()

        resp = client.post(
            "/v1/auth/login",
            json={
                "cedula": "1234567890",
                "password": "test123",
                "hardware_serial": serial,
            },
        )
        assert resp.status_code == 200

    def test_login_wrong_pendrive(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session, hardware_token_hash=hash_hardware_token("REAL-SERIAL"))
        session.close()

        resp = client.post(
            "/v1/auth/login",
            json={
                "cedula": "1234567890",
                "password": "test123",
                "hardware_serial": "FAKE-SERIAL",
            },
        )
        assert resp.status_code == 401

    def test_login_pendrive_required(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session, hardware_token_hash=hash_hardware_token("ONLY-USB"))
        session.close()

        resp = client.post(
            "/v1/auth/login",
            json={"cedula": "1234567890", "password": "test123"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "pendrive_required"

    def test_login_expired_subscription(self, client) -> None:
        """D05: suscripción vencida hace 2+ días (después de gracia) → 403."""
        session = next(get_billing_db())
        utc_today = datetime.now(timezone.utc).date()
        seed_cliente(session, fecha_vencimiento=utc_today - timedelta(days=2))
        session.close()

        resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        assert resp.status_code == 403
        assert "subscription_expired" in resp.json()["detail"]

    def test_login_grace_period_allows(self, client) -> None:
        """D05: el día después del vencimiento (gracia) permite login."""
        session = next(get_billing_db())
        utc_today = datetime.now(timezone.utc).date()
        seed_cliente(session, fecha_vencimiento=utc_today - timedelta(days=1))
        session.close()

        resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        assert resp.status_code == 200

    def test_login_active_subscription_on_expiry_date(self, client) -> None:
        """Misma regla que el frontend: vigente hasta inclusive el día de vencimiento (UTC)."""
        utc_today = datetime.now(timezone.utc).date()
        session = next(get_billing_db())
        seed_cliente(session, fecha_vencimiento=utc_today)
        session.close()

        resp = client.post(
            "/v1/auth/login",
            json={"cedula": "1234567890", "password": "test123"},
        )
        assert resp.status_code == 200
        assert resp.json()["cliente"]["fecha_vencimiento"] == utc_today.isoformat()


class TestRefresh:
    def test_refresh_success(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session)
        session.close()

        login_resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post("/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["expires_in"] > 0

    def test_refresh_invalid_token(self, client) -> None:
        resp = client.post("/v1/auth/refresh", json={
            "refresh_token": "invalid.token.here",
        })
        assert resp.status_code == 401

    def test_refresh_with_access_token(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session)
        session.close()

        login_resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        access_token = login_resp.json()["access_token"]

        resp = client.post("/v1/auth/refresh", json={
            "refresh_token": access_token,
        })
        assert resp.status_code == 401

    def test_refresh_revoked_after_password_reset(self, client) -> None:
        session = next(get_billing_db())
        row = seed_cliente(session)
        session.close()

        login_resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        revoke_resp = client.post(
            "/v1/admin/revoke-user-tokens",
            headers={"X-Admin-Key": "test-admin-key"},
            json={"uid": str(row.id)},
        )
        assert revoke_resp.status_code == 204

        refresh_resp = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refresh_resp.status_code == 401
        assert "revocado" in refresh_resp.json()["detail"].lower()


class TestMe:
    def test_me_authenticated(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session)
        session.close()

        login_resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        token = login_resp.json()["access_token"]

        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"]
        assert data["cedula"] == "1234567890"

    def test_me_no_token(self, client) -> None:
        resp = client.get("/me")
        assert resp.status_code == 401

    def test_me_invalid_bearer(self, client) -> None:
        resp = client.get("/me", headers={"Authorization": "Bearer not.a.valid.jwt"})
        assert resp.status_code == 401

    def test_me_token_revoked_by_admin(self, client) -> None:
        session = next(get_billing_db())
        row = seed_cliente(session)
        session.close()

        login_resp = client.post("/v1/auth/login", json={
            "cedula": "1234567890",
            "password": "test123",
        })
        token = login_resp.json()["access_token"]

        revoke_resp = client.post(
            "/v1/admin/revoke-user-tokens",
            headers={"X-Admin-Key": "test-admin-key"},
            json={"uid": str(row.id)},
        )
        assert revoke_resp.status_code == 204

        me_resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 401
        assert "revocado" in me_resp.json()["detail"].lower()


class TestAdminRevocation:
    def test_admin_revoke_requires_api_key(self, client) -> None:
        resp = client.post("/v1/admin/revoke-user-tokens", json={"uid": "abc"})
        assert resp.status_code == 403


class TestHealth:
    def test_health(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
