"""Recovery key: backup, obtener, eliminar, login y rotacion por recovery key."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_deps import claims_uid, require_product_jwt
from app.billing_db import get_billing_db
from app.billing_models import ClienteORM
from app.services.pendrive_service import get_recovery_key, save_recovery_key
from app.services.auth_service import _cliente_dto, plan_to_str
from app.schemas.auth import LoginResponse
from app.jwt_keys import get_jwt_signing_config
from app import jwt_util
from app.jwt_util import encode_access_token
from app.password_util import verify_password
from app.refresh_store import create_family
from app.dependencies.limiter import limiter

log = __import__("logging").getLogger("dot.pendrive_recovery")

router = APIRouter(tags=["pendrive"])


class RecoveryBackupRequest(BaseModel):
    recovery_key: str


class RecoveryResponse(BaseModel):
    ok: bool
    recovery_key: str | None = None
    error: str | None = None


class RecoveryLoginRequest(BaseModel):
    cedula: str
    password: str
    recovery_key: str


class RecoveryRotateRequest(BaseModel):
    old_recovery_key: str
    new_recovery_key: str


@router.post("/v1/pendrive/recovery-backup", response_model=RecoveryResponse)
@limiter.limit("10/minute")
def backup_recovery_key(
    request: Request,
    body: RecoveryBackupRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Guarda la recovery key del vault en Firestore (cifrada con Fernet)."""
    uid = claims_uid(claims)

    rk = body.recovery_key.strip()
    if not rk:
        raise HTTPException(status_code=400, detail="Recovery key requerida")

    if len(rk) < 40:
        raise HTTPException(status_code=400, detail="Recovery key invalida (min. 40 caracteres)")

    try:
        saved = save_recovery_key(uid, rk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar recovery key: {e}")

    if not saved:
        raise HTTPException(status_code=503, detail="recovery_backup_failed")

    return RecoveryResponse(ok=True)


@router.get("/v1/pendrive/recovery/{cliente_id}", response_model=RecoveryResponse)
def get_recovery(
    cliente_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Recupera la recovery key del vault desde Firestore (propio usuario)."""
    uid = claims_uid(claims)

    if uid != cliente_id:
        raise HTTPException(status_code=403, detail="No autorizado para ver esta recovery key")

    try:
        rk = get_recovery_key(cliente_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al recuperar recovery key: {e}")

    if not rk:
        return RecoveryResponse(ok=False, error="No hay recovery key almacenada")

    return RecoveryResponse(ok=True, recovery_key=rk)


@router.delete("/v1/pendrive/recovery/{cliente_id}", response_model=RecoveryResponse)
def delete_recovery(
    cliente_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Elimina el backup de recovery key de Firestore (solo el propio usuario)."""
    uid = claims_uid(claims)

    if uid != cliente_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    try:
        from app.firebase_db import delete_pendrive_recovery

        delete_pendrive_recovery(cliente_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al eliminar recovery key: {e}")

    return RecoveryResponse(ok=True)


@router.post("/v1/pendrive/recovery-login", response_model=LoginResponse)
@limiter.limit("3/minute")
def recovery_login(
    request: Request,
    body: RecoveryLoginRequest,
    db: Session = Depends(get_billing_db),
):
    """Login alternativo usando recovery key cuando se pierde el pendrive."""
    cid = body.cedula.strip()
    row = db.execute(select(ClienteORM).where(ClienteORM.cedula == cid)).scalar_one_or_none()
    ok = row is not None and verify_password(row.clave_acceso, body.password)
    if not ok:
        raise HTTPException(status_code=401, detail="credenciales_invalidas")

    uid = str(row.id)
    stored_key = get_recovery_key(uid)
    if not stored_key or stored_key.strip() != body.recovery_key.strip():
        raise HTTPException(status_code=401, detail="recovery_key_invalida")

    from app.services.subscription_service import is_subscription_expired
    if is_subscription_expired(row.fecha_vencimiento):
        raise HTTPException(status_code=403, detail="subscription_expired")

    cfg = get_jwt_signing_config()
    cliente_uuid = UUID(str(row.id))
    plan_str = plan_to_str(row.plan)

    access_token, expires_in, _ = encode_access_token(
        cliente_id=cliente_uuid,
        cedula=row.cedula,
        correo=row.correo,
        plan_val=plan_str,
        fecha_vencimiento=row.fecha_vencimiento,
        expires_minutes=4 * 60,  # 4h — recovery es emergencia, no sesion permanente
        extra_claims={"hardware_required": False},
        cfg=cfg,
    )
    family_id, refresh_jti = create_family(str(cliente_uuid))
    refresh_token, _ = jwt_util.encode_refresh_token(
        cliente_id=cliente_uuid,
        expires_days=1,
        family_id=family_id,
        jti=refresh_jti,
        cfg=cfg,
    )

    cliente_dto = _cliente_dto(row)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        cliente=cliente_dto,
    )


@router.post("/v1/pendrive/recovery/rotate-key", response_model=RecoveryResponse)
@limiter.limit("5/minute")
def rotate_recovery_key(
    request: Request,
    body: RecoveryRotateRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Rota la recovery key: reemplaza la vieja por una nueva (JWT requerido).

    Valida que la recovery key anterior coincida antes de sobrescribir.
    Permite al usuario rotar su clave despues de usarla exitosamente.
    """
    uid = claims_uid(claims)

    old_key = body.old_recovery_key.strip()
    new_key = body.new_recovery_key.strip()

    if not old_key:
        raise HTTPException(status_code=400, detail="Recovery key anterior requerida")
    if not new_key:
        raise HTTPException(status_code=400, detail="Nueva recovery key requerida")
    if len(new_key) < 40:
        raise HTTPException(status_code=400, detail="Nueva recovery key invalida (min. 40 caracteres)")
    if old_key == new_key:
        raise HTTPException(status_code=400, detail="La nueva recovery key debe ser diferente a la anterior")

    # Verificar que la recovery key anterior coincide con la almacenada
    try:
        stored_key = get_recovery_key(uid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al recuperar recovery key: {e}")

    if not stored_key or stored_key.strip() != old_key:
        raise HTTPException(status_code=403, detail="La recovery key anterior no coincide")

    # Guardar la nueva recovery key
    try:
        saved = save_recovery_key(uid, new_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar nueva recovery key: {e}")

    if not saved:
        raise HTTPException(status_code=503, detail="rotate_recovery_key_failed")

    log.info("[DOT AUDIT] recovery_key_rotated uid=%s", uid)

    return RecoveryResponse(ok=True)
