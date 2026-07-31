"""Codificacion/decodificacion JWT (RS256 preferido, HS256 legacy) con jti y familias refresh."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from app.jwt_keys import JwtSigningConfig, get_jwt_signing_config


def subscription_exp_claim(fecha: date) -> int:
    dt = datetime(fecha.year, fecha.month, fecha.day, 23, 59, 59, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _encode(payload: dict[str, object], cfg: JwtSigningConfig) -> str:
    token = jwt.encode(payload, cfg.sign_key, algorithm=cfg.algorithm)
    if isinstance(token, bytes):
        return token.decode("ascii")
    return token


def encode_access_token(
    *,
    cliente_id: UUID,
    cedula: str,
    correo: str,
    plan_val: str,
    fecha_vencimiento: date,
    expires_minutes: int,
    extra_claims: dict[str, object] | None = None,
    cfg: JwtSigningConfig | None = None,
) -> tuple[str, int, str]:
    """Devuelve (access_token, expires_in_segundos, jti)."""
    cfg = cfg or get_jwt_signing_config()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=max(5, expires_minutes))
    jti = str(uuid4())
    sub_exp = subscription_exp_claim(fecha_vencimiento)
    payload: dict[str, object] = {
        "sub": str(cliente_id),
        "cedula": cedula,
        "email": correo,
        "plan": plan_val,
        "subscription_exp": sub_exp,
        "fecha_vencimiento": fecha_vencimiento.isoformat(),
        "token_use": "access",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = _encode(payload, cfg)
    return token, int((exp - now).total_seconds()), jti


def encode_refresh_token(
    *,
    cliente_id: UUID,
    expires_days: int,
    family_id: str,
    jti: str,
    cfg: JwtSigningConfig | None = None,
) -> tuple[str, int]:
    """Devuelve (refresh_token, expires_in_segundos)."""
    cfg = cfg or get_jwt_signing_config()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=expires_days)
    payload: dict[str, object] = {
        "sub": str(cliente_id),
        "token_use": "refresh",
        "jti": jti,
        "family_id": family_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = _encode(payload, cfg)
    return token, int((exp - now).total_seconds())


def decode_product_token(token: str, cfg: JwtSigningConfig | None = None) -> dict[str, object]:
    cfg = cfg or get_jwt_signing_config()
    data = jwt.decode(
        token,
        cfg.verify_key,
        algorithms=[cfg.algorithm],
        options={"require": ["exp", "sub", "jti"]},
    )
    if data.get("token_use") not in ("access", "refresh"):
        raise InvalidTokenError("token_use debe ser access o refresh")
    return dict(data)


def claims_for_firestore_user_id(claims: dict[str, object]) -> str:
    return str(claims["sub"])
