from __future__ import annotations

import logging

import bcrypt

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")

_log = logging.getLogger("dot_billing.passwords")


def hash_password(plain: str) -> str:
    """Hash bcrypt para almacenar en `clave_acceso`."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(stored: str, given: str) -> bool:
    """Verifica contraseña contra hash bcrypt."""
    if not stored or not given:
        return False
    if stored.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(given.encode("utf-8"), stored.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    # Ya no se aceptan contraseñas en texto plano
    _log.error(
        "Password legacy (no bcrypt) detectada. "
        "La cuenta debe migrarse a bcrypt."
    )
    return False


def is_hashed(stored: str) -> bool:
    return stored.startswith(_BCRYPT_PREFIXES)
