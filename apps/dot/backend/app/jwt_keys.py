"""Carga de claves JWT (RS256 preferido, HS256 legacy).

Las claves se leen desde archivos PEM en config/jwt/ (si existen)
o desde variables de entorno JWT_PRIVATE_KEY_PEM / JWT_PUBLIC_KEY_PEM.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jwt.algorithms import RSAAlgorithm

from app.settings import settings

JWT_ALGORITHM_RS256 = "RS256"
JWT_ALGORITHM_HS256 = "HS256"

JWT_KEYS_DIR = Path(__file__).resolve().parent.parent / "config" / "jwt"


@dataclass(frozen=True)
class JwtSigningConfig:
    algorithm: str
    sign_key: str | bytes
    verify_key: str | bytes


def _normalize_pem(pem: str) -> str:
    return pem.strip().replace("\\n", "\n")


def _read_key_from_file(filename: str) -> str:
    """Lee una clave PEM desde archivo. Retorna vacio si no existe."""
    key_file = JWT_KEYS_DIR / filename
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


def get_jwt_signing_config() -> JwtSigningConfig:
    # Intentar leer desde archivos PEM primero
    private_pem = _read_key_from_file("private.pem")
    public_pem = _read_key_from_file("public.pem")

    # Fallback a variables de entorno
    if not private_pem or not public_pem:
        private_pem = settings.jwt_private_key_pem.strip()
        public_pem = settings.jwt_public_key_pem.strip()

    if private_pem and public_pem:
        private_norm = _normalize_pem(private_pem)
        public_norm = _normalize_pem(public_pem)
        # Validar que las claves son parseables
        RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(private_norm.encode())
        RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(public_norm.encode())
        return JwtSigningConfig(
            algorithm=JWT_ALGORITHM_RS256,
            sign_key=private_norm,
            verify_key=public_norm,
        )

    secret = settings.jwt_secret.strip()
    if secret:
        if settings.is_production:
            raise RuntimeError(
                "En producción configure JWT_PRIVATE_KEY_PEM y JWT_PUBLIC_KEY_PEM (RS256). "
                "JWT_SECRET (HS256) no está permitido."
            )
        return JwtSigningConfig(
            algorithm=JWT_ALGORITHM_HS256,
            sign_key=secret,
            verify_key=secret,
        )

    raise RuntimeError(
        "JWT no configurado: defina JWT_PRIVATE_KEY_PEM + JWT_PUBLIC_KEY_PEM o JWT_SECRET (solo dev)."
    )


def jwt_configured() -> bool:
    try:
        get_jwt_signing_config()
        return True
    except RuntimeError:
        return False
