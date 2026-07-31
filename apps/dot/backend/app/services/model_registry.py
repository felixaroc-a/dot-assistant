"""
Registro central de modelos LLM disponibles en DOT.

Cada modelo tiene metadata: proveedor, context_window, costos estimados y capacidades.
Solo se exponen modelos cuyas API keys estén configuradas en settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.llm_providers import create_provider
from app.settings import settings

log = logging.getLogger("dot.model_registry")


# ── Modelo de datos ────────────────────────────────────────────

@dataclass
class ModelInfo:
    """Metadata de un modelo LLM registrado en DOT."""
    model_id: str
    provider: str  # "deepseek", "openai", "anthropic", "groq"
    display_name: str
    context_window: int
    cost_input_1m: float  # USD por 1M tokens de entrada
    cost_output_1m: float  # USD por 1M tokens de salida
    capabilities: list[str] = field(default_factory=list)
    is_reasoner: bool = False
    is_default: bool = False
    tier: str = "standard"  # "free", "standard", "premium"

    @property
    def is_available(self) -> bool:
        """True si la API key del proveedor está configurada."""
        key_map = {
            "deepseek": settings.deepseek_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "groq": settings.groq_api_key,
            "gemini": settings.gemini_api_key,
            "ollama": "ollama-local" if settings.ollama_enabled else "",
        }
        return bool(key_map.get(self.provider, ""))

    def to_dict(self) -> dict:
        return {
            "id": self.model_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "context_window": self.context_window,
            "cost_input_1m": self.cost_input_1m,
            "cost_output_1m": self.cost_output_1m,
            "capabilities": self.capabilities,
            "is_reasoner": self.is_reasoner,
            "available": self.is_available,
            "tier": self.tier,
        }


# ═══════════════════════════════════════════════════════════════
# Catálogo de modelos
# ═══════════════════════════════════════════════════════════════

_MODELS: list[ModelInfo] = [
    # ── DeepSeek ──────────────────────────────────────────────
    ModelInfo(
        model_id="deepseek-chat",
        provider="deepseek",
        display_name="DeepSeek V4 (Chat)",
        context_window=65536,
        cost_input_1m=0.14,
        cost_output_1m=0.28,
        capabilities=["chat", "tools", "streaming"],
        is_reasoner=False,
        is_default=True,
        tier="standard",
    ),
    ModelInfo(
        model_id="deepseek-reasoner",
        provider="deepseek",
        display_name="DeepSeek R1 (Reasoner)",
        context_window=65536,
        cost_input_1m=0.55,
        cost_output_1m=2.19,
        capabilities=["chat", "reasoning", "streaming"],
        is_reasoner=True,
        tier="premium",
    ),

    # ── OpenAI ────────────────────────────────────────────────
    ModelInfo(
        model_id="gpt-4o-mini",
        provider="openai",
        display_name="GPT-4o Mini",
        context_window=128000,
        cost_input_1m=0.15,
        cost_output_1m=0.60,
        capabilities=["chat", "tools", "streaming", "vision"],
        tier="standard",
    ),
    ModelInfo(
        model_id="gpt-4o",
        provider="openai",
        display_name="GPT-4o",
        context_window=128000,
        cost_input_1m=2.50,
        cost_output_1m=10.00,
        capabilities=["chat", "tools", "streaming", "vision", "reasoning"],
        tier="premium",
    ),

    # ── Anthropic ─────────────────────────────────────────────
    ModelInfo(
        model_id="claude-3-haiku-20240307",
        provider="anthropic",
        display_name="Claude 3 Haiku",
        context_window=200000,
        cost_input_1m=0.25,
        cost_output_1m=1.25,
        capabilities=["chat", "tools", "streaming", "vision"],
        tier="standard",
    ),
    ModelInfo(
        model_id="claude-3-5-sonnet-20241022",
        provider="anthropic",
        display_name="Claude 3.5 Sonnet",
        context_window=200000,
        cost_input_1m=3.00,
        cost_output_1m=15.00,
        capabilities=["chat", "tools", "streaming", "vision", "reasoning"],
        tier="premium",
    ),

    # ── Groq (FREE tier) ──────────────────────────────────────
    ModelInfo(
        model_id="llama-3.3-70b-versatile",
        provider="groq",
        display_name="Llama 3.3 70B (Groq)",
        context_window=128000,
        cost_input_1m=0.0,  # FREE tier
        cost_output_1m=0.0,
        capabilities=["chat", "tools", "streaming"],
        tier="free",
    ),
    ModelInfo(
        model_id="mixtral-8x7b-32768",
        provider="groq",
        display_name="Mixtral 8x7B (Groq)",
        context_window=32768,
        cost_input_1m=0.0,  # FREE tier
        cost_output_1m=0.0,
        capabilities=["chat", "tools", "streaming"],
        tier="free",
    ),

    # ── Google Gemini ─────────────────────────────────────────
    ModelInfo(
        model_id="gemini-2.5-flash",
        provider="gemini",
        display_name="Gemini 2.5 Flash",
        context_window=1048576,
        cost_input_1m=0.15,
        cost_output_1m=0.60,
        capabilities=["chat", "tools", "streaming"],
        tier="standard",
    ),
    ModelInfo(
        model_id="gemini-2.5-pro",
        provider="gemini",
        display_name="Gemini 2.5 Pro",
        context_window=2097152,
        cost_input_1m=1.25,
        cost_output_1m=5.00,
        capabilities=["chat", "tools", "streaming", "reasoning"],
        tier="premium",
    ),
]

# Orden de preferencia para fallback
_PROVIDER_PRIORITY = ["deepseek", "gemini", "openai", "anthropic", "groq"]


# ── API pública ────────────────────────────────────────────────

def get_all_models() -> list[ModelInfo]:
    """Devuelve todos los modelos registrados (incluyendo no disponibles)."""
    return list(_MODELS)


def get_available_models() -> list[ModelInfo]:
    """Devuelve solo modelos cuyas API keys están configuradas."""
    return [m for m in _MODELS if m.is_available]


def get_default_model() -> ModelInfo | None:
    """Devuelve el mejor modelo disponible según prioridad de proveedor.

    Preferencia: DeepSeek > OpenAI > Anthropic > Groq.
    Dentro de cada proveedor, prefiere el modelo marcado como default.
    """
    available = get_available_models()

    if not available:
        return None

    # Ordenar por prioridad de proveedor
    available_sorted = sorted(
        available,
        key=lambda m: (
            _PROVIDER_PRIORITY.index(m.provider) if m.provider in _PROVIDER_PRIORITY else 999,
            0 if m.is_default else 1,
        ),
    )

    return available_sorted[0]


def get_model_by_id(model_id: str) -> ModelInfo | None:
    """Busca un modelo por su ID exacto."""
    for m in _MODELS:
        if m.model_id == model_id:
            return m
    return None


def get_models_for_provider(provider_name: str) -> list[ModelInfo]:
    """Todos los modelos de un proveedor específico."""
    return [m for m in _MODELS if m.provider == provider_name.lower()]


def get_fallback_chain(preferred_model_id: str | None = None) -> list[ModelInfo]:
    """Cadena de fallback ordenada por prioridad, empezando por el modelo preferido.

    Si preferred_model_id es None, usa get_default_model().
    La cadena incluye todos los modelos disponibles en orden de prioridad.
    """
    available = get_available_models()
    if not available:
        return []

    # Orden base por prioridad de proveedor
    sorted_models = sorted(
        available,
        key=lambda m: (
            _PROVIDER_PRIORITY.index(m.provider) if m.provider in _PROVIDER_PRIORITY else 999,
            0 if m.is_default else 1,
        ),
    )

    if preferred_model_id is None:
        return sorted_models

    # Mover el modelo preferido al frente si existe
    preferred = None
    rest = []
    for m in sorted_models:
        if m.model_id == preferred_model_id:
            preferred = m
        else:
            rest.append(m)

    if preferred:
        return [preferred] + rest
    return sorted_models


def is_multi_model_available() -> bool:
    """True si hay al menos 2 proveedores configurados (para habilitar routing multi-model)."""
    providers_with_keys = sum(
        1 for key in [
            settings.deepseek_api_key,
            settings.openai_api_key,
            settings.anthropic_api_key,
            settings.groq_api_key,
            settings.gemini_api_key,
        ]
        if key
    )
    # Ollama cuenta como proveedor si está habilitado
    if settings.ollama_enabled:
        providers_with_keys += 1
    return providers_with_keys >= 2


def auto_discover_ollama_models() -> list[ModelInfo]:
    """Descubre modelos Ollama instalados localmente via GET /api/tags.

    Solo funciona si OLLAMA_ENABLED=true y Ollama está corriendo.
    Los modelos descubiertos se registran dinámicamente en _MODELS.

    Returns:
        Lista de ModelInfo para los modelos Ollama descubiertos.
    """
    if not settings.ollama_enabled:
        log.debug("Ollama deshabilitado (OLLAMA_ENABLED=false)")
        return []

    base_url = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")

    try:
        import httpx

        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=10.0)) as client:
            resp = client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models_raw = data.get("models", [])
        if not models_raw:
            log.warning("Ollama: sin modelos instalados. Ejecuta 'ollama pull <modelo>' primero.")
            return []

        discovered: list[ModelInfo] = []
        for m in models_raw:
            name = m.get("name", "")
            if not name:
                continue

            # Evitar duplicados
            existing = get_model_by_id(f"ollama/{name}")
            if existing is not None:
                discovered.append(existing)
                continue

            size_bytes = m.get("size", 0)
            size_gb = size_bytes / (1024 ** 3) if size_bytes else 0

            model_info = ModelInfo(
                model_id=f"ollama/{name}",
                provider="ollama",
                display_name=f"Ollama: {name}",
                context_window=8192,  # default conservador
                cost_input_1m=0.0,  # local = gratuito
                cost_output_1m=0.0,
                capabilities=["chat", "streaming"],
                tier="free",
            )
            # Registrar dinámicamente
            _MODELS.append(model_info)
            discovered.append(model_info)
            log.info(
                "Ollama: modelo descubierto %s (%.1f GB)",
                name,
                size_gb,
            )

        return discovered

    except httpx.ConnectError:
        log.warning("Ollama no está corriendo en %s. Inicia Ollama primero.", base_url)
        return []
    except Exception:
        log.warning("Error descubriendo modelos Ollama", exc_info=True)
        return []
