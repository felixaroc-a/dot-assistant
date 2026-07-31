from __future__ import annotations

import pytest

from dot_billing.hardware_token import (
    SELLER_INVALID_SERIAL_MESSAGE,
    hash_hardware_token,
    resolve_stable_usb_serial,
    sanitize_hardware_serial,
    serial_from_pnp_device_id,
    verify_hardware_token,
)


def test_sanitize_rejects_generic_and_all_zeros():
    assert sanitize_hardware_serial(None) is None
    assert sanitize_hardware_serial("") is None
    assert sanitize_hardware_serial("0000000005") is None
    assert sanitize_hardware_serial("000000000000") is None
    assert sanitize_hardware_serial("12345678") is None
    assert sanitize_hardware_serial("1234567890") == "1234567890"
    assert sanitize_hardware_serial("ab") is None
    assert sanitize_hardware_serial("VALID-SERIAL_99") == "VALID-SERIAL_99"


def test_resolve_stable_usb_serial_prefers_wmi_then_pnp():
    pnp = r"USBSTOR\DISK&VEN_KINGSTON&PROD_X&REV_1.0\2CFDA1BBB4CF1931090703CE&0"
    assert resolve_stable_usb_serial("0000000005", pnp) == "2CFDA1BBB4CF1931090703CE"
    assert resolve_stable_usb_serial("ABCD1234", pnp) == "ABCD1234"
    assert resolve_stable_usb_serial("0000000005", None) is None
    assert serial_from_pnp_device_id(pnp) == "2CFDA1BBB4CF1931090703CE"


def test_hash_and_verify_roundtrip(monkeypatch):
    monkeypatch.setenv("HARDWARE_TOKEN_PEPPER", "test-pepper-32-chars-minimum!!")
    serial = "PENDRIVE-SERIAL-42"
    token_hash = hash_hardware_token(serial)
    assert len(token_hash) == 64
    assert verify_hardware_token(serial, token_hash)
    assert not verify_hardware_token("OTHER", token_hash)


def test_hash_rejects_invalid_serial(monkeypatch):
    monkeypatch.setenv("HARDWARE_TOKEN_PEPPER", "test-pepper-32-chars-minimum!!")
    with pytest.raises(ValueError, match="inválido"):
        hash_hardware_token("0000000005")


def test_seller_message_is_stable():
    assert "genérico" in SELLER_INVALID_SERIAL_MESSAGE.lower()
