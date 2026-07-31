"""MCP (Model Context Protocol) Client — subprocess management, tool discovery, JSON-RPC.

Arquitectura:
- Lanza servidores MCP como subprocesos independientes.
- Comunicación via JSON-RPC 2.0 sobre stdin/stdout.
- Auto-discovery: escanea .env buscando MCP_SERVER_* para cargar configuraciones.
- Health monitoring: ping periódico con reconexión automática.
- Registro dinámico de tools en ToolRegistry del Agent Runtime.

GOAL 1 + GOAL 2 del Sprint MCP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from app.application.agent.ports import ToolSpec, ToolResult

log = logging.getLogger("dot.mcp")

# ── Constantes MCP ──────────────────────────────────────
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_PING_INTERVAL_SECONDS = 30
MCP_RECONNECT_DELAY_SECONDS = 5
MCP_MAX_RECONNECT_ATTEMPTS = 3
MCP_JSONRPC_VERSION = "2.0"

# ── Servidores MCP pre-configurados ─────────────────────

MCP_SERVER_PRESETS: dict[str, dict[str, Any]] = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "env_var_enabled": "MCP_FILESYSTEM_ENABLED",
        "env_var_dirs": "MCP_FILESYSTEM_ALLOWED_DIRS",
        "description": "Filesystem MCP — read/write/list files with path restrictions",
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_var_enabled": "MCP_GITHUB_ENABLED",
        "env_var_token": "GITHUB_TOKEN",
        "description": "GitHub MCP — issue/PR/repo management (requires GITHUB_TOKEN)",
    },
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env_var_enabled": "MCP_POSTGRES_ENABLED",
        "env_var_url": "MCP_POSTGRES_URL",
        "description": "Postgres MCP — query DOT's own database via SQL",
    },
    "brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_var_enabled": "MCP_BRAVE_ENABLED",
        "env_var_key": "BRAVE_API_KEY",
        "description": "Brave Search MCP — web search (requires BRAVE_API_KEY)",
    },
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env_var_enabled": "MCP_MEMORY_ENABLED",
        "env_var_path": "MCP_MEMORY_PATH",
        "description": "Memory MCP — persistent knowledge graph",
    },
}


@dataclass
class MCPServerConfig:
    """Configuración de un servidor MCP."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


@dataclass
class MCPToolInfo:
    """Metadatos de una tool descubierta de un servidor MCP."""
    server_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerState:
    """Estado runtime de un servidor MCP conectado."""
    config: MCPServerConfig
    process: subprocess.Popen | None = None
    connected: bool = False
    tools: list[MCPToolInfo] = field(default_factory=list)
    last_ping_ok: bool = False
    reconnect_attempts: int = 0
    request_id: int = 0
    _pending_futures: dict[int, asyncio.Future] = field(default_factory=dict)
    _reader_task: asyncio.Task | None = None
    _health_task: asyncio.Task | None = None


class MCPClient:
    """Cliente MCP central — gestiona conexiones, tools y ejecución.

    Singleton por proceso. Usa JSON-RPC 2.0 sobre stdin/stdout de subprocesos.
    """

    def __init__(self):
        self._servers: dict[str, MCPServerState] = {}
        self._registry: Any = None
        self._shutting_down = False

    # ═══════════════════════════════════════════════════════
    # GOAL 1: Conexión y gestión de servidores MCP
    # ═══════════════════════════════════════════════════════

    def set_registry(self, registry: Any) -> None:
        """Vincula el ToolRegistry para registro dinámico de tools MCP."""
        self._registry = registry

    async def connect_to_server(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        """Lanza un servidor MCP como subproceso y establece la conexión JSON-RPC.

        Args:
            server_name: Nombre lógico del servidor (ej: "filesystem").
            command: Comando para lanzar el servidor (ej: "npx").
            args: Argumentos del comando.
            env: Variables de entorno adicionales para el subproceso.

        Returns:
            True si la conexión fue exitosa.
        """
        if server_name in self._servers:
            existing = self._servers[server_name]
            if existing.connected:
                log.info("MCP server '%s' ya conectado, reutilizando", server_name)
                return True
            await self.disconnect_server(server_name)

        config = MCPServerConfig(
            name=server_name,
            command=command,
            args=list(args or []),
            env=dict(env or {}),
        )

        state = MCPServerState(config=config)
        self._servers[server_name] = state

        try:
            await self._launch_process(state)
            await self._handshake(state)
            state.connected = True
            state.reconnect_attempts = 0

            # Iniciar lector de respuestas y health monitor
            state._reader_task = asyncio.create_task(
                self._read_responses(server_name),
                name=f"mcp-reader-{server_name}",
            )
            state._health_task = asyncio.create_task(
                self._health_monitor(server_name),
                name=f"mcp-health-{server_name}",
            )

            # Descubrir tools del servidor
            await self._discover_tools(server_name)

            log.info(
                "MCP server '%s' conectado — %d tools descubiertas",
                server_name,
                len(state.tools),
            )
            return True

        except Exception:
            log.exception("Error conectando MCP server '%s'", server_name)
            await self._cleanup_state(state)
            return False

    async def disconnect_server(self, server_name: str) -> None:
        """Apagado limpio de un servidor MCP."""
        state = self._servers.pop(server_name, None)
        if state is None:
            return

        log.info("Desconectando MCP server '%s'", server_name)
        await self._cleanup_state(state)

    async def disconnect_all(self) -> None:
        """Apaga todos los servidores MCP conectados."""
        self._shutting_down = True
        names = list(self._servers.keys())
        for name in names:
            await self.disconnect_server(name)
        log.info("Todos los servidores MCP desconectados")

    # ═══════════════════════════════════════════════════════
    # GOAL 1: Tool discovery y ejecución
    # ═══════════════════════════════════════════════════════

    def list_tools(self, server_name: str) -> list[MCPToolInfo]:
        """Devuelve las tools descubiertas de un servidor MCP."""
        state = self._servers.get(server_name)
        if state is None or not state.connected:
            return []
        return list(state.tools)

    def list_all_tools(self) -> list[MCPToolInfo]:
        """Devuelve todas las tools de todos los servidores MCP conectados."""
        all_tools: list[MCPToolInfo] = []
        for state in self._servers.values():
            if state.connected:
                all_tools.extend(state.tools)
        return all_tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> ToolResult:
        """Ejecuta una tool via MCP JSON-RPC.

        Args:
            server_name: Nombre del servidor MCP.
            tool_name: Nombre de la tool a ejecutar.
            arguments: Argumentos de la tool.
            timeout: Timeout en segundos para la llamada.

        Returns:
            ToolResult con ok=True y output, o ok=False y error.
        """
        arguments = arguments or {}
        state = self._servers.get(server_name)

        if state is None or not state.connected:
            return ToolResult(
                ok=False,
                output="",
                error=f"Servidor MCP '{server_name}' no conectado",
            )

        if state.process is None or state.process.stdin is None:
            return ToolResult(
                ok=False,
                output="",
                error=f"Servidor MCP '{server_name}' sin proceso activo",
            )

        request_id = state.request_id
        state.request_id += 1

        payload = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            # Enviar request
            request_json = json.dumps(payload) + "\n"
            state.process.stdin.write(request_json)
            state.process.stdin.flush()

            # Esperar respuesta via future
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            state._pending_futures[request_id] = future

            result_data = await asyncio.wait_for(future, timeout=timeout)

            # Extraer contenido
            content = result_data.get("content", [])
            text_output = ""
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        parts.append(item.get("text", str(item)))
                    else:
                        parts.append(str(item))
                text_output = "\n".join(parts)
            elif isinstance(content, str):
                text_output = content
            else:
                text_output = json.dumps(content, ensure_ascii=False)

            return ToolResult(
                ok=True,
                output=text_output,
                duration_ms=0,
            )

        except asyncio.TimeoutError:
            state._pending_futures.pop(request_id, None)
            return ToolResult(
                ok=False,
                output="",
                error=f"Timeout ({timeout}s) ejecutando '{tool_name}' en '{server_name}'",
            )
        except Exception as e:
            state._pending_futures.pop(request_id, None)
            log.exception("Error ejecutando tool MCP '%s/%s'", server_name, tool_name)
            return ToolResult(
                ok=False,
                output="",
                error=f"Error MCP: {e}",
            )

    # ═══════════════════════════════════════════════════════
    # GOAL 1: Auto-discovery desde .env
    # ═══════════════════════════════════════════════════════

    async def auto_discover_and_connect(self) -> list[str]:
        """Escanea .env buscando MCP_SERVER_* patterns y conecta los encontrados.

        Prioriza los 5 presets pre-configurados. También soporta servidores
        custom via MCP_CUSTOM_* variables de entorno.

        Returns:
            Lista de nombres de servidores conectados exitosamente.
        """
        connected: list[str] = []

        # 1. Conectar presets si están habilitados
        for preset_name, preset in MCP_SERVER_PRESETS.items():
            enabled_var = preset["env_var_enabled"]
            enabled = os.getenv(enabled_var, "false").strip().lower() == "true"

            if not enabled:
                log.debug("MCP preset '%s' deshabilitado (%s no es 'true')", preset_name, enabled_var)
                continue

            # Construir args con las variables de entorno específicas
            args = list(preset["args"])

            # Filesystem: agregar directorios permitidos
            if preset_name == "filesystem":
                dirs = os.getenv(preset["env_var_dirs"], "").strip()
                if dirs:
                    for d in dirs.split(","):
                        d = d.strip()
                        if d and os.path.isdir(d):
                            args.append(d)
                if len(args) <= len(preset["args"]):
                    log.warning(
                        "MCP filesystem: %s vacío o sin directorios válidos",
                        preset["env_var_dirs"],
                    )
                    continue

            # GitHub: verificar token
            if preset_name == "github":
                token = os.getenv(preset["env_var_token"], "").strip()
                if not token:
                    log.warning("MCP github: GITHUB_TOKEN no configurado, saltando")
                    continue
                env = {"GITHUB_TOKEN": token}

            # Postgres: verificar URL
            elif preset_name == "postgres":
                db_url = os.getenv(preset["env_var_url"], "").strip()
                if not db_url:
                    log.warning("MCP postgres: MCP_POSTGRES_URL no configurado, saltando")
                    continue
                env = {"DATABASE_URL": db_url}

            # Brave Search: verificar API key
            elif preset_name == "brave-search":
                key = os.getenv(preset["env_var_key"], "").strip()
                if not key:
                    log.warning("MCP brave-search: BRAVE_API_KEY no configurado, saltando")
                    continue
                env = {"BRAVE_API_KEY": key}

            # Memory: configurar path
            elif preset_name == "memory":
                mem_path = os.getenv(preset["env_var_path"], "").strip()
                if mem_path:
                    env = {"MCP_MEMORY_PATH": mem_path}
                else:
                    env = {}

            else:
                env = {}

            ok = await self.connect_to_server(
                preset_name,
                preset["command"],
                args,
                env=env,
            )
            if ok:
                connected.append(preset_name)

        # 2. Servidores custom via MCP_CUSTOM_* vars
        custom_servers = self._discover_custom_servers()
        for custom_name, custom_config in custom_servers.items():
            ok = await self.connect_to_server(
                custom_name,
                custom_config["command"],
                custom_config.get("args", []),
                env=custom_config.get("env", {}),
            )
            if ok:
                connected.append(custom_name)

        log.info(
            "MCP auto-discovery: %d/%d servidores conectados",
            len(connected),
            len(list(MCP_SERVER_PRESETS)) + len(custom_servers),
        )
        return connected

    def _discover_custom_servers(self) -> dict[str, dict[str, Any]]:
        """Descubre servidores MCP custom desde variables MCP_CUSTOM_*_COMMAND."""
        custom: dict[str, dict[str, Any]] = {}
        prefix = "MCP_CUSTOM_"

        for key, value in os.environ.items():
            if not key.startswith(prefix) or not key.endswith("_COMMAND"):
                continue

            # Extraer nombre: MCP_CUSTOM_MYSERVER_COMMAND → myserver
            middle = key[len(prefix):-len("_COMMAND")]
            name = middle.lower()

            command = value.strip()
            if not command:
                continue

            # Buscar args: MCP_CUSTOM_MYSERVER_ARGS
            args_str = os.getenv(f"{prefix}{middle}_ARGS", "").strip()
            args = args_str.split() if args_str else []

            # Buscar env vars: MCP_CUSTOM_MYSERVER_ENV (JSON string)
            env = {}
            env_str = os.getenv(f"{prefix}{middle}_ENV", "").strip()
            if env_str:
                try:
                    env = json.loads(env_str)
                except json.JSONDecodeError:
                    log.warning("MCP custom '%s': ENV JSON inválido", name)

            custom[name] = {
                "command": command,
                "args": args,
                "env": env,
            }

        if custom:
            log.info("MCP custom servers descubiertos: %s", list(custom.keys()))
        return custom

    # ═══════════════════════════════════════════════════════
    # GOAL 2: Registro dinámico en ToolRegistry
    # ═══════════════════════════════════════════════════════

    def register_tools_in_registry(self, server_name: str) -> int:
        """Registra las tools de un servidor MCP en el ToolRegistry global.

        Las tools MCP aparecen con prefijo 'mcp_{server_name}__' para
        evitar colisiones con tools nativas.

        Returns:
            Número de tools registradas.
        """
        if self._registry is None:
            log.warning("ToolRegistry no vinculado; no se pueden registrar tools MCP")
            return 0

        tools = self.list_tools(server_name)
        registered = 0

        for tool in tools:
            prefixed_name = f"mcp_{server_name}__{tool.tool_name}"
            full_desc = f"[MCP:{server_name}] {tool.description}"

            spec = ToolSpec(
                name=prefixed_name,
                description=full_desc,
                parameters_schema=tool.input_schema,
            )

            # Handler que delega a call_tool
            def make_handler(srv: str, tn: str):
                def handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
                    # Ejecución síncrona: usa asyncio.run en un hilo
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                future = pool.submit(
                                    asyncio.run,
                                    self.call_tool(srv, tn, arguments),
                                )
                                return future.result(timeout=90)
                        else:
                            return asyncio.run(self.call_tool(srv, tn, arguments))
                    except Exception as e:
                        return ToolResult(
                            ok=False,
                            output="",
                            error=f"Error MCP handler: {e}",
                        )
                return handler

            self._registry.register(spec, make_handler(server_name, tool.tool_name))
            registered += 1

        if registered:
            log.info(
                "MCP: %d tools de '%s' registradas en ToolRegistry",
                registered,
                server_name,
            )
        return registered

    def register_all_tools_in_registry(self) -> int:
        """Registra todas las tools de todos los servidores MCP conectados."""
        total = 0
        for name in list(self._servers.keys()):
            total += self.register_tools_in_registry(name)
        return total

    # ═══════════════════════════════════════════════════════
    # GOAL 1: Health monitoring
    # ═══════════════════════════════════════════════════════

    async def ping_server(self, server_name: str) -> bool:
        """Envía un ping JSON-RPC al servidor MCP."""
        state = self._servers.get(server_name)
        if state is None or not state.connected:
            return False

        if state.process is None or state.process.stdin is None:
            return False

        try:
            request_id = state.request_id
            state.request_id += 1

            payload = {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "method": "ping",
                "params": {},
            }

            request_json = json.dumps(payload) + "\n"
            state.process.stdin.write(request_json)
            state.process.stdin.flush()

            future: asyncio.Future = asyncio.get_event_loop().create_future()
            state._pending_futures[request_id] = future

            await asyncio.wait_for(future, timeout=10.0)
            state.last_ping_ok = True
            return True

        except Exception:
            state.last_ping_ok = False
            return False

    async def _health_monitor(self, server_name: str) -> None:
        """Monitorea la salud del servidor MCP y reconecta si falla."""
        state = self._servers.get(server_name)
        if state is None:
            return

        while not self._shutting_down and state.connected:
            await asyncio.sleep(MCP_PING_INTERVAL_SECONDS)

            if self._shutting_down:
                break

            ok = await self.ping_server(server_name)
            if not ok:
                log.warning(
                    "MCP health: ping falló para '%s', intento %d/%d",
                    server_name,
                    state.reconnect_attempts + 1,
                    MCP_MAX_RECONNECT_ATTEMPTS,
                )

                if state.reconnect_attempts < MCP_MAX_RECONNECT_ATTEMPTS:
                    state.reconnect_attempts += 1
                    await self._reconnect_server(server_name)
                else:
                    log.error(
                        "MCP health: '%s' agotó reintentos (%d), desconectando",
                        server_name,
                        MCP_MAX_RECONNECT_ATTEMPTS,
                    )
                    await self._cleanup_state(state)
                    state.connected = False
                    break

    async def _reconnect_server(self, server_name: str) -> None:
        """Intenta reconectar un servidor MCP que falló."""
        state = self._servers.get(server_name)
        if state is None:
            return

        log.info("MCP: reintentando conexión a '%s' en %ds...", server_name, MCP_RECONNECT_DELAY_SECONDS)
        await asyncio.sleep(MCP_RECONNECT_DELAY_SECONDS)

        # Limpiar estado anterior
        await self._cleanup_process(state)

        try:
            await self._launch_process(state)
            await self._handshake(state)
            state.connected = True
            state.reconnect_attempts = 0

            # Reiniciar tareas
            state._reader_task = asyncio.create_task(
                self._read_responses(server_name),
                name=f"mcp-reader-{server_name}",
            )
            state._health_task = asyncio.create_task(
                self._health_monitor(server_name),
                name=f"mcp-health-{server_name}",
            )

            # Re-descubrir tools
            await self._discover_tools(server_name)
            self.register_tools_in_registry(server_name)

            log.info("MCP: reconexión exitosa a '%s'", server_name)

        except Exception:
            log.exception("MCP: reconexión fallida para '%s'", server_name)

    # ═══════════════════════════════════════════════════════
    # GOAL 1: Getters de estado
    # ═══════════════════════════════════════════════════════

    def get_connected_servers(self) -> list[str]:
        """Lista los nombres de servidores MCP conectados."""
        return [name for name, state in self._servers.items() if state.connected]

    def is_connected(self, server_name: str) -> bool:
        """Verifica si un servidor MCP está conectado."""
        state = self._servers.get(server_name)
        return state is not None and state.connected

    def get_server_state(self, server_name: str) -> dict[str, Any] | None:
        """Devuelve el estado detallado de un servidor MCP."""
        state = self._servers.get(server_name)
        if state is None:
            return None
        return {
            "name": state.config.name,
            "connected": state.connected,
            "command": state.config.command,
            "args": state.config.args,
            "tools_count": len(state.tools),
            "last_ping_ok": state.last_ping_ok,
            "reconnect_attempts": state.reconnect_attempts,
            "description": state.config.description,
        }

    # ═══════════════════════════════════════════════════════
    # Internals — JSON-RPC sobre stdin/stdout
    # ═══════════════════════════════════════════════════════

    async def _launch_process(self, state: MCPServerState) -> None:
        """Lanza el subproceso del servidor MCP."""
        env = os.environ.copy()
        env.update(state.config.env)
        # Evitar que herede PYTHONPATH u otras vars que interfieran
        env.pop("PYTHONPATH", None)

        # En Windows, usar shell=True para npx
        use_shell = sys.platform == "win32"

        state.process = subprocess.Popen(
            [state.config.command] + state.config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            shell=use_shell,
            bufsize=1,
        )

        log.debug(
            "MCP process lanzado: %s %s (pid=%s)",
            state.config.command,
            " ".join(state.config.args),
            state.process.pid,
        )

    async def _handshake(self, state: MCPServerState) -> None:
        """Handshake JSON-RPC: initialize → initialized.

        Envía:
        {"jsonrpc":"2.0","id":0,"method":"initialize","params":{...}}

        Espera respuesta con server capabilities.
        Luego envía "notifications/initialized".
        """
        if state.process is None or state.process.stdin is None:
            raise RuntimeError("Proceso no iniciado")

        init_request = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": state.request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "DOT-MCP-Client",
                    "version": "1.0.0",
                },
            },
        }

        request_json = json.dumps(init_request) + "\n"
        state.process.stdin.write(request_json)
        state.process.stdin.flush()

        # Leer respuesta del handshake
        if state.process.stdout is None:
            raise RuntimeError("stdout no disponible")

        line = await asyncio.get_event_loop().run_in_executor(
            None, state.process.stdout.readline,
        )

        if not line:
            raise RuntimeError("Servidor MCP no respondió al handshake")

        response = json.loads(line)

        if "error" in response:
            error_msg = response.get("error", {}).get("message", "Error desconocido")
            raise RuntimeError(f"Handshake MCP falló: {error_msg}")

        log.debug("MCP handshake OK para '%s': %s", state.config.name, response.get("result", {}).get("serverInfo", {}))

        # Enviar notificación "initialized"
        initialized = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "method": "notifications/initialized",
            "params": {},
        }
        state.process.stdin.write(json.dumps(initialized) + "\n")
        state.process.stdin.flush()

    async def _discover_tools(self, server_name: str) -> None:
        """Descubre tools via tools/list JSON-RPC."""
        state = self._servers.get(server_name)
        if state is None or state.process is None or state.process.stdin is None:
            return

        request_id = state.request_id
        state.request_id += 1

        payload = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "method": "tools/list",
            "params": {},
        }

        request_json = json.dumps(payload) + "\n"
        state.process.stdin.write(request_json)
        state.process.stdin.flush()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        state._pending_futures[request_id] = future

        try:
            result_data = await asyncio.wait_for(future, timeout=15.0)
            tools_raw = result_data.get("tools", [])

            state.tools = []
            for tool_data in tools_raw:
                tool_info = MCPToolInfo(
                    server_name=server_name,
                    tool_name=tool_data.get("name", "unknown"),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                )
                state.tools.append(tool_info)

        except asyncio.TimeoutError:
            log.warning("Timeout descubriendo tools de '%s'", server_name)
            state._pending_futures.pop(request_id, None)
        except Exception:
            log.exception("Error descubriendo tools de '%s'", server_name)
            state._pending_futures.pop(request_id, None)

    async def _read_responses(self, server_name: str) -> None:
        """Lee respuestas JSON-RPC del stdout del subproceso y resuelve futures."""
        state = self._servers.get(server_name)
        if state is None:
            return

        while state.connected and not self._shutting_down:
            if state.process is None or state.process.stdout is None:
                await asyncio.sleep(0.1)
                continue

            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, state.process.stdout.readline,
                )

                if not line:
                    # EOF — el proceso murió
                    log.warning("MCP '%s': EOF en stdout, proceso terminó", server_name)
                    state.connected = False
                    break

                line = line.strip()
                if not line:
                    continue

                response = json.loads(line)
                req_id = response.get("id")

                if req_id is not None:
                    future = state._pending_futures.pop(req_id, None)
                    if future is not None and not future.done():
                        if "error" in response:
                            future.set_exception(
                                RuntimeError(
                                    response["error"].get("message", "MCP error")
                                )
                            )
                        else:
                            future.set_result(response.get("result", {}))

                # Notificaciones (sin id) — las ignoramos por ahora

            except asyncio.CancelledError:
                break
            except Exception:
                if state.connected:
                    log.debug("Error leyendo respuesta MCP de '%s'", server_name, exc_info=True)
                await asyncio.sleep(0.05)

    async def _cleanup_state(self, state: MCPServerState) -> None:
        """Limpia todos los recursos de un estado de servidor."""
        state.connected = False

        # Cancelar tareas
        for task_attr in ("_reader_task", "_health_task"):
            task = getattr(state, task_attr, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Resolver futures pendientes con error
        for req_id, future in state._pending_futures.items():
            if not future.done():
                future.set_exception(
                    RuntimeError("Servidor MCP desconectado")
                )
        state._pending_futures.clear()

        await self._cleanup_process(state)

    async def _cleanup_process(self, state: MCPServerState) -> None:
        """Termina el subproceso del servidor MCP."""
        if state.process is None:
            return

        try:
            if state.process.stdin:
                state.process.stdin.close()
        except Exception:
            pass

        try:
            state.process.terminate()
            try:
                state.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                state.process.kill()
                state.process.wait(timeout=3)
        except Exception:
            try:
                state.process.kill()
            except Exception:
                pass

        state.process = None


# ── Singleton ───────────────────────────────────────────

_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """Devuelve el singleton MCPClient."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


async def init_mcp(registry: Any | None = None) -> MCPClient:
    """Inicializa el cliente MCP con auto-discovery y registro de tools.

    Llamar desde lifespan de FastAPI. Conecta todos los servidores
    MCP configurados en .env y registra sus tools en el ToolRegistry.
    """
    client = get_mcp_client()

    if registry is not None:
        client.set_registry(registry)

    connected = await client.auto_discover_and_connect()

    if connected:
        total_tools = client.register_all_tools_in_registry()
        log.info("MCP inicializado: %d servidores, %d tools totales", len(connected), total_tools)
    else:
        log.info("MCP inicializado: sin servidores configurados")

    return client


async def shutdown_mcp() -> None:
    """Apaga todos los servidores MCP. Llamar desde lifespan shutdown."""
    client = get_mcp_client()
    await client.disconnect_all()
