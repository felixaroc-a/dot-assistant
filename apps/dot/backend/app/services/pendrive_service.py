"""Servicio de verificación server-side de pendrives DOT.

Funcionalidades:
- Verificar vault de pendrive (POST /v1/pendrive/verify)
- Guardar/recuperar recovery keys en Firestore
"""
from __future__ import annotations

import logging

from app import crypto_tokens
from app.firebase_db import get_pendrive_recovery, save_pendrive_recovery

log = logging.getLogger("dot.pendrive_service")


def save_recovery_key(uid: str, recovery_key: str) -> bool:
    """Guarda la recovery key (48 chars) cifrada con Fernet en Firestore.

    Returns:
        True si se guardo y confirmo exitosamente, False en caso contrario.
    """
    ciphertext = crypto_tokens.encrypt_token_blob(
        {"recovery_key": recovery_key, "type": "pendrive_vault"}
    )
    try:
        return save_pendrive_recovery(uid, ciphertext)
    except RuntimeError:
        log.critical(
            "No se pudo guardar la recovery key en Firestore. "
            "El cliente no podra recuperar su pendrive si se pierde."
        )
        return False


def get_recovery_key(uid: str) -> str | None:
    """Recupera y descifra la recovery key desde Firestore."""
    ciphertext = get_pendrive_recovery(uid)
    if not ciphertext:
        return None
    try:
        data = crypto_tokens.decrypt_token_blob(ciphertext)
        return data.get("recovery_key")
    except Exception:
        log.warning("Error descifrando recovery key para uid=%s", uid[:8], exc_info=True)
        return None
