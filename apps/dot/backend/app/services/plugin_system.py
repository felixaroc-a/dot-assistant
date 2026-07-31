"""Plugin System — gestor de plugins al estilo OpenClaw's ClawHub.

Permite cargar, descargar, recargar y listar plugins de terceros que extienden
las herramientas del Agent Runtime sin tocar el core de DOT.

Cada plugin es un directorio con:
  - plugin.yaml  (manifiesto: nombre, versión, tools, dependencias)
  - main.py      (código del plugin con funciones @plugin_tool)
  - requirements.txt (opcional)
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.application.agent.ports import ToolSpec
from app.application.agent.registry import ToolRegistry
from app.plugin_sdk import PluginToolMeta, discover_plugin_tools

log = logging.getLogger("dot.plugins")


# ── Modelos ────────────────────────────────────────────────────────


@dataclass
class PluginManifest:
    """Manifiesto parseado de plugin.yaml."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "General"
    tags: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    marketplace_url: str = ""
    min_dot_version: str = "1.0.0"


@dataclass
class PluginInfo:
    """Información pública de un plugin instalado."""

    name: str
    version: str
    description: str
    author: str
    category: str
    tags: list[str]
    tools: list[str]
    dependencies: list[str]
    path: str
    loaded: bool
    error: str | None = None


# ── Manager ─────────────────────────────────────────────────────────


class PluginManager:
    """Gestor de plugins: carga, descarga, recarga y hot-reload.

    Se instancia al arranque y se guarda en app.state.plugin_manager.
    Acepta un ToolRegistry opcional donde auto-registrar las tools
    descubiertas en los plugins.
    """

    def __init__(
        self,
        plugins_dir: str | Path,
        registry: ToolRegistry | None = None,
        hot_reload: bool = False,
    ) -> None:
        self._plugins_dir = Path(plugins_dir).resolve()
        self._registry = registry
        self._hot_reload = hot_reload
        self._plugins: dict[str, PluginInfo] = {}
        self._manifest_cache: dict[str, PluginManifest] = {}
        # Mapeo tool_name → plugin_name para desregistrar al descargar
        self._tool_to_plugin: dict[str, str] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._lock = threading.Lock()
        self._enabled = True

    # ── Propiedades ─────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    # ── Registro / carga ────────────────────────────────────────────

    def register_plugin(self, manifest_path: str | Path) -> PluginInfo | None:
        """Valida y carga un plugin desde su plugin.yaml.

        Retorna PluginInfo si se cargó OK, None si el manifiesto es inválido.
        Lanza excepción si el plugin ya estaba cargado o hay conflicto.
        """
        if not self._enabled:
            log.warning("PluginManager deshabilitado; ignorando register_plugin")
            return None

        manifest_path = Path(manifest_path).resolve()
        manifest = self._parse_manifest(manifest_path)

        # Validar unicidad
        if manifest.name in self._plugins:
            existing = self._plugins[manifest.name]
            if existing.loaded:
                raise ValueError(
                    f"Plugin '{manifest.name}' ya está cargado (v{existing.version}). "
                    "Use reload para actualizarlo."
                )
            raise ValueError(
                f"Plugin '{manifest.name}' ya existe pero está en estado de error. "
                "Elimínelo primero."
            )

        # Validar dependencias
        missing_deps = self._check_dependencies(manifest)
        if missing_deps:
            raise ValueError(
                f"Plugin '{manifest.name}' requiere dependencias no satisfechas: "
                f"{', '.join(missing_deps)}"
            )

        # Cargar código del plugin
        plugin_dir = manifest_path.parent
        module = self._load_module(plugin_dir)

        # Descubrir tools decoradas con @plugin_tool
        plugin_tools = discover_plugin_tools(module)

        # Registrar en ToolRegistry
        tool_names: list[str] = []
        if self._registry is not None:
            for tool_meta in plugin_tools:
                if not tool_meta.handler:
                    log.warning(
                        "Tool '%s' en plugin '%s' no tiene handler, omitiendo",
                        tool_meta.name, manifest.name,
                    )
                    continue
                # Verificar que no colisione con otra tool
                if self._registry.has(tool_meta.name):
                    raise ValueError(
                        f"Conflicto: la tool '{tool_meta.name}' del plugin "
                        f"'{manifest.name}' ya existe en el ToolRegistry."
                    )
                spec = ToolSpec(
                    name=tool_meta.name,
                    description=tool_meta.description or f"Plugin: {manifest.name}",
                    parameters_schema=tool_meta.parameters_schema,
                )
                self._registry.register(spec, tool_meta.handler)
                log.info(
                    "Tool '%s' (plugin '%s') registrada en ToolRegistry",
                    tool_meta.name, manifest.name,
                )
                tool_names.append(tool_meta.name)

        # Guardar estado
        info = PluginInfo(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            category=manifest.category,
            tags=manifest.tags,
            tools=tool_names,
            dependencies=manifest.dependencies,
            path=str(plugin_dir),
            loaded=True,
        )
        with self._lock:
            self._plugins[manifest.name] = info
            self._manifest_cache[manifest.name] = manifest
            for t in tool_names:
                self._tool_to_plugin[t] = manifest.name

        log.info(
            "Plugin '%s' v%s cargado con %d tools",
            manifest.name, manifest.version, len(tool_names),
        )
        return info

    def unregister_plugin(self, plugin_name: str) -> bool:
        """Descarga un plugin y elimina sus tools del ToolRegistry.

        Retorna True si el plugin estaba cargado, False si no existía.
        """
        plugin_name = plugin_name.strip()
        with self._lock:
            info = self._plugins.get(plugin_name)
            if info is None:
                log.warning("Plugin '%s' no encontrado para descargar", plugin_name)
                return False

            # Desregistrar tools del ToolRegistry
            if self._registry is not None:
                for tool_name in info.tools:
                    self._registry.unregister(tool_name)
                    self._tool_to_plugin.pop(tool_name, None)
                    log.info(
                        "Tool '%s' (plugin '%s') eliminada del ToolRegistry",
                        tool_name, plugin_name,
                    )

            del self._plugins[plugin_name]
            self._manifest_cache.pop(plugin_name, None)

        log.info("Plugin '%s' descargado exitosamente", plugin_name)
        return True

    def reload_plugin(self, plugin_name: str) -> PluginInfo:
        """Recarga un plugin (útil durante desarrollo y hot-reload).

        Busca el plugin.yaml en el path original y lo vuelve a cargar.
        """
        with self._lock:
            info = self._plugins.get(plugin_name)
            if info is None:
                raise ValueError(f"Plugin '{plugin_name}' no encontrado.")

            plugin_dir = Path(info.path)
            manifest_path = plugin_dir / "plugin.yaml"
            if not manifest_path.is_file():
                raise FileNotFoundError(
                    f"plugin.yaml no encontrado en {plugin_dir}"
                )

        # Descargar y volver a cargar
        self.unregister_plugin(plugin_name)
        return self.register_plugin(manifest_path)

    def load_all_from_directory(self, directory: str | Path | None = None) -> int:
        """Carga todos los plugins de un directorio recursivamente.

        Retorna el número de plugins cargados exitosamente.
        """
        directory = Path(directory or self._plugins_dir).resolve()
        if not directory.is_dir():
            log.warning("Directorio de plugins no existe: %s", directory)
            return 0

        count = 0
        for yaml_file in sorted(directory.rglob("plugin.yaml")):
            if "__pycache__" in str(yaml_file):
                continue
            try:
                self.register_plugin(yaml_file)
                count += 1
            except Exception as e:
                log.warning(
                    "Error cargando plugin %s: %s",
                    yaml_file.parent.name, e,
                )
                # Registrar como error
                plugin_dir = yaml_file.parent
                try:
                    manifest = self._parse_manifest(yaml_file)
                    name = manifest.name
                except Exception:
                    name = plugin_dir.name
                with self._lock:
                    self._plugins[name] = PluginInfo(
                        name=name,
                        version="?",
                        description="",
                        author="",
                        category="Error",
                        tags=[],
                        tools=[],
                        dependencies=[],
                        path=str(plugin_dir),
                        loaded=False,
                        error=str(e),
                    )

        log.info("Cargados %d plugins desde %s", count, directory)
        return count

    def list_plugins(self) -> list[PluginInfo]:
        """Lista todos los plugins (cargados o con error)."""
        with self._lock:
            return list(self._plugins.values())

    def get_plugin(self, name: str) -> PluginInfo | None:
        """Obtiene info de un plugin por nombre."""
        with self._lock:
            return self._plugins.get(name.strip())

    # ── Hot-reload ───────────────────────────────────────────────────

    async def start_hot_reload(self) -> None:
        """Inicia el watcher de directorio para recarga automática de plugins."""
        if not self._hot_reload:
            return
        self._watchdog_task = asyncio.create_task(
            self._watch_loop(),
            name="plugin-hot-reload",
        )
        log.info("Plugin hot-reload iniciado en %s", self._plugins_dir)

    async def stop_hot_reload(self) -> None:
        """Detiene el watcher de hot-reload."""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        log.info("Plugin hot-reload detenido")

    async def _watch_loop(self, interval: float = 5.0) -> None:
        """Loop de polling: detecta cambios en el directorio de plugins.

        Estrategia simple sin dependencia externa (watchdog). Cada `interval`
        segundos escanea el directorio y recarga plugins cuyo plugin.yaml
        haya cambiado (mtime).
        """
        known_mtimes: dict[str, float] = {}

        # Escaneo inicial
        self._scan_known_mtimes(known_mtimes)

        while True:
            try:
                await asyncio.sleep(interval)
                current_mtimes: dict[str, float] = {}
                self._scan_known_mtimes(current_mtimes)

                # Detectar cambios
                for plugin_dir_str, mtime in current_mtimes.items():
                    old_mtime = known_mtimes.get(plugin_dir_str)
                    if old_mtime is not None and mtime > old_mtime:
                        plugin_dir = Path(plugin_dir_str)
                        plugin_name = plugin_dir.name
                        log.info(
                            "Hot-reload detectado: %s (mtime %.2f → %.2f)",
                            plugin_name, old_mtime, mtime,
                        )
                        try:
                            self.reload_plugin(plugin_name)
                        except Exception as e:
                            log.error(
                                "Error en hot-reload de %s: %s",
                                plugin_name, e,
                            )

                # Detectar plugins nuevos
                for plugin_dir_str in set(current_mtimes) - set(known_mtimes):
                    try:
                        yaml_path = Path(plugin_dir_str) / "plugin.yaml"
                        self.register_plugin(yaml_path)
                    except Exception as e:
                        log.warning(
                            "Error cargando plugin nuevo %s: %s",
                            plugin_dir_str, e,
                        )

                # Detectar plugins eliminados
                for plugin_dir_str in set(known_mtimes) - set(current_mtimes):
                    plugin_name = Path(plugin_dir_str).name
                    log.info(
                        "Plugin eliminado detectado: %s", plugin_name,
                    )
                    self.unregister_plugin(plugin_name)

                known_mtimes = current_mtimes

            except asyncio.CancelledError:
                break
            except Exception:
                log.warning("Error en watch loop:", exc_info=True)

    def _scan_known_mtimes(self, out: dict[str, float]) -> None:
        """Escanea plugin.yaml en el directorio y llena out con {dir_str: mtime}."""
        if not self._plugins_dir.is_dir():
            return
        for yaml_file in self._plugins_dir.rglob("plugin.yaml"):
            if "__pycache__" in str(yaml_file):
                continue
            plugin_dir = yaml_file.parent
            out[str(plugin_dir)] = yaml_file.stat().st_mtime

    # ── Helpers ──────────────────────────────────────────────────────

    def _parse_manifest(self, yaml_path: Path | str) -> PluginManifest:
        """Lee y valida un plugin.yaml."""
        yaml_path = Path(yaml_path)
        if not yaml_path.is_file():
            raise FileNotFoundError(f"plugin.yaml no encontrado: {yaml_path}")

        try:
            raw = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Error parseando {yaml_path}: {e}")

        if not isinstance(data, dict):
            raise ValueError(f"{yaml_path} no contiene un mapping YAML válido")

        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError(f"plugin.yaml sin 'name' en {yaml_path}")

        version = str(data.get("version", "0.0.0")).strip()
        description = str(data.get("description", "")).strip()
        author = str(data.get("author", "")).strip()
        category = str(data.get("category", "General")).strip()
        tags = [str(t).strip() for t in data.get("tags", []) if t]
        tools = [str(t).strip() for t in data.get("tools", []) if t]
        dependencies = [str(d).strip() for d in data.get("dependencies", []) if d]
        marketplace_url = str(data.get("marketplace_url", "")).strip()
        min_dot_version = str(data.get("min_dot_version", "1.0.0")).strip()

        return PluginManifest(
            name=name,
            version=version,
            description=description,
            author=author,
            category=category,
            tags=tags,
            tools=tools,
            dependencies=dependencies,
            marketplace_url=marketplace_url,
            min_dot_version=min_dot_version,
        )

    def _check_dependencies(self, manifest: PluginManifest) -> list[str]:
        """Verifica que las dependencias de otros plugins estén cargadas."""
        missing: list[str] = []
        for dep in manifest.dependencies:
            dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
            if dep_name not in self._plugins:
                missing.append(dep)
        return missing

    def _load_module(self, plugin_dir: Path):
        """Importa main.py de un directorio de plugin como módulo Python.

        Usa importlib para cargar el módulo de forma aislada y fresh en cada carga.
        """
        main_py = plugin_dir / "main.py"
        if not main_py.is_file():
            raise FileNotFoundError(f"main.py no encontrado en {plugin_dir}")

        # Nombre único del módulo para evitar colisiones en sys.modules
        module_name = f"nordik_plugin_{plugin_dir.name}"
        # Generar un sufijo único si ya existe (recargas)
        counter = 1
        while module_name in sys.modules:
            module_name = f"nordik_plugin_{plugin_dir.name}_{counter}"
            counter += 1

        spec = importlib.util.spec_from_file_location(
            module_name, str(main_py)
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo crear spec para {main_py}")

        module = importlib.util.module_from_spec(spec)

        # Asegurar que el directorio del plugin esté en sys.path para imports relativos
        plugin_dir_str = str(plugin_dir)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            log.error(
                "Error ejecutando plugin %s:\n%s",
                plugin_dir.name, traceback.format_exc(),
            )
            raise RuntimeError(f"Error cargando plugin {plugin_dir.name}: {e}") from e

        return module

    # ── Limpieza ─────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Descarga todos los plugins. Llamar en el graceful shutdown."""
        for name in list(self._plugins.keys()):
            try:
                self.unregister_plugin(name)
            except Exception as e:
                log.warning("Error descargando plugin '%s' en shutdown: %s", name, e)
        log.info("PluginManager apagado (%d plugins descargados)", len(self._plugins))


# ── Factory ─────────────────────────────────────────────────────────


def create_plugin_manager(
    plugins_dir: str | Path,
    registry: ToolRegistry | None = None,
    hot_reload: bool = False,
    enabled: bool = True,
) -> PluginManager | None:
    """Factory que crea y configura un PluginManager.

    Si enabled=False, retorna None (no se inicializa el sistema de plugins).
    """
    if not enabled:
        log.info("Sistema de plugins deshabilitado (PLUGIN_SYSTEM_ENABLED=false)")
        return None

    plugins_dir = Path(plugins_dir).resolve()
    plugins_dir.mkdir(parents=True, exist_ok=True)

    mgr = PluginManager(
        plugins_dir=plugins_dir,
        registry=registry,
        hot_reload=hot_reload,
    )
    log.info("PluginManager creado (dir=%s, hot_reload=%s)", plugins_dir, hot_reload)
    return mgr
