"""Enrutador de proveedores IA para el chat.
Estrategia v2: multi-model con fallback automático cuando hay varios proveedores configurados.
Si solo DeepSeek está configurado, mantiene comportamiento legacy v1."""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from app.services.circuit_breaker import deepseek_breaker
from app.settings import settings

if TYPE_CHECKING:
    from app.services.ai_provider import AIProvider

log = logging.getLogger("dot.provider_router")

DEFAULT_SYSTEM_PROMPT = (
    "Eres DOT, el asistente personal del usuario. "
    "Responde en español de forma clara y amable. "
    "Puedes ayudar con tareas, responder preguntas y ejecutar herramientas "
    "como creacion de documentos, busqueda web y automatizaciones."
)

DOCUMENT_ACTION_PROMPT = (
    "Si el usuario pide crear o generar un documento (Word, Excel, texto, plantilla, reporte), "
    "responde SOLO con JSON válido, sin markdown, con este esquema exacto: "
    '{"action":"create_document","type":"docx|xlsx|txt|pdf","title":"titulo","content":"contenido completo"}. '
    "Para cualquier otra intención, responde normalmente en texto."
)

TRANSLATE_SYSTEM_PROMPT = (
    "Eres un traductor profesional y preciso. "
    "Devuelve solo la traducción final sin explicaciones, notas ni formato markdown."
)

SUMMARY_SYSTEM_PROMPT = (
    "Eres una asistente experta en síntesis. "
    "Responde siempre en español claro, conciso y accionable."
)

GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"

LANGUAGE_ALIASES = {
    "es": "es",
    "espanol": "es",
    "español": "es",
    "spanish": "es",
    "en": "en",
    "ingles": "en",
    "inglés": "en",
    "english": "en",
    "fr": "fr",
    "frances": "fr",
    "francés": "fr",
    "french": "fr",
    "de": "de",
    "aleman": "de",
    "alemán": "de",
    "german": "de",
    "it": "it",
    "italiano": "it",
    "italian": "it",
    "pt": "pt",
    "portugues": "pt",
    "portugués": "pt",
    "portuguese": "pt",
}


class ProviderNotAvailableError(RuntimeError):
    """El proveedor solicitado no está disponible o no tiene API key configurada."""


@dataclass
class ProviderInfo:
    id: str
    name: str
    api_key_setting: str
    is_available: bool


def get_available_providers() -> list[ProviderInfo]:
    """Lista todos los proveedores con su estado de disponibilidad."""
    providers = [
        ProviderInfo(
            id="deepseek",
            name="DeepSeek",
            api_key_setting="deepseek_api_key",
            is_available=bool(settings.deepseek_api_key),
        ),
        ProviderInfo(
            id="openai",
            name="OpenAI",
            api_key_setting="openai_api_key",
            is_available=bool(settings.openai_api_key),
        ),
        ProviderInfo(
            id="anthropic",
            name="Anthropic",
            api_key_setting="anthropic_api_key",
            is_available=bool(settings.anthropic_api_key),
        ),
        ProviderInfo(
            id="groq",
            name="Groq",
            api_key_setting="groq_api_key",
            is_available=bool(settings.groq_api_key),
        ),
        ProviderInfo(
            id="gemini",
            name="Gemini",
            api_key_setting="gemini_api_key",
            is_available=bool(settings.gemini_api_key),
        ),
    ]
    return providers


def route_chat(
    text: str,
    provider_id: str | None = None,
    system_prompt: str | None = None,
    include_document_action_prompt: bool = True,
    ai_provider: AIProvider | None = None,
) -> str:
    """
    Enruta un mensaje de chat a DeepSeek (único proveedor).
    El parámetro provider_id se ignora — estrategia v1.
    """
    return route_chat_detailed(
        text,
        provider_id,
        system_prompt,
        include_document_action_prompt,
        ai_provider,
    ).content


def route_chat_detailed(
    text: str,
    provider_id: str | None = None,
    system_prompt: str | None = None,
    include_document_action_prompt: bool = True,
    ai_provider: AIProvider | None = None,
):
    """Enruta un mensaje de chat con fallback multi-model cuando está habilitado.
    
    Si model_routing_enabled=True y hay múltiples proveedores, usa el router
    multi-model con fallback automático. Si no, mantiene comportamiento legacy DeepSeek.
    """
    from app.services.model_router import route_chat_completion, AllProvidersExhaustedError

    if include_document_action_prompt:
        system_prompt = _with_document_action_prompt(system_prompt)
    else:
        system_prompt = (system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT

    # Si multi-model está habilitado y hay múltiples providers, usar router nuevo
    if settings.model_routing_enabled:
        from app.services.model_registry import get_available_models
        if get_available_models():
            try:
                messages = [{"role": "user", "content": text}]
                result = route_chat_completion(
                    messages,
                    system_prompt=system_prompt,
                    preferred_model=provider_id if provider_id and provider_id != "deepseek" else None,
                )
                # Adaptar ChatResponse a AIResponse para backward compat
                from app.services.ai_provider import AIResponse
                return AIResponse(
                    content=result.text,
                    model=result.model,
                    finish_reason=result.finish_reason,
                    usage=result.usage,
                )
            except AllProvidersExhaustedError as e:
                raise ProviderNotAvailableError(str(e))

    # Legacy: solo DeepSeek
    from app.services.ai_provider import AIProvider

    if not settings.deepseek_api_key:
        raise ProviderNotAvailableError(
            "DeepSeek no está configurado. Agrega DEEPSEEK_API_KEY en el .env del servidor."
        )

    if not deepseek_breaker.acquire():
        raise ProviderNotAvailableError("Proveedor IA no disponible temporalmente")

    if ai_provider is None:
        ai_provider = AIProvider()
    messages = [{"role": "user", "content": text}]
    return ai_provider.chat(messages, system_prompt)


def route_chat_stream(
    text: str,
    provider_id: str | None = None,
    system_prompt: str | None = None,
    include_document_action_prompt: bool = True,
    ai_provider: AIProvider | None = None,
):
    """
    Enruta un mensaje de chat a DeepSeek con streaming (único proveedor).
    El parámetro provider_id se ignora — estrategia v1.
    """
    if include_document_action_prompt:
        system_prompt = _with_document_action_prompt(system_prompt)
    else:
        system_prompt = (system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT

    yield from _stream_deepseek(text, system_prompt, ai_provider)


def route_translate(
    text: str,
    target_lang: str,
    provider_id: str | None = None,
    ai_provider: AIProvider | None = None,
) -> tuple[str, str, str]:
    """Traduce texto priorizando Google Translate y usando DeepSeek como fallback."""
    clean_text = (text or "").strip()
    clean_target = (target_lang or "").strip()
    if not clean_text:
        raise ValueError("El texto a traducir no puede estar vacío.")
    if not clean_target:
        raise ValueError("Debes indicar el idioma destino.")

    normalized_target = _normalize_target_lang(clean_target)

    google_api_key = getattr(settings, "google_translate_api_key", "").strip()
    if google_api_key:
        try:
            translated = _translate_with_google(clean_text, normalized_target, google_api_key)
            return translated, "google_translate", normalized_target
        except Exception as exc:
            log.warning("Google Translate falló, usando fallback DeepSeek: %s", exc)

    translated = _translate_with_deepseek(clean_text, normalized_target, clean_target, ai_provider)
    return translated, "deepseek", normalized_target


def route_summarize(
    content: str,
    provider_id: str | None = None,
    ai_provider: AIProvider | None = None,
) -> tuple[str, str, int]:
    from app.services.summarizer_service import SummarizerService

    summarizer = SummarizerService()

    result = summarizer.summarize(
        content,
        summarize_fn=lambda prompt: route_chat(
            prompt,
            None,
            SUMMARY_SYSTEM_PROMPT,
            include_document_action_prompt=False,
            ai_provider=ai_provider,
        ),
    )

    summary = str(result.get("summary") or "").strip()
    source_type = str(result.get("source_type") or "text").strip() or "text"
    chunks = int(result.get("chunks") or 1)
    if not summary:
        raise RuntimeError("No se pudo generar el resumen.")
    return summary, source_type, max(1, chunks)


def _call_deepseek(
    text: str,
    system_prompt: str,
    ai_provider: AIProvider | None = None,
) -> str:
    """Llama a DeepSeek API."""
    if not settings.deepseek_api_key:
        raise ProviderNotAvailableError(
            "DeepSeek no está configurado. Agrega DEEPSEEK_API_KEY en el .env del servidor."
        )
    if ai_provider is None:
        from app.services.ai_provider import AIProvider

        ai_provider = AIProvider()
    return ai_provider.simple_chat(text, system_prompt)


def _stream_deepseek(
    text: str,
    system_prompt: str,
    ai_provider: AIProvider | None = None,
):
    """Streaming desde DeepSeek API (síncrono, deprecado — usa async_stream_deepseek)."""
    if not settings.deepseek_api_key:
        raise ProviderNotAvailableError(
            "DeepSeek no está configurado. Agrega DEEPSEEK_API_KEY en el .env del servidor."
        )
    if not deepseek_breaker.acquire():
        raise ProviderNotAvailableError("Proveedor IA no disponible temporalmente")
    if ai_provider is None:
        from app.services.ai_provider import AIProvider

        ai_provider = AIProvider()
    messages = [{"role": "user", "content": text}]
    yield from ai_provider.chat_stream(messages, system_prompt)


async def async_stream_deepseek(
    text: str,
    system_prompt: str,
    ai_provider: AIProvider | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    """Streaming async con fallback multi-model cuando está habilitado.

    Si model_routing_enabled=True y hay múltiples proveedores, usa el router
    multi-model con fallback automático. Si no, mantiene comportamiento legacy DeepSeek.
    """
    # Si multi-model está habilitado, usar router nuevo
    if settings.model_routing_enabled:
        from app.services.model_registry import get_available_models
        if get_available_models():
            try:
                from app.services.model_router import route_chat_stream
            except ImportError:
                log.warning("model_router no disponible, usando DeepSeek legacy")
            else:
                kwargs = {}
                if temperature is not None:
                    kwargs["temperature"] = temperature
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                messages = [{"role": "user", "content": text}]
                async for token, finish in route_chat_stream(
                    messages,
                    system_prompt=system_prompt,
                    **kwargs,
                ):
                    yield token, finish
                return

    # Legacy: solo DeepSeek
    if not settings.deepseek_api_key:
        raise ProviderNotAvailableError(
            "DeepSeek no está configurado. Agrega DEEPSEEK_API_KEY en el .env del servidor."
        )
    if not deepseek_breaker.acquire():
        raise ProviderNotAvailableError("Proveedor IA no disponible temporalmente")
    if ai_provider is None:
        from app.services.ai_provider import AIProvider

        ai_provider = AIProvider()
    messages = [{"role": "user", "content": text}]
    async for token, finish in ai_provider.async_chat_stream(messages, system_prompt):
        yield token, finish


def _with_document_action_prompt(system_prompt: str | None) -> str:
    base = (system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
    if "create_document" in base:
        return base
    return f"{base}\n\n{DOCUMENT_ACTION_PROMPT}"


def _normalize_target_lang(target_lang: str) -> str:
    raw = target_lang.strip().lower()
    if not raw:
        return "es"
    normalized = raw.replace("_", "-")
    if normalized in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[normalized]
    return normalized


def _translate_with_google(text: str, target_lang: str, api_key: str) -> str:
    payload = {
        "q": text,
        "target": target_lang,
        "format": "text",
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(
            GOOGLE_TRANSLATE_URL,
            params={"key": api_key},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    translations = data.get("data", {}).get("translations", [])
    if not translations:
        raise RuntimeError("Google Translate respondió sin traducción.")
    translated = str(translations[0].get("translatedText") or "").strip()
    if not translated:
        raise RuntimeError("Google Translate devolvió una traducción vacía.")
    return html.unescape(translated)


def _translate_with_deepseek(
    text: str,
    target_lang_code: str,
    target_lang_raw: str,
    ai_provider: AIProvider | None = None,
) -> str:
    if not settings.deepseek_api_key:
        raise ProviderNotAvailableError(
            "Traducción no disponible: configura GOOGLE_TRANSLATE_API_KEY o DEEPSEEK_API_KEY."
        )

    instruction = (
        f"Traduce al idioma '{target_lang_raw}' (código {target_lang_code}) el siguiente texto. "
        "Devuelve solo la traducción final:\n\n"
        f"{text}"
    )
    translated = _call_deepseek(instruction, TRANSLATE_SYSTEM_PROMPT, ai_provider).strip()
    if not translated:
        raise RuntimeError("DeepSeek devolvió una traducción vacía.")
    return translated
