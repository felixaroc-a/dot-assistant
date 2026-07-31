"""Tests de cifrado de mensajes de chat (chat_crypto).

Verifica que:
- encrypt_message / decrypt_message roundtrip funciona.
- Diferentes claves para chat y tokens producen ciphertexts incompatibles.
- Mensajes legacy (sin prefijo) se devuelven tal cual.
- Token inválido se maneja gracefulmente.
- Clave ausente no causa error.
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from app.services.chat_crypto import (
    CHAT_ENC_PREFIX,
    decrypt_message,
    encrypt_message,
)


def test_roundtrip_with_explicit_key() -> None:
    key = Fernet.generate_key()
    f = Fernet(key)
    original = "Mensaje secreto de prueba con caracteres especiales: ñáéíóú"
    encrypted = encrypt_message(original, key=f)
    assert encrypted.startswith(CHAT_ENC_PREFIX)
    decrypted = decrypt_message(encrypted, key=f)
    assert decrypted == original


def test_legacy_plaintext_passthrough() -> None:
    """Mensajes sin prefijo se devuelven sin cambios (legacy)."""
    plain = "texto plano legacy sin cifrar"
    assert decrypt_message(plain) == plain


def test_tampered_ciphertext_returns_placeholder() -> None:
    """Token manipulado debe devolver placeholder, no lanzar excepción."""
    key = Fernet.generate_key()
    f = Fernet(key)
    encrypted = encrypt_message("real", key=f)
    tampered = encrypted[:-4] + "XXXX"
    result = decrypt_message(tampered, key=f)
    assert "inválido" in result


def test_empty_input() -> None:
    assert decrypt_message("") == ""
    assert decrypt_message(None) == ""  # type: ignore[arg-type]


def test_different_keys_are_incompatible() -> None:
    """Mensaje cifrado con clave A no debe descifrarse con clave B."""
    key_a = Fernet.generate_key()
    key_b = Fernet.generate_key()
    f_a = Fernet(key_a)
    f_b = Fernet(key_b)

    encrypted = encrypt_message("secreto con clave A", key=f_a)
    result = decrypt_message(encrypted, key=f_b)
    assert "inválido" in result or result != "secreto con clave A"

    result_a = decrypt_message(encrypted, key=f_a)
    assert result_a == "secreto con clave A"


def test_chat_key_differs_from_token_key() -> None:
    """Verifica que TOKEN_ENCRYPTION_KEY y CHAT_ENCRYPTION_KEY
    (cuando ambas existen) sean claves distintas que producen
    ciphertexts incompatibles.

    En settings, chat_encryption_key es independiente de
    token_encryption_key. Este test valida que si se configuran
    ambas, el sistema no las confunda.
    """
    from app.settings import settings

    chat_key_raw = (settings.chat_encryption_key or "").strip()
    token_key_raw = (settings.token_encryption_key or "").strip()

    if chat_key_raw and token_key_raw:
        # Si ambas están configuradas, deben ser DIFERENTES
        assert chat_key_raw != token_key_raw, (
            "CHAT_ENCRYPTION_KEY y TOKEN_ENCRYPTION_KEY no deben ser iguales "
            "en producción. Usa claves Fernet distintas."
        )

        try:
            chat_f = Fernet(chat_key_raw.encode("utf-8"))
            token_f = Fernet(token_key_raw.encode("utf-8"))
        except Exception:
            return  # Si alguna clave no es Fernet válida, omitimos

        encrypted_with_chat = encrypt_message("solo chat", key=chat_f)
        result_with_token = decrypt_message(encrypted_with_chat, key=token_f)
        # No debe descifrarse con la clave de tokens
        assert "inválido" in result_with_token, (
            "Mensaje cifrado con CHAT_ENCRYPTION_KEY no debe "
            "descifrarse con TOKEN_ENCRYPTION_KEY"
        )

        # Sanity: descifrar con chat sí funciona
        assert decrypt_message(encrypted_with_chat, key=chat_f) == "solo chat"
