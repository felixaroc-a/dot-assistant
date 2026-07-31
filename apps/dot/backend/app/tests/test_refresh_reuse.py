"""Detección de reutilización de refresh token."""
from __future__ import annotations


from app.billing_db import get_billing_db
from app.tests.conftest import seed_cliente


class TestRefreshReuse:
    def test_reused_refresh_revoked(self, client) -> None:
        session = next(get_billing_db())
        seed_cliente(session)
        session.close()

        login = client.post(
            "/v1/auth/login",
            json={"cedula": "1234567890", "password": "test123"},
        )
        refresh = login.json()["refresh_token"]

        first = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert first.status_code == 200
        new_refresh = first.json()["refresh_token"]

        reuse = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert reuse.status_code == 401

        # Token nuevo también invalidado tras detección de robo
        after_theft = client.post("/v1/auth/refresh", json={"refresh_token": new_refresh})
        assert after_theft.status_code == 401
