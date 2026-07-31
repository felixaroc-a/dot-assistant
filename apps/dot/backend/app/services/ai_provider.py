"""
Proveedor de IA para DOT — conecta con Deepseek (compatible con API OpenAI).

Proposito:
- Enviar mensajes al modelo de Deepseek y obtener respuestas reales.
- Manejar errores de conexion, rate limits y timeouts.
- Soporte para streaming (preparado para Fase 2+).
- Protección con Circuit Breaker para evitar cascadas de fallos.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.services.circuit_breaker import deepseek_breaker
from app.settings import settings

log = logging.getLogger("dot.ai_provider")

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# Modelos disponibles
MODEL_CHAT = "deepseek-chat"       # Modelo principal de chat
MODEL_REASONER = "deepseek-reasoner"  # Modelo razonador (mas lento pero mas preciso)


def _deepseek_http_timeout(seconds: int) -> httpx.Timeout:
    """Timeout soft T06b: connect corto; read acotado (streaming tolera pausas entre chunks)."""
    return httpx.Timeout(connect=5.0, read=float(seconds), write=30.0, pool=5.0)


@dataclass
class AIResponse:
    content: str
    model: str
    finish_reason: str | None = None
    usage: dict | None = None


@dataclass
class AIConfig:
    api_key: str
    base_url: str = DEEPSEEK_BASE_URL
    model: str = MODEL_CHAT
    max_tokens: int = 8192
    temperature: float = 0.7
    timeout_seconds: int = 30


class AIProvider:
    """
    Proveedor de IA que usa la API de Deepseek (compatible OpenAI).
    """

    def __init__(self, config: AIConfig | None = None):
        if config:
            self.config = config
        else:
            self.config = AIConfig(
                api_key=settings.deepseek_api_key,
                model=settings.default_chat_model or MODEL_CHAT,
                timeout_seconds=settings.deepseek_chat_timeout_seconds,
            )

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list[dict], system_prompt: str | None = None) -> AIResponse:
        """
        Envia un historial de mensajes al modelo y devuelve la respuesta.
        """
        if not deepseek_breaker.acquire():
            raise RuntimeError("Proveedor IA no disponible temporalmente")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.config.model,
            "messages": full_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        log.info(
            "AI request: model=%s messages=%d tokens=%d",
            self.config.model,
            len(full_messages),
            self.config.max_tokens,
        )

        try:
            with httpx.Client(timeout=_deepseek_http_timeout(self.config.timeout_seconds)) as client:
                response = client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            choice = data["choices"][0]
            result = AIResponse(
                content=choice["message"]["content"],
                model=data.get("model", self.config.model),
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage"),
            )

            log.info(
                "AI response: model=%s finish=%s tokens=%s",
                result.model,
                result.finish_reason,
                result.usage.get("total_tokens") if result.usage else "?",
            )
            deepseek_breaker.on_success()
            return result

        except RuntimeError:
            raise

        except httpx.HTTPStatusError as e:
            deepseek_breaker.on_failure()
            status = e.response.status_code
            body = e.response.text[:500]
            log.error("AI HTTP error %d: %s", status, body)

            if status == 401:
                raise RuntimeError("API key de Deepseek invalida o sin credito.")
            elif status == 429:
                raise RuntimeError("Limite de tasa de Deepseek excedido. Espera un momento.")
            elif status == 402:
                raise RuntimeError("Cuenta de Deepseek sin credito suficiente.")
            else:
                raise RuntimeError(f"Error del proveedor IA ({status}).")

        except httpx.TimeoutException:
            deepseek_breaker.on_failure()
            log.error("AI request timeout after %ds", self.config.timeout_seconds)
            raise RuntimeError("El proveedor IA no respondio a tiempo.")

        except Exception as e:
            deepseek_breaker.on_failure()
            log.exception("AI request failed")
            raise RuntimeError(f"Error de conexion con el proveedor IA: {e}")

    def simple_chat(self, user_message: str, system_prompt: str | None = None) -> str:
        """
        Metodo simplificado: un solo mensaje de usuario, devuelve solo el texto.
        """
        messages = [{"role": "user", "content": user_message}]
        result = self.chat(messages, system_prompt)
        return result.content

    def chat_stream(
        self, messages: list[dict], system_prompt: str | None = None
    ):
        """Deprecado: usa async_chat_stream para evitar bloqueo del event loop."""
        import warnings
        warnings.warn("chat_stream es síncrono; usa async_chat_stream", DeprecationWarning)

        if not deepseek_breaker.acquire():
            raise RuntimeError("Proveedor IA no disponible temporalmente")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.config.model,
            "messages": full_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": True,
        }

        log.info(
            "AI stream request: model=%s messages=%d",
            self.config.model,
            len(full_messages),
        )

        try:
            with httpx.Client(timeout=_deepseek_http_timeout(self.config.timeout_seconds)) as client:
                with client.stream(
                    "POST",
                    f"{self.config.base_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                deepseek_breaker.on_success()
                                yield "", "stop"
                                return
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content", "")
                                finish_reason = chunk.get("choices", [{}])[0].get(
                                    "finish_reason"
                                )
                                if token:
                                    yield token, None
                                if finish_reason:
                                    deepseek_breaker.on_success()
                                    yield "", finish_reason
                                    return
                            except json.JSONDecodeError:
                                log.warning(
                                    "Error parseando chunk streaming: %s",
                                    data_str[:200],
                                )

        except httpx.HTTPStatusError as e:
            deepseek_breaker.on_failure()
            status = e.response.status_code
            try:
                e.response.read()
                body = e.response.text[:500]
            except Exception:
                body = "(could not read response body)"
            log.error("AI stream HTTP error %d: %s", status, body)
            if status == 401:
                raise RuntimeError("API key de Deepseek invalida o sin credito.")
            elif status == 429:
                raise RuntimeError("Limite de tasa de Deepseek excedido.")
            elif status == 402:
                raise RuntimeError("Cuenta de Deepseek sin credito suficiente.")
            else:
                raise RuntimeError(f"Error del proveedor IA ({status}).")

        except httpx.TimeoutException:
            deepseek_breaker.on_failure()
            log.error("AI stream timeout after %ds", self.config.timeout_seconds)
            raise RuntimeError("El proveedor IA no respondio a tiempo.")

        except Exception as e:
            deepseek_breaker.on_failure()
            log.exception("AI stream request failed")
            raise RuntimeError(f"Error de conexion con el proveedor IA: {e}")

    async def async_chat_stream(
        self, messages: list[dict], system_prompt: str | None = None
    ):
        """
        Streaming nativo async con httpx.AsyncClient.
        No bloquea el event loop de FastAPI.
        """
        if not deepseek_breaker.acquire():
            raise RuntimeError("Proveedor IA no disponible temporalmente")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.config.model,
            "messages": full_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": True,
        }

        log.info(
            "AI async stream request: model=%s messages=%d",
            self.config.model,
            len(full_messages),
        )

        try:
            async with httpx.AsyncClient(
                timeout=_deepseek_http_timeout(self.config.timeout_seconds),
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
                                deepseek_breaker.on_success()
                                yield "", "stop"
                                return
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content", "")
                                finish_reason = chunk.get("choices", [{}])[0].get(
                                    "finish_reason"
                                )
                                if token:
                                    yield token, None
                                if finish_reason:
                                    deepseek_breaker.on_success()
                                    yield "", finish_reason
                                    return
                            except json.JSONDecodeError:
                                log.warning(
                                    "Error parseando chunk streaming: %s",
                                    data_str[:200],
                                )

        except httpx.HTTPStatusError as e:
            deepseek_breaker.on_failure()
            status = e.response.status_code
            try:
                await e.response.aread()
                body = e.response.text[:500]
            except Exception:
                body = "(could not read response body)"
            log.error("AI stream HTTP error %d: %s", status, body)
            if status == 401:
                raise RuntimeError("API key de Deepseek invalida o sin credito.")
            elif status == 429:
                raise RuntimeError("Limite de tasa de Deepseek excedido.")
            elif status == 402:
                raise RuntimeError("Cuenta de Deepseek sin credito suficiente.")
            else:
                raise RuntimeError(f"Error del proveedor IA ({status}).")

        except httpx.TimeoutException:
            deepseek_breaker.on_failure()
            log.error("AI stream timeout after %ds", self.config.timeout_seconds)
            raise RuntimeError("El proveedor IA no respondio a tiempo.")

        except Exception as e:
            deepseek_breaker.on_failure()
            log.exception("AI stream request failed")
            raise RuntimeError(f"Error de conexion con el proveedor IA: {e}")
