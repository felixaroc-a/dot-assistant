"""Portal de autogestión para clientes — consultar plan, cambiar clave."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db
from dot_billing.passwords import hash_password, verify_password
from dot_billing.models import ClienteORM

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

router = APIRouter(tags=["self_service"])
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/portal", response_class=HTMLResponse)
def portal_login(request: Request):
    """Formulario de ingreso al portal."""
    return templates.TemplateResponse(request, "portal_login.html", {})


@router.post("/portal", response_class=HTMLResponse)
def portal_login_post(
    request: Request,
    cedula: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_billing_db),
):
    """Validar credenciales y mostrar dashboard del cliente."""
    q = select(ClienteORM).where(ClienteORM.cedula == cedula)
    cliente = db.scalars(q).first()
    if not cliente or not verify_password(cliente.clave_acceso, clave):
        return templates.TemplateResponse(
            request,
            "portal_login.html",
            {"error": "Cédula o clave incorrectos."},
        )
    return templates.TemplateResponse(
        request,
        "portal_dashboard.html",
        {
            "cliente": {
                "nombre": cliente.nombre,
                "cedula": cliente.cedula,
                "correo": cliente.correo,
                "telefono": cliente.telefono,
                "plan": cliente.plan.value,
                "fecha_vencimiento": cliente.fecha_vencimiento.isoformat(),
                "ai_provider": cliente.ai_provider_id.value,
            }
        },
    )


@router.post("/portal/cambiar-clave", response_class=HTMLResponse)
def portal_cambiar_clave(
    request: Request,
    cedula: str = Form(...),
    clave_actual: str = Form(...),
    clave_nueva: str = Form(...),
    db: Session = Depends(get_billing_db),
):
    """Cambiar la clave de acceso del cliente."""
    q = select(ClienteORM).where(ClienteORM.cedula == cedula)
    cliente = db.scalars(q).first()
    if not cliente or not verify_password(cliente.clave_acceso, clave_actual):
        return templates.TemplateResponse(
            request,
            "portal_dashboard.html",
            {"error": "Clave actual incorrecta.", "cliente": {}},
        )
    if len(clave_nueva) < 6:
        return templates.TemplateResponse(
            request,
            "portal_dashboard.html",
            {
                "error": "La clave nueva debe tener al menos 6 caracteres.",
                "cliente": {},
            },
        )
    cliente.clave_acceso = hash_password(clave_nueva)
    db.commit()
    return templates.TemplateResponse(
        request,
        "portal_dashboard.html",
        {
            "exito": "Clave cambiada exitosamente.",
            "cliente": {
                "nombre": cliente.nombre,
                "cedula": cliente.cedula,
                "correo": cliente.correo,
                "plan": cliente.plan.value,
                "fecha_vencimiento": cliente.fecha_vencimiento.isoformat(),
            },
        },
    )
