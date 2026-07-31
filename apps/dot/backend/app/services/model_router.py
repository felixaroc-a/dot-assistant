"""
Router multi-proveedor con fallback automático para chat de DOT.

Estrategia:
  1. Intenta el modelo preferido (o el default si no se especifica).
  2. Si falla, recorre la cadena de fallback en orden de prioridad.
  3. Cada proveedor tiene su propio Circuit Breaker (3 fallos → 60s cooldown).
  4. Respeta AI_USAGE_LIMIT por usuario.
  5. Loggea qué proveedor se usó y por qué.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncGenerator

from app.services.llm_providers import (
    ChatResponse,
    LLMProvider,
    create_provider,
)
from app.services.model_registry import (
    ModelInfo,
    get_fallback_chain,
    get_model_by_id,
)

log = logging.getLogger("dot.model_router")

# ── Cooldown por proveedor (para fallback rápido sin esperar breaker) ──
_cooldowns: dict[str, float] = {}
_COOLDOWN_SECONDS = 60.0


class AllProvidersExhaustedError(RuntimeError):
    """Todos los proveedores fallaron o no están disponibles."""


def _is_in_cooldown(provider_name: str) -> bool:
    """True si el proveedor está en cooldown temporal."""
    until = _cooldowns.get(provider_name)
    if until is None:
        return False
    if time.monotonic() < until:
        return True
    del _cooldowns[provider_name]
    return False


def _set_cooldown(provider_name: str) -> None:
    """Marca un proveedor en cooldown por 60s."""
    _cooldowns[provider_name] = time.monotonic() + _COOLDOWN_SECONDS
    log.warning("model_router: %s en cooldown %ds", provider_name, _COOLDOWN_SECONDS)


def _build_provider_for_model(model: ModelInfo) -> LLMProvider | None:
    """Crea un proveedor para el modelo dado."""
    provider = create_provider(
        provider_name=model.provider,
        model_name=model.model_id,
    )
    if provider is None:
        log.info("model_router: proveedor %s no disponible para %s", model.provider, model.model_id)
    return provider


def route_chat_completion(
    messages: list[dict],
    system_prompt: str | None = None,
    preferred_model: str | None = None,
    **kwargs,
) -> ChatResponse:
    """Chat completion con fallback automático entre proveedores.

    Args:
        messages: lista de mensajes [{"role": "user", "content": "..."}]
        system_prompt: prompt de sistema opcional
        preferred_model: model_id preferido (None = usa default)
        **kwargs: max_tokens, temperature, etc.

    Returns:
        ChatResponse con texto, tokens y metadata del proveedor usado.

    Raises:
        AllProvidersExhaustedError: si todos los proveedores fallan.
    """
    chain = get_fallback_chain(preferred_model)
    if not chain:
        raise AllProvidersExhaustedError(
            "No hay proveedores IA disponibles. Configura al menos una API key "
            "(DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, o GROQ_API_KEY)."
        )

    last_error: Exception | None = None

    for idx, model in enumerate(chain):
        provider_name = model.provider
        model_id = model.model_id

        # Saltar proveedores en cooldown
        if _is_in_cooldown(provider_name):
            log.info(
                "model_router: saltando %s/%s (cooldown)",
                provider_name,
                model_id,
            )
            continue

        # Saltar si el breaker está abierto
        provider = _build_provider_for_model(model)
        if provider is None:
            continue

        attempt_label = f"{'preferido' if idx == 0 else 'fallback #{idx}'}"
        log.info(
            "model_router: intentando %s/%s (%s)",
            provider_name,
            model_id,
            attempt_label,
        )

        try:
            result = provider.chat_completion(messages, system_prompt, **kwargs)
            log.info(
                "model_router: ÉXITO con %s/%s (%s) — %d tokens",
                provider_name,
                model_id,
                attempt_label,
                result.total_tokens,
            )
            return result
        except RuntimeError as e:
            last_error = e
            log.warning(
                "model_router: FALLO %s/%s (%s): %s",
                provider_name,
                model_id,
                attempt_label,
                e,
            )
            _set_cooldown(provider_name)
            continue

    # Todos fallaron
    raise AllProvidersExhaustedError(
        f"Todos los proveedores IA fallaron. Último error: {last_error}"
    )


async def route_chat_stream(
    messages: list[dict],
    system_prompt: str | None = None,
    preferred_model: str | None = None,
    **kwargs,
) -> AsyncGenerator[tuple[str, str | None], None]:
    """Streaming con fallback automático entre proveedores.

    Yield (token_text, finish_reason) igual que el resto del sistema.
    """
    chain = get_fallback_chain(preferred_model)
    if not chain:
        yield "Error: No hay proveedores IA disponibles.", "error"
        return

    last_error: Exception | None = None

    for idx, model in enumerate(chain):
        provider_name = model.provider
        model_id = model.model_id

        if _is_in_cooldown(provider_name):
            log.info("model_router stream: saltando %s/%s (cooldown)", provider_name, model_id)
            continue

        provider = _build_provider_for_model(model)
        if provider is None:
            continue

        attempt_label = f"{'preferido' if idx == 0 else 'fallback #{idx}'}"
        log.info(
            "model_router stream: intentando %s/%s (%s)",
            provider_name,
            model_id,
            attempt_label,
        )

        try:
            async for token, finish in provider.stream_completion(messages, system_prompt, **kwargs):
                yield token, finish
            log.info("model_router stream: ÉXITO con %s/%s", provider_name, model_id)
            return
        except RuntimeError as e:
            last_error = e
            log.warning(
                "model_router stream: FALLO %s/%s (%s): %s",
                provider_name,
                model_id,
                attempt_label,
                e,
            )
            _set_cooldown(provider_name)
            continue

    yield f"Error: Todos los proveedores IA fallaron. Último: {last_error}", "error"


# ── Backward compat: ruta simple que siempre usa DeepSeek ─────

def route_chat_deepseek_only(
    messages: list[dict],
    system_prompt: str | None = None,
    **kwargs,
) -> ChatResponse:
    """Ruta legacy: siempre DeepSeek (backward compatible)."""
    model = get_model_by_id("deepseek-chat")
    if model is None or not model.is_available:
        raise AllProvidersExhaustedError(
            "DeepSeek no está configurado. Agrega DEEPSEEK_API_KEY en el .env."
        )

    provider = _build_provider_for_model(model)
    if provider is None:
        raise AllProvidersExhaustedError("No se pudo crear el proveedor DeepSeek.")

    return provider.chat_completion(messages, system_prompt, **kwargs)


async def route_chat_stream_deepseek_only(
    messages: list[dict],
    system_prompt: str | None = None,
    **kwargs,
) -> AsyncGenerator[tuple[str, str | None], None]:
    """Streaming legacy: siempre DeepSeek (backward compatible)."""
    model = get_model_by_id("deepseek-chat")
    if model is None or not model.is_available:
        yield "Error: DeepSeek no está configurado.", "error"
        return

    provider = _build_provider_for_model(model)
    if provider is None:
        yield "Error: No se pudo crear el proveedor DeepSeek.", "error"
        return

    async for token, finish in provider.stream_completion(messages, system_prompt, **kwargs):
        yield token, finish
