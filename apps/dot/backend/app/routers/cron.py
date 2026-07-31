"""Rutas para gestion de tareas programadas recurrentes (cron).

Endpoints:
- POST   /v1/cron/jobs              — crear job
- GET    /v1/cron/jobs              — listar jobs del usuario
- DELETE /v1/cron/jobs/{job_id}     — eliminar job
- POST   /v1/cron/jobs/{job_id}/pause   — pausar
- POST   /v1/cron/jobs/{job_id}/resume  — reanudar
- GET    /v1/cron/jobs/{job_id}/history — historial de ejecuciones
- GET    /v1/cron/templates         — plantillas preconfiguradas

Todos requieren JWT auth.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services.cron_service import (
    CRON_TEMPLATES,
    CronScheduleType,
)

log = logging.getLogger("dot.cron_router")

router = APIRouter(prefix="/v1/cron", tags=["cron"])


# ─── Modelos Pydantic ─────────────────────────────────────────


class CronJobCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Nombre descriptivo del job")
    schedule_type: CronScheduleType = Field(..., description="Tipo de programación")
    schedule_value: str = Field(..., min_length=1, max_length=100, description="Valor del schedule (HH:MM, 'mon@18:00', '*/5 * * * *', etc.)")
    tool_name: str = Field(..., min_length=1, max_length=80, description="Tool a ejecutar")
    tool_args: dict | None = Field(default=None, description="Argumentos del tool")


class CronJobResponse(BaseModel):
    job_id: str
    name: str
    schedule_type: str
    schedule_value: str
    tool_name: str
    tool_args: dict
    status: str
    last_run: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    run_count: int
    next_run: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class CronJobListResponse(BaseModel):
    jobs: list[CronJobResponse]
    total: int


class CronJobHistoryItem(BaseModel):
    executed_at: str
    status: str
    error: str | None = None


class CronJobHistoryResponse(BaseModel):
    history: list[CronJobHistoryItem]
    total: int


class CronTemplateResponse(BaseModel):
    name: str
    description: str
    schedule_type: str
    schedule_value: str
    tool_name: str
    tool_args: dict


class CronTemplatesResponse(BaseModel):
    templates: list[CronTemplateResponse]


class MessageResponse(BaseModel):
    message: str


# ─── Helper ────────────────────────────────────────────────────


def _require_cron_service(request: Request):
    """Obtiene el CronService desde el estado de la app."""
    svc = getattr(request.app.state, "cron_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Servicio de tareas programadas no disponible.")
    return svc


# ─── Endpoints ──────────────────────────────────────────────────


@router.post("/jobs", response_model=CronJobResponse, status_code=201)
def create_cron_job(
    body: Annotated[CronJobCreateRequest, Body()],
    claims: dict = Depends(require_product_jwt),
    request: Request = None,  # usado internamente por FastAPI
) -> CronJobResponse:
    """Crea un nuevo job cron para el usuario autenticado."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    try:
        job = cron.add_cron_job(
            uid=uid,
            name=body.name,
            schedule_type=body.schedule_type,
            schedule_value=body.schedule_value,
            tool_name=body.tool_name,
            tool_args=body.tool_args or {},
        )
        return CronJobResponse(**job.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/jobs", response_model=CronJobListResponse)
def list_cron_jobs(
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> CronJobListResponse:
    """Lista todos los jobs cron del usuario autenticado."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    jobs = cron.get_user_jobs(uid)
    return CronJobListResponse(
        jobs=[CronJobResponse(**j) for j in jobs],
        total=len(jobs),
    )


@router.delete("/jobs/{job_id}", response_model=MessageResponse)
def delete_cron_job(
    job_id: str,
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> MessageResponse:
    """Elimina un job cron del usuario autenticado."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    deleted = cron.remove_cron_job(uid, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job no encontrado o no pertenece al usuario.")
    return MessageResponse(message="Job eliminado correctamente.")


@router.post("/jobs/{job_id}/pause", response_model=MessageResponse)
def pause_cron_job(
    job_id: str,
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> MessageResponse:
    """Pausa un job cron (no se ejecutará hasta reanudar)."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    ok = cron.pause_cron_job(uid, job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job no encontrado o no pertenece al usuario.")
    return MessageResponse(message="Job pausado correctamente.")


@router.post("/jobs/{job_id}/resume", response_model=MessageResponse)
def resume_cron_job(
    job_id: str,
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> MessageResponse:
    """Reanuda un job cron previamente pausado."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    ok = cron.resume_cron_job(uid, job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job no encontrado o no pertenece al usuario.")
    return MessageResponse(message="Job reanudado correctamente.")


@router.get("/jobs/{job_id}/history", response_model=CronJobHistoryResponse)
def get_cron_job_history(
    job_id: str,
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> CronJobHistoryResponse:
    """Devuelve el historial de ejecuciones de un job cron."""
    cron = _require_cron_service(request)
    uid = claims_uid(claims)

    entries = cron.get_job_history(uid, job_id)
    return CronJobHistoryResponse(
        history=[CronJobHistoryItem(**e) for e in entries],
        total=len(entries),
    )


@router.get("/templates", response_model=CronTemplatesResponse)
def get_cron_templates(
    claims: dict = Depends(require_product_jwt),
) -> CronTemplatesResponse:
    """Devuelve las plantillas preconfiguradas de jobs cron."""
    return CronTemplatesResponse(
        templates=[CronTemplateResponse(**t) for t in CRON_TEMPLATES],
    )
