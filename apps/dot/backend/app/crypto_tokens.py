"""Cifrado Fernet para tokens OAuth."""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet

from app.settings import settings


def _fernet() -> Fernet:
    key = settings.token_encryption_key.strip()
    if not key:
        raise RuntimeError(
            "Falta TOKEN_ENCRYPTION_KEY en .env (genera una con cryptography.fernet)."
        )
    return Fernet(key.encode())


def encrypt_token_blob(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def decrypt_token_blob(ciphertext: str) -> dict[str, Any]:
    raw = _fernet().decrypt(ciphertext.encode())
    return json.loads(raw.decode())
