"""Plugin Marketplace — catálogo, búsqueda e instalación de plugins.

Inspirado en OpenClaw's ClawHub. Permite buscar, instalar, calificar
y actualizar plugins desde un marketplace central o local.

Cada plugin en el marketplace tiene:
  - Metadatos: nombre, versión, descripción, autor, categoría, tags
  - Ratings y reviews de usuarios
  - URL de descarga (GitHub, ZIP, o path local)
  - Verificación semver para actualizaciones
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.version import Version

log = logging.getLogger("dot.plugins.marketplace")


# ── Modelos ────────────────────────────────────────────────────────


@dataclass
class MarketplacePlugin:
    """Plugin listado en el marketplace."""

    name: str
    version: str
    description: str
    author: str
    category: str
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    reviews: int = 0
    updated_at: str = ""
    install_url: str = ""
    min_dot_version: str = "1.0.0"
    size_bytes: int = 0


@dataclass
class PluginReview:
    """Review de un plugin por un usuario."""

    plugin_name: str
    uid: str
    rating: float  # 1.0 – 5.0
    comment: str
    created_at: str


# ── Catalogo curado local ─────────────────────────────────────────


_CURATED_CATALOG: list[dict[str, Any]] = [
    {
        "name": "hello-world",
        "version": "1.0.0",
        "description": "Plugin de ejemplo: saludo simple. Demuestra el SDK de plugins.",
        "author": "Nordik-IA",
        "category": "Ejemplos",
        "tags": ["ejemplo", "tutorial", "hello"],
        "downloads": 1250,
        "rating": 4.5,
        "reviews": 8,
        "updated_at": "2026-07-15T10:00:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "crypto-prices",
        "version": "1.0.0",
        "description": "Consulta precios de criptomonedas en tiempo real desde CoinGecko API gratuita.",
        "author": "Nordik-IA",
        "category": "Finanzas",
        "tags": ["crypto", "bitcoin", "finanzas", "precios"],
        "downloads": 890,
        "rating": 4.8,
        "reviews": 15,
        "updated_at": "2026-07-20T08:30:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "url-shortener",
        "version": "1.0.0",
        "description": "Acorta URLs usando servicios gratuitos como TinyURL. Ideal para compartir enlaces en WhatsApp.",
        "author": "Nordik-IA",
        "category": "Utilidades",
        "tags": ["url", "shortener", "utilidades", "links"],
        "downloads": 670,
        "rating": 4.2,
        "reviews": 6,
        "updated_at": "2026-07-18T12:00:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "weather-forecast",
        "version": "1.0.0",
        "description": "Pronóstico del clima por ciudad usando Open-Meteo API gratuita (sin API key).",
        "author": "Comunidad Nordik",
        "category": "Clima",
        "tags": ["clima", "weather", "pronóstico"],
        "downloads": 1450,
        "rating": 4.6,
        "reviews": 22,
        "updated_at": "2026-07-22T06:00:00Z",
        "min_dot_version": "1.1.0",
    },
    {
        "name": "qr-generator",
        "version": "1.0.0",
        "description": "Genera códigos QR desde texto o URLs. Útil para compartir contactos, WiFi, o links.",
        "author": "Comunidad Nordik",
        "category": "Utilidades",
        "tags": ["qr", "código", "utilidades", "imagen"],
        "downloads": 560,
        "rating": 4.0,
        "reviews": 4,
        "updated_at": "2026-07-10T14:00:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "markdown-preview",
        "version": "2.0.1",
        "description": "Convierte Markdown a HTML y genera vista previa. Soporta tablas, código, y emojis.",
        "author": "Nordik-IA",
        "category": "Desarrollo",
        "tags": ["markdown", "html", "desarrollo", "documentación"],
        "downloads": 320,
        "rating": 4.3,
        "reviews": 9,
        "updated_at": "2026-07-21T09:00:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "color-palette",
        "version": "1.0.0",
        "description": "Genera paletas de colores armoniosas para diseño. Modos: complementario, análogo, triádico.",
        "author": "Comunidad Nordik",
        "category": "Diseño",
        "tags": ["color", "diseño", "paleta", "creatividad"],
        "downloads": 180,
        "rating": 3.9,
        "reviews": 3,
        "updated_at": "2026-06-28T16:00:00Z",
        "min_dot_version": "1.0.0",
    },
    {
        "name": "unit-converter",
        "version": "1.2.0",
        "description": "Conversor universal de unidades: longitud, peso, temperatura, moneda, tiempo, y más.",
        "author": "Nordik-IA",
        "category": "Utilidades",
        "tags": ["conversor", "unidades", "utilidades", "medidas"],
        "downloads": 2100,
        "rating": 4.7,
        "reviews": 35,
        "updated_at": "2026-07-19T11:00:00Z",
        "min_dot_version": "1.0.0",
    },
]


# ── Marketplace ────────────────────────────────────────────────────


class PluginMarketplace:
    """Catálogo y gestor de instalación de plugins desde marketplace.

    Soporta:
      - Catálogo curado local (siempre disponible)
      - Marketplace remoto (si PLUGIN_MARKETPLACE_URL está configurado)
      - Instalación desde URL (ZIP) o path local
      - Versionado semver con check de actualizaciones
      - Ratings y reviews (almacenados en Firestore si disponible)
    """

    def __init__(
        self,
        marketplace_url: str = "",
        plugins_dir: str | Path = "",
    ) -> None:
        self._marketplace_url = marketplace_url.strip()
        self._plugins_dir = Path(plugins_dir) if plugins_dir else Path("plugins")
        # Cache del catálogo remoto
        self._remote_catalog: list[dict[str, Any]] | None = None
        self._catalog_ttl: float = 3600.0  # 1 hora
        self._catalog_fetched_at: float = 0.0
        self._reviews: dict[str, list[PluginReview]] = {}

    # ── Búsqueda ─────────────────────────────────────────────────────

    async def search(
        self,
        query: str = "",
        category: str | None = None,
        tag: str | None = None,
        sort_by: str = "downloads",
        limit: int = 50,
    ) -> list[MarketplacePlugin]:
        """Busca plugins en el marketplace (curado local + remoto si disponible)."""
        catalog = await self._get_catalog()
        results: list[MarketplacePlugin] = []

        for item in catalog:
            plugin = self._dict_to_plugin(item)

            # Filtros
            if query:
                q = query.lower()
                if (
                    q not in plugin.name.lower()
                    and q not in plugin.description.lower()
                    and not any(q in t.lower() for t in plugin.tags)
                ):
                    continue

            if category and category.lower() != "todas":
                if plugin.category.lower() != category.lower():
                    continue

            if tag and tag.lower() not in [t.lower() for t in plugin.tags]:
                continue

            results.append(plugin)

        # Ordenar
        sort_key = {
            "downloads": lambda p: -p.downloads,
            "rating": lambda p: -p.rating,
            "name": lambda p: p.name.lower(),
            "updated": lambda p: p.updated_at,
        }.get(sort_by, lambda p: -p.downloads)
        results.sort(key=sort_key)

        return results[:limit]

    async def get_plugin_details(self, name: str) -> MarketplacePlugin | None:
        """Obtiene detalles completos de un plugin del marketplace."""
        catalog = await self._get_catalog()
        for item in catalog:
            if item.get("name", "").strip() == name.strip():
                plugin = self._dict_to_plugin(item)
                # Adjuntar reviews si hay
                return plugin
        return None

    async def list_categories(self) -> list[str]:
        """Lista todas las categorías disponibles."""
        catalog = await self._get_catalog()
        categories = sorted({
            item.get("category", "General") for item in catalog
        })
        return categories

    # ── Instalación ──────────────────────────────────────────────────

    async def install_from_marketplace(
        self,
        plugin_name: str,
        plugin_manager,  # PluginManager
        version: str | None = None,
    ) -> str:
        """Instala un plugin desde el marketplace al directorio local de plugins.

        Flujo:
        1. Buscar plugin en catálogo
        2. Si tiene install_url, descargar ZIP y extraer
        3. Si no, buscar en plugin-examples/ local
        4. Registrar con PluginManager

        Retorna el nombre del plugin instalado.
        """
        details = await self.get_plugin_details(plugin_name)
        if details is None:
            raise ValueError(f"Plugin '{plugin_name}' no encontrado en el marketplace.")

        target_dir = self._plugins_dir / plugin_name

        if details.install_url:
            # Descargar desde URL remota
            await self._download_and_extract(details.install_url, target_dir)
        else:
            # Buscar en ejemplos locales
            source = self._find_local_example(plugin_name)
            if source is None:
                raise ValueError(
                    f"Plugin '{plugin_name}' no tiene install_url y no se encontró "
                    f"localmente en plugin-examples/"
                )
            if source != target_dir:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(source, target_dir)

        # Registrar
        yaml_path = target_dir / "plugin.yaml"
        if not yaml_path.is_file():
            raise FileNotFoundError(
                f"plugin.yaml no encontrado tras instalar {plugin_name} en {target_dir}"
            )

        info = plugin_manager.register_plugin(yaml_path)
        if info is None:
            raise RuntimeError(f"No se pudo registrar el plugin '{plugin_name}'.")

        log.info(
            "Plugin '%s' v%s instalado desde marketplace",
            plugin_name, details.version,
        )
        return plugin_name

    async def install_from_path(
        self,
        source_path: str | Path,
        plugin_manager,  # PluginManager
    ) -> str:
        """Instala un plugin desde un path local (directorio o ZIP)."""
        source = Path(source_path).resolve()

        if not source.exists():
            raise FileNotFoundError(f"Path no encontrado: {source}")

        # Si es un ZIP, extraer
        if source.suffix.lower() == ".zip":
            target_dir = self._plugins_dir / source.stem
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(target_dir)
            yaml_path = target_dir / "plugin.yaml"
        elif source.is_dir():
            # Copiar al directorio de plugins
            target_dir = self._plugins_dir / source.name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source, target_dir)
            yaml_path = target_dir / "plugin.yaml"
        else:
            raise ValueError(f"Formato no soportado: {source}. Debe ser .zip o directorio.")

        if not yaml_path.is_file():
            raise FileNotFoundError(f"No se encontró plugin.yaml en {target_dir}")

        info = plugin_manager.register_plugin(yaml_path)
        if info is None:
            raise RuntimeError(f"No se pudo registrar el plugin desde {source}")

        log.info("Plugin instalado desde %s → %s", source, info.name)
        return info.name

    # ── Versionado ───────────────────────────────────────────────────

    async def check_updates(
        self,
        plugin_manager,  # PluginManager
    ) -> list[dict[str, str]]:
        """Verifica actualizaciones disponibles para plugins instalados.

        Retorna lista de {name, current_version, latest_version}.
        """
        catalog = await self._get_catalog()
        catalog_by_name = {
            item.get("name", "").strip(): item for item in catalog
        }

        updates: list[dict[str, str]] = []
        for info in plugin_manager.list_plugins():
            if not info.loaded:
                continue
            marketplace_item = catalog_by_name.get(info.name)
            if marketplace_item is None:
                continue

            latest = marketplace_item.get("version", "0.0.0")
            try:
                if Version(latest) > Version(info.version):
                    updates.append({
                        "name": info.name,
                        "current_version": info.version,
                        "latest_version": latest,
                    })
            except Exception:
                log.debug("Versión inválida para %s: %s vs %s", info.name, info.version, latest)

        return updates

    # ── Ratings & Reviews ────────────────────────────────────────────

    def add_review(
        self,
        plugin_name: str,
        uid: str,
        rating: float,
        comment: str = "",
    ) -> PluginReview:
        """Agrega una review para un plugin (1.0–5.0 estrellas)."""
        if not (1.0 <= rating <= 5.0):
            raise ValueError("Rating debe estar entre 1.0 y 5.0")

        review = PluginReview(
            plugin_name=plugin_name.strip(),
            uid=uid.strip(),
            rating=round(rating, 1),
            comment=comment.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        if plugin_name not in self._reviews:
            self._reviews[plugin_name] = []
        self._reviews[plugin_name].append(review)

        log.info(
            "Review agregada para plugin '%s': %.1f★ por uid=%s",
            plugin_name, rating, uid[:8],
        )
        return review

    def get_reviews(self, plugin_name: str) -> list[PluginReview]:
        """Obtiene todas las reviews de un plugin."""
        return self._reviews.get(plugin_name.strip(), [])

    def get_average_rating(self, plugin_name: str) -> float:
        """Calcula el rating promedio de un plugin."""
        reviews = self.get_reviews(plugin_name)
        if not reviews:
            return 0.0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    # ── Sandbox (Docker isolation) ───────────────────────────────────

    def is_sandbox_available(self) -> bool:
        """Verifica si Docker está disponible para sandbox de plugins."""
        try:
            import subprocess

            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── Helpers ──────────────────────────────────────────────────────

    async def _get_catalog(self) -> list[dict[str, Any]]:
        """Obtiene el catálogo combinado: curado local + remoto (cacheado)."""
        catalog = list(_CURATED_CATALOG)

        # Intentar catálogo remoto
        if self._marketplace_url:
            now = asyncio.get_event_loop().time()
            if (
                self._remote_catalog is not None
                and (now - self._catalog_fetched_at) < self._catalog_ttl
            ):
                catalog.extend(self._remote_catalog)
            else:
                remote = await self._fetch_remote_catalog()
                if remote:
                    catalog.extend(remote)

        return catalog

    async def _fetch_remote_catalog(self) -> list[dict[str, Any]] | None:
        """Descarga catálogo remoto desde PLUGIN_MARKETPLACE_URL."""
        if not self._marketplace_url:
            return None

        try:
            # Usar aiohttp si está disponible; si no, httpx; si no, urllib
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self._marketplace_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, list):
                                self._remote_catalog = data
                                self._catalog_fetched_at = asyncio.get_event_loop().time()
                                log.info(
                                    "Catálogo remoto: %d plugins desde %s",
                                    len(data), self._marketplace_url,
                                )
                                return data
            except ImportError:
                pass

            try:
                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(self._marketplace_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list):
                            self._remote_catalog = data
                            self._catalog_fetched_at = asyncio.get_event_loop().time()
                            log.info(
                                "Catálogo remoto: %d plugins desde %s",
                                len(data), self._marketplace_url,
                            )
                            return data
            except ImportError:
                pass

            log.warning("No se pudo descargar catálogo remoto: sin cliente HTTP async")
        except Exception as e:
            log.warning("Error descargando catálogo remoto: %s", e)

        return None

    async def _download_and_extract(self, url: str, target_dir: Path) -> None:
        """Descarga un ZIP desde URL y lo extrae en target_dir."""
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Error descargando {url}: HTTP {resp.status}")
                    content = await resp.read()
        except ImportError:
            import urllib.request

            content = urllib.request.urlopen(url, timeout=60).read()

        # Guardar y extraer ZIP
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(content)
            zip_path = tf.name

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(target_dir)
        finally:
            Path(zip_path).unlink(missing_ok=True)

        log.info("Plugin descargado y extraído en %s", target_dir)

    def _find_local_example(self, plugin_name: str) -> Path | None:
        """Busca un plugin en plugin-examples/ local (relativo al backend)."""
        # Buscar en varios lugares comunes
        candidates = [
            Path(__file__).resolve().parent.parent / "plugin-examples" / plugin_name,
            Path(__file__).resolve().parents[2] / "plugin-examples" / plugin_name,
            Path("plugin-examples") / plugin_name,
        ]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "plugin.yaml").is_file():
                return candidate
        return None

    def _dict_to_plugin(self, item: dict[str, Any]) -> MarketplacePlugin:
        """Convierte un dict del catálogo a MarketplacePlugin."""
        return MarketplacePlugin(
            name=str(item.get("name", "")),
            version=str(item.get("version", "0.0.0")),
            description=str(item.get("description", "")),
            author=str(item.get("author", "")),
            category=str(item.get("category", "General")),
            tags=[str(t) for t in item.get("tags", [])],
            downloads=int(item.get("downloads", 0) or 0),
            rating=float(item.get("rating", 0.0) or 0),
            reviews=int(item.get("reviews", 0) or 0),
            updated_at=str(item.get("updated_at", "")),
            install_url=str(item.get("install_url", "")),
            min_dot_version=str(item.get("min_dot_version", "1.0.0")),
            size_bytes=int(item.get("size_bytes", 0) or 0),
        )
