"""
Abstracción multi-proveedor LLM para DOT.

Proveedores:
  - DeepSeek (OpenAI-compatible)
  - OpenAI (GPT-4o, GPT-4o-mini)
  - Anthropic (Claude 3 Haiku, Claude 3.5 Sonnet)
  - Groq (Llama 3.3, Mixtral — FREE tier)

Cada proveedor tiene su propio Circuit Breaker independiente.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator

import httpx

from app.services.circuit_breaker import CircuitBreaker
from app.settings import settings

log = logging.getLogger("dot.llm_providers")

# ── Breakers por proveedor ─────────────────────────────────────
deepseek_breaker = CircuitBreaker(
    name="deepseek_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)
openai_breaker = CircuitBreaker(
    name="openai_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)
anthropic_breaker = CircuitBreaker(
    name="anthropic_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)
groq_breaker = CircuitBreaker(
    name="groq_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)
gemini_breaker = CircuitBreaker(
    name="gemini_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)


# ── Modelos de datos ───────────────────────────────────────────

@dataclass
class ChatResponse:
    """Respuesta estandarizada de cualquier proveedor LLM."""
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None
    usage: dict | None = None
    provider: str = ""

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class ProviderConfig:
    """Configuración de un proveedor LLM."""
    api_key: str
    model_name: str
    base_url: str
    max_tokens: int = 8192
    temperature: float = 0.7
    timeout_seconds: int = 30


# ── Timeout HTTP helper ────────────────────────────────────────

def _http_timeout(seconds: int) -> httpx.Timeout:
    """Timeout soft: connect corto; read acotado (streaming tolera pausas entre chunks)."""
    return httpx.Timeout(connect=5.0, read=float(seconds), write=30.0, pool=5.0)


# ═══════════════════════════════════════════════════════════════
# Clase base abstracta
# ═══════════════════════════════════════════════════════════════

class LLMProvider(ABC):
    """Interfaz común para todos los proveedores LLM."""

    def __init__(self, config: ProviderConfig, breaker: CircuitBreaker):
        self.config = config
        self.breaker = breaker

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__.replace("Provider", "").lower()

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        """Chat completion no-streaming."""

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, str | None], None]:
        """Streaming async nativo. Yield (token_text, finish_reason)."""

    @abstractmethod
    def health_check(self) -> bool:
        """Ping mínimo (1 token) para verificar disponibilidad."""

    @abstractmethod
    def is_available(self) -> bool:
        """True si la API key está configurada y el breaker permite paso."""


# ═══════════════════════════════════════════════════════════════
# Base OpenAI-compatible (DeepSeek, OpenAI, Groq)
# ═══════════════════════════════════════════════════════════════

class _OpenAICompatProvider(LLMProvider):
    """Base para proveedores con API compatible OpenAI (/v1/chat/completions)."""

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> dict:
        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        temperature = kwargs.get("temperature", self.config.temperature)

        return {
            "model": self.config.model_name,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def chat_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        payload = self._build_payload(messages, system_prompt, **kwargs)

        log.info(
            "%s request: model=%s messages=%d",
            self.provider_name,
            self.config.model_name,
            len(payload["messages"]),
        )

        try:
            with httpx.Client(timeout=_http_timeout(self.config.timeout_seconds)) as client:
                response = client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            choice = data["choices"][0]
            usage = data.get("usage", {})
            result = ChatResponse(
                text=choice["message"]["content"],
                model=data.get("model", self.config.model_name),
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason"),
                usage=usage,
                provider=self.provider_name,
            )

            log.info(
                "%s response: model=%s finish=%s tokens=%d",
                self.provider_name,
                result.model,
                result.finish_reason,
                result.total_tokens,
            )
            self.breaker.on_success()
            return result

        except RuntimeError:
            raise

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("%s HTTP error %d: %s", self.provider_name, status, body)

            if status == 401:
                raise RuntimeError(f"API key de {self.provider_name} inválida o sin crédito.")
            elif status == 429:
                raise RuntimeError(f"Límite de tasa de {self.provider_name} excedido.")
            elif status == 402:
                raise RuntimeError(f"Cuenta de {self.provider_name} sin crédito suficiente.")
            else:
                raise RuntimeError(f"Error del proveedor {self.provider_name} ({status}).")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("%s request timeout after %ds", self.provider_name, self.config.timeout_seconds)
            raise RuntimeError(f"El proveedor {self.provider_name} no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("%s request failed", self.provider_name)
            raise RuntimeError(f"Error de conexión con {self.provider_name}: {e}")

    async def stream_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, str | None], None]:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        payload = self._build_payload(messages, system_prompt, **kwargs)
        payload["stream"] = True

        log.info(
            "%s async stream: model=%s messages=%d",
            self.provider_name,
            self.config.model_name,
            len(payload["messages"]) - (1 if system_prompt else 0),
        )

        try:
            async with httpx.AsyncClient(
                timeout=_http_timeout(self.config.timeout_seconds),
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                self.breaker.on_success()
                                yield "", "stop"
                                return
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content", "")
                                finish_reason = chunk.get("choices", [{}])[0].get("finish_reason")
                                if token:
                                    yield token, None
                                if finish_reason:
                                    self.breaker.on_success()
                                    yield "", finish_reason
                                    return
                            except json.JSONDecodeError:
                                log.warning(
                                    "%s stream parse error: %s",
                                    self.provider_name,
                                    data_str[:200],
                                )

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                await e.response.aread()
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("%s stream HTTP error %d: %s", self.provider_name, status, body)
            if status == 401:
                raise RuntimeError(f"API key de {self.provider_name} inválida.")
            elif status == 429:
                raise RuntimeError(f"Límite de tasa de {self.provider_name} excedido.")
            elif status == 402:
                raise RuntimeError(f"Cuenta de {self.provider_name} sin crédito suficiente.")
            else:
                raise RuntimeError(f"Error del proveedor {self.provider_name} ({status}).")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("%s stream timeout after %ds", self.provider_name, self.config.timeout_seconds)
            raise RuntimeError(f"El proveedor {self.provider_name} no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("%s stream request failed", self.provider_name)
            raise RuntimeError(f"Error de conexión con {self.provider_name}: {e}")

    def health_check(self) -> bool:
        """Ping mínimo: 1 token de entrada, 1 token de salida."""
        if not self.config.api_key:
            return False
        if not self.breaker.acquire():
            return False
        try:
            payload = {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            }
            with httpx.Client(timeout=_http_timeout(10)) as client:
                resp = client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                )
                resp.raise_for_status()
            self.breaker.on_success()
            return True
        except Exception:
            self.breaker.on_failure()
            log.warning("%s health check failed", self.provider_name, exc_info=True)
            return False

    def is_available(self) -> bool:
        return bool(self.config.api_key) and self.breaker.acquire()


# ═══════════════════════════════════════════════════════════════
# DeepSeek Provider
# ═══════════════════════════════════════════════════════════════

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

MODEL_CHAT = "deepseek-chat"
MODEL_REASONER = "deepseek-reasoner"


class DeepSeekProvider(_OpenAICompatProvider):
    """Proveedor DeepSeek — API compatible OpenAI."""

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout_seconds: int | None = None,
    ):
        config = ProviderConfig(
            api_key=api_key or settings.deepseek_api_key,
            model_name=model_name or settings.default_chat_model or MODEL_CHAT,
            base_url=DEEPSEEK_BASE_URL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds or settings.deepseek_chat_timeout_seconds,
        )
        super().__init__(config, deepseek_breaker)


# ═══════════════════════════════════════════════════════════════
# OpenAI Provider
# ═══════════════════════════════════════════════════════════════

OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(_OpenAICompatProvider):
    """Proveedor OpenAI — GPT-4o, GPT-4o-mini."""

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        api_key: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout_seconds: int = 30,
    ):
        config = ProviderConfig(
            api_key=api_key or settings.openai_api_key,
            model_name=model_name,
            base_url=OPENAI_BASE_URL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(config, openai_breaker)


# ═══════════════════════════════════════════════════════════════
# Anthropic Provider
# ═══════════════════════════════════════════════════════════════

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    """Proveedor Anthropic — Claude 3 Haiku, Claude 3.5 Sonnet."""

    def __init__(
        self,
        model_name: str = "claude-3-haiku-20240307",
        api_key: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout_seconds: int = 30,
    ):
        config = ProviderConfig(
            api_key=api_key or settings.anthropic_api_key,
            model_name=model_name,
            base_url=ANTHROPIC_BASE_URL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(config, anthropic_breaker)

    def _build_headers(self) -> dict:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _build_messages(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> tuple[str | None, list[dict]]:
        """Convierte mensajes OpenAI-style a formato Anthropic Messages API."""
        anthropic_messages: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = (system_prompt or "") + "\n" + content
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({"role": "user", "content": content})
        return system_prompt, anthropic_messages

    def chat_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        system, anthropic_msgs = self._build_messages(messages, system_prompt)

        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        temperature = kwargs.get("temperature", self.config.temperature)

        payload: dict = {
            "model": self.config.model_name,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        log.info(
            "anthropic request: model=%s messages=%d",
            self.config.model_name,
            len(anthropic_msgs),
        )

        try:
            with httpx.Client(timeout=_http_timeout(self.config.timeout_seconds)) as client:
                response = client.post(
                    f"{self.config.base_url}/messages",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            content_blocks = data.get("content", [])
            text = "".join(
                block.get("text", "") for block in content_blocks if block.get("type") == "text"
            )

            usage = data.get("usage", {})
            result = ChatResponse(
                text=text,
                model=data.get("model", self.config.model_name),
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
                finish_reason=data.get("stop_reason"),
                usage=usage,
                provider=self.provider_name,
            )

            log.info(
                "anthropic response: model=%s finish=%s tokens=%d",
                result.model,
                result.finish_reason,
                result.total_tokens,
            )
            self.breaker.on_success()
            return result

        except RuntimeError:
            raise

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("anthropic HTTP error %d: %s", status, body)

            if status == 401:
                raise RuntimeError("API key de Anthropic inválida.")
            elif status == 429:
                raise RuntimeError("Límite de tasa de Anthropic excedido.")
            else:
                raise RuntimeError(f"Error del proveedor Anthropic ({status}).")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("anthropic request timeout after %ds", self.config.timeout_seconds)
            raise RuntimeError("El proveedor Anthropic no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("anthropic request failed")
            raise RuntimeError(f"Error de conexión con Anthropic: {e}")

    async def stream_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, str | None], None]:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        system, anthropic_msgs = self._build_messages(messages, system_prompt)

        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        temperature = kwargs.get("temperature", self.config.temperature)

        payload: dict = {
            "model": self.config.model_name,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        log.info(
            "anthropic async stream: model=%s messages=%d",
            self.config.model_name,
            len(anthropic_msgs),
        )

        try:
            async with httpx.AsyncClient(
                timeout=_http_timeout(self.config.timeout_seconds),
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.base_url}/messages",
                    headers=self._build_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                self.breaker.on_success()
                                yield "", "stop"
                                return
                            try:
                                event = json.loads(data_str)
                                event_type = event.get("type", "")

                                if event_type == "content_block_delta":
                                    delta = event.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        token = delta.get("text", "")
                                        if token:
                                            yield token, None

                                elif event_type == "message_delta":
                                    delta = event.get("delta", {})
                                    stop_reason = delta.get("stop_reason")
                                    if stop_reason:
                                        self.breaker.on_success()
                                        yield "", stop_reason
                                        return

                                elif event_type == "message_stop":
                                    self.breaker.on_success()
                                    yield "", "end_turn"
                                    return

                            except json.JSONDecodeError:
                                log.warning("anthropic stream parse error: %s", data_str[:200])

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                await e.response.aread()
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("anthropic stream HTTP error %d: %s", status, body)
            if status == 401:
                raise RuntimeError("API key de Anthropic inválida.")
            elif status == 429:
                raise RuntimeError("Límite de tasa de Anthropic excedido.")
            else:
                raise RuntimeError(f"Error del proveedor Anthropic ({status}).")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("anthropic stream timeout after %ds", self.config.timeout_seconds)
            raise RuntimeError("El proveedor Anthropic no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("anthropic stream request failed")
            raise RuntimeError(f"Error de conexión con Anthropic: {e}")

    def health_check(self) -> bool:
        """Ping mínimo con 1 token."""
        if not self.config.api_key:
            return False
        if not self.breaker.acquire():
            return False
        try:
            payload = {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            }
            with httpx.Client(timeout=_http_timeout(10)) as client:
                resp = client.post(
                    f"{self.config.base_url}/messages",
                    headers=self._build_headers(),
                    json=payload,
                )
                resp.raise_for_status()
            self.breaker.on_success()
            return True
        except Exception:
            self.breaker.on_failure()
            log.warning("anthropic health check failed", exc_info=True)
            return False

    def is_available(self) -> bool:
        return bool(self.config.api_key) and self.breaker.acquire()


# ═══════════════════════════════════════════════════════════════
# Groq Provider
# ═══════════════════════════════════════════════════════════════

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(_OpenAICompatProvider):
    """Proveedor Groq — Llama 3.3, Mixtral (FREE tier)."""

    def __init__(
        self,
        model_name: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout_seconds: int = 30,
    ):
        config = ProviderConfig(
            api_key=api_key or settings.groq_api_key,
            model_name=model_name,
            base_url=GROQ_BASE_URL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(config, groq_breaker)


# ═══════════════════════════════════════════════════════════════
# Gemini Provider (Google — FREE tier)
# ═══════════════════════════════════════════════════════════════

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Proveedor Google Gemini — gemini-2.5-flash (rápido), gemini-2.5-pro (potente).

    Usa el SDK google-generativeai con API key (no Vertex AI).
    Convierte formato OpenAI-style messages a formato Gemini.
    """

    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        api_key: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout_seconds: int = 60,
    ):
        config = ProviderConfig(
            api_key=api_key or settings.gemini_api_key,
            model_name=model_name,
            base_url=GEMINI_BASE_URL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(config, gemini_breaker)

    def _to_gemini_messages(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> tuple[str | None, list[dict]]:
        """Convierte mensajes OpenAI-style a formato Gemini.

        Gemini usa 'user' y 'model' como roles, con 'parts' en vez de 'content'.
        """
        gemini_msgs: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = (system_prompt or "") + "\n" + content
            elif role == "assistant":
                gemini_msgs.append({"role": "model", "parts": [{"text": content}]})
            else:
                gemini_msgs.append({"role": "user", "parts": [{"text": content}]})
        return system_prompt, gemini_msgs

    def _build_generation_config(self, **kwargs) -> dict:
        return {
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_output_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

    def _estimate_tokens(self, messages_text: str) -> int:
        """Estimación rápida: ~4 chars por token."""
        return max(1, len(messages_text) // 4)

    def chat_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        system, gemini_msgs = self._to_gemini_messages(messages, system_prompt)
        gen_config = self._build_generation_config(**kwargs)

        try:
            import google.generativeai as genai

            genai.configure(api_key=self.config.api_key)
            model = genai.GenerativeModel(
                model_name=self.config.model_name,
                generation_config=gen_config,
                system_instruction=system,
            )

            user_parts: list[str] = []
            for gm in gemini_msgs:
                parts = gm.get("parts", [])
                for p in parts:
                    text = p.get("text", "")
                    if text:
                        user_parts.append(text)

            combined_text = "\n\n".join(user_parts)

            log.info(
                "gemini request: model=%s messages=%d",
                self.config.model_name,
                len(gemini_msgs),
            )

            response = model.generate_content(combined_text)

            text = ""
            tokens_in = 0
            tokens_out = 0
            finish_reason = "stop"

            if response.candidates and response.candidates[0].content:
                parts = response.candidates[0].content.parts
                text = "".join(part.text for part in parts if hasattr(part, "text"))
                finish_reason = str(response.candidates[0].finish_reason.name).lower() if response.candidates[0].finish_reason else "stop"

            if response.usage_metadata:
                tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0)
                tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0)

            # Si no hay metadata de tokens, estimar
            if tokens_in == 0 and tokens_out == 0:
                tokens_in = self._estimate_tokens(combined_text)
                tokens_out = self._estimate_tokens(text)

            result = ChatResponse(
                text=text,
                model=response.model_version or self.config.model_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                finish_reason=finish_reason,
                usage={
                    "prompt_tokens": tokens_in,
                    "completion_tokens": tokens_out,
                },
                provider=self.provider_name,
            )

            log.info(
                "gemini response: model=%s finish=%s tokens=%d",
                result.model,
                result.finish_reason,
                result.total_tokens,
            )
            self.breaker.on_success()
            return result

        except RuntimeError:
            raise

        except Exception as e:
            self.breaker.on_failure()
            msg = str(e)
            log.error("gemini request error: %s", msg)
            if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
                raise RuntimeError(f"API key de Gemini inválida o sin crédito: {msg[:200]}")
            elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise RuntimeError("Límite de tasa de Gemini excedido.")
            raise RuntimeError(f"Error del proveedor Gemini: {msg[:300]}")

    async def stream_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, str | None], None]:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        system, gemini_msgs = self._to_gemini_messages(messages, system_prompt)
        gen_config = self._build_generation_config(**kwargs)

        try:
            import google.generativeai as genai

            genai.configure(api_key=self.config.api_key)
            model = genai.GenerativeModel(
                model_name=self.config.model_name,
                generation_config=gen_config,
                system_instruction=system,
            )

            user_parts: list[str] = []
            for gm in gemini_msgs:
                parts = gm.get("parts", [])
                for p in parts:
                    text = p.get("text", "")
                    if text:
                        user_parts.append(text)

            combined_text = "\n\n".join(user_parts)

            log.info(
                "gemini async stream: model=%s messages=%d",
                self.config.model_name,
                len(gemini_msgs),
            )

            # Gemini SDK no tiene stream async nativo; usamos asyncio.to_thread
            import asyncio

            response = await asyncio.to_thread(
                model.generate_content, combined_text, stream=True
            )

            for chunk in response:
                if chunk.candidates and chunk.candidates[0].content:
                    parts = chunk.candidates[0].content.parts
                    token = "".join(part.text for part in parts if hasattr(part, "text"))
                    if token:
                        yield token, None

                    if chunk.candidates[0].finish_reason:
                        finish = str(chunk.candidates[0].finish_reason.name).lower()
                        self.breaker.on_success()
                        yield "", finish
                        return

            self.breaker.on_success()
            yield "", "stop"

        except RuntimeError:
            raise

        except Exception as e:
            self.breaker.on_failure()
            msg = str(e)
            log.error("gemini stream error: %s", msg)
            if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
                raise RuntimeError(f"API key de Gemini inválida: {msg[:200]}")
            elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise RuntimeError("Límite de tasa de Gemini excedido.")
            raise RuntimeError(f"Error del proveedor Gemini: {msg[:300]}")

    def health_check(self) -> bool:
        """Ping mínimo con 1 token."""
        if not self.config.api_key:
            return False
        if not self.breaker.acquire():
            return False
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.config.api_key)
            model = genai.GenerativeModel(
                model_name=self.config.model_name,
                generation_config={"max_output_tokens": 1},
            )
            response = model.generate_content("ping")
            if response.candidates:
                self.breaker.on_success()
                return True
            self.breaker.on_failure()
            return False
        except Exception:
            self.breaker.on_failure()
            log.warning("gemini health check failed", exc_info=True)
            return False

    def is_available(self) -> bool:
        return bool(self.config.api_key) and self.breaker.acquire()


# ═══════════════════════════════════════════════════════════════
# Ollama Local Models
# ═══════════════════════════════════════════════════════════════

ollama_breaker = CircuitBreaker(
    name="ollama_provider",
    failure_threshold=3,
    recovery_timeout=60.0,
    half_open_max=1,
)


class OllamaProvider(LLMProvider):
    """Proveedor para modelos locales via Ollama (http://localhost:11434).

    Usa la API nativa de Ollama (/api/chat), que es OpenAI-compatible
    pero con diferencias en endpoints y formato de respuesta.

    Modelos se auto-descubren via GET /api/tags.
    """

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ):
        base_url = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        model = model_name or "llama3.2"
        config = ProviderConfig(
            api_key="ollama-local",  # Ollama no requiere API key
            model_name=model,
            base_url=base_url,
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", 0.7),
            timeout_seconds=kwargs.get("timeout_seconds", 120),
        )
        super().__init__(config, ollama_breaker)

    def _build_headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _build_payload(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> dict:
        full_messages: list[dict] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        return {
            "model": self.config.model_name,
            "messages": full_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "num_predict": kwargs.get("max_tokens", self.config.max_tokens),
            },
        }

    def chat_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        payload = self._build_payload(messages, system_prompt, **kwargs)

        log.info(
            "%s request: model=%s messages=%d",
            self.provider_name,
            self.config.model_name,
            len(payload["messages"]),
        )

        try:
            with httpx.Client(timeout=_http_timeout(self.config.timeout_seconds)) as client:
                response = client.post(
                    f"{self.config.base_url}/api/chat",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            message = data.get("message", {})
            text = message.get("content", "")
            result = ChatResponse(
                text=text,
                model=data.get("model", self.config.model_name),
                tokens_in=data.get("prompt_eval_count", 0),
                tokens_out=data.get("eval_count", 0),
                finish_reason=data.get("done_reason", "stop") if data.get("done") else None,
                provider=self.provider_name,
            )

            log.info(
                "%s response: model=%s finish=%s tokens=%d",
                self.provider_name,
                result.model,
                result.finish_reason,
                result.total_tokens,
            )
            self.breaker.on_success()
            return result

        except RuntimeError:
            raise

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("%s HTTP error %d: %s", self.provider_name, status, body)
            raise RuntimeError(f"Error del proveedor {self.provider_name} ({status}): {body[:200]}")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("%s request timeout after %ds", self.provider_name, self.config.timeout_seconds)
            raise RuntimeError(f"El proveedor {self.provider_name} no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("%s request failed", self.provider_name)
            raise RuntimeError(f"Error de conexión con {self.provider_name}: {e}")

    async def stream_completion(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[tuple[str, str | None], None]:
        if not self.breaker.acquire():
            raise RuntimeError(f"Proveedor {self.provider_name} no disponible temporalmente")

        payload = self._build_payload(messages, system_prompt, **kwargs)
        payload["stream"] = True

        log.info(
            "%s async stream: model=%s messages=%d",
            self.provider_name,
            self.config.model_name,
            len(payload["messages"]) - (1 if system_prompt else 0),
        )

        try:
            async with httpx.AsyncClient(
                timeout=_http_timeout(self.config.timeout_seconds),
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.base_url}/api/chat",
                    headers=self._build_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            message = chunk.get("message", {})
                            token = message.get("content", "")
                            done = chunk.get("done", False)
                            if token:
                                yield token, None
                            if done:
                                self.breaker.on_success()
                                yield "", chunk.get("done_reason", "stop")
                                return
                        except json.JSONDecodeError:
                            log.warning(
                                "%s stream parse error: %s",
                                self.provider_name,
                                line[:200],
                            )

        except httpx.HTTPStatusError as e:
            self.breaker.on_failure()
            status = e.response.status_code
            try:
                await e.response.aread()
                body = e.response.text[:500]
            except Exception:
                body = "(no body)"
            log.error("%s stream HTTP error %d: %s", self.provider_name, status, body)
            raise RuntimeError(f"Error del proveedor {self.provider_name} ({status}).")

        except httpx.TimeoutException:
            self.breaker.on_failure()
            log.error("%s stream timeout after %ds", self.provider_name, self.config.timeout_seconds)
            raise RuntimeError(f"El proveedor {self.provider_name} no respondió a tiempo.")

        except Exception as e:
            self.breaker.on_failure()
            log.exception("%s stream request failed", self.provider_name)
            raise RuntimeError(f"Error de conexión con {self.provider_name}: {e}")

    def health_check(self) -> bool:
        """Verifica que Ollama esté corriendo y tenga modelos disponibles.

        Usa GET /api/tags que lista los modelos instalados.
        """
        if not settings.ollama_enabled:
            return False
        if not self.breaker.acquire():
            return False
        try:
            with httpx.Client(timeout=_http_timeout(10)) as client:
                resp = client.get(
                    f"{self.config.base_url}/api/tags",
                )
                resp.raise_for_status()
                data = resp.json()
                models = data.get("models", [])
                if not models:
                    log.warning("Ollama health: sin modelos instalados")
                    return False
            self.breaker.on_success()
            return True
        except Exception:
            self.breaker.on_failure()
            log.warning("ollama health check failed", exc_info=True)
            return False

    def is_available(self) -> bool:
        return settings.ollama_enabled and self.breaker.acquire()


# ═══════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════

_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def create_provider(
    provider_name: str,
    model_name: str | None = None,
    api_key: str | None = None,
    **kwargs,
) -> LLMProvider | None:
    """Crea una instancia del proveedor solicitado.

    Args:
        provider_name: "deepseek", "openai", "anthropic", "groq"
        model_name: nombre del modelo (usa default del proveedor si None)
        api_key: API key (usa settings si None)
        **kwargs: max_tokens, temperature, timeout_seconds

    Returns:
        Instancia del proveedor o None si no está disponible.
    """
    cls = _PROVIDER_REGISTRY.get(provider_name.lower())
    if cls is None:
        return None

    provider = cls(model_name=model_name, api_key=api_key, **kwargs)
    if not provider.is_available():
        return None
    return provider


def get_available_provider_names() -> list[str]:
    """Lista proveedores con API key configurada y breaker no abierto."""
    available: list[str] = []
    for name in _PROVIDER_REGISTRY:
        provider = create_provider(name)
        if provider is not None and provider.is_available():
            available.append(name)
    return available
