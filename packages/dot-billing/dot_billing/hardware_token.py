"""Hash y verificación del serial de hardware USB (pendrive)."""
from __future__ import annotations

import hashlib
import os
import re
import secrets

_SERIAL_MIN_LEN = 4
_SERIAL_MAX_LEN = 128
_SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9_.\-&]+$")
_INVALID_SERIALS = frozenset(
    {
        "",
        "none",
        "null",
        "00000000",
        "000000000000",
        "0000000001",
        "0000000005",
        "ffffffff",
        "n/a",
        "not available",
        "default string",
        "12345678",
        "0123456789",
    }
)

# Mensaje operativo (panel / provisioner) — alineado con frontend/electron/usb-serial-policy.cjs
SELLER_INVALID_SERIAL_MESSAGE = (
    "Este pendrive no tiene un número de serie único válido (reporta un serial genérico de fábrica). "
    "Usa otro modelo de USB o contacta a soporte técnico; no se puede entregar Nordik en este dispositivo."
)


def serial_from_pnp_device_id(pnp_device_id: str | None) -> str | None:
    """Extrae serial del tail de PNPDeviceID (misma regla que usb-serial-policy.cjs)."""
    if not pnp_device_id:
        return None
    parts = pnp_device_id.split("\\")
    if len(parts) < 3:
        return None
    tail = parts[-1]
    # Eliminar sufijo de instancia del SO (&0, &1, etc.) para obtener serial base estable
    tail = re.sub(r"&[0-9]+$", "", tail)
    return sanitize_hardware_serial(tail)


def resolve_stable_usb_serial(
    wmi_serial: str | None = None,
    pnp_device_id: str | None = None,
) -> str | None:
    """
    Serial estable para registro y provisión: WMI primero, PNP solo si WMI no es válido.
    """
    clean = sanitize_hardware_serial(wmi_serial)
    if clean:
        return clean
    return serial_from_pnp_device_id(pnp_device_id)


def sanitize_hardware_serial(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip().strip("\x00")
    if not cleaned or cleaned.lower() in _INVALID_SERIALS:
        return None
    if cleaned.isdigit() and set(cleaned) == {"0"}:
        return None
    if len(cleaned) < _SERIAL_MIN_LEN or len(cleaned) > _SERIAL_MAX_LEN:
        return None
    if not _SERIAL_PATTERN.match(cleaned):
        return None
    if cleaned.isdigit() and set(cleaned) == {"0"}:
        return None
    return cleaned


def _pepper_bytes() -> bytes:
    pepper = os.environ.get("HARDWARE_TOKEN_PEPPER", "").strip()
    if not pepper:
        pepper = os.environ.get("SESSION_SECRET", "").strip()
    if not pepper:
        raise ValueError(
            "HARDWARE_TOKEN_PEPPER no configurada. "
            "Establezca esta variable con un secreto compartido de al menos 32 caracteres."
        )
    return pepper.encode("utf-8")


def hash_hardware_token(serial: str) -> str:
    clean = sanitize_hardware_serial(serial)
    if not clean:
        raise ValueError("Serial de hardware inválido")
    payload = clean.encode("utf-8") + b"\x00" + _pepper_bytes()
    return hashlib.sha256(payload).hexdigest()


def verify_hardware_token(serial: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        expected = hash_hardware_token(serial)
        return secrets.compare_digest(expected, stored_hash)
    except ValueError:
        return False
