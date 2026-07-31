"""Rutas para ejecucion y seguimiento de automatizaciones y pipelines."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter
from app.firebase_db import FIRESTORE_AVAILABLE, get_db as get_firestore_client, get_user_profile
from app.models.pipeline import (
    PipelineCreateRequest,
    PipelineDef,
    PipelineExecuteResponse,
    PipelineListResponse,
    PipelineUpdateRequest,
)
from app.schemas.profile import SavedAutomationDto

log = logging.getLogger("dot.automations")

router = APIRouter(prefix="/v1/automations", tags=["automations"])

pipelines_router = APIRouter(prefix="/v1/pipelines", tags=["pipelines"])

automation_templates_router = APIRouter(prefix="/v1/templates/automation", tags=["automation-templates"])


class ExecuteResponse(BaseModel):
    success: bool
    result: str
    executed_at: str


class HistoryItem(BaseModel):
    executed_at: str
    result: str
    output_type: str


class HistoryResponse(BaseModel):
    executions: list[HistoryItem]


class PendingResultsResponse(BaseModel):
    has_new: bool = False
    last_auto_id: str | None = None
    last_auto_name: str | None = None
    last_executed_at: str | None = None
    last_result_preview: str | None = None


def _require_scheduler(request: Request):
    """Obtiene el scheduler desde el estado de la app."""
    scheduler = getattr(request.app.state, "auto_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Servicio de automatizaciones no disponible.")
    return scheduler


def _find_automation_in_profile(uid: str, auto_id: str) -> SavedAutomationDto:
    """Busca una automatizacion en el perfil del usuario."""
    profile = get_user_profile(uid)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado.")
    raw_autos = profile.get("saved_automations", [])
    for raw in raw_autos:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("id", "")) == auto_id:
            try:
                return SavedAutomationDto(
                    id=str(raw.get("id", "")),
                    name=str(raw.get("name", "")),
                    integration_id=str(
                        raw.get("integration_id") or raw.get("integrationId") or ""
                    ),
                    instruction=str(raw.get("instruction", "")),
                    active=bool(raw.get("active", True)),
                    output_type=(
                        str(raw["output_type"])
                        if raw.get("output_type")
                        else str(raw["outputType"])
                        if raw.get("outputType")
                        else None
                    ),
                    schedule=str(raw["schedule"]) if raw.get("schedule") else None,
                    description=str(raw["description"]) if raw.get("description") else None,
                )
            except Exception:
                raise HTTPException(status_code=500, detail="Error al leer automatizacion.")
    raise HTTPException(status_code=404, detail=f"Automatizacion {auto_id} no encontrada.")


@router.post("/{auto_id}/execute", response_model=ExecuteResponse)
@limiter.limit("10/minute")
def execute_automation(
    request: Request,
    auto_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Ejecuta una automatizacion inmediatamente (trigger manual).

    Busca la automatizacion en el perfil del usuario y la ejecuta.
    """
    uid = claims_uid(claims)
    scheduler = _require_scheduler(request)

    auto_dto = _find_automation_in_profile(uid, auto_id)

    auto_dict = {
        "id": auto_dto.id,
        "name": auto_dto.name,
        "integration_id": auto_dto.integration_id,
        "instruction": auto_dto.instruction,
        "output_type": auto_dto.output_type or "chat",
        "active": auto_dto.active,
        "schedule": auto_dto.schedule or "manual",
    }

    try:
        result = scheduler.execute_now(uid, auto_dict)
        return ExecuteResponse(
            success=True,
            result=result,
            executed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        log.error("Error ejecutando automation %s: %s", auto_id, e)
        # Guardar fallo en Firestore
        try:
            from app.services.automation_scheduler import AutomationScheduler
            AutomationScheduler._record_failure_firestore(
                uid, auto_id, auto_dict.get("name", auto_id), str(e)
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Error al ejecutar la automatizacion: {e}",
        )


@router.get("/{auto_id}/history", response_model=HistoryResponse)
def get_automation_history(
    request: Request,
    auto_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve historial de ejecuciones de una automatizacion."""
    uid = claims_uid(claims)
    scheduler = _require_scheduler(request)

    # Verificar que la automatizacion existe en el perfil
    _find_automation_in_profile(uid, auto_id)

    executions = scheduler.get_execution_history(uid, auto_id)

    return HistoryResponse(
        executions=[
            HistoryItem(
                executed_at=ex.get("executed_at", ""),
                result=ex.get("result", ""),
                output_type=ex.get("output_type", "chat"),
            )
            for ex in executions
        ]
    )


@router.post("/results/ack")
def ack_pending_results(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Marca los resultados pendientes como leidos."""
    uid = claims_uid(claims)
    scheduler = _require_scheduler(request)
    scheduler.clear_pending_results(uid)
    return {"ok": True}


@router.get("/results/pending", response_model=PendingResultsResponse)
def get_pending_results(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve metadata de resultados pendientes para notificación desktop."""
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("get_pending_results: Firestore no disponible, retornando vacio")
        return PendingResultsResponse()
    profile = get_user_profile(uid) or {}
    pending = profile.get("pending_automation_results") or {}
    if not isinstance(pending, dict):
        pending = {}

    return PendingResultsResponse(
        has_new=bool(pending.get("has_new", False)),
        last_auto_id=str(pending.get("last_auto_id") or "").strip() or None,
        last_auto_name=str(pending.get("last_auto_name") or "").strip() or None,
        last_executed_at=str(pending.get("last_executed_at") or "").strip() or None,
        last_result_preview=str(pending.get("last_result_preview") or "").strip() or None,
    )


# ═══════════════════════════════════════════════════════
# C3 — Plantillas populares para automatizaciones
# ═══════════════════════════════════════════════════════


class PopularTemplateItem(BaseModel):
    """Template ligero para preview en UI de automatizaciones."""
    id: str
    name: str
    description: str
    category: str
    schedule: str
    # Campos pre-llenados para automatizacion simple
    suggested_name: str
    suggested_instruction: str
    suggested_integration: str  # integration_id sugerido
    suggested_output_type: str  # chat, notify, file


POPULAR_AUTOMATION_TEMPLATES: list[PopularTemplateItem] = [
    PopularTemplateItem(
        id="tmpl_revisar_correo",
        name="Revisar correo semanal",
        description="Cada lunes revisa tu Gmail, busca correos importantes y te notifica con un resumen.",
        category="Productividad",
        schedule="weekly:mon:08:00",
        suggested_name="Revisar correo semanal",
        suggested_instruction="Revisa mi bandeja de Gmail, busca los correos no leídos importantes de la semana y hazme un resumen con los más relevantes.",
        suggested_integration="gmail",
        suggested_output_type="notify",
    ),
    PopularTemplateItem(
        id="tmpl_recordatorio_reuniones",
        name="Recordatorio de reuniones",
        description="Cada mañana revisa tu Google Calendar y te recuerda las reuniones del día.",
        category="Planificación",
        schedule="daily:07:00",
        suggested_name="Recordatorio de reuniones",
        suggested_instruction="Revisa mi Google Calendar, busca los eventos de hoy y envíame un recordatorio con las reuniones programadas, incluyendo hora y enlace si hay.",
        suggested_integration="google-calendar",
        suggested_output_type="notify",
    ),
    PopularTemplateItem(
        id="tmpl_reporte_gastos",
        name="Generar reporte de gastos",
        description="Busca facturas en tu Gmail y genera un reporte de gastos mensual en Excel.",
        category="Finanzas",
        schedule="monthly_1_09",
        suggested_name="Reporte de gastos mensual",
        suggested_instruction="Busca en mi Gmail los correos con facturas del último mes, extrae los montos, fechas y conceptos, y genera un resumen de gastos categorizado.",
        suggested_integration="gmail",
        suggested_output_type="file",
    ),
    PopularTemplateItem(
        id="tmpl_ofertas_trabajo",
        name="Monitor de ofertas de trabajo",
        description="Busca ofertas de trabajo según tu perfil y te envía las mejores cada semana.",
        category="Empleo",
        schedule="weekly:mon:09:00",
        suggested_name="Monitor de ofertas de trabajo",
        suggested_instruction="Busca en Computrabajo Venezuela ofertas recientes según mi perfil. Filtra las 5 mejores y envíamelas con enlaces si hay.",
        suggested_integration="third-option",
        suggested_output_type="notify",
    ),
    PopularTemplateItem(
        id="tmpl_alerta_dolar",
        name="Alerta dólar paralelo",
        description="Cada mañana consulta la tasa del dólar paralelo y te notifica.",
        category="Finanzas",
        schedule="daily:09:00",
        suggested_name="Alerta dólar paralelo",
        suggested_instruction="Consulta la tasa del dólar paralelo en Venezuela y notifícame el valor actual en 3–5 líneas.",
        suggested_integration="third-option",
        suggested_output_type="notify",
    ),
]


class PopularTemplatesResponse(BaseModel):
    templates: list[PopularTemplateItem]


@router.get("/templates/popular", response_model=PopularTemplatesResponse)
def get_popular_templates(
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve plantillas populares predefinidas para automatizaciones.

    Cada plantilla incluye campos sugeridos para pre-llenar el formulario
    de creación de automatización. No requiere acceso a Firestore.
    """
    _ = claims_uid(claims)
    return PopularTemplatesResponse(templates=POPULAR_AUTOMATION_TEMPLATES)


# ═══════════════════════════════════════════════════════
# Gap #3 — Notificación de fallos de automatizaciones
# ═══════════════════════════════════════════════════════

class AutomationFailureItem(BaseModel):
    id: str
    auto_id: str
    auto_name: str
    error: str
    failed_at: str


class AutomationFailuresResponse(BaseModel):
    failures: list[AutomationFailureItem]
    total: int


@router.get("/failures", response_model=AutomationFailuresResponse)
def get_automation_failures(
    claims: dict = Depends(require_product_jwt),
):
    """Últimos fallos de automatizaciones no acknowledged."""
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("get_automation_failures: Firestore no disponible, retornando vacio")
        return AutomationFailuresResponse(failures=[], total=0)
    db = get_firestore_client()
    failures = (
        db.collection("users")
        .document(uid)
        .collection("automation_failures")
        .where("acknowledged", "==", False)
        .order_by("failed_at", direction="DESCENDING")
        .limit(10)
        .stream()
    )
    items = [
        AutomationFailureItem(
            id=f.id,
            auto_id=f.get("auto_id") or "",
            auto_name=f.get("auto_name") or "",
            error=f.get("error") or "",
            failed_at=f.get("failed_at") or "",
        )
        for f in failures
    ]
    return AutomationFailuresResponse(failures=items, total=len(items))


class AckResponse(BaseModel):
    ok: bool = True


@router.post("/failures/{failure_id}/acknowledge", response_model=AckResponse)
def acknowledge_failure(
    failure_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Marca un fallo como visto."""
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("acknowledge_failure: Firestore no disponible, retornando ok")
        return AckResponse(ok=True)
    db = get_firestore_client()
    db.collection("users").document(uid).collection("automation_failures").document(failure_id).update({
        "acknowledged": True,
    })
    return AckResponse(ok=True)


# ═══════════════════════════════════════════════════════
# C2 — Pipelines compuestos multi-paso
# ═══════════════════════════════════════════════════════

def _require_orchestrator():
    """Obtiene el PipelineOrchestrator (singleton per request)."""
    from app.services.pipeline_orchestrator import PipelineOrchestrator
    return PipelineOrchestrator()


@pipelines_router.post("", response_model=PipelineDef)
@limiter.limit("10/minute")
def create_pipeline(
    request: Request,
    payload: Annotated[PipelineCreateRequest, Body()],
    claims: dict = Depends(require_product_jwt),
):
    """Crea un pipeline desde lenguaje natural o estructura manual.

    Ejemplo NL: "cada lunes revisa Gmail, si hay PDFs guárdalos y avísame por WhatsApp"
    """
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    try:
        pipeline = orchestrator.create_pipeline(uid, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Programar en scheduler si tiene schedule
    if pipeline.schedule and pipeline.schedule != "manual" and pipeline.active:
        scheduler = _require_scheduler(request)
        try:
            task_payload = orchestrator.to_task_payload(pipeline)
            from app.services.automation_jobs import parse_schedule, schedule_automation

            trigger = parse_schedule(pipeline.schedule)
            if trigger:
                schedule_automation(
                    scheduler._scheduler, uid, task_payload, "mensual",
                    job_fn=scheduler._on_trigger,
                )
                log.info("Pipeline programado: %s con schedule=%s", pipeline.id, pipeline.schedule)
        except Exception as e:
            log.warning("Error programando pipeline %s: %s", pipeline.id, e)

    return pipeline


@pipelines_router.get("", response_model=PipelineListResponse)
def list_pipelines(
    claims: dict = Depends(require_product_jwt),
):
    """Lista todos los pipelines del usuario."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    pipelines = orchestrator.list_pipelines(uid)
    return PipelineListResponse(pipelines=pipelines)


@pipelines_router.get("/{pipeline_id}", response_model=PipelineDef)
def get_pipeline(
    pipeline_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene un pipeline por ID."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    pipeline = orchestrator.get_pipeline(uid, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline no encontrado.")
    return pipeline


@pipelines_router.patch("/{pipeline_id}", response_model=PipelineDef)
@limiter.limit("10/minute")
def update_pipeline(
    request: Request,
    pipeline_id: str,
    payload: Annotated[PipelineUpdateRequest, Body()],
    claims: dict = Depends(require_product_jwt),
):
    """Actualiza un pipeline (nombre, pasos, schedule, activo)."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    try:
        pipeline = orchestrator.update_pipeline(uid, pipeline_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Re-programar si cambió el schedule
    if payload.schedule is not None or payload.active is not None:
        scheduler = _require_scheduler(request)
        # Eliminar job existente
        from app.services.automation_jobs import remove_automation_job
        remove_automation_job(scheduler._scheduler, uid, pipeline_id)

        # Re-programar si está activo y tiene schedule
        if pipeline.active and pipeline.schedule and pipeline.schedule != "manual":
            task_payload = orchestrator.to_task_payload(pipeline)
            from app.services.automation_jobs import parse_schedule, schedule_automation
            trigger = parse_schedule(pipeline.schedule)
            if trigger:
                schedule_automation(
                    scheduler._scheduler, uid, task_payload, "mensual",
                    job_fn=scheduler._on_trigger,
                )
    return pipeline


@pipelines_router.delete("/{pipeline_id}")
@limiter.limit("10/minute")
def delete_pipeline(
    request: Request,
    pipeline_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Elimina un pipeline."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    deleted = orchestrator.delete_pipeline(uid, pipeline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pipeline no encontrado.")

    # Eliminar job programado si existe
    scheduler = _require_scheduler(request)
    from app.services.automation_jobs import remove_automation_job
    remove_automation_job(scheduler._scheduler, uid, pipeline_id)

    return {"ok": True}


@pipelines_router.post("/{pipeline_id}/execute", response_model=PipelineExecuteResponse)
@limiter.limit("5/minute")
def execute_pipeline(
    request: Request,
    pipeline_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Ejecuta un pipeline inmediatamente."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    try:
        result = orchestrator.execute_pipeline(uid, pipeline_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return PipelineExecuteResponse(
        execution_id=f"exec_{pipeline_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        success=result.success,
        final_output=result.final_output,
        steps_count=len(result.steps),
        executed_at=result.completed_at or datetime.now(timezone.utc).isoformat(),
        error=result.error,
        steps=result.steps,
    )


@pipelines_router.get("/{pipeline_id}/history")
def get_pipeline_history(
    pipeline_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve historial de ejecuciones de un pipeline."""
    uid = claims_uid(claims)
    orchestrator = _require_orchestrator()
    pipeline = orchestrator.get_pipeline(uid, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline no encontrado.")

    # Usar el historial de automatizaciones existente
    try:
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        docs = (
            db.collection("users")
            .document(uid)
            .collection("automation_executions")
            .where("automation_id", "==", pipeline_id)
            .order_by("executed_at", direction="DESCENDING")
            .limit(20)
            .stream()
        )
        executions = [
            {
                "executed_at": d.to_dict().get("executed_at", ""),
                "result": d.to_dict().get("result", ""),
                "output_type": d.to_dict().get("output_type", "chat"),
            }
            for d in docs
        ]
        return {"executions": executions}
    except Exception as e:
        log.warning("Error obteniendo historial de pipeline %s: %s", pipeline_id, e)
        return {"executions": []}


@pipelines_router.post("/intent/detect")
def detect_pipeline_intent(
    body: dict,
    claims: dict = Depends(require_product_jwt),
):
    """Detecta si un mensaje del usuario describe un pipeline y devuelve la estructura.

    Usado por el frontend para mostrar preview del pipeline antes de crearlo.
    """
    uid = claims_uid(claims)
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texto vacío.")

    orchestrator = _require_orchestrator()
    try:
        pipeline = orchestrator.parse_natural_language(uid, text)
        return {
            "is_pipeline": True,
            "pipeline": pipeline.model_dump(),
            "explanation": f"Pipeline detectado: {pipeline.name} con {len(pipeline.steps)} pasos.",
        }
    except Exception as e:
        return {
            "is_pipeline": False,
            "pipeline": None,
            "explanation": str(e),
        }


# ═══════════════════════════════════════════════════════
# C3 — Plantillas reutilizables de automatizaciones
# ═══════════════════════════════════════════════════════

class TemplateListItem(BaseModel):
    id: str
    name: str
    description: str
    category: str
    schedule: str
    author_uid: str
    usage_count: int
    created_at: str


class TemplateListResponse(BaseModel):
    templates: list[TemplateListItem]


class TemplateCloneResponse(BaseModel):
    template_id: str
    template_name: str
    schedule: str
    workflow_def: dict


class TemplateSaveRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    workflow_def: dict
    schedule: str = "manual"


def _require_template_service(request: Request):
    service = getattr(request.app.state, "auto_template_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Servicio de plantillas no disponible.")
    return service


@automation_templates_router.get("", response_model=TemplateListResponse)
def list_automation_templates(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Lista todas las plantillas públicas de automatizaciones."""
    _ = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("list_automation_templates: Firestore no disponible, retornando vacio")
        return TemplateListResponse(templates=[])
    service = _require_template_service(request)
    try:
        templates = service.list_templates()
        return TemplateListResponse(
            templates=[
                TemplateListItem(
                    id=t.get("id", ""),
                    name=str(t.get("name", "")),
                    description=str(t.get("description", "")),
                    category=str(t.get("category", "General")),
                    schedule=str(t.get("schedule", "manual")),
                    author_uid=str(t.get("author_uid", "")),
                    usage_count=int(t.get("usage_count", 0)),
                    created_at=str(t.get("created_at", "")),
                )
                for t in templates
            ]
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@automation_templates_router.post("", response_model=TemplateListItem)
@limiter.limit("10/minute")
def save_as_template(
    request: Request,
    payload: Annotated[TemplateSaveRequest, Body()],
    claims: dict = Depends(require_product_jwt),
):
    """Guarda una automatización o pipeline como plantilla pública."""
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        created = service.save_as_template(
            uid=uid,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            workflow_def=payload.workflow_def,
            schedule=payload.schedule,
        )
        return TemplateListItem(
            id=created.get("id", ""),
            name=str(created.get("name", "")),
            description=str(created.get("description", "")),
            category=str(created.get("category", "General")),
            schedule=str(created.get("schedule", "manual")),
            author_uid=str(created.get("author_uid", "")),
            usage_count=int(created.get("usage_count", 0)),
            created_at=str(created.get("created_at", "")),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@automation_templates_router.post("/{template_id}/clone", response_model=TemplateCloneResponse)
@limiter.limit("10/minute")
def clone_template(
    request: Request,
    template_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Clona una plantilla y la asigna al usuario actual."""
    uid = claims_uid(claims)
    service = _require_template_service(request)
    try:
        result = service.clone_template(uid, template_id)
        if not result:
            raise HTTPException(status_code=404, detail="Plantilla no encontrada.")
        return TemplateCloneResponse(**result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# --- FREE-AU01: optional composite automation hook (flag off by default) ---


class CompositeStepBody(BaseModel):
    tool_name: str
    arguments: dict = {}


class CompositeRunRequest(BaseModel):
    name: str
    steps: list[CompositeStepBody]


class CompositeRunResponse(BaseModel):
    ok: bool
    name: str
    step_outputs: list[str] = []
    error: str | None = None


@router.post("/composite/run", response_model=CompositeRunResponse)
@limiter.limit("20/minute")
def run_composite_automation_hook(
    request: Request,
    body: CompositeRunRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Stub endpoint: encadena hasta 2 tools cuando AUTOMATIONS_COMPOSITE_ENABLED=true."""
    from app.application.agent.tools import build_default_registry
    from app.application.automations.composite import (
        AutomationSpec,
        AutomationStep,
        execute_composite_if_enabled,
    )
    from app.settings import settings

    if not settings.automations_composite_enabled:
        raise HTTPException(status_code=404, detail="Automatizaciones compuestas deshabilitadas.")

    uid = claims_uid(claims)
    registry = build_default_registry(
        include_web_search=bool(settings.enable_web_search)
    )
    spec = AutomationSpec(
        name=body.name,
        steps=[
            AutomationStep(tool_name=s.tool_name, arguments=s.arguments or {})
            for s in body.steps
        ],
    )
    result = execute_composite_if_enabled(uid, spec, registry)
    if result is None:
        raise HTTPException(status_code=404, detail="Automatizaciones compuestas deshabilitadas.")
    return CompositeRunResponse(
        ok=result.ok,
        name=result.name,
        step_outputs=result.step_outputs,
        error=result.error,
    )
