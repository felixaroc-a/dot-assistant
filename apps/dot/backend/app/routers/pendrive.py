"""Router de verificacion server-side de pendrives DOT.

Endpoints:
- POST /v1/pendrive/verify: Verifica que el serial este registrado
- POST /v1/pendrive/challenge/request: Solicita nonce criptografico
- POST /v1/pendrive/challenge/verify: Verifica firma HMAC-SHA256
- POST /v1/pendrive/link: Vincula nuevo pendrive a la cuenta
- POST /v1/pendrive/report-lost: Reporta pendrive como perdido/robado
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_deps import claims_uid, require_product_jwt
from app.billing_db import get_billing_db
from app.billing_models import ClienteORM
from app.services.challenge_service import create_challenge, verify_challenge_response
from dot_billing.hardware_token import hash_hardware_token
from app.dependencies.limiter import limiter
from app.token_revocation import revoke_user_tokens

log = __import__("logging").getLogger("dot.pendrive")

router = APIRouter(tags=["pendrive"])


# ─── Dependencia JWT opcional (no lanza 401 si no hay token) ───────────────

def _optional_product_jwt(
    authorization: str | None = Header(None),
) -> dict[str, object] | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        from app.jwt_keys import get_jwt_signing_config, jwt_configured
        if not jwt_configured():
            return None
        cfg = get_jwt_signing_config()
        claims = __import__("app.jwt_util", fromlist=["jwt_util"]).decode_product_token(token, cfg)
        if claims.get("token_use") != "access":
            return None
        from app.token_revocation import assert_not_revoked
        assert_not_revoked(claims)
        return claims
    except Exception:
        log.warning("Error validando JWT opcional de pendrive", exc_info=True)
        return None


# ─── Schemas ──────────────────────────────────────────────────────────────


class PendriveVerifyRequest(BaseModel):
    serial: str
    drive_path: str | None = None


class PendriveVerifyResponse(BaseModel):
    ok: bool
    serial_hash: str | None = None
    uid: str | None = None
    cedula: str | None = None
    nombre: str | None = None
    hardware_bound: bool = False
    message: str | None = None
    error: str | None = None


class ChallengeRequestResponse(BaseModel):
    nonce: str


class ChallengeVerifyRequest(BaseModel):
    nonce: str
    signature: str


class ChallengeVerifyResponse(BaseModel):
    ok: bool


class PendriveLinkRequest(BaseModel):
    serial: str


class PendriveLinkResponse(BaseModel):
    ok: bool
    message: str | None = None
    error: str | None = None


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.post("/v1/pendrive/verify", response_model=PendriveVerifyResponse)
@limiter.limit("10/minute")
def verify_pendrive(
    request: Request,
    body: PendriveVerifyRequest,
    claims: dict[str, object] | None = Depends(_optional_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Verifica server-side que el serial pertenece a un cliente registrado.

    Sin JWT: solo retorna ok + hardware_bound (datos minimos de seguridad).
    Con JWT valido: retorna ademas cedula, nombre y uid.
    """
    clean_serial = body.serial.strip()
    if not clean_serial:
        raise HTTPException(status_code=400, detail="Serial requerido")

    serial_hash = hash_hardware_token(clean_serial)

    row = (
        db.execute(select(ClienteORM).where(ClienteORM.hardware_token_hash == serial_hash))
        .scalar_one_or_none()
    )

    if not row:
        return PendriveVerifyResponse(
            ok=False,
            serial_hash=serial_hash,
            hardware_bound=False,
            error="PENDRIVE_NOT_REGISTERED",
        )

    # Sin JWT: respuesta minima
    if not claims:
        return PendriveVerifyResponse(
            ok=True,
            serial_hash=serial_hash,
            hardware_bound=True,
            message="Pendrive verificado (datos limitados sin autenticacion)",
        )

    # Con JWT: respuesta completa
    return PendriveVerifyResponse(
        ok=True,
        serial_hash=serial_hash,
        uid=str(row.id),
        cedula=row.cedula,
        nombre=row.nombre,
        hardware_bound=True,
        message="Pendrive verificado correctamente",
    )


@router.post("/v1/pendrive/challenge/request", response_model=ChallengeRequestResponse)
@limiter.limit("5/minute")
def request_challenge(request: Request, claims: dict = Depends(require_product_jwt)):
    """Solicita un nonce criptografico para iniciar el handshake del pendrive."""
    uid = claims_uid(claims)
    nonce = create_challenge(uid)
    return ChallengeRequestResponse(nonce=nonce)


@router.post("/v1/pendrive/challenge/verify", response_model=ChallengeVerifyResponse)
@limiter.limit("5/minute")
def verify_challenge(
    request: Request,
    body: ChallengeVerifyRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Verifica la firma HMAC-SHA256 del nonce usando el hardware_token_hash del usuario."""
    uid = claims_uid(claims)

    row = (
        db.execute(select(ClienteORM).where(ClienteORM.id == uid))
        .scalar_one_or_none()
    )
    if not row or not row.hardware_token_hash:
        raise HTTPException(status_code=401, detail="CHALLENGE_FAILED")

    ok = verify_challenge_response(body.nonce, body.signature, row.hardware_token_hash)
    if not ok:
        raise HTTPException(status_code=401, detail="CHALLENGE_FAILED")

    return ChallengeVerifyResponse(ok=True)


@router.post("/v1/pendrive/link", response_model=PendriveLinkResponse)
@limiter.limit("10/minute")
def link_new_pendrive(
    request: Request,
    body: PendriveLinkRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Vincula un nuevo pendrive a la cuenta del usuario autenticado."""
    uid = claims_uid(claims)
    clean_serial = body.serial.strip()
    if not clean_serial:
        raise HTTPException(status_code=400, detail="Serial requerido")

    serial_hash = hash_hardware_token(clean_serial)

    row = db.execute(
        select(ClienteORM).where(ClienteORM.id == UUID(uid))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    row.hardware_token_hash = serial_hash
    row.pendrive_status = "active"
    db.commit()

    return PendriveLinkResponse(
        ok=True,
        message="Nuevo pendrive vinculado exitosamente",
    )


# ─── Reporte de pendrive perdido ────────────────────────────────────────


class ReportLostRequest(BaseModel):
    reason: str | None = None


class ReportLostResponse(BaseModel):
    ok: bool
    alert_id: str | None = None
    message: str | None = None
    error: str | None = None


@router.post("/v1/pendrive/report-lost", response_model=ReportLostResponse)
@limiter.limit("5/minute")
def report_lost_pendrive(
    request: Request,
    body: ReportLostRequest,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Reporta el pendrive actual como perdido/robado.

    - Marca el serial como 'lost' en clientes_suscripcion.
    - Genera alerta en Firestore (admin_alerts).
    - Revoca todos los tokens del usuario para forzar re-login.
    """
    uid = claims_uid(claims)

    row = db.execute(
        select(ClienteORM).where(ClienteORM.id == UUID(uid))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if row.pendrive_status == "lost":
        return ReportLostResponse(
            ok=True,
            message="El pendrive ya fue reportado como perdido anteriormente",
        )

    previous_status = row.pendrive_status
    serial = row.hardware_token_hash

    row.pendrive_status = "lost"
    db.commit()

    reported_at = datetime.now(timezone.utc).isoformat()

    alert_id: str | None = None
    try:
        from app.firebase_db import save_admin_alert

        alert_id = save_admin_alert(
            alert_type="pendrive_lost",
            cliente_id=str(row.id),
            serial=serial,
            reported_at=reported_at,
            reason=body.reason,
        )
    except Exception:
        log.warning(
            "No se pudo crear alerta admin para pendrive_lost uid=%s",
            uid,
            exc_info=True,
        )

    try:
        revoke_user_tokens(str(row.id))
        log.info(
            "[DOT AUDIT] pendrive_lost uid=%s previous_status=%s serial=%s reason=%s",
            uid,
            previous_status,
            serial,
            body.reason or "",
        )
    except Exception:
        log.warning(
            "Error revocando tokens tras report-lost para uid=%s",
            uid,
            exc_info=True,
        )

    return ReportLostResponse(
        ok=True,
        alert_id=alert_id,
        message="Pendrive reportado como perdido. Contacta a soporte para obtener un reemplazo.",
    )
