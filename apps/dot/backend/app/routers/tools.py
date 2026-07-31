"""Tool policies & audit REST API.

Endpoints:
  GET  /v1/tools/policies           — consultar mis políticas
  PUT  /v1/tools/policies           — actualizar mis políticas
  GET  /v1/tools/policies/defaults  — políticas por defecto del sistema
  GET  /v1/tools/audit              — mi log de auditoría de herramientas
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter
from app.services import tool_audit_service, tool_policy_service

log = logging.getLogger("dot.tools_router")

router = APIRouter(prefix="/v1/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Schemas inline (simples — no justifican archivo separado)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class ToolPolicyUpdate(BaseModel):
    """Body para PUT /v1/tools/policies."""

    allow_list: list[str] | None = Field(
        default=None,
        description="Lista de herramientas a permitir explícitamente. None = no modificar.",
    )
    deny_list: list[str] | None = Field(
        default=None,
        description="Lista de herramientas a denegar explícitamente. None = no modificar.",
    )


class BrowserWebPolicyUpdate(BaseModel):
    """Body para PUT /v1/tools/policies/browser-web."""

    enabled: bool = Field(
        description="True = DOT puede usar webs (entrar, leer, clic, formularios); False = modo seguro.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/policies/defaults")
def get_default_policies(
    request: Request,
    claims: dict[str, Any] = Depends(require_product_jwt),
):
    """Políticas por defecto del sistema (dangerous tools, descripción)."""
    return tool_policy_service.get_default_policies()


@router.get("/policies")
def get_my_policies(
    request: Request,
    claims: dict[str, Any] = Depends(require_product_jwt),
):
    """Obtiene las políticas de herramientas del usuario autenticado."""
    uid = claims_uid(claims)
    policy = tool_policy_service.get_user_policy_raw(uid)
    if policy is None:
        raise HTTPException(
            status_code=503,
            detail="Servicio de políticas no disponible (Firestore offline).",
        )
    return policy


@router.get("/policies/browser-web")
def get_browser_web_policy(
    request: Request,
    claims: dict[str, Any] = Depends(require_product_jwt),
):
    """Estado del permiso de navegación web (capa B) para el usuario."""
    uid = claims_uid(claims)
    return {"enabled": tool_policy_service.is_browser_web_enabled(uid)}


@router.put("/policies/browser-web")
@limiter.limit("10/minute")
def update_browser_web_policy(
    request: Request,
    body: BrowserWebPolicyUpdate,
    claims: dict[str, Any] = Depends(require_product_jwt),
):
    """Activa o desactiva «DOT puede usar webs» para el usuario."""
    uid = claims_uid(claims)
    ok = tool_policy_service.set_browser_web_enabled(uid, body.enabled)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar el permiso. Intenta de nuevo en unos segundos.",
        )
    return {"enabled": tool_policy_service.is_browser_web_enabled(uid)}


@router.put("/policies")
@limiter.limit("10/minute")
def update_my_policies(
    request: Request,
    body: ToolPolicyUpdate,
    claims: dict[str, Any] = Depends(require_product_jwt),
):
    """Actualiza las políticas de herramientas del usuario autenticado.

    Campos no enviados (None) no se modifican.
    Enviar lista vacía [] limpia la lista correspondiente.
    """
    uid = claims_uid(claims)

    ok = tool_policy_service.save_user_policy(
        uid=uid,
        allow_list=body.allow_list,
        deny_list=body.deny_list,
    )
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar la política. Firestore no disponible.",
        )

    # Devolver la política actualizada
    updated = tool_policy_service.get_user_policy_raw(uid)
    return updated or {"message": "Política guardada (offline — puede no persistir)."}


@router.get("/audit")
def get_my_audit_log(
    request: Request,
    claims: dict[str, Any] = Depends(require_product_jwt),
    limit: int = Query(default=50, ge=1, le=200, description="Número máximo de entradas"),
    tool_name: str | None = Query(
        default=None,
        description="Filtrar por nombre de herramienta (opcional)",
    ),
):
    """Obtiene el log de auditoría de herramientas del usuario autenticado.

    Ordenado por timestamp descendente (más reciente primero).
    """
    uid = claims_uid(claims)
    entries = tool_audit_service.get_user_audit_log(
        uid=uid,
        limit=limit,
        tool_name=tool_name,
    )
    return {
        "uid": uid,
        "total": len(entries),
        "limit": limit,
        "entries": entries,
    }
