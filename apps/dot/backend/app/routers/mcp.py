"""Router HTTP para MCP Server — expone DOT como servidor MCP.

Endpoints:
- GET  /v1/mcp/.well-known  → server capabilities
- POST /v1/mcp/message       → JSON-RPC message handler
- GET  /v1/mcp/sse           → SSE transport (streaming)

Gate: MCP_SERVER_ENABLED (default false). Si está deshabilitado,
todos los endpoints retornan 503.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.services.mcp_server import get_mcp_server, init_mcp_server
from app.settings import settings

router = APIRouter(prefix="/v1/mcp", tags=["mcp-server"])
log = logging.getLogger("dot.mcp.router")


def _check_enabled() -> None:
    """Verifica que MCP_SERVER_ENABLED esté activo."""
    if not settings.mcp_server_enabled:
        raise HTTPException(
            status_code=503,
            detail="MCP Server deshabilitado (MCP_SERVER_ENABLED=false). "
                   "Activar en .env para exponer DOT como servidor MCP.",
        )


def _ensure_initialized() -> None:
    """Asegura que el MCPServer esté inicializado con ToolRegistry."""
    server = get_mcp_server()
    if server.registry is None:
        # Inicialización lazy: si el lifespan no lo hizo, inicializar aquí
        from app.application.agent.tools import build_default_registry

        registry = build_default_registry(
            uid="mcp-http",
            enable_browser=False,
            require_db=False,
        )
        init_mcp_server(registry, uid="mcp-http")


# ── Endpoints ────────────────────────────────────────────


@router.get("/.well-known")
def mcp_well_known():
    """Devuelve las capabilities del servidor MCP para discovery automático."""
    _check_enabled()
    _ensure_initialized()
    server = get_mcp_server()
    return server.well_known()


@router.post("/message")
async def mcp_message(request: Request):
    """JSON-RPC 2.0 message handler.

    Recibe un mensaje JSON-RPC en el body y devuelve la respuesta.
    Soporta: initialize, ping, tools/list, tools/call.
    """
    _check_enabled()
    _ensure_initialized()
    server = get_mcp_server()

    raw_body = await request.body()
    response = await server.handle_sse_message(raw_body)
    return response


@router.get("/sse")
async def mcp_sse(request: Request):
    """SSE transport para MCP.

    Establece una conexión SSE para recibir eventos del servidor MCP.
    Los mensajes JSON-RPC se envían via POST /v1/mcp/message.
    """
    _check_enabled()
    _ensure_initialized()
    server = get_mcp_server()

    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        server_task = asyncio.create_task(server.serve_sse_client(queue))

        try:
            while True:
                # Check disconnect
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    event_type = event.get("event", "message")
                    data = event.get("data", "{}")
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Enviar keepalive comment
                    yield ": keepalive\n\n"
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
