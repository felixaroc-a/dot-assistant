"""Login, refresh y emisión de tokens JWT."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jwt_util
from app.billing_models import ClienteORM, PlanSuscripcionORM
from app.jwt_keys import JwtSigningConfig, get_jwt_signing_config
from app.password_util import verify_password
from dot_billing.hardware_token import sanitize_hardware_serial, verify_hardware_token
from app.refresh_store import RefreshTokenReuseError, create_family, rotate_refresh
from app.schemas.auth import (
    LoginResponse,
    MeResponse,
    RefreshResponse,
    SuscripcionClienteDto,
)
from app.services.subscription_service import is_subscription_expired, parse_fecha_vencimiento
from app.settings import settings
from jwt.exceptions import InvalidTokenError as PyJWTError
from app.token_revocation import assert_not_revoked

log = logging.getLogger("dot.auth_service")


def plan_to_str(p: PlanSuscripcionORM | str) -> str:
    return p.value if hasattr(p, "value") else str(p)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _cliente_dto(row: ClienteORM) -> SuscripcionClienteDto:
    return SuscripcionClienteDto(
        cliente_id=str(row.id),
        cedula=row.cedula,
        plan=plan_to_str(row.plan),
        fecha_vencimiento=row.fecha_vencimiento,
        correo=row.correo,
    )


def _issue_tokens(row: ClienteORM, cfg: JwtSigningConfig) -> TokenPair:
    plan_str = plan_to_str(row.plan)
    cliente_uuid = UUID(str(row.id))
    access_token, expires_in, _ = jwt_util.encode_access_token(
        cliente_id=cliente_uuid,
        cedula=row.cedula,
        correo=row.correo,
        plan_val=plan_str,
        fecha_vencimiento=row.fecha_vencimiento,
        expires_minutes=settings.jwt_expires_minutes_clamped,
        cfg=cfg,
    )
    family_id, refresh_jti = create_family(str(cliente_uuid))
    refresh_token, _ = jwt_util.encode_refresh_token(
        cliente_id=cliente_uuid,
        expires_days=settings.jwt_refresh_expires_days,
        family_id=family_id,
        jti=refresh_jti,
        cfg=cfg,
    )
    return TokenPair(access_token, refresh_token, expires_in)


def _verify_pendrive(row: ClienteORM, hardware_serial: str | None) -> None:
    """Exige pendrive registrado cuando la cuenta tiene hardware_token_hash.

    Si el cliente tiene hardware_token_hash, verifica que el serial provisto
    coincida con el hash almacenado. Si no coincide, lanza 401.
    """
    if not row.hardware_token_hash:
        return
    clean = sanitize_hardware_serial(hardware_serial)
    if not clean:
        raise HTTPException(status_code=400, detail="pendrive_required")
    if not verify_hardware_token(clean, row.hardware_token_hash):
        raise HTTPException(status_code=401, detail="credenciales_invalidas")


def _verify_pendrive_from_claims(row: ClienteORM, claims: dict) -> None:
    """Verifica que el serial del pendrive en el JWT coincida con el
    hardware_token_hash del cliente. Si no coincide, lanza 401."""
    if not row.hardware_token_hash:
        return
    jwt_serial = claims.get("hardware_serial")
    if not jwt_serial:
        raise HTTPException(status_code=400, detail="pendrive_required")
    clean = sanitize_hardware_serial(str(jwt_serial))
    if not clean:
        raise HTTPException(status_code=400, detail="pendrive_required")
    if not verify_hardware_token(clean, row.hardware_token_hash):
        raise HTTPException(status_code=401, detail="hardware_serial_mismatch")


def login(
    db: Session,
    cedula: str,
    password: str,
    hardware_serial: str | None = None,
    _cfg_override: JwtSigningConfig | None = None,
) -> LoginResponse:
    cid = cedula.strip()
    row = db.execute(select(ClienteORM).where(ClienteORM.cedula == cid)).scalar_one_or_none()
    ok = row is not None and verify_password(row.clave_acceso, password)
    if not ok:
        raise HTTPException(status_code=401, detail="credenciales_invalidas")
    _verify_pendrive(row, hardware_serial)
    if is_subscription_expired(row.fecha_vencimiento):
        raise HTTPException(status_code=403, detail="subscription_expired")

    cfg = _cfg_override or get_jwt_signing_config()
    tokens = _issue_tokens(row, cfg)
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        cliente=_cliente_dto(row),
    )


def refresh_session(
    db: Session,
    refresh_token: str,
    _cfg_override: JwtSigningConfig | None = None,
    hardware_serial: str | None = None,
) -> RefreshResponse:
    try:
        cfg = _cfg_override or get_jwt_signing_config()
        claims = jwt_util.decode_product_token(refresh_token.strip(), cfg)
    except PyJWTError as e:
        log.error("Error decodificando refresh token: %s", e, exc_info=True)
        raise HTTPException(status_code=401, detail="Refresh token invalido o expirado.")

    if claims.get("token_use") != "refresh":
        raise HTTPException(status_code=401, detail="token_use debe ser refresh.")
    try:
        assert_not_revoked(claims)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="No se pudo validar revocación de sesión en este momento.",
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token revocado.")

    cliente_id_str = claims.get("sub")
    family_id = claims.get("family_id")
    presented_jti = claims.get("jti")
    if not cliente_id_str or not isinstance(family_id, str) or not isinstance(presented_jti, str):
        raise HTTPException(status_code=401, detail="Refresh token malformado.")

    try:
        new_jti = rotate_refresh(family_id, presented_jti, str(cliente_id_str))
    except RefreshTokenReuseError:
        raise HTTPException(
            status_code=401, detail="Sesion revocada por actividad sospechosa."
        )

    try:
        row = db.execute(
            select(ClienteORM).where(ClienteORM.id == UUID(str(cliente_id_str)))
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=401, detail="Cliente no encontrado.")
        if is_subscription_expired(row.fecha_vencimiento):
            raise HTTPException(status_code=403, detail="subscription_expired")

        # Verificacion opcional de pendrive: si el cliente tiene hardware_token_hash,
        # validar que el serial provisto coincida. Si no se provee serial y la cuenta
        # exige pendrive, emitir refresh con hardware_required.
        hardware_required = False
        if row.hardware_token_hash:
            if hardware_serial:
                clean_serial = sanitize_hardware_serial(hardware_serial)
                if clean_serial and verify_hardware_token(clean_serial, row.hardware_token_hash):
                    pass  # pendrive valido
                else:
                    raise HTTPException(status_code=401, detail="hardware_serial_mismatch")
            else:
                # Pendrive no presente — marcar hardware_required en el token
                hardware_required = True

        cliente_uuid = UUID(str(row.id))
        plan_str = plan_to_str(row.plan)

        extra_claims = {}
        if hardware_required:
            extra_claims["hardware_required"] = True
        if hardware_serial:
            extra_claims["hardware_serial"] = sanitize_hardware_serial(hardware_serial)

        access_token, expires_in, _ = jwt_util.encode_access_token(
            cliente_id=cliente_uuid,
            cedula=row.cedula,
            correo=row.correo,
            plan_val=plan_str,
            fecha_vencimiento=row.fecha_vencimiento,
            expires_minutes=settings.jwt_expires_minutes_clamped,
            extra_claims=extra_claims if extra_claims else None,
            cfg=cfg,
        )
        refresh_out, _ = jwt_util.encode_refresh_token(
            cliente_id=cliente_uuid,
            expires_days=settings.jwt_refresh_expires_days,
            family_id=family_id,
            jti=new_jti,
            cfg=cfg,
        )
        return RefreshResponse(
            access_token=access_token,
            refresh_token=refresh_out,
            expires_in=expires_in,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error inesperado en refresh_session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor.")


def me_from_claims(claims: dict[str, object]) -> MeResponse:
    uid = str(claims.get("sub", ""))
    email = claims.get("email")
    return MeResponse(
        uid=uid,
        cedula=str(claims.get("cedula")) if claims.get("cedula") else None,
        email=str(email) if email else None,
        plan=str(claims["plan"]) if claims.get("plan") else None,
        fecha_vencimiento=parse_fecha_vencimiento(claims.get("fecha_vencimiento")),
        email_verified=None,
    )
