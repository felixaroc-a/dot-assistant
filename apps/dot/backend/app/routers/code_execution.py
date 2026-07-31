"""Endpoints REST para ejecución de código en sandbox Docker.

POST /v1/code/execute — ejecuta código Python/JS en sandbox aislado
GET  /v1/code/status   — verifica disponibilidad del sandbox

Seguridad:
- Gate detrás de CODE_EXECUTION_ENABLED (default false)
- Requiere JWT auth (require_product_jwt)
- Rate limit: 10/min por usuario
- Validación de código peligroso pre-ejecución
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth_deps import claims_uid, require_product_jwt
from app.services.code_execution_service import (
    CodeSecurityError,
    SandboxUnavailableError,
    get_code_execution_service,
)
from app.settings import settings

router = APIRouter(tags=["code-execution"])
log = logging.getLogger("dot.code_execution.router")


class CodeExecuteRequest(BaseModel):
    language: str = Field(
        ...,
        description="Lenguaje de ejecución: 'python' o 'javascript'",
    )
    code: str = Field(
        ...,
        description="Código fuente a ejecutar",
        min_length=1,
        max_length=10_000,
    )
    timeout: int = Field(
        default=30,
        description="Timeout en segundos (1-300)",
        ge=1,
        le=300,
    )

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        if v not in ("python", "javascript"):
            raise ValueError("Lenguaje debe ser 'python' o 'javascript'")
        return v


class CodeExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    sandbox_id: str


class SandboxStatusResponse(BaseModel):
    available: bool
    image: str
    message: str


def _gate_code_execution() -> None:
    """Verifica que la feature flag CODE_EXECUTION_ENABLED esté activa."""
    if not settings.code_execution_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "code_execution_disabled",
                "message": (
                    "Ejecución de código deshabilitada. "
                    "Configure CODE_EXECUTION_ENABLED=true en .env para activar."
                ),
            },
        )


@router.get("/v1/code/status", response_model=SandboxStatusResponse)
def sandbox_status(claims: dict = Depends(require_product_jwt)):
    """Verifica si el sandbox Docker está disponible."""
    _gate_code_execution()
    service = get_code_execution_service()
    available = service.is_available()
    return SandboxStatusResponse(
        available=available,
        image="dot-sandbox:latest",
        message=(
            "Sandbox listo para ejecución"
            if available
            else "Sandbox no disponible. Verifique Docker y la imagen dot-sandbox:latest."
        ),
    )


@router.post("/v1/code/execute", response_model=CodeExecuteResponse)
def execute_code(
    payload: CodeExecuteRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Ejecuta código Python o JavaScript en un sandbox Docker aislado.

    Rate limit: 10 solicitudes por minuto por usuario (via middleware global).

    El código se ejecuta en un contenedor Docker con:
    - Sin acceso a red
    - Filesystem solo lectura
    - Memoria limitada a 256MB
    - CPU limitada a 0.5 cores
    - Timeout forzado
    """
    _gate_code_execution()

    uid = claims_uid(claims)
    service = get_code_execution_service()

    try:
        if payload.language == "python":
            result = service.execute_python(payload.code, payload.timeout)
        else:
            result = service.execute_javascript(payload.code, payload.timeout)
    except CodeSecurityError as e:
        log.warning(
            "Código bloqueado por seguridad (uid=%s, lang=%s): %s",
            uid[:12] if uid else "?", payload.language, str(e)[:200],
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "security_blocked", "message": str(e)},
        )
    except SandboxUnavailableError as e:
        log.error("Sandbox no disponible (uid=%s): %s", uid[:12] if uid else "?", e)
        raise HTTPException(
            status_code=503,
            detail={"code": "sandbox_unavailable", "message": str(e)},
        )

    log.info(
        "Código ejecutado (uid=%s, lang=%s, sandbox=%s, exit=%d, len_out=%d)",
        uid[:12] if uid else "?",
        payload.language,
        result.sandbox_id,
        result.exit_code,
        len(result.stdout),
    )

    return CodeExecuteResponse(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        sandbox_id=result.sandbox_id,
    )
