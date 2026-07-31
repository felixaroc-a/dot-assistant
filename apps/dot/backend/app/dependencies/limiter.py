"""Rate limiter compartido con clave por IP y por sub JWT."""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import jwt_util
from app.jwt_keys import get_jwt_signing_config, jwt_configured


def _rate_limit_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and jwt_configured():
        token = auth[7:].strip()
        if token:
            try:
                claims = jwt_util.decode_product_token(token, get_jwt_signing_config())
                sub = claims.get("sub")
                if isinstance(sub, str) and sub:
                    return f"user:{sub}"
            except Exception:
                pass
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, default_limits=["60/minute"])
