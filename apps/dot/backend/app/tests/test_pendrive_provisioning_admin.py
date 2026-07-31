"""Tests de endpoints admin para provisión de pendrive."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.billing_models import ClienteORM
from app.tests.conftest import seed_cliente
from dot_billing.hardware_token import hash_hardware_token
from sqlalchemy.orm import Session


def test_provisioning_clients_requires_admin_key(client) -> None:
    resp = client.get("/v1/admin/pendrive/provisioning/clients")
    assert resp.status_code == 403


def test_provisioning_clients_lists_only_active(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    seed_cliente(
        db_session,
        cedula="10001",
        nombre="Cliente Activo 1",
        hardware_token_hash=hash_hardware_token("SERIAL-ACTIVO-1"),
    )
    seed_cliente(
        db_session,
        cedula="10002",
        nombre="Cliente Activo 2",
        hardware_token_hash=None,
    )
    seed_cliente(
        db_session,
        cedula="10003",
        nombre="Cliente Vencido",
        fecha_vencimiento=date.today() - timedelta(days=1),
    )

    resp = client.get(
        "/v1/admin/pendrive/provisioning/clients",
        headers=admin_api_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2

    cedulas = {item["cedula"] for item in data["clients"]}
    assert cedulas == {"10001", "10002"}
    for item in data["clients"]:
        assert item["uid"]
        assert item["nombre"]
        assert item["estado"] == "activo"
        assert isinstance(item["has_hardware_linked"], bool)


def test_provisioning_validate_matches_existing_serial(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    serial = "SERIAL-REAL-VALIDA"
    row = seed_cliente(
        db_session,
        cedula="20001",
        hardware_token_hash=hash_hardware_token(serial),
    )

    resp = client.post(
        "/v1/admin/pendrive/provisioning/validate",
        headers=admin_api_headers,
        json={"uid": str(row.id), "serial": serial, "mark_completed": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["serial_matches"] is True
    assert data["provision_completed"] is False
    assert data["has_hardware_linked"] is True


def test_provisioning_validate_mark_completed_links_serial(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    serial = "SERIAL-NUEVO-LINK"
    row = seed_cliente(
        db_session,
        cedula="20002",
        hardware_token_hash=None,
    )

    resp = client.post(
        "/v1/admin/pendrive/provisioning/validate",
        headers=admin_api_headers,
        json={"uid": str(row.id), "serial": serial, "mark_completed": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["provision_completed"] is True
    assert data["serial_matches"] is True
    assert data["has_hardware_linked"] is True

    db_session.expire_all()
    refreshed = db_session.execute(
        select(ClienteORM).where(ClienteORM.id == row.id)
    ).scalar_one()
    assert refreshed.hardware_token_hash == hash_hardware_token(serial)


def test_pendrive_verify_returns_client_info(client, db_session: Session) -> None:
    serial = "SERIAL-VERIFY-INFO"
    row = seed_cliente(
        db_session,
        cedula="30001",
        nombre="Cliente Verify Info",
        hardware_token_hash=hash_hardware_token(serial),
    )

    # Sin JWT: solo retorna ok + hardware_bound (datos minimos)
    resp = client.post("/v1/pendrive/verify", json={"serial": serial})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["hardware_bound"] is True
    assert data["serial_hash"] == hash_hardware_token(serial)
    assert data["uid"] is None  # sin JWT no expone datos personales
    assert data["cedula"] is None
    assert data["nombre"] is None


def test_provisioning_validate_mark_completed_rejects_mismatch(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    row = seed_cliente(
        db_session,
        cedula="20003",
        hardware_token_hash=hash_hardware_token("SERIAL-ORIGINAL"),
    )

    resp = client.post(
        "/v1/admin/pendrive/provisioning/validate",
        headers=admin_api_headers,
        json={
            "uid": str(row.id),
            "serial": "SERIAL-DISTINTO",
            "mark_completed": True,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "SERIAL_MISMATCH"
