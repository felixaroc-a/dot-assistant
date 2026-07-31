"""Router de ejecución remota via WhatsApp — DEPRECADO (PROMPTSOTE FASE 5).

Path feliz: Agent Runtime → download_url_to_desktop → bridge /v1/tools/execute.
El proxy a OpenClaw :3000 queda deshabilitado (410).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth_deps import require_product_jwt

log = logging.getLogger("dot.whatsapp_remote")

router = APIRouter(prefix="/v1/whatsapp", tags=["whatsapp"])


class RemoteExecutionInput(BaseModel):
    command: str
    params: dict = {}


class RemoteExecutionOutput(BaseModel):
    success: bool
    command: str = ""
    result: dict | None = None
    error: str | None = None
    deprecated: bool = True


@router.post("/remote", response_model=RemoteExecutionOutput, status_code=410)
async def execute_remote(
    body: RemoteExecutionInput,
    claims: dict = Depends(require_product_jwt),
):
    """Deshabilitado: usar Agent Runtime download_url_to_desktop (no OpenClaw :3000)."""
    _ = claims
    log.info(
        "whatsapp_remote disabled command=%s (use download_url_to_desktop)",
        (body.command or "")[:40],
    )
    return RemoteExecutionOutput(
        success=False,
        command=body.command,
        deprecated=True,
        error=(
            "Endpoint deprecado. Las descargas van por el Agent Runtime "
            "(download_url_to_desktop → bridge local). OpenClaw :3000 ya no es path feliz."
        ),
    )
