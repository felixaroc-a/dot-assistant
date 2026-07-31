"""Capacidades: expone el catalogo de funcionalidades del producto (unificado).

GET /v1/capabilities — producto unificado (BIBLIA D1): mismas capacidades en todos
los planes; solo feature flags y settings restringen disponibilidad.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request

from app.auth_deps import require_product_jwt
from app.dependencies.limiter import limiter
from app.services.cache_service import cached
from app.settings import settings

# ─── Capacidades (inlineadas desde openclaw_adapter DEPRECADO) ──────────────

CAPABILITIES_REGISTRY = frozenset({
    "whatsapp_channel_login",
    "automation_plugins",
    "chat_completion",
    "image_generation",
    "web_search",
    "file_tools",
    "remote_execution",
})

UNIFIED_PRODUCT_CAPABILITIES: frozenset[str] = CAPABILITIES_REGISTRY

CAPABILITY_FLAG_KEYS: dict[str, str] = {
    "chat_completion": "enable_chat_core",
    "whatsapp_channel_login": "enable_whatsapp_qr",
    "automation_plugins": "enable_automation_plugins",
    "image_generation": "enable_image_gen",
    "web_search": "enable_web_search",
    "file_tools": "enable_file_tools",
    "remote_execution": "enable_remote_execution",
}

FEATURE_FLAGS: dict[str, bool] = {
    "enable_chat_core": settings.enable_chat,
    "enable_whatsapp_qr": True,
    "enable_automation_plugins": True,
    "enable_image_gen": settings.image_generation_enabled,
    "enable_web_search": settings.enable_web_search,
    "enable_file_tools": False,
    "enable_remote_execution": False,
}


def _feature_flag_enabled(capability_id: str) -> bool:
    """True si el feature flag asociado a la capacidad esta activo."""
    flag_key = CAPABILITY_FLAG_KEYS.get(capability_id)
    if flag_key is None:
        return False
    return FEATURE_FLAGS.get(flag_key, True)


@dataclass
class CapabilityInfo:
    id: str
    label: str
    description: str
    enabled_by_default: bool = True


CAPABILITIES_META: dict[str, CapabilityInfo] = {
    "chat_completion": CapabilityInfo(
        id="chat_completion",
        label="Chat con IA",
        description="Conversaciones con modelos de lenguaje",
    ),
    "whatsapp_channel_login": CapabilityInfo(
        id="whatsapp_channel_login",
        label="WhatsApp QR",
        description="Vinculacion de WhatsApp para conversar con IA",
    ),
    "automation_plugins": CapabilityInfo(
        id="automation_plugins",
        label="Automatizaciones",
        description="Plugins de Gmail y Google Calendar",
        enabled_by_default=False,
    ),
    "image_generation": CapabilityInfo(
        id="image_generation",
        label="Generacion de imagenes",
        description="Creacion de imagenes con IA",
        enabled_by_default=False,
    ),
    "web_search": CapabilityInfo(
        id="web_search",
        label="Busqueda web",
        description="Busqueda de informacion en internet",
    ),
    "file_tools": CapabilityInfo(
        id="file_tools",
        label="Herramientas de archivos",
        description="Creacion y edicion de documentos locales",
        enabled_by_default=False,
    ),
    "remote_execution": CapabilityInfo(
        id="remote_execution",
        label="Ejecucion remota",
        description="Descarga de archivos y ejecucion de comandos via WhatsApp",
        enabled_by_default=False,
    ),
}


def get_product_capabilities() -> list[CapabilityInfo]:
    """Devuelve capacidades habilitadas por feature flags (producto unificado, sin gating por plan)."""
    return [
        CAPABILITIES_META[c] for c in CAPABILITIES_META
        if c in UNIFIED_PRODUCT_CAPABILITIES and _feature_flag_enabled(c)
    ]


# Alias legacy — no filtrar por plan.
get_capabilities_for_plan = get_product_capabilities


def is_capability_enabled(capability_id: str) -> bool:
    """Verifica si una capacidad esta habilitada via feature flags (sin gating por plan)."""
    if capability_id not in CAPABILITIES_REGISTRY:
        return False
    return _feature_flag_enabled(capability_id)


router = APIRouter(prefix="/v1/capabilities", tags=["capabilities"])


@router.get("/")
@limiter.limit("60/minute")
@cached(ttl_seconds=300)
def list_capabilities(
    request: Request,
    claims: dict = Depends(require_product_jwt),
):
    """Lista capacidades disponibles del producto (unificadas, sin gating por plan)."""
    _ = claims  # autenticación requerida pero plan es irrelevante para capacidades
    capabilities = get_product_capabilities()
    return {
        "capabilities": [
            {
                "id": c.id,
                "label": c.label,
                "description": c.description,
                "enabled_by_default": c.enabled_by_default,
            }
            for c in capabilities
        ],
    }


@router.get("/{capability_id}")
@cached(ttl_seconds=300)
def get_capability_detail(
    request: Request,
    capability_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Detalle de una capacidad especifica."""
    meta = CAPABILITIES_META.get(capability_id)
    if not meta:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Capacidad '{capability_id}' no encontrada.")

    return {
        "id": meta.id,
        "label": meta.label,
        "description": meta.description,
        "enabled_by_default": meta.enabled_by_default,
        "available_in_plan": True,
    }
