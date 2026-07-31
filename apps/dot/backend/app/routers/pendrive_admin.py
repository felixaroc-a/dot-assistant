"""Endpoints admin de pendrive (proteccion con X-Admin-Key)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db
from app.billing_models import ClienteORM
from app.services.pendrive_service import get_recovery_key
from app.services.subscription_service import is_subscription_expired
from app.settings import settings
from app.routers.pendrive_recovery import RecoveryResponse
from dot_billing.hardware_token import hash_hardware_token
from app.dependencies.limiter import limiter

log = __import__("logging").getLogger("dot.pendrive_admin")

router = APIRouter(tags=["pendrive"])


def _check_admin_api_key(x_admin_key: str | None) -> bool:
    configured = settings.admin_api_key.strip()
    if not configured:
        return False
    return bool(x_admin_key and x_admin_key.strip() == configured)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


class ProvisioningClientItem(BaseModel):
    uid: str
    cedula: str
    nombre: str
    estado: str
    has_hardware_linked: bool


class ProvisioningClientsResponse(BaseModel):
    ok: bool
    count: int
    clients: list[ProvisioningClientItem]


class ProvisioningValidateRequest(BaseModel):
    uid: str
    serial: str
    mark_completed: bool = False


class ProvisioningValidateResponse(BaseModel):
    ok: bool
    uid: str
    cedula: str
    nombre: str
    estado: str
    has_hardware_linked: bool
    serial_matches: bool
    provision_completed: bool
    message: str | None = None
    error: str | None = None


def _cliente_estado(row: ClienteORM) -> str:
    return "vencido" if is_subscription_expired(row.fecha_vencimiento) else "activo"


@router.get(
    "/v1/admin/pendrive/provisioning/clients",
    response_model=ProvisioningClientsResponse,
)
@limiter.limit("30/minute")
def admin_list_provisioning_clients(
    request: Request,
    limit: int = 100,
    q: str | None = None,
    x_admin_key: str | None = Header(None),
    db: Session = Depends(get_billing_db),
):
    """Lista clientes activos aptos para provision de pendrive."""
    if not _check_admin_api_key(x_admin_key):
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    safe_limit = min(max(limit, 1), 500)
    stmt = (
        select(ClienteORM)
        .where(ClienteORM.fecha_vencimiento >= date.today())
        .order_by(ClienteORM.nombre.asc())
        .limit(safe_limit)
    )

    term = (q or "").strip()
    if term:
        like_term = f"%{term}%"
        stmt = stmt.where(
            or_(
                ClienteORM.cedula.ilike(like_term),
                ClienteORM.nombre.ilike(like_term),
            )
        )

    rows = db.execute(stmt).scalars().all()
    items = [
        ProvisioningClientItem(
            uid=str(row.id),
            cedula=row.cedula,
            nombre=row.nombre,
            estado=_cliente_estado(row),
            has_hardware_linked=bool(row.hardware_token_hash),
        )
        for row in rows
    ]
    return ProvisioningClientsResponse(ok=True, count=len(items), clients=items)


@router.post(
    "/v1/admin/pendrive/provisioning/validate",
    response_model=ProvisioningValidateResponse,
)
@limiter.limit("20/minute")
async def admin_validate_provisioning_serial(
    request: Request,
    x_admin_key: str | None = Header(None),
    db: Session = Depends(get_billing_db),
):
    """Valida serial para provision y opcionalmente confirma la provision."""
    if not _check_admin_api_key(x_admin_key):
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    try:
        raw = await request.json()
        body = ProvisioningValidateRequest(**raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    uid = body.uid.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="uid requerido")

    clean_serial = body.serial.strip()
    if not clean_serial:
        raise HTTPException(status_code=400, detail="Serial requerido")

    try:
        uid_obj = UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="uid invalido")

    row = db.execute(select(ClienteORM).where(ClienteORM.id == uid_obj)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    estado = _cliente_estado(row)
    if estado != "activo":
        raise HTTPException(status_code=409, detail="CLIENTE_NO_APTO")

    serial_hash = hash_hardware_token(clean_serial)
    has_hardware_linked = bool(row.hardware_token_hash)
    serial_matches = has_hardware_linked and row.hardware_token_hash == serial_hash
    valid_for_provision = (not has_hardware_linked) or serial_matches

    if body.mark_completed:
        if not valid_for_provision:
            raise HTTPException(status_code=409, detail="SERIAL_MISMATCH")
        if not serial_matches:
            previous_hash = row.hardware_token_hash
            row.hardware_token_hash = serial_hash
            db.commit()
            log.info(
                "[DOT AUDIT] link_new_pendrive admin=%s uid=%s previous_serial_hash=%s new_serial_hash=%s",
                _get_client_ip(request), uid, previous_hash, serial_hash,
            )
        else:
            db.commit()
        return ProvisioningValidateResponse(
            ok=True,
            uid=str(row.id),
            cedula=row.cedula,
            nombre=row.nombre,
            estado=estado,
            has_hardware_linked=True,
            serial_matches=True,
            provision_completed=True,
            message="Provision marcada y serial vinculado correctamente",
        )

    return ProvisioningValidateResponse(
        ok=valid_for_provision,
        uid=str(row.id),
        cedula=row.cedula,
        nombre=row.nombre,
        estado=estado,
        has_hardware_linked=has_hardware_linked,
        serial_matches=serial_matches,
        provision_completed=False,
        message="Serial valido para provision" if valid_for_provision else None,
        error=None if valid_for_provision else "SERIAL_MISMATCH",
    )


@router.get("/v1/admin/pendrive/recovery/{cliente_id}", response_model=RecoveryResponse)
@limiter.limit("10/minute")
def admin_get_recovery(
    request: Request,
    cliente_id: str,
    x_admin_key: str | None = Header(None),
):
    """Recupera la recovery key del vault desde Firestore (solo X-Admin-Key)."""
    if not _check_admin_api_key(x_admin_key):
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    admin_ip = _get_client_ip(request)
    log.info(
        "[DOT AUDIT] admin_get_recovery admin_ip=%s cliente_id=%s timestamp=%s",
        admin_ip, cliente_id, __import__("datetime").datetime.utcnow().isoformat(),
    )

    try:
        rk = get_recovery_key(cliente_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al recuperar recovery key: {e}")

    if not rk:
        return RecoveryResponse(ok=False, error="No hay recovery key almacenada")

    return RecoveryResponse(ok=True, recovery_key=rk)
