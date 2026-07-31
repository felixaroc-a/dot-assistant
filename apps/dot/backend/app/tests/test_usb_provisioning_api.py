"""Tests de API /v1/usb/* para provisión comercial."""
from __future__ import annotations

from unittest.mock import patch

from app.tests.conftest import seed_cliente
from dot_billing.hardware_token import hash_hardware_token
from sqlalchemy.orm import Session


def test_usb_devices_requires_admin_key(client) -> None:
    resp = client.get("/v1/usb/devices")
    assert resp.status_code == 403


def test_usb_devices_lists_with_registered_client(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    serial = "USB-DEV-REGISTERED"
    row = seed_cliente(
        db_session,
        cedula="30001",
        nombre="Cliente USB Registrado",
        hardware_token_hash=hash_hardware_token(serial),
    )

    fake_devices = [
        {
            "serial": serial,
            "driveLetter": "E:",
            "model": "SanDisk Ultra",
            "interfaceType": "USB",
            "source": "wmi",
        },
        {
            "serial": "USB-SIN-CLIENTE",
            "driveLetter": "F:",
            "model": None,
            "interfaceType": "USB",
            "source": "wmi",
        },
    ]

    with patch(
        "app.routers.usb_provisioning.list_usb_devices",
        return_value=fake_devices,
    ):
        resp = client.get("/v1/usb/devices", headers=admin_api_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2

    by_serial = {item["serial"]: item for item in data["devices"]}
    assert by_serial[serial]["drive"] == "E:"
    assert by_serial[serial]["model"] == "SanDisk Ultra"
    assert by_serial[serial]["registered"]["cedula"] == row.cedula
    assert by_serial[serial]["registered"]["nombre"] == row.nombre
    assert by_serial[serial]["registered"]["uid"] == str(row.id)
    assert by_serial["USB-SIN-CLIENTE"]["registered"] is None


def test_client_by_serial_found(
    client, db_session: Session, admin_api_headers: dict[str, str]
) -> None:
    serial = "USB-LOOKUP-001"
    row = seed_cliente(
        db_session,
        cedula="40001",
        nombre="Ana Lookup",
        hardware_token_hash=hash_hardware_token(serial),
    )

    resp = client.get(
        f"/v1/usb/client-by-serial/{serial}", headers=admin_api_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["cedula"] == row.cedula
    assert data["nombre"] == row.nombre
    assert data["uid"] == str(row.id)


def test_client_by_serial_not_registered(client, admin_api_headers: dict[str, str]) -> None:
    resp = client.get(
        "/v1/usb/client-by-serial/NO-EXISTE", headers=admin_api_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "SERIAL_NOT_REGISTERED"


def test_usb_provision_requires_admin_key(client) -> None:
    resp = client.post(
        "/v1/usb/provision",
        json={"serial": "USB-1", "drive": "E:"},
    )
    assert resp.status_code == 403


def test_usb_provision_success(client, admin_api_headers: dict[str, str]) -> None:
    serial = "USB-PROVISION-OK"
    fake_result = {
        "ok": True,
        "code": "PROVISION_COMPLETED",
        "message": "Listo.",
        "steps": [{"key": "completado", "status": "ok", "message": "OK"}],
        "result": {
            "driveLetter": "E:",
            "serial": serial,
            "vaultRegenerated": True,
            "installerCopied": True,
        },
    }

    with patch(
        "app.routers.usb_provisioning.run_usb_provisioning",
        return_value=fake_result,
    ) as mock_run:
        resp = client.post(
            "/v1/usb/provision",
            headers=admin_api_headers,
            json={
                "serial": serial,
                "drive": "E:",
                "force": True,
                "copy_installer": False,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["code"] == "PROVISION_COMPLETED"
    assert data["result"]["serial"] == serial

    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    assert kwargs["serial"] == serial
    assert kwargs["drive_letter"] == "E:"
    assert kwargs["force"] is True
    assert kwargs["copy_installer"] is False
    assert kwargs["require_registered"] is True


def test_usb_provision_rejects_generic_serial(
    client, admin_api_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/v1/usb/provision",
        headers=admin_api_headers,
        json={"serial": "0000000005", "drive": "E:"},
    )
    assert resp.status_code == 422
    assert "serial" in resp.json()["detail"].lower()


def test_usb_provision_maps_script_error(
    client, admin_api_headers: dict[str, str]
) -> None:
    from app.services.usb_provisioning_service import UsbProvisioningError

    with patch(
        "app.routers.usb_provisioning.run_usb_provisioning",
        side_effect=UsbProvisioningError(
            message="Serial no registrado",
            code="SERIAL_NOT_REGISTERED",
            status_code=422,
        ),
    ):
        resp = client.post(
            "/v1/usb/provision",
            headers=admin_api_headers,
            json={"serial": "USB-FAIL"},
        )

    assert resp.status_code == 422
    data = resp.json()
    assert data["ok"] is False
    assert data["code"] == "SERIAL_NOT_REGISTERED"
