"""DOT as MCP Server — expone el ToolRegistry como servidor MCP.

Transportes:
- stdio: stdin/stdout JSON-RPC (para Claude Desktop, Cursor, etc.)
- SSE: Server-Sent Events via HTTP (para clientes web)

Protocolo MCP 2024-11-05:
- tools/list → lista tools de DOT desde ToolRegistry
- tools/call → ejecuta una tool via ToolRegistry.execute()
- resources/list, prompts/list → stubs (extensible)
- initialize, ping → lifecycle MCP
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from app.application.agent.ports import ToolSpec, ToolResult

log = logging.getLogger("dot.mcp.server")

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_JSONRPC_VERSION = "2.0"
MCP_SERVER_NAME = "DOT"
MCP_SERVER_VERSION = "1.0.0"

# ── Tipos internos ──────────────────────────────────────


@dataclass
class _PendingRequest:
    future: asyncio.Future
    created_at: float = field(default_factory=time.monotonic)


# ── Conversión de ToolSpec a schema MCP ─────────────────


def _tool_spec_to_mcp_schema(spec: ToolSpec) -> dict[str, Any]:
    """Convierte un ToolSpec de DOT a schema MCP tools/list."""
    schema: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
    }
    if spec.parameters_schema:
        schema["inputSchema"] = {
            "type": "object",
            "properties": spec.parameters_schema,
            "required": list(spec.parameters_schema.keys()),
        }
    return schema


# ── MCPServer ───────────────────────────────────────────


class MCPServer:
    """Servidor MCP que expone DOT's ToolRegistry como tools MCP.

    Soporta transporte stdio (stdin/stdout) y SSE (HTTP streaming).
    """

    def __init__(self, registry: Any = None, uid: str = "mcp-anonymous") -> None:
        self.registry = registry
        self.uid = uid
        self._stdio_running = False
        self._request_id = 0
        self._pending: dict[int, _PendingRequest] = {}
        self._sse_clients: list[asyncio.Queue] = []

    # ═══════════════════════════════════════════════════════
    # Transporte stdio
    # ═══════════════════════════════════════════════════════

    async def serve_stdio(self) -> None:
        """Ejecuta el servidor MCP via stdin/stdout JSON-RPC.

        Lee líneas de stdin, procesa mensajes JSON-RPC, escribe respuestas a stdout.
        Bloquea hasta que stdin se cierra o recibe shutdown.
        """
        self._stdio_running = True
        log.info("MCP Server stdio iniciado en stdin/stdout")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            lambda: asyncio.streams.FlowControlMixin(loop=asyncio.get_event_loop()),
            sys.stdout,
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        while self._stdio_running:
            try:
                line = await reader.readline()
            except Exception:
                break

            if not line:
                # EOF
                break

            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as exc:
                log.warning("MCP Server stdio: JSON inválido: %s", exc)
                error_response = {
                    "jsonrpc": MCP_JSONRPC_VERSION,
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
                writer.write((json.dumps(error_response) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            response = await self._handle_jsonrpc(request)
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()

        log.info("MCP Server stdio detenido")

    def stop_stdio(self) -> None:
        """Detiene el loop stdio."""
        self._stdio_running = False

    # ═══════════════════════════════════════════════════════
    # Transporte SSE (para HTTP)
    # ═══════════════════════════════════════════════════════

    async def serve_sse_client(self, queue: asyncio.Queue) -> None:
        """Registra un cliente SSE y lo mantiene hasta que se desconecta."""
        self._sse_clients.append(queue)
        try:
            # Enviar evento de conexión
            await queue.put({
                "event": "connected",
                "data": json.dumps({"server": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION}),
            })
            # Mantener vivo hasta que el cliente se vaya
            while True:
                await asyncio.sleep(30)
                await queue.put({"event": "ping", "data": "{}"})
        except asyncio.CancelledError:
            pass
        finally:
            self._sse_clients.remove(queue)

    async def handle_sse_message(self, raw_body: bytes) -> dict[str, Any]:
        """Procesa un mensaje JSON-RPC recibido via SSE POST."""
        try:
            request = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }

        return await self._handle_jsonrpc(request)

    # ═══════════════════════════════════════════════════════
    # JSON-RPC message handler
    # ═══════════════════════════════════════════════════════

    async def _handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        """Maneja un mensaje JSON-RPC 2.0.

        Soporta:
        - initialize → capabilities del servidor
        - ping → health check
        - tools/list → lista tools DOT
        - tools/call → ejecuta tool via ToolRegistry
        - resources/list → stub
        - prompts/list → stub
        """
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = await self._handle_tools_call(params)
            elif method == "resources/list":
                result = self._handle_resources_list()
            elif method == "prompts/list":
                result = self._handle_prompts_list()
            else:
                return {
                    "jsonrpc": MCP_JSONRPC_VERSION,
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            return {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": req_id,
                "result": result,
            }

        except Exception as exc:
            log.exception("MCP Server error procesando %s", method)
            return {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }

    # ── Handlers ──────────────────────────────────────────

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handshake MCP initialize."""
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            },
        }

    def _handle_tools_list(self) -> dict[str, Any]:
        """Lista todas las tools de DOT registradas en ToolRegistry."""
        if self.registry is None:
            return {"tools": []}

        specs = self.registry.list_specs()
        tools = [_tool_spec_to_mcp_schema(s) for s in specs]
        log.debug("MCP Server tools/list: %d tools expuestas", len(tools))
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una tool via ToolRegistry."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            return {
                "content": [{"type": "text", "text": "Error: tool name vacío"}],
                "isError": True,
            }

        if self.registry is None:
            return {
                "content": [{"type": "text", "text": "Error: ToolRegistry no configurado"}],
                "isError": True,
            }

        if not self.registry.has(tool_name):
            return {
                "content": [{"type": "text", "text": f"Tool no encontrada: {tool_name}"}],
                "isError": True,
            }

        # Ejecutar en thread pool para no bloquear el event loop
        loop = asyncio.get_event_loop()
        result: ToolResult = await loop.run_in_executor(
            None,
            self.registry.execute,
            self.uid,
            tool_name,
            arguments,
        )

        content = []
        if result.ok and result.output:
            content.append({"type": "text", "text": result.output})
        if result.error:
            content.append({"type": "text", "text": f"Error: {result.error}"})

        # Artifacts como recursos adicionales
        for artifact in result.artifacts or []:
            if isinstance(artifact, dict):
                mime = artifact.get("mime", "application/octet-stream")
                if mime.startswith("image/"):
                    content.append({
                        "type": "image",
                        "data": artifact.get("data", ""),
                        "mimeType": mime,
                    })
                elif mime.startswith("text/"):
                    content.append({
                        "type": "text",
                        "text": artifact.get("content", artifact.get("text", str(artifact))),
                    })

        return {
            "content": content,
            "isError": not result.ok,
            "duration_ms": result.duration_ms,
        }

    def _handle_resources_list(self) -> dict[str, Any]:
        """Stub: lista recursos MCP (extensible)."""
        return {"resources": []}

    def _handle_prompts_list(self) -> dict[str, Any]:
        """Stub: lista prompts MCP (extensible)."""
        return {"prompts": []}

    # ═══════════════════════════════════════════════════════
    # Well-known discovery
    # ═══════════════════════════════════════════════════════

    def well_known(self) -> dict[str, Any]:
        """Devuelve las capabilities del servidor MCP para discovery."""
        tool_count = len(self.registry.list_specs()) if self.registry else 0
        return {
            "server": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "capabilities": ["tools", "resources", "prompts"],
            "transports": ["stdio", "sse"],
            "tools_count": tool_count,
            "endpoints": {
                "sse": "/v1/mcp/sse",
                "message": "/v1/mcp/message",
                "well_known": "/v1/mcp/.well-known",
            },
        }


# ── Singleton ───────────────────────────────────────────

_mcp_server: MCPServer | None = None


def get_mcp_server() -> MCPServer:
    """Devuelve el singleton MCPServer."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
    return _mcp_server


def init_mcp_server(registry: Any, uid: str = "mcp-anonymous") -> MCPServer:
    """Inicializa el servidor MCP con el ToolRegistry de DOT."""
    global _mcp_server
    _mcp_server = MCPServer(registry=registry, uid=uid)
    log.info("MCP Server inicializado con ToolRegistry (%d tools)", len(registry.list_specs()) if registry else 0)
    return _mcp_server


# ── Entry point para stdio standalone ────────────────────


def serve() -> None:
    """Entry point para ejecutar el servidor MCP via stdio.

    Usar en mcp.json de Claude Desktop / Cursor:
    {
      "mcpServers": {
        "dot": {
          "command": "python",
          "args": ["-m", "app.services.mcp_server"]
        }
      }
    }
    """
    from app.application.agent.tools import build_default_registry

    registry = build_default_registry(
        uid="mcp-standalone",
        enable_browser=False,
        require_db=False,
    )
    server = MCPServer(registry=registry, uid="mcp-standalone")
    asyncio.run(server.serve_stdio())


if __name__ == "__main__":
    serve()
