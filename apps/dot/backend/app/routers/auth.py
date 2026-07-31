"""Autenticacion: login, refresh, logout, informacion del usuario."""
import asyncio
import logging
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

log = logging.getLogger("dot.auth_router")


def _run_in_background(fn, *, name: str) -> None:
    """Ejecuta trabajo post-login fuera del request.

    Los handlers sync de FastAPI corren en threadpool: no hay event loop
    (`asyncio.get_running_loop()` falla con RuntimeError → 500).
    """
    threading.Thread(target=fn, daemon=True, name=name).start()

from app import jwt_util
from app.auth_deps import require_product_jwt
from app.billing_db import get_billing_db

from app.jwt_keys import get_jwt_signing_config, jwt_configured
from app.refresh_store import revoke_family
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
)
from app.security.audit import audit_event
from app.services import auth_service
from app.services.cache_service import cached
from app.services.ws_manager import notify_user
from dot_billing.webhook_alert import send_alert
from app.token_revocation import revoke_jti, revoke_user_tokens
from app.settings import settings
from app.dependencies.limiter import limiter

router = APIRouter(tags=["auth"])


class RevokeUserTokensRequest(BaseModel):
    uid: str


@router.post("/v1/auth/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def auth_login(request: Request, body: LoginRequest, db: Session = Depends(get_billing_db)):
    if not jwt_configured():
        raise HTTPException(status_code=503, detail="JWT no configurado en el servidor.")
    try:
        result = auth_service.login(
            db, body.cedula, body.password, hardware_serial=body.hardware_serial
        )
    except HTTPException as e:
        if e.status_code == 401:
            audit_event("login_failed", cedula=body.cedula.strip(), ip=request.client.host if request.client else None)
        elif e.status_code == 403:
            audit_event("login_subscription_expired", cedula=body.cedula.strip())
        raise
    audit_event("login_success", cliente_id=result.cliente.cliente_id)

    # T-ML-001: Cargar automatizaciones del usuario al login (Firestore no debe bloquear la respuesta)
    scheduler = getattr(request.app.state, "auto_scheduler", None)
    if scheduler is not None:
        uid = result.cliente.cliente_id
        plan = result.cliente.plan

        def _load_automations_bg() -> None:
            try:
                scheduler.load_user_automations(uid=uid, plan=plan)
            except Exception:
                log.warning("No se pudieron cargar automatizaciones al login", exc_info=True)

        _run_in_background(_load_automations_bg, name="login-load-automations")

    # Notificar via WebSocket al usuario sobre login exitoso
    cliente_id = str(result.cliente.cliente_id)

    def _notify_login_ws() -> None:
        try:
            asyncio.run(
                notify_user(
                    cliente_id,
                    "login",
                    {"mensaje": "Inicio de sesion exitoso"},
                )
            )
        except Exception:
            log.warning("No se pudo enviar notificacion WS de login", exc_info=True)

    _run_in_background(_notify_login_ws, name="login-ws-notify")

    return result


@router.post("/v1/auth/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
def auth_refresh(request: Request, body: RefreshRequest, db: Session = Depends(get_billing_db)):
    if not jwt_configured():
        raise HTTPException(status_code=503, detail="JWT no configurado.")
    try:
        result = auth_service.refresh_session(db, body.refresh_token)
    except HTTPException as e:
        if e.status_code == 401 and "sospechosa" in str(e.detail):
            audit_event("refresh_token_reuse_detected")
            try:
                cfg = get_jwt_signing_config()
                rclaims = jwt_util.decode_product_token(body.refresh_token.strip(), cfg)
                username = rclaims.get("sub", "unknown")
            except Exception:
                username = "unknown"
            send_alert("Refresh Token Reused", f"Usuario {username} reutilizo refresh token", level="critical")
        raise
    audit_event("refresh_success")
    return result


@router.post("/v1/auth/logout", status_code=204)
@limiter.limit("10/minute")
def auth_logout(request: Request, body: LogoutRequest, claims: dict = Depends(require_product_jwt)):
    cfg = get_jwt_signing_config()
    uid = str(claims.get("sub", ""))
    access_jti = claims.get("jti")
    if isinstance(access_jti, str):
        exp = claims.get("exp")
        revoke_jti(access_jti, int(exp) if isinstance(exp, (int, float)) else None)

    if body.refresh_token:
        try:
            rclaims = jwt_util.decode_product_token(body.refresh_token.strip(), cfg)
            family_id = rclaims.get("family_id")
            if isinstance(family_id, str):
                revoke_family(family_id)
            rjti = rclaims.get("jti")
            if isinstance(rjti, str):
                revoke_jti(rjti)
        except Exception:
            # best-effort: no bloquear respuesta de logout
            log.debug("Error revocando refresh token en logout uid=%s", uid[:8], exc_info=True)

    audit_event("logout", cliente_id=uid)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
@limiter.limit("30/minute")
@cached(ttl_seconds=60)
def me(request: Request, claims: dict = Depends(require_product_jwt)):
    return auth_service.me_from_claims(claims)


@router.post("/v1/admin/revoke-user-tokens", status_code=204)
@limiter.limit("10/minute")
def admin_revoke_user_tokens(
    request: Request,
    body: RevokeUserTokensRequest,
    x_admin_key: str | None = Header(None),
):
    import secrets
    configured = settings.admin_api_key.strip()
    if not configured or not x_admin_key or not secrets.compare_digest(x_admin_key.strip(), configured):
        raise HTTPException(status_code=403, detail="Admin API key inválida o no configurada.")

    uid = body.uid.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="uid requerido.")

    revoke_user_tokens(uid)
    audit_event("admin_revoke_user_tokens", target_uid=uid, ip=request.client.host if request.client else None)
    return Response(status_code=204)
