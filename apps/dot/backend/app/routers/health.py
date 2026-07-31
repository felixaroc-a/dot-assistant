"""Health check + admin scheduler status + recarga IA + metrics summary."""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db, get_engine
from app.services.circuit_breaker import get_all_breakers
from app.services.db_schema_checklist import format_missing_tables_hint, missing_tables
from app.services.usage_service import topup_ai_usage
from app.settings import settings

router = APIRouter(tags=["health"])
log = logging.getLogger("dot.health")


# ─── Modelos de respuesta ──────────────────────────────

class SchedulerStatusResponse(BaseModel):
    ok: bool
    ready: bool
    started: bool
    job_count: int
    jobs: list[dict] = []
    recent_errors: list[dict] = []
    error_count: int = 0
    queue: dict | None = None
    worker_heartbeat_estimate: str | None = None


# ─── Endpoints basicos ────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/full")
async def health_full(request: Request):
    """Health check completo: DB + Redis + DeepSeek + Scheduler.

    Devuelve 200 solo si todos los servicios críticos están ok.
    """
    checks: dict[str, dict] = {}

    # 1. DB check (sync, rápido: solo verifica conexión)
    try:
        from app.billing_db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception as e:
        checks["db"] = {"status": "error", "detail": str(e)[:200]}

    # 2. Redis check (si configurado)
    try:
        from app.services.redis_client import redis_health_check

        checks["redis"] = redis_health_check()
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)[:200]}

    # 3. DeepSeek connectivity (lightweight: solo verifica API reachable)
    if settings.deepseek_api_key.strip():
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                )
                if resp.status_code == 200:
                    checks["deepseek"] = {"status": "ok"}
                else:
                    checks["deepseek"] = {"status": "error", "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            checks["deepseek"] = {"status": "error", "detail": str(e)[:200]}
    else:
        checks["deepseek"] = {"status": "disabled", "detail": "DEEPSEEK_API_KEY no configurada"}

    # 4. Scheduler health
    scheduler = getattr(request.app.state, "auto_scheduler", None)
    if scheduler is not None:
        try:
            sch = scheduler.health_check()
            checks["scheduler"] = {"status": "ok" if sch.get("ok") else "degraded", **sch}
        except Exception as e:
            checks["scheduler"] = {"status": "error", "detail": str(e)[:200]}
    else:
        checks["scheduler"] = {"status": "not_initialized"}

    # 5. Metrics summary (Prometheus)
    metrics_summary: dict = {}
    if settings.metrics_enabled:
        try:
            from prometheus_client import REGISTRY

            def _get_metric_value(metric_name: str, labels: dict | None = None) -> float | None:
                """Extrae el valor actual de una métrica Prometheus."""
                try:
                    for _metric in REGISTRY.collect():
                        if _metric.name == metric_name:
                            for sample in _metric.samples:
                                sample_labels = dict(sample.labels)
                                sample_labels.pop("__name__", None)
                                if labels is None or all(
                                    sample_labels.get(k) == v for k, v in labels.items()
                                ):
                                    return float(sample.value)
                    return None
                except Exception:
                    return None

            total_requests = _get_metric_value(
                "http_requests_total",
                {"method": "GET", "status": "2xx"},
            )
            total_requests_all = _get_metric_value("http_requests_total")
            error_count = _get_metric_value(
                "http_requests_total",
                {"status": "5xx"},
            )
            if total_requests_all and total_requests_all > 0 and error_count:
                error_rate = round((error_count / total_requests_all) * 100, 2)
            else:
                error_rate = 0.0

            metrics_summary["total_requests"] = (
                int(total_requests_all) if total_requests_all is not None else 0
            )
            metrics_summary["error_rate_5min_percent"] = error_rate
            metrics_summary["avg_latency_5min_seconds"] = (
                round(_get_metric_value("http_request_duration_seconds_sum") or 0.0, 4)
            )

        except Exception as e:
            metrics_summary = {"error": str(e)[:200]}

    # 6. Active circuit breakers
    active_breakers: list[str] = []
    try:
        breakers = get_all_breakers()
        for name, breaker_obj in breakers.items():
            snap = breaker_obj.snapshot()
            if snap.state in ("OPEN", "HALF_OPEN"):
                active_breakers.append(name)
    except Exception:
        pass

    # Determinar estado global
    critical_checks = [checks.get("db", {}), checks.get("scheduler", {})]
    all_ok = all(c.get("status") == "ok" for c in critical_checks)
    degraded = any(c.get("status") in ("degraded", "error") for c in critical_checks)

    status_code = 200 if all_ok else 503
    overall = "ok" if all_ok else "degraded" if not degraded else "critical"

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "checks": checks,
            "metrics_summary": metrics_summary,
            "active_circuit_breakers": active_breakers,
        },
    )


@router.get("/health/db")
def health_db():
    """Verifica tablas billing + chat; 503 si faltan tablas críticas de chat."""
    if not settings.database_url.strip():
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": "DATABASE_URL no configurada.",
            },
        )

    try:
        from app import chat_models  # noqa: F401

        engine = get_engine()
        schema = missing_tables(engine, check_chat=True)
    except (RuntimeError, SQLAlchemyError, OSError) as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": f"No se pudo verificar esquema de BD: {exc}",
            },
        )

    if not schema.ok_billing_minimum:
        hint = format_missing_tables_hint(schema, enable_chat=False)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": f"Falta tabla crítica clientes_suscripcion. {hint}",
                "missing_billing": list(schema.missing_billing),
            },
        )

    if not schema.ok_chat:
        hint = format_missing_tables_hint(schema, enable_chat=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": (
                    "Tablas chat faltantes; GET /v1/chat fallará con 500. "
                    f"{hint}"
                ),
                "missing_chat": list(schema.missing_chat),
            },
        )

    return {
        "status": "ok",
        "billing": "ok",
        "chat": "ok",
    }


@router.get("/health/search")
def health_search(db: Session = Depends(get_billing_db)):
    """Verifica el estado de pg_trgm y búsqueda full-text."""
    from app.services.search_service import pg_trgm_status

    status = pg_trgm_status(db)
    if status["enabled"]:
        return status
    return JSONResponse(
        status_code=200,  # No es crítico — la app funciona con ILIKE fallback
        content=status,
    )


@router.get("/health/scheduler")
def health_scheduler(request: Request):
    """Verifica el estado del AutomationScheduler."""
    scheduler = getattr(request.app.state, "auto_scheduler", None)
    if scheduler is None:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "detail": "AutomationScheduler no inicializado"},
        )
    health = scheduler.health_check()
    if health.get("ok"):
        return {"status": "ok", **health}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", **health},
    )


@router.get("/health/circuit-breakers")
def health_circuit_breakers():
    """Estado de todos los circuit breakers registrados."""
    breakers = get_all_breakers()
    now = time.monotonic()

    result = {}
    for name, breaker in breakers.items():
        snap = breaker.snapshot()
        open_for = None
        if snap.open_since is not None:
            open_for = round(now - snap.open_since, 1)

        result[name] = {
            "state": snap.state,
            "failure_count": snap.failure_count,
            "failure_threshold": snap.failure_threshold,
            "recovery_timeout": snap.recovery_timeout,
            "half_open_max": snap.half_open_max,
            "half_open_attempts": snap.half_open_attempts,
            "total_successes": snap.total_successes,
            "total_failures": snap.total_failures,
            "last_failure_time": snap.last_failure_time,
            "last_success_time": snap.last_success_time,
            "open_for_seconds": open_for,
        }

    healthy = all(b["state"] == "CLOSED" for b in result.values())
    status_code = 200 if healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if healthy else "degraded",
            "breakers": result,
        },
    )


# ─── Admin: endpoint completo de estado ────────────────

def _check_admin_key(x_admin_key: str | None) -> bool:
    configured = settings.admin_api_key.strip()
    if not configured:
        return False
    return bool(x_admin_key and x_admin_key.strip() == configured)


@router.get(
    "/v1/admin/scheduler/status",
    response_model=SchedulerStatusResponse,
)
def admin_scheduler_status(
    request: Request,
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Estado completo del scheduler y cola de tareas (requiere X-Admin-Key).

    Devuelve:
    - Estado del APScheduler (running, ready, job_count)
    - Lista de jobs activos con nombre, schedule, next_run, last_run
    - Errores recientes del scheduler
    - Estado de la cola SQLite (pending, running, completed, failed)
    """
    if not _check_admin_key(x_admin_key):
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    scheduler = getattr(request.app.state, "auto_scheduler", None)
    if scheduler is None:
        return SchedulerStatusResponse(
            ok=False,
            ready=False,
            started=False,
            job_count=0,
            recent_errors=[{"error": "AutomationScheduler no inicializado"}],
        )

    # Estado del scheduler
    try:
        sched_health = scheduler.health_check()
    except Exception as e:
        log.exception("Error consultando health del scheduler")
        return SchedulerStatusResponse(
            ok=False,
            ready=False,
            started=scheduler._started if hasattr(scheduler, '_started') else False,
            job_count=0,
            recent_errors=[{"error": str(e)}],
        )

    # Estado de la cola
    queue_info: dict | None = None
    worker_estimate: str | None = None
    try:
        from worker.task_queue import TaskQueue

        queue = TaskQueue()
        queue_info = queue.stats()
        queue_info["recent_failures"] = queue.get_recent_failures(5)

        # Estimar actividad del worker: si hay tareas pending y no running,
        # el worker probablemente esta caido
        pending = queue_info["by_status"].get("pending", 0)
        running = queue_info["by_status"].get("running", 0)
        if pending > 0 and running == 0:
            worker_estimate = "probablemente_caido"
        elif running > 0:
            worker_estimate = "activo"
        else:
            worker_estimate = "idle"
    except Exception as e:
        log.warning("Error consultando cola de tareas: %s", e)
        queue_info = {"error": str(e)}

    return SchedulerStatusResponse(
        ok=sched_health.get("ok", False),
        ready=sched_health.get("ready", False),
        started=sched_health.get("started", False),
        job_count=sched_health.get("job_count", 0),
        jobs=sched_health.get("jobs", []),
        recent_errors=sched_health.get("recent_errors", []),
        error_count=sched_health.get("error_count", 0),
        queue=queue_info,
        worker_heartbeat_estimate=worker_estimate,
    )


# ─── Admin: recarga IA (D25) ───────────────────────────

class TopupRequest(BaseModel):
    cliente_id: str
    amount_usd: float


class TopupResponse(BaseModel):
    topup_id: str
    amount_usd_paid: float
    credit_added: float
    nordik_profit: float
    new_balance: float
    consumed_percent: int
    blocked: bool


@router.post(
    "/v1/admin/topup-ia-usage",
    response_model=TopupResponse,
    status_code=201,
)
def admin_topup_ia_usage(
    body: TopupRequest,
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_billing_db),
):
    """Registra una recarga de credito IA via servicio tecnico (D25).

    Requiere X-Admin-Key.
    El margen es 25% Nordik / 75% usuario:
    - Si se recargan $5, al usuario le llegan $3.75 de credito IA.
    - Nordik gana $1.25.
    """
    if not _check_admin_key(x_admin_key):
        raise HTTPException(status_code=403, detail="Admin API key invalida o no configurada")

    if body.amount_usd <= 0:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_amount", "message": "El monto debe ser mayor a 0."},
        )

    try:
        cliente_id = UUID(body.cliente_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_cliente_id", "message": "cliente_id debe ser un UUID valido."},
        )

    result = topup_ai_usage(
        db,
        cliente_id=cliente_id,
        amount_usd_paid=Decimal(str(body.amount_usd)),
    )

    log.info(
        "Recarga IA: cliente=%s pagado=%.2f credito=%.2f beneficio=%.2f",
        str(cliente_id)[:8],
        body.amount_usd,
        result["credit_added"],
        result["nordik_profit"],
    )

    return TopupResponse(**result)
