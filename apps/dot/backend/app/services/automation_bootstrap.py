"""Rehidratación de automatizaciones programadas al arrancar el API."""
from __future__ import annotations

import logging
from uuid import UUID

from app.firebase_db import get_db as get_firestore_client
from app.services.automation_scheduler import AutomationScheduler

log = logging.getLogger("dot.automation_bootstrap")


def _resolve_plan(uid: str) -> str:
    """Obtiene el plan del usuario desde billing; fallback mensual."""
    try:
        from sqlalchemy import select

        from app.billing_db import get_engine
        from app.services.auth_service import plan_to_str
        from dot_billing.models import ClienteORM

        with get_engine().connect() as conn:
            row = conn.execute(
                select(ClienteORM.plan).where(ClienteORM.id == UUID(uid))
            ).fetchone()
            if row and row[0] is not None:
                return plan_to_str(row[0])
    except Exception:
        log.debug("Plan no resuelto para uid=%s; usando mensual", uid[:8], exc_info=True)
    return "mensual"


def hydrate_all_scheduled_automations(scheduler: AutomationScheduler) -> int:
    """Recarga jobs APScheduler para usuarios con automatizaciones activas.

    Necesario tras reinicio del API: APScheduler es in-memory y los jobs
    solo se cargaban en login o PATCH de perfil.
    """
    try:
        db = get_firestore_client()
    except Exception:
        log.warning("Rehidratación omitida: Firestore no disponible")
        return 0

    loaded = 0
    for doc in db.collection("users").stream():
        profile = doc.to_dict() or {}
        automations = profile.get("saved_automations")
        if not isinstance(automations, list) or not automations:
            continue

        has_scheduled = any(
            isinstance(auto, dict)
            and auto.get("active")
            and auto.get("schedule")
            and auto.get("schedule") != "manual"
            for auto in automations
        )
        if not has_scheduled:
            continue

        uid = doc.id
        plan = _resolve_plan(uid)
        try:
            scheduler.load_user_automations(uid=uid, plan=plan)
            loaded += 1
        except Exception:
            log.warning("Error rehidratando automatizaciones uid=%s", uid[:8], exc_info=True)

    log.info("Rehidratación completada: %d usuario(s) con jobs programados", loaded)
    return loaded


def hydrate_all_scheduled_pipelines(scheduler: AutomationScheduler) -> int:
    """C2: Recarga pipelines programados de la subcolección Firestore.

    Los pipelines se almacenan en users/{uid}/pipelines/{pipeline_id},
    no en el perfil saved_automations.
    """
    try:
        db = get_firestore_client()
    except Exception:
        log.warning("Rehidratación de pipelines omitida: Firestore no disponible")
        return 0

    loaded = 0
    from app.services.automation_jobs import parse_schedule, schedule_automation

    for user_doc in db.collection("users").stream():
        uid = user_doc.id
        try:
            pipeline_docs = (
                db.collection("users")
                .document(uid)
                .collection("pipelines")
                .where("active", "==", True)
                .stream()
            )
            for p_doc in pipeline_docs:
                pipeline = p_doc.to_dict() or {}
                schedule_str = pipeline.get("schedule", "manual")
                if not schedule_str or schedule_str == "manual":
                    continue

                trigger = parse_schedule(schedule_str)
                if not trigger:
                    continue

                # Convertir a payload compatible con TaskQueue
                from app.services.pipeline_orchestrator import PipelineOrchestrator

                orchestrator = PipelineOrchestrator()
                pipeline_def = orchestrator.get_pipeline(uid, p_doc.id)
                if not pipeline_def:
                    continue

                payload = orchestrator.to_task_payload(pipeline_def)
                schedule_automation(
                    scheduler._scheduler, uid, payload, "mensual",
                    job_fn=scheduler._on_trigger,
                )
                loaded += 1
                log.info(
                    "Pipeline rehidratado: %s (%s) para uid=%s",
                    pipeline.get("name", "?"), schedule_str, uid[:8],
                )
        except Exception:
            log.warning(
                "Error rehidratando pipelines uid=%s", uid[:8], exc_info=True,
            )

    log.info("Rehidratación de pipelines completada: %d programados", loaded)
    return loaded
