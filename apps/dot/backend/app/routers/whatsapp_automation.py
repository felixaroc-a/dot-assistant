"""Router de automatizaciones disparadas desde el canal WhatsApp.

Endpoint:
- POST /v1/whatsapp/automation → Agent Runtime unificado (BIBLIA §20), no OpenClaw
- GET  /v1/whatsapp/campaign/{auto_id}/status → estado de campana masiva
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth_deps import claims_uid, require_product_jwt
from app.firebase_db import get_db as get_firestore_client
from app.services.error_messages import sanitize_user_message
from app.services.whatsapp_link import get_channel_state

log = logging.getLogger("dot.whatsapp_automation")

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])


class AutomationInput(BaseModel):
    integration: str
    instruction: str


class AutomationOutput(BaseModel):
    success: bool
    status: str = "pending"
    integration: str = ""
    instruction: str = ""
    result: dict | None = None
    error: str | None = None


@router.post("/automation", response_model=AutomationOutput)
def run_automation(
    body: AutomationInput,
    claims: dict = Depends(require_product_jwt),
):
    """Ejecuta una automatizacion via Agent Runtime (mismo cerebro que chat/worker)."""
    uid = claims_uid(claims)
    state = get_channel_state(uid)

    if not state.linked:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp no esta vinculado. Escanea el QR primero.",
        )

    integration = body.integration.strip().lower().replace(" ", "-")
    # Agentic / Google: todo pasa por AutomationExecutor → run_agent o handlers propios
    allowed = {
        "gmail",
        "google-calendar",
        "google_calendar",
        "calendar",
        "third-option",
        "chat",
        "manual",
        "",
    }
    if integration not in allowed and integration not in {"whatsapp", "wa"}:
        # Integraciones desconocidas también son agentic (Gateway §20)
        pass

    instruction = body.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction requerida")

    try:
        from worker.executor import AutomationExecutor

        text = AutomationExecutor().execute(
            uid,
            {
                "integration_id": integration or "third-option",
                "instruction": instruction,
                "output_type": "notify",
            },
        )
        log.info("WA automation uid=%s integration=%s via Agent Runtime", uid, integration)
        return AutomationOutput(
            success=True,
            status="completed",
            integration=integration or "third-option",
            instruction=instruction[:100],
            result={"text": text[:8000]},
            error=None,
        )
    except Exception as e:
        log.warning("WA automation falló uid=%s: %s", uid, e)
        return AutomationOutput(
            success=False,
            status="failed",
            integration=integration or "third-option",
            instruction=instruction[:100],
            result=None,
            error=sanitize_user_message(str(e)),
        )


# ─── Estado de campana WhatsApp ─────────────────────────────────────────


class CampaignStatusOutput(BaseModel):
    auto_id: str
    status: str = "unknown"          # pending | running | completed | partial
    sent: int = 0
    failed: int = 0
    pending: int = 0
    total: int = 0
    last_execution: str | None = None
    executions: list[dict] = []


@router.get("/campaign/{auto_id}/status", response_model=CampaignStatusOutput)
def get_campaign_status(
    auto_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Devuelve el progreso de una campana de WhatsApp (enviados, fallidos, pendientes, total).

    Los datos provienen de Firestore: automation_results/{auto_id}/campaigns/
    """
    uid = claims_uid(claims)
    try:
        db = get_firestore_client()
        campaigns_ref = (
            db.collection("users")
            .document(uid)
            .collection("automation_results")
            .document(auto_id)
            .collection("campaigns")
        )
        docs = list(campaigns_ref.stream())
    except Exception as e:
        log.warning("Error consultando campana %s: %s", auto_id[:12], e)
        raise HTTPException(
            status_code=500,
            detail=sanitize_user_message(str(e), "No se pudo consultar el estado de la campaña."),
        )

    if not docs:
        return CampaignStatusOutput(
            auto_id=auto_id,
            status="not_found",
        )

    sent_total = 0
    failed_total = 0
    total_messages = 0
    pending_count = 0
    last_execution: str | None = None
    executions: list[dict] = []

    for doc in docs:
        data = doc.to_dict() or {}
        doc_status = str(data.get("status", "")).strip().lower()

        if doc_status == "registered":
            # Campana registrada pero no ejecutada aun
            pending_count = int(data.get("total", 0))
            total_messages = pending_count
        else:
            # Ejecucion completada
            s = int(data.get("sent", 0))
            f = int(data.get("failed", 0))
            t = int(data.get("total", 0))
            sent_total += s
            failed_total += f
            total_messages = max(total_messages, t)
            exec_time = data.get("executed_at", "")
            if exec_time and (last_execution is None or exec_time > last_execution):
                last_execution = exec_time
            executions.append({
                "executed_at": exec_time,
                "sent": s,
                "failed": f,
                "total": t,
            })

    # Estado agregado
    if sent_total == 0 and failed_total == 0 and pending_count > 0:
        status = "pending"
    elif failed_total == 0 and sent_total >= total_messages:
        status = "completed"
    elif sent_total > 0 and sent_total + failed_total >= total_messages:
        status = "partial" if failed_total > 0 else "completed"
    elif failed_total > 0 and sent_total == 0:
        status = "failed"
    else:
        status = "running"

    return CampaignStatusOutput(
        auto_id=auto_id,
        status=status,
        sent=sent_total,
        failed=failed_total,
        pending=pending_count,
        total=total_messages,
        last_execution=last_execution,
        executions=executions,
    )
