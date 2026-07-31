"""API admin de provisión comercial USB (equipo local Windows + Node)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db
from app.billing_models import ClienteORM
from app.dependencies.limiter import limiter
from app.services.usb_provisioning_service import (
    UsbProvisioningError,
    list_usb_devices,
    provisioning_runtime_status,
    run_usb_provisioning,
)
from app.settings import settings
from dot_billing.hardware_token import (
    SELLER_INVALID_SERIAL_MESSAGE,
    hash_hardware_token,
    sanitize_hardware_serial,
)

router = APIRouter(tags=["usb-provisioning"])


def _check_admin_api_key(x_admin_key: str | None) -> bool:
    configured = settings.admin_api_key.strip()
    if not configured:
        return False
    return bool(x_admin_key and x_admin_key.strip() == configured)


def _require_admin(x_admin_key: str | None = Header(None)) -> None:
    if not _check_admin_api_key(x_admin_key):
        raise HTTPException(
            status_code=403,
            detail="Admin API key inválida o no configurada",
        )


def _normalize_drive_letter(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().upper().replace("\\", "")
    if value.endswith(":"):
        value = value[:-1]
    if len(value) != 1 or not value.isalpha():
        return None
    return f"{value}:"


def _api_base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _cliente_by_serial(db: Session, serial: str) -> ClienteORM | None:
    clean = serial.strip()
    if not clean:
        return None
    serial_hash = hash_hardware_token(clean)
    return (
        db.execute(select(ClienteORM).where(ClienteORM.hardware_token_hash == serial_hash))
        .scalar_one_or_none()
    )


class RegisteredClienteSummary(BaseModel):
    uid: str
    cedula: str
    nombre: str


class UsbDeviceItem(BaseModel):
    serial: str
    drive: str
    model: str | None = None
    interface_type: str | None = None
    source: str | None = None
    registered: RegisteredClienteSummary | None = None


class UsbDevicesResponse(BaseModel):
    ok: bool
    count: int
    devices: list[UsbDeviceItem]
    runtime: dict | None = None


class UsbProvisionRequest(BaseModel):
    serial: str = Field(min_length=1, max_length=128)
    drive: str | None = Field(default=None, max_length=8)
    force: bool = False
    copy_installer: bool = True


class UsbProvisionResponse(BaseModel):
    ok: bool
    message: str | None = None
    code: str | None = None
    steps: list[dict] | None = None
    result: dict | None = None


class ClientBySerialResponse(BaseModel):
    ok: bool
    serial: str
    cedula: str | None = None
    nombre: str | None = None
    uid: str | None = None
    error: str | None = None


@router.get("/v1/usb/devices", response_model=UsbDevicesResponse)
def get_usb_devices(
    _: None = Depends(_require_admin),
    db: Session = Depends(get_billing_db),
):
    """Lista USB conectados en el equipo local y cliente registrado por serial."""
    try:
        raw_devices = list_usb_devices()
    except UsbProvisioningError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "count": 0,
                "devices": [],
                "runtime": provisioning_runtime_status(),
                "code": exc.code,
                "message": exc.message,
                "details": exc.details or {},
            },
        )

    items: list[UsbDeviceItem] = []
    for device in sorted(raw_devices, key=lambda d: d["driveLetter"]):
        serial = device["serial"]
        row = _cliente_by_serial(db, serial)
        registered = None
        if row:
            registered = RegisteredClienteSummary(
                uid=str(row.id),
                cedula=row.cedula,
                nombre=row.nombre,
            )
        items.append(
            UsbDeviceItem(
                serial=serial,
                drive=device["driveLetter"],
                model=device.get("model"),
                interface_type=device.get("interfaceType"),
                source=device.get("source"),
                registered=registered,
            )
        )

    return UsbDevicesResponse(
        ok=True,
        count=len(items),
        devices=items,
        runtime=provisioning_runtime_status(),
    )


@router.post("/v1/usb/provision", response_model=UsbProvisionResponse)
@limiter.limit("10/minute")
def provision_usb(
    request: Request,
    body: UsbProvisionRequest,
    _: None = Depends(_require_admin),
):
    """Ejecuta provisión de entrega (vault + verificación + instalador opcional)."""
    serial = sanitize_hardware_serial(body.serial.strip())
    if not serial:
        raise HTTPException(status_code=422, detail=SELLER_INVALID_SERIAL_MESSAGE)

    drive_letter = _normalize_drive_letter(body.drive)
    if body.drive and not drive_letter:
        raise HTTPException(status_code=422, detail="Unidad USB inválida (use formato E: o F:)")

    try:
        payload = run_usb_provisioning(
            serial=serial,
            drive_letter=drive_letter,
            api_base=_api_base(request),
            require_registered=True,
            force=body.force,
            copy_installer=body.copy_installer,
        )
    except UsbProvisioningError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "code": exc.code,
                "message": exc.message,
                "details": exc.details or {},
            },
        )

    return UsbProvisionResponse(
        ok=True,
        message=str(payload.get("message") or "Provisión USB completada."),
        code=str(payload.get("code") or "PROVISION_COMPLETED"),
        steps=payload.get("steps") if isinstance(payload.get("steps"), list) else [],
        result=payload.get("result") if isinstance(payload.get("result"), dict) else {},
    )


@router.get("/v1/usb/client-by-serial/{serial}", response_model=ClientBySerialResponse)
def get_client_by_serial(
    serial: str,
    _: None = Depends(_require_admin),
    db: Session = Depends(get_billing_db),
):
    """Devuelve cédula y nombre del cliente vinculado al serial USB."""
    clean = sanitize_hardware_serial(serial.strip())
    if not clean:
        raise HTTPException(status_code=422, detail=SELLER_INVALID_SERIAL_MESSAGE)

    row = _cliente_by_serial(db, clean)
    if not row:
        return ClientBySerialResponse(
            ok=False,
            serial=clean,
            error="SERIAL_NOT_REGISTERED",
        )

    return ClientBySerialResponse(
        ok=True,
        serial=clean,
        cedula=row.cedula,
        nombre=row.nombre,
        uid=str(row.id),
    )
