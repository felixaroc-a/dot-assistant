"""Telemetria: eventos anonimos del cliente (sin datos personales)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

log = logging.getLogger("dot.telemetry")

router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


class TelemetryEvent(BaseModel):
    type: str
    timestamp: str
    meta: dict = {}


@router.post("/event", status_code=204)
def telemetry_event(request: Request, body: TelemetryEvent):
    """Recibe evento de telemetria anonimo del cliente."""
    if body.type not in ("session_error", "api_latency", "provider_failure", "login_failure"):
        log.warning("Telemetry event type desconocido: %s", body.type)
        return Response(status_code=204)

    log.debug(
        "Telemetry [%s] meta=%s ip=%s",
        body.type,
        {k: v for k, v in body.meta.items() if k != "detail" or len(str(v)) < 100},
        request.client.host if request.client else "?",
    )

    return Response(status_code=204)
