"""Challenge-response protocol para autenticación de pendrives.

Implementa un handshake criptográfico donde el servidor emite un nonce
y el cliente debe responder con HMAC-SHA256(nonce, hardware_token_hash).
Previene ataques de replay mediante single-use + TTL.
"""

import secrets
import hmac
import hashlib
import logging
from datetime import datetime, timedelta

log = logging.getLogger("dot.challenge")

# En memoria para desarrollo. Producción: Redis.
_challenges: dict[str, dict] = {}


def create_challenge(uid: str) -> str:
    """Genera un nonce de 32 bytes para el usuario. TTL 10 minutos."""
    nonce = secrets.token_hex(32)
    _challenges[nonce] = {
        "uid": uid,
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
        "used": False,
    }
    # Limpiar expirados
    expired = [k for k, v in _challenges.items() if v["expires_at"] < datetime.utcnow()]
    for k in expired:
        del _challenges[k]
    return nonce


def verify_challenge_response(nonce: str, signature: str, stored_key: str) -> bool:
    """
    Verifica que la firma HMAC-SHA256 del nonce sea correcta.
    stored_key es la clave derivada del vault (simulada por ahora con el
    hardware_token_hash del usuario).
    """
    chal = _challenges.get(nonce)
    if not chal:
        return False
    if chal["used"]:
        return False  # Replay attack prevention
    if chal["expires_at"] < datetime.utcnow():
        del _challenges[nonce]
        return False
    expected = hmac.new(
        stored_key.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if hmac.compare_digest(expected, signature):
        chal["used"] = True
        del _challenges[nonce]
        return True
    return False


def get_challenge_uid(nonce: str) -> str | None:
    chal = _challenges.get(nonce)
    if chal and not chal["used"] and chal["expires_at"] > datetime.utcnow():
        return chal["uid"]
    return None
