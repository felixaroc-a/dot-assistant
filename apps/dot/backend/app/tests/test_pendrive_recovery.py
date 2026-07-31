"""Tests de recovery-backup y recovery-login (pendrive perdido)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.billing_db import get_billing_db
from app.tests.conftest import seed_cliente

RECOVERY_KEY = "A" * 48


def _unique_cedula() -> str:
    return uuid4().hex[:12]


def _seed_and_login(client, *, cedula: str | None = None) -> str:
    cedula = cedula or _unique_cedula()
    session = next(get_billing_db())
    seed_cliente(session, cedula=cedula)
    session.close()

    resp = client.post(
        "/v1/auth/login",
        json={"cedula": cedula, "password": "test123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_recovery_backup_success(client) -> None:
    token = _seed_and_login(client)

    with patch("app.routers.pendrive_recovery.save_recovery_key", return_value=True):
        resp = client.post(
            "/v1/pendrive/recovery-backup",
            headers={"Authorization": f"Bearer {token}"},
            json={"recovery_key": RECOVERY_KEY},
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_recovery_backup_returns_503_when_save_fails(client) -> None:
    token = _seed_and_login(client)

    with patch("app.routers.pendrive_recovery.save_recovery_key", return_value=False):
        resp = client.post(
            "/v1/pendrive/recovery-backup",
            headers={"Authorization": f"Bearer {token}"},
            json={"recovery_key": RECOVERY_KEY},
        )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "recovery_backup_failed"


def test_recovery_backup_returns_500_on_exception(client) -> None:
    token = _seed_and_login(client)

    with patch(
        "app.routers.pendrive_recovery.save_recovery_key",
        side_effect=RuntimeError("firestore down"),
    ):
        resp = client.post(
            "/v1/pendrive/recovery-backup",
            headers={"Authorization": f"Bearer {token}"},
            json={"recovery_key": RECOVERY_KEY},
        )

    assert resp.status_code == 500
    assert "Error al guardar recovery key" in resp.json()["detail"]


def test_recovery_login_success(client) -> None:
    cedula = _unique_cedula()
    session = next(get_billing_db())
    seed_cliente(session, cedula=cedula)
    session.close()

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


def test_recovery_login_subscription_expired(client) -> None:
    """D05: suscripción vencida hace 2+ días → bloqueo en recovery login."""
    cedula = _unique_cedula()
    session = next(get_billing_db())
    seed_cliente(session, cedula=cedula, fecha_vencimiento=date.today() - timedelta(days=2))
    session.close()

    with patch("app.routers.pendrive_recovery.get_recovery_key", return_value=RECOVERY_KEY):
        resp = client.post(
            "/v1/pendrive/recovery-login",
            json={
                "cedula": cedula,
                "password": "test123",
                "recovery_key": RECOVERY_KEY,
            },
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "subscription_expired"
