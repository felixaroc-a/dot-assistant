"""Cifrado Fernet para mensajes de chat.

Provee encrypt/decrypt usando CHAT_ENCRYPTION_KEY de settings.
Los mensajes se persisten con prefijo ``enc:v1:`` para distinguirlos
de texto plano legacy.

FAIL-CLOSED CERTIFICADO (Jul 2026): en producci?n (DOT_ENV=production),
si CHAT_ENCRYPTION_KEY falta o es inv?lida:
  - encrypt_message() ? lanza ChatCryptoError (no escribe texto plano)
  - decrypt_message() ? lanza ChatCryptoError (no devuelve placeholder)
  - main.py lifespan ? log.critical + advertencia en startup
NO existe path donde chat sin cifrar se acepte en producci?n.
En desarrollo (dot_env != production): texto plano para no bloquear iteraci?n local.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.settings import settings

log = logging.getLogger("dot.chat_crypto")

CHAT_ENC_PREFIX = "enc:v1:"


class ChatCryptoError(RuntimeError):
    """Clave de cifrado ausente o inválida (fail-closed)."""


def _get_chat_fernet() -> Fernet | None:
    """Devuelve instancia Fernet o None si no hay clave configurada."""
    key = settings.chat_encryption_key.strip() or settings.token_encryption_key.strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError):
        log.warning("CHAT_ENCRYPTION_KEY invalida; se usará texto plano en chat_messages.")
        return None


def encrypt_message(text: str, key: Fernet | None = None) -> str:
    """Cifra texto plano para persistencia.

    P0 fail-closed: si CHAT_ENCRYPTION_KEY falta en producción, lanza
    ChatCryptoError. En desarrollo retorna texto sin cifrar para no
    bloquear la iteración local.
    """
    fernet = key or _get_chat_fernet()
    if fernet is None:
        if settings.is_production:
            raise ChatCryptoError(
                "CHAT_ENCRYPTION_KEY no configurada. "
                "No se pueden cifrar mensajes en producción."
            )
        return text
    token = fernet.encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{CHAT_ENC_PREFIX}{token}"


def decrypt_message(ciphertext: str, key: Fernet | None = None) -> str:
    """Descifra un mensaje previamente cifrado.

    Maneja gracefulmente:
    - Texto plano legacy (sin prefijo).
    - Token inválido / manipulado (log warning + placeholder).

    P0 fail-closed: si CHAT_ENCRYPTION_KEY falta en producción, lanza
    ChatCryptoError. En desarrollo devuelve placeholder para no bloquear
    la iteración local.
    """
    if not isinstance(ciphertext, str):
        return ""
    if not ciphertext.startswith(CHAT_ENC_PREFIX):
        return ciphertext

    fernet = key or _get_chat_fernet()
    if fernet is None:
        if settings.is_production:
            raise ChatCryptoError(
                "CHAT_ENCRYPTION_KEY no configurada. "
                "No se pueden descifrar mensajes en producción."
            )
        log.warning("CHAT_ENCRYPTION_KEY ausente; placeholder en desarrollo.")
        return "[contenido cifrado no disponible: falta CHAT_ENCRYPTION_KEY]"

    token = ciphertext[len(CHAT_ENC_PREFIX):]
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError, UnicodeDecodeError):
        log.warning("InvalidToken al descifrar mensaje de chat; posible manipulación.")
        return "[contenido cifrado inválido]"
