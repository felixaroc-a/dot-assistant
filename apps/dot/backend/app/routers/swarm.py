"""Router de Agent Swarms — ejecución paralela de múltiples agentes.

Permite lanzar swarms de agentes que trabajan en paralelo sobre
sub-tareas de un objetivo, con un coordinador que mergea resultados.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import require_product_jwt, claims_uid
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.swarm.router")

router = APIRouter(prefix="/v1/swarm", tags=["swarm"])


# ─── Schemas ───────────────────────────────────────────────────────────


class LaunchSwarmRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=2000, description="Objetivo principal del swarm")
    sub_goals: list[str] | None = Field(
        default=None,
        description="Sub-objetivos (si es None, DOT los divide automáticamente)",
    )
    max_parallel: int = Field(default=4, ge=1, le=8, description="Máximo de agentes simultáneos")
    timeout_seconds: float = Field(default=600.0, ge=30.0, le=3600.0, description="Timeout en segundos")


class SwarmResultResponse(BaseModel):
    ok: bool
    swarm_id: str | None = None
    goal: str | None = None
    status: str | None = None
    sub_results: list[dict] | None = None
    merged_result: str | None = None
    agents_used: int = 0
    agents_completed: int = 0
    agents_failed: int = 0
    error: str | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.post("/launch", response_model=SwarmResultResponse)
@limiter.limit("5/minute")
async def launch_swarm(
    request: Request,
    body: LaunchSwarmRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Lanza un swarm de agentes en paralelo.

    Divide el objetivo en sub-tareas (o usa las proporcionadas), lanza
    agentes en paralelo, espera resultados y los mergea en una respuesta cohesiva.

    Ejemplo:
    ```json
    {
      "goal": "Investigar el mercado de IA en Latinoamérica y generar un reporte",
      "max_parallel": 3
    }
    ```
    """
    uid = claims_uid(claims)

    try:
        from app.services.swarm_service import get_swarm_manager

        manager = get_swarm_manager()
        result = await manager.launch_swarm(
            uid=uid,
            goal=body.goal,
            sub_goals=body.sub_goals,
            max_parallel=body.max_parallel,
            timeout_seconds=body.timeout_seconds,
        )

        return SwarmResultResponse(
            ok=True,
            swarm_id=result.swarm_id,
            goal=result.goal,
            status=result.status,
            sub_results=result.sub_results,
            merged_result=result.merged_result,
            agents_used=result.agents_used,
            agents_completed=result.agents_completed,
            agents_failed=result.agents_failed,
        )
    except Exception as e:
        log.exception("Error lanzando swarm")
        raise HTTPException(status_code=500, detail=f"Error lanzando swarm: {e}")


@router.get("/{swarm_id}", response_model=SwarmResultResponse)
async def get_swarm_status(
    swarm_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el estado y resultados de un swarm."""
    from app.services.swarm_service import get_swarm_manager

    manager = get_swarm_manager()
    state = await manager.get_swarm_status(swarm_id)

    if state is None:
        raise HTTPException(status_code=404, detail="Swarm no encontrado")

    return SwarmResultResponse(
        ok=True,
        swarm_id=state["swarm_id"],
        goal=state["goal"],
        status=state["status"],
        sub_results=state["results"],
        merged_result="",
    )
