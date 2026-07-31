"""Dependencias de autenticacion JWT para FastAPI."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Depends, Header, HTTPException

log = logging.getLogger("dot.auth_deps")
from sqlalchemy.orm import Session

from app import jwt_util
from app.billing_db import get_billing_db
from app.jwt_keys import get_jwt_signing_config, jwt_configured
from app.services.subscription_service import is_subscription_expired, parse_fecha_vencimiento
from app.services.usage_service import assert_ai_usage_allowed
from app.token_revocation import TokenRevokedError, assert_not_revoked


def claims_uid(claims: dict[str, object]) -> str:
    return jwt_util.claims_for_firestore_user_id(claims)


def claims_cliente_id(claims: dict[str, object]) -> UUID:
    return UUID(str(claims["sub"]))


def require_product_jwt(authorization: str | None = Header(None)) -> dict[str, object]:
    if not jwt_configured():
        raise HTTPException(
            status_code=503,
            detail="Servidor sin claves JWT: no es posible verificar sesiones.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta encabezado Authorization: Bearer <access_token>.")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token vacio.")
    try:
        cfg = get_jwt_signing_config()
        claims = jwt_util.decode_product_token(token, cfg)
        if claims.get("token_use") != "access":
            raise HTTPException(status_code=401, detail="Se requiere access token.")
        assert_not_revoked(claims)
    except TokenRevokedError as e:
        raise HTTPException(status_code=401, detail="Token revocado.") from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail="No se pudo validar revocación de sesión en este momento.",
        ) from e
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Error decodificando JWT: %s", exc, exc_info=True)
        raise HTTPException(status_code=401, detail="Token invalido o expirado.") from None

    fecha = parse_fecha_vencimiento(claims.get("fecha_vencimiento"))
    if fecha is not None and is_subscription_expired(fecha):
        raise HTTPException(status_code=403, detail="subscription_expired")

    # Heartbeat D5: cualquier request autenticada cuenta como uso (BIBLIA §11).
    try:
        from app.services.activity_service import touch_last_active_best_effort

        touch_last_active_best_effort(claims_uid(claims))
    except Exception as exc:
        log.debug("touch_last_active_best_effort fallo (no critico): %s", exc)

    return claims


def check_usage_limit(
    claims: dict[str, object] = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
) -> dict[str, object]:
    """Bloquea endpoints de IA cuando el cliente alcanzó el tope mensual."""
    assert_ai_usage_allowed(db, claims_cliente_id(claims))
    return claims
