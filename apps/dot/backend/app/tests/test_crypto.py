"""Tests de cifrado Fernet para tokens OAuth."""
from __future__ import annotations

import os
os.environ["DOT_ENV"] = "testing"
os.environ["TOKEN_ENCRYPTION_KEY"] = "ySmbGdhaPWIrdHxlbm4tFcmnvFiXQ4lrEVTN0wOFZIQ="


class TestCryptoTokens:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        from app.crypto_tokens import encrypt_token_blob, decrypt_token_blob

        data = {"token": "abc123", "refresh_token": "def456", "scopes": ["gmail.modify"]}
        cipher = encrypt_token_blob(data)
        assert cipher != str(data)
        decrypted = decrypt_token_blob(cipher)
        assert decrypted == data

    def test_encrypt_empty_dict(self) -> None:
        from app.crypto_tokens import encrypt_token_blob, decrypt_token_blob

        cipher = encrypt_token_blob({})
        decrypted = decrypt_token_blob(cipher)
        assert decrypted == {}

    def test_tampered_cipher_raises(self) -> None:
        import pytest
        from cryptography.fernet import InvalidToken
        from app.crypto_tokens import decrypt_token_blob

        with pytest.raises(InvalidToken):
            decrypt_token_blob("not-a-valid-ciphertext==")
