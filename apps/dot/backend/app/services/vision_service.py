"""Servicio de visión IA con rutas hacia Gemini API key o Vertex Vision."""
from __future__ import annotations

import base64
import logging

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services.circuit_breaker import vertex_vision_breaker
from app.services.vision_vertex_service import analyze_image as analyze_image_vertex
from app.settings import settings

log = logging.getLogger("dot.vision")

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _handle_gemini_error(status_code: int, detail: str) -> None:
    raise HTTPException(status_code=status_code, detail=detail)


def _extract_gemini_error_detail(response: httpx.Response) -> str | None:
    if not response.text:
        return None
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if message:
                return str(message)
        message = payload.get("message")
        if message:
            return str(message)
    if isinstance(payload, str):
        return payload.strip()
    return response.text.strip()


def _resolve_gemini_model(model: str | None) -> str:
    normalized = (model or DEFAULT_GEMINI_MODEL).strip()
    if not normalized:
        return DEFAULT_GEMINI_MODEL
    return normalized


def _assemble_payload(image_base64: str, prompt: str, mime_type: str) -> dict[str, object]:
    return {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 1024,
        },
    }


async def _call_gemini_api(
    image_base64: str,
    prompt: str,
    mime_type: str,
    api_key: str,
    model: str | None,
) -> str:
    if not api_key:
        _handle_gemini_error(
            503,
            "Vision no disponible: API key de Gemini no configurada",
        )

    resolved_model = _resolve_gemini_model(model)
    url = f"{GEMINI_BASE_URL}/{resolved_model}:generateContent"
    params = {"key": api_key}
    payload = _assemble_payload(image_base64, prompt, mime_type)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, params=params)
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return text

            return "[Gemini no generó contenido]"

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        detail = _extract_gemini_error_detail(exc.response)
        log.error(
            "Gemini API error: %s - %s",
            status_code,
            detail or exc.response.text[:500],
        )
        if status_code == 429:
            _handle_gemini_error(
                status_code,
                "Gemini limitó temporalmente la solicitud (cuota/rate limit). Intenta más tarde o revisa cuota/API key.",
            )
        if status_code == 403:
            user_detail = "API key sin permiso para Gemini/modelo o restricciones de clave."
            if detail:
                user_detail = f"{user_detail} Detalle: {detail}"
            user_detail += (
                " Revisa Google Cloud Console > APIs y servicios > Credenciales, habilita generativeLanguage.googleapis.com "
                "y asegúrate de que la clave pueda llamar al modelo seleccionado."
            )
            _handle_gemini_error(status_code, user_detail)
        _handle_gemini_error(
            status_code,
            "Error al analizar la imagen con Gemini. Intenta de nuevo más tarde.",
        )
    except Exception as exc:
        log.error("Error inesperado en Gemini Vision: %s", exc)
        _handle_gemini_error(500, "Error interno al analizar la imagen.")


async def analyze_image(
    image_bytes: bytes,
    mime_type: str,
    prompt: str = "Describe esta imagen en detalle.",
) -> str:
    """Selecciona el proveedor de visión (api_key o vertex) y retorna el análisis."""
    provider = settings.normalized_gemini_provider
    mime_type_normalized = (mime_type or "image/jpeg").strip() or "image/jpeg"

    if provider == "vertex":
        if not vertex_vision_breaker.acquire():
            raise HTTPException(
                status_code=503,
                detail="Proveedor IA no disponible temporalmente",
            )
        try:
            result = await run_in_threadpool(
                analyze_image_vertex,
                image_bytes,
                mime_type_normalized,
                prompt,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
                model_name=settings.gemini_vertex_model,
            )
            vertex_vision_breaker.on_success()
            return result
        except HTTPException:
            vertex_vision_breaker.on_failure()
            raise
        except Exception as exc:
            vertex_vision_breaker.on_failure()
            log.error("Error al ejecutar Vertex Vision: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Error interno al analizar la imagen con Vertex Vision.",
            )

    return await _call_gemini_api(
        base64.b64encode(image_bytes).decode(),
        prompt,
        mime_type_normalized,
        settings.gemini_api_key,
        settings.gemini_model,
    )


def is_image_content(content_type: str) -> bool:
    """Detecta si un tipo de contenido es una imagen."""
    return content_type.startswith("image/")
