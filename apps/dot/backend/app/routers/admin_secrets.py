"""Endpoints de administración para rotación de secretos.

POST /v1/admin/secrets/rotate — rota secretos (admin only).
GET  /v1/admin/secrets/rotation-history — historial de rotaciones.
"""

from __future__ import annotations

import logging
import secrets as _secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.security.audit import audit_event
from app.services.secret_rotation_service import (
    SecretRotationService,
    get_secret_rotation_service,
)
from app.settings import settings

log = logging.getLogger("dot.admin_secrets")

router = APIRouter(prefix="/v1/admin/secrets", tags=["admin-secrets"])


# ─── Schemas ───────────────────────────────────────────────────────

class SecretRotationRequest(BaseModel):
    secret_type: str = Field(
        ...,
        pattern="^(jwt|fernet|api_keys|all)$",
        description="Tipo de secreto a rotar: jwt, fernet, api_keys, o all",
    )
    reason: str | None = Field(
        None,
        max_length=500,
        description="Razón de la rotación (para auditoría)",
    )


class RotationResult(BaseModel):
    rotation_id: str
    secret_type: str
    success: bool
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


# ─── Auth helper ────────────────────────────────────────────────────

def _verify_admin(x_admin_key: str | None = Header(None)) -> str:
    """Verifica clave de administrador. Retorna el key hasheado para auditoría."""
    configured = settings.admin_api_key.strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_KEY no configurada en el servidor.",
        )
    if not x_admin_key:
        raise HTTPException(status_code=401, detail="X-Admin-Key requerido.")
    if not _secrets.compare_digest(x_admin_key.strip(), configured):
        raise HTTPException(status_code=403, detail="Admin API key inválida.")
    return "admin"


# ─── Endpoints ──────────────────────────────────────────────────────

@router.post("/rotate", response_model=RotationResult)
async def rotate_secrets(
    body: SecretRotationRequest,
    request: Request,
    initiator: str = Depends(_verify_admin),  # noqa: F821
):
    """Rota secretos del sistema. Solo administradores.

    Tipos soportados:
    - jwt: Genera nuevo par RS256, respalda clave anterior.
    - fernet: Genera nueva clave Fernet, re-encripta tokens OAuth.
    - api_keys: Cicla DeepSeek/OpenAI desde backup configurado.
    - all: Rota los tres tipos secuencialmente.
    """
    svc: SecretRotationService = get_secret_rotation_service()

    reason = body.reason or "Rotación manual desde panel admin"
    audit_event(
        "secret_rotation_requested",
        secret_type=body.secret_type,
        reason=reason,
        ip=request.client.host if request.client else None,
    )

    results: list[dict] = []

    if body.secret_type in ("jwt", "all"):
        record = svc.rotate_jwt_keys(initiator=initiator)
        results.append({
            "rotation_id": record.rotation_id,
            "secret_type": record.secret_type,
            "success": record.success,
            "error": record.error,
            "metadata": record.metadata,
        })

    if body.secret_type in ("fernet", "all"):
        record = svc.rotate_fernet_key(initiator=initiator)
        results.append({
            "rotation_id": record.rotation_id,
            "secret_type": record.secret_type,
            "success": record.success,
            "error": record.error,
            "metadata": record.metadata,
        })

    if body.secret_type in ("api_keys", "all"):
        record = svc.rotate_api_keys(initiator=initiator)
        results.append({
            "rotation_id": record.rotation_id,
            "secret_type": record.secret_type,
            "success": record.success,
            "error": record.error,
            "metadata": record.metadata,
        })

    # Si se rotó "all", devolver resultado combinado
    if body.secret_type == "all":
        all_ok = all(r["success"] for r in results)
        return RotationResult(
            rotation_id="all-" + results[0]["rotation_id"] if results else "all-none",
            secret_type="all",
            success=all_ok,
            error="; ".join(r["error"] for r in results if r["error"]) or None,
            metadata={"rotations": results},
        )

    return RotationResult(**results[0])


@router.get("/rotation-history")
async def get_rotation_history(
    request: Request,
    secret_type: str | None = Query(None, pattern="^(jwt|fernet|api_keys)$"),
    limit: int = Query(20, ge=1, le=100),
    initiator: str = Depends(_verify_admin),  # noqa: F821
):
    """Historial de rotaciones de secretos (admin only)."""
    svc: SecretRotationService = get_secret_rotation_service()
    history = svc.get_rotation_history(secret_type=secret_type, limit=limit)
    return {"rotations": history, "count": len(history)}
