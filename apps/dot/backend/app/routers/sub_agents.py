"""REST endpoints para Sub-Agentes y MCP.

GOAL 4:
- POST /v1/agents/spawn — crear sub-agente
- GET /v1/agents/{agent_id}/status — estado del sub-agente
- POST /v1/agents/{agent_id}/cancel — cancelar sub-agente
- GET /v1/agents — listar agentes activos del usuario
- GET /v1/mcp/servers — listar servidores MCP conectados
- GET /v1/mcp/servers/{name}/tools — listar tools de un servidor MCP
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services.mcp_service import get_mcp_client
from app.services.sub_agent_service import get_sub_agent_manager

log = logging.getLogger("dot.sub_agents_router")

router = APIRouter(prefix="/v1", tags=["agents", "mcp"])

# ── Sub-agent router ────────────────────────────────────

sub_agents_router = APIRouter(prefix="/v1/agents", tags=["sub-agents"])


class SpawnAgentRequest(BaseModel):
    """Request para crear un sub-agente."""
    name: str = Field(..., min_length=1, max_length=100, description="Nombre del sub-agente")
    goal: str = Field(..., min_length=1, description="Objetivo que debe cumplir")
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools permitidas (vacío = todas disponibles)",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Contexto adicional para el sub-agente",
    )
    parent_conversation_id: str | None = Field(
        default=None,
        description="ID de conversación padre (opcional)",
    )


class SpawnAgentResponse(BaseModel):
    """Respuesta al crear un sub-agente."""
    agent_id: str
    name: str
    status: str
    message: str


class AgentStatusResponse(BaseModel):
    """Estado detallado de un sub-agente."""
    agent_id: str
    name: str
    status: str
    progress: float
    current_step: str
    goal: str
    steps_completed: int
    steps_total: int
    created_at: str
    last_active_at: str
    result_summary: str | None = None
    error_message: str | None = None
    allowed_tools: list[str] = []


class CancelAgentResponse(BaseModel):
    """Respuesta al cancelar un sub-agente."""
    agent_id: str
    cancelled: bool
    message: str


# MCP router

mcp_router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


# ═══════════════════════════════════════════════════════════
# GOAL 4: Endpoints de Sub-Agentes
# ═══════════════════════════════════════════════════════════


@sub_agents_router.post("/spawn", response_model=SpawnAgentResponse)
def spawn_agent(
    request: Request,
    body: SpawnAgentRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Crea un sub-agente que ejecuta una tarea en background.

    El sub-agente tiene su propio contexto de conversación y acceso
    a tools. Corre en background con progreso reportable.

    Límite: 5 sub-agentes activos por usuario.
    """
    uid = claims_uid(claims)
    manager = get_sub_agent_manager()

    # Obtener registry global para el sub-agente
    from app.application.agent.tools import build_default_registry
    from app.settings import settings

    registry = build_default_registry(
        include_web_search=bool(settings.enable_web_search)
    )

    try:
        agent_id = manager.spawn_sub_agent(
            uid=uid,
            name=body.name,
            goal=body.goal,
            allowed_tools=body.allowed_tools,
            context=body.context,
            parent_conversation_id=body.parent_conversation_id,
            registry=registry,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))

    return SpawnAgentResponse(
        agent_id=agent_id,
        name=body.name,
        status="running",
        message=f"Sub-agente '{body.name}' creado y ejecutándose en background",
    )


@sub_agents_router.get("", response_model=list[dict[str, Any]])
def list_agents(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    include_completed: bool = False,
):
    """Lista los sub-agentes del usuario autenticado.

    Por defecto solo muestra activos (pending + running).
    Usa include_completed=true para ver también terminados.
    """
    uid = claims_uid(claims)
    manager = get_sub_agent_manager()

    if include_completed:
        agents = manager.get_all_sub_agents(uid)
    else:
        agents = manager.get_active_sub_agents(uid)

    return agents


@sub_agents_router.get("/{agent_id}/status", response_model=AgentStatusResponse)
def get_agent_status(
    agent_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el estado y progreso de un sub-agente específico."""
    uid = claims_uid(claims)
    manager = get_sub_agent_manager()

    status = manager.get_sub_agent_status(uid, agent_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Sub-agente no encontrado")

    return AgentStatusResponse(**status)


@sub_agents_router.post("/{agent_id}/cancel", response_model=CancelAgentResponse)
def cancel_agent(
    agent_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Cancela un sub-agente en ejecución."""
    uid = claims_uid(claims)
    manager = get_sub_agent_manager()

    cancelled = manager.cancel_sub_agent(uid, agent_id)

    if not cancelled:
        # Verificar si existe pero ya terminó
        status = manager.get_sub_agent_status(uid, agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Sub-agente no encontrado")
        return CancelAgentResponse(
            agent_id=agent_id,
            cancelled=False,
            message=f"El sub-agente ya está en estado '{status['status']}'",
        )

    return CancelAgentResponse(
        agent_id=agent_id,
        cancelled=True,
        message="Sub-agente cancelado exitosamente",
    )


@sub_agents_router.get("/{agent_id}/result", response_model=dict[str, Any])
def get_agent_result(
    agent_id: str,
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene el resultado final de un sub-agente completado."""
    uid = claims_uid(claims)
    manager = get_sub_agent_manager()

    result = manager.get_sub_agent_result(uid, agent_id)
    if result is None:
        status = manager.get_sub_agent_status(uid, agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Sub-agente no encontrado")
        raise HTTPException(
            status_code=400,
            detail=f"El sub-agente aún está en estado '{status['status']}'",
        )

    return result


# ═══════════════════════════════════════════════════════════
# GOAL 4: Endpoints de MCP
# ═══════════════════════════════════════════════════════════


@mcp_router.get("/servers")
def list_mcp_servers(request: Request):
    """Lista todos los servidores MCP conectados con su estado."""
    client = get_mcp_client()
    servers = client.get_connected_servers()

    result = []
    for name in servers:
        state = client.get_server_state(name)
        if state:
            result.append(state)

    return {
        "connected_count": len(result),
        "servers": result,
    }


@mcp_router.get("/servers/{server_name}/tools")
def list_mcp_server_tools(
    server_name: str,
    request: Request,
):
    """Lista las tools disponibles en un servidor MCP específico."""
    client = get_mcp_client()

    if not client.is_connected(server_name):
        raise HTTPException(
            status_code=404,
            detail=f"Servidor MCP '{server_name}' no conectado",
        )

    tools = client.list_tools(server_name)
    return {
        "server": server_name,
        "tools_count": len(tools),
        "tools": [
            {
                "name": t.tool_name,
                "description": t.description,
                "input_schema": t.input_schema,
                "full_name": f"mcp_{server_name}__{t.tool_name}",
            }
            for t in tools
        ],
    }


@mcp_router.get("/tools")
def list_all_mcp_tools(request: Request):
    """Lista todas las tools de todos los servidores MCP conectados."""
    client = get_mcp_client()
    tools = client.list_all_tools()

    return {
        "tools_count": len(tools),
        "tools": [
            {
                "server": t.server_name,
                "name": t.tool_name,
                "description": t.description,
                "input_schema": t.input_schema,
                "full_name": f"mcp_{t.server_name}__{t.tool_name}",
            }
            for t in tools
        ],
    }


# ═══════════════════════════════════════════════════════════
# Incluir sub-routers en el router principal
# ═══════════════════════════════════════════════════════════

# Ambos routers se registran por separado en main.py para claridad
