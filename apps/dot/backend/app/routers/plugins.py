"""Plugins REST API — endpoints para gestionar plugins de terceros.

Inspirado en OpenClaw's ClawHub:
  GET    /v1/plugins                         — listar plugins instalados
  POST   /v1/plugins/install                 — instalar plugin
  DELETE /v1/plugins/{name}                  — desinstalar plugin
  POST   /v1/plugins/{name}/reload           — recarga en caliente
  GET    /v1/plugins/marketplace/search      — buscar en marketplace
  GET    /v1/plugins/marketplace/{name}      — detalles de plugin
  GET    /v1/plugins/marketplace/categories  — categorías disponibles
  GET    /v1/plugins/updates                 — verificar actualizaciones
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.plugins.router")

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


# ── Modelos Pydantic ────────────────────────────────────────────────


class PluginItemResponse(BaseModel):
    name: str
    version: str
    description: str
    author: str
    category: str
    tags: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    loaded: bool
    error: str | None = None


class PluginListResponse(BaseModel):
    plugins: list[PluginItemResponse]
    total: int


class PluginInstallRequest(BaseModel):
    source: str = Field(..., description="Nombre del plugin en marketplace, URL ZIP, o path local")
    version: str | None = Field(None, description="Versión específica a instalar (opcional)")


class PluginInstallResponse(BaseModel):
    ok: bool
    name: str
    version: str
    tools: list[str] = Field(default_factory=list)


class PluginReloadResponse(BaseModel):
    ok: bool
    name: str
    version: str
    tools: list[str] = Field(default_factory=list)


class MarketplaceSearchRequest(BaseModel):
    q: str = Field("", alias="q")
    category: str | None = None
    tag: str | None = None
    sort_by: str = "downloads"
    limit: int = Field(50, ge=1, le=100)


class MarketplacePluginItem(BaseModel):
    name: str
    version: str
    description: str
    author: str
    category: str
    tags: list[str] = Field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    reviews: int = 0
    updated_at: str = ""
    min_dot_version: str = "1.0.0"


class MarketplaceSearchResponse(BaseModel):
    results: list[MarketplacePluginItem]
    total: int


class MarketplaceCategoriesResponse(BaseModel):
    categories: list[str]


class UpdatesResponse(BaseModel):
    updates: list[dict[str, str]]


# ── Helpers ──────────────────────────────────────────────────────────


def _require_plugin_manager(request: Request):
    """Obtiene PluginManager desde app.state, o 503 si no disponible."""
    mgr = getattr(request.app.state, "plugin_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="Sistema de plugins no disponible. PLUGIN_SYSTEM_ENABLED=false?",
        )
    return mgr


def _require_plugin_marketplace(request: Request):
    """Obtiene PluginMarketplace desde app.state, o 503 si no disponible."""
    marketplace = getattr(request.app.state, "plugin_marketplace", None)
    if marketplace is None:
        raise HTTPException(
            status_code=503,
            detail="Marketplace de plugins no disponible.",
        )
    return marketplace


def _plugin_info_to_response(info) -> PluginItemResponse:
    return PluginItemResponse(
        name=info.name,
        version=info.version,
        description=info.description,
        author=info.author,
        category=info.category,
        tags=info.tags,
        tools=info.tools,
        dependencies=info.dependencies,
        loaded=info.loaded,
        error=info.error,
    )


# ── Endpoints: plugins instalados ───────────────────────────────────


@router.get("", response_model=PluginListResponse)
@limiter.limit("30/minute")
def list_plugins(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Lista todos los plugins instalados (cargados y con error)."""
    _ = claims_uid(claims)
    mgr = _require_plugin_manager(request)
    plugins = mgr.list_plugins()
    items = [_plugin_info_to_response(p) for p in plugins]
    return PluginListResponse(plugins=items, total=len(items))


@router.post("/install", response_model=PluginInstallResponse)
@limiter.limit("10/minute")
async def install_plugin(
    request: Request,
    body: PluginInstallRequest,
    claims: dict = Depends(require_product_jwt),
):
    """Instala un plugin desde marketplace, URL, o path local."""
    _ = claims_uid(claims)
    mgr = _require_plugin_manager(request)
    marketplace = _require_plugin_marketplace(request)
    source = body.source.strip()

    try:
        # Detectar si es un path local (contiene / o \ o termina en .zip)
        if "/" in source or "\\" in source or source.endswith(".zip") or source.startswith("."):
            name = await marketplace.install_from_path(source, mgr)
        else:
            name = await marketplace.install_from_marketplace(
                source, mgr, version=body.version,
            )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Error instalando plugin desde '%s'", source)
        raise HTTPException(status_code=500, detail=f"Error al instalar plugin: {e}")

    info = mgr.get_plugin(name)
    if info is None:
        raise HTTPException(status_code=500, detail="Plugin instalado pero no encontrado en registry.")

    return PluginInstallResponse(
        ok=True,
        name=info.name,
        version=info.version,
        tools=info.tools,
    )


@router.delete("/{plugin_name}", response_model=dict)
@limiter.limit("10/minute")
def uninstall_plugin(
    request: Request,
    plugin_name: str,
    claims: dict = Depends(require_product_jwt),
):
    """Desinstala un plugin y elimina sus tools del ToolRegistry."""
    _ = claims_uid(claims)
    mgr = _require_plugin_manager(request)

    info = mgr.get_plugin(plugin_name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' no encontrado.")

    ok = mgr.unregister_plugin(plugin_name)
    if not ok:
        raise HTTPException(status_code=500, detail=f"No se pudo desinstalar '{plugin_name}'.")

    # Limpiar directorio del plugin
    import shutil
    from pathlib import Path

    plugin_dir = Path(info.path)
    if plugin_dir.exists():
        try:
            shutil.rmtree(plugin_dir)
            log.info("Directorio de plugin eliminado: %s", plugin_dir)
        except Exception as e:
            log.warning("No se pudo eliminar directorio %s: %s", plugin_dir, e)

    return {"ok": True, "name": plugin_name}


@router.post("/{plugin_name}/reload", response_model=PluginReloadResponse)
@limiter.limit("10/minute")
def reload_plugin(
    request: Request,
    plugin_name: str,
    claims: dict = Depends(require_product_jwt),
):
    """Recarga un plugin en caliente (útil en desarrollo)."""
    _ = claims_uid(claims)
    mgr = _require_plugin_manager(request)

    try:
        info = mgr.reload_plugin(plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("Error recargando plugin '%s'", plugin_name)
        raise HTTPException(status_code=500, detail=f"Error recargando plugin: {e}")

    return PluginReloadResponse(
        ok=True,
        name=info.name,
        version=info.version,
        tools=info.tools,
    )


# ── Endpoints: marketplace ──────────────────────────────────────────


@router.get("/marketplace/search", response_model=MarketplaceSearchResponse)
@limiter.limit("60/minute")
async def search_marketplace(
    request: Request,
    q: str = "",
    category: str | None = None,
    tag: str | None = None,
    sort_by: str = "downloads",
    limit: int = 50,
    claims: dict = Depends(require_product_jwt),
):
    """Busca plugins en el marketplace (catálogo curado + remoto)."""
    _ = claims_uid(claims)
    marketplace = _require_plugin_marketplace(request)

    results = await marketplace.search(
        query=q.strip(),
        category=category.strip() if category else None,
        tag=tag.strip() if tag else None,
        sort_by=sort_by,
        limit=min(limit, 100),
    )

    items = [
        MarketplacePluginItem(
            name=r.name,
            version=r.version,
            description=r.description,
            author=r.author,
            category=r.category,
            tags=r.tags,
            downloads=r.downloads,
            rating=r.rating,
            reviews=r.reviews,
            updated_at=r.updated_at,
            min_dot_version=r.min_dot_version,
        )
        for r in results
    ]

    return MarketplaceSearchResponse(results=items, total=len(items))


@router.get("/marketplace/categories", response_model=MarketplaceCategoriesResponse)
@limiter.limit("60/minute")
async def list_marketplace_categories(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Lista todas las categorías de plugins disponibles en el marketplace."""
    _ = claims_uid(claims)
    marketplace = _require_plugin_marketplace(request)
    categories = await marketplace.list_categories()
    return MarketplaceCategoriesResponse(categories=categories)


@router.get("/marketplace/{plugin_name}", response_model=MarketplacePluginItem)
@limiter.limit("60/minute")
async def get_marketplace_plugin(
    request: Request,
    plugin_name: str,
    claims: dict = Depends(require_product_jwt),
):
    """Obtiene detalles de un plugin del marketplace."""
    _ = claims_uid(claims)
    marketplace = _require_plugin_marketplace(request)

    details = await marketplace.get_plugin_details(plugin_name)
    if details is None:
        raise HTTPException(
            status_code=404, detail=f"Plugin '{plugin_name}' no encontrado en el marketplace."
        )

    return MarketplacePluginItem(
        name=details.name,
        version=details.version,
        description=details.description,
        author=details.author,
        category=details.category,
        tags=details.tags,
        downloads=details.downloads,
        rating=details.rating,
        reviews=details.reviews,
        updated_at=details.updated_at,
        min_dot_version=details.min_dot_version,
    )


# ── Endpoints: actualizaciones ──────────────────────────────────────


@router.get("/updates", response_model=UpdatesResponse)
@limiter.limit("30/minute")
async def check_plugin_updates(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Verifica actualizaciones disponibles para plugins instalados."""
    _ = claims_uid(claims)
    mgr = _require_plugin_manager(request)
    marketplace = _require_plugin_marketplace(request)

    updates = await marketplace.check_updates(mgr)
    return UpdatesResponse(updates=updates)
