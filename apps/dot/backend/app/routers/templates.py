"""Rutas para plantillas reutilizables de documentos."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services.cache_service import cached, invalidate_pattern
from app.services.template_service import (
    TemplateNotFoundError,
    TemplateServiceDisabledError,
)

log = logging.getLogger("dot.templates")

router = APIRouter(prefix="/v1/templates", tags=["templates"])


class DocumentTemplateItem(BaseModel):
    id: str
    name: str
    document_type: str
    structure: str
    created_at: str | None = None
    updated_at: str | None = None


class TemplateListResponse(BaseModel):
    templates: list[DocumentTemplateItem]


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    document_type: str = Field(..., description="docx, xlsx, txt")
    structure: str = Field(..., min_length=1, max_length=8_000)


class TemplateRenderRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=12_000)
    provider: str | None = None


class TemplateRenderResponse(BaseModel):
    template_id: str
    template_name: str
    document_type: str
    title: str
    content: str


def _require_template_service(request: Request):
    service = getattr(request.app.state, "template_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Servicio de plantillas no disponible.")
    return service


@router.get("", response_model=TemplateListResponse)
@cached(ttl_seconds=300)
def list_templates(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        rows = service.list_templates(uid)
        items = [DocumentTemplateItem(**row) for row in rows]
        return TemplateListResponse(templates=items)
    except TemplateServiceDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error listando plantillas uid=%s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="No se pudieron listar las plantillas.") from exc


@router.post("", response_model=DocumentTemplateItem)
def create_template(
    request: Request,
    body: TemplateCreateRequest,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        created = service.create_template(
            uid=uid,
            name=body.name,
            document_type=body.document_type,
            structure=body.structure,
        )
        invalidate_pattern(f"/v1/templates:{uid}")
        return DocumentTemplateItem(**created)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateServiceDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error creando plantilla uid=%s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="No se pudo crear la plantilla.") from exc


@router.delete("/{template_id}")
def delete_template(
    request: Request,
    template_id: str,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        service.delete_template(uid=uid, template_id=template_id)
        invalidate_pattern(f"/v1/templates:{uid}")
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TemplateServiceDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error borrando plantilla uid=%s id=%s: %s", uid, template_id, exc)
        raise HTTPException(status_code=500, detail="No se pudo borrar la plantilla.") from exc


@router.post("/{template_id}/render", response_model=TemplateRenderResponse)
def render_template(
    request: Request,
    template_id: str,
    body: TemplateRenderRequest,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        rendered = service.render_template(
            uid=uid,
            template_id=template_id,
            user_input=body.user_input,
            provider_id=body.provider,
        )
        return TemplateRenderResponse(**rendered)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TemplateServiceDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Error renderizando plantilla uid=%s id=%s: %s", uid, template_id, exc)
        raise HTTPException(status_code=500, detail="No se pudo renderizar la plantilla.") from exc
