#!/usr/bin/env python3
"""Genera par RSA para JWT RS256 y muestra variables .env."""
from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    print("Pegar en frontend/backend/.env:\n")
    print('JWT_PRIVATE_KEY_PEM="' + private_pem.replace("\n", "\\n") + '"')
    print('JWT_PUBLIC_KEY_PEM="' + public_pem.replace("\n", "\\n") + '"')


if __name__ == "__main__":
    main()
