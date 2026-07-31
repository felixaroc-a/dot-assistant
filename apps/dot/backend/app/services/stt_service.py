"""STT multi-proveedor — Gemini, OpenAI Whisper.

Proveedores:
  - Gemini: via generateContent + inline_data (GEMINI_API_KEY)
  - Whisper: via OpenAI Transcription API (OPENAI_API_KEY)

Autoselección:
  auto → Whisper > Gemini (Whisper mejor STT, Gemini es multimodal).
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx
from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger("dot.stt")

# Mensajes orientados al usuario (sin nombres de proveedor ni claves técnicas).
STT_UNAVAILABLE = "La transcripción por voz no está disponible en el servidor."
STT_FAILED = "No pudimos transcribir tu voz. Inténtalo de nuevo."
STT_QUOTA = "Has alcanzado el límite de transcripción. Inténtalo más tarde."
STT_AUDIO_TOO_SHORT = "Audio demasiado corto. Habla un poco más e inténtalo de nuevo."

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

ALLOWED_AUDIO_MIMES = frozenset({
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/mp3",
    "audio/flac",
})


def _normalize_mime(mime: str) -> str:
    raw = (mime or "").split(";")[0].strip().lower()
    if raw in ALLOWED_AUDIO_MIMES:
        return raw
    if raw.startswith("audio/"):
        return raw
    return "audio/webm"


def _transcribe_prompt(language: str) -> str:
    lang = (language or "es").strip().lower()[:8] or "es"
    return (
        f"Transcribe exactly what the user says in the audio. "
        f"Prefer language code '{lang}' if the speech matches it. "
        "Return ONLY the transcribed text, without quotes or explanations. "
        "If the audio is empty or unintelligible, reply exactly: (sin audio)"
    )


# ─── Proveedores ────────────────────────────────────────────────────────


class STTProvider(ABC):
    """Proveedor base de STT."""

    name: ClassVar[str] = "base"

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str) -> str:
        """Transcribe audio y devuelve texto."""

    def available(self) -> bool:
        """True si el proveedor está configurado y usable."""
        return True


class GeminiSTTProvider(STTProvider):
    """STT via Gemini generateContent + inline_data."""

    name: ClassVar[str] = "gemini"

    def available(self) -> bool:
        return bool((settings.gemini_api_key or "").strip())

    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str) -> str:
        api_key = (settings.gemini_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail=STT_UNAVAILABLE)

        if len(audio_bytes) < 64:
            raise HTTPException(400, detail=STT_AUDIO_TOO_SHORT)

        mime = _normalize_mime(mime_type)
        model = (settings.gemini_model or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        url = f"{GEMINI_BASE_URL}/{model}:generateContent"
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "contents": [{
                "parts": [
                    {"text": _transcribe_prompt(language)},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, params={"key": api_key})
            if resp.status_code != 200:
                detail = resp.text[:400]
                log.error("stt gemini http=%s detail=%s", resp.status_code, detail)
                if resp.status_code in (401, 403):
                    raise HTTPException(503, detail=STT_FAILED)
                if resp.status_code == 429:
                    raise HTTPException(429, detail=STT_QUOTA)
                raise HTTPException(502, detail=STT_FAILED)

            data = resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text += str(part["text"])
        text = text.strip()
        return "" if text == "(sin audio)" else text


class WhisperSTTProvider(STTProvider):
    """STT via OpenAI Whisper API."""

    name: ClassVar[str] = "whisper"

    def available(self) -> bool:
        return bool((settings.openai_api_key or "").strip())

    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str) -> str:
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail=STT_UNAVAILABLE)

        if len(audio_bytes) < 64:
            raise HTTPException(400, detail=STT_AUDIO_TOO_SHORT)

        mime = _normalize_mime(mime_type)
        # Whisper API espera formatos: flac, m4a, mp3, mp4, mpeg, mpga, oga, ogg, wav, webm
        ext = "webm"
        if "mp3" in mime or "mpeg" in mime:
            ext = "mp3"
        elif "ogg" in mime:
            ext = "ogg"
        elif "wav" in mime or "x-wav" in mime:
            ext = "wav"
        elif "flac" in mime:
            ext = "flac"
        elif "mp4" in mime:
            ext = "m4a"

        lang_code = (language or "es").strip().lower()[:2] or "es"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                WHISPER_API_URL,
                files={"file": (f"audio.{ext}", audio_bytes, mime)},
                data={
                    "model": "whisper-1",
                    "language": lang_code,
                    "response_format": "json",
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                detail = resp.text[:400]
                log.error("stt whisper http=%s detail=%s", resp.status_code, detail)
                if resp.status_code == 401:
                    raise HTTPException(503, detail=STT_FAILED)
                if resp.status_code == 429:
                    raise HTTPException(429, detail=STT_QUOTA)
                raise HTTPException(502, detail=STT_FAILED)

            data = resp.json()
            text = data.get("text", "").strip()
            return text


# ─── Registro y fábrica ──────────────────────────────────────────────────


def _get_stt_providers() -> list[STTProvider]:
    """Devuelve proveedores STT ordenados por prioridad.

    Prioridad: Whisper > Gemini (Whisper es mejor para STT puro).
    """
    providers: list[STTProvider] = []
    if settings.openai_api_key:
        providers.append(WhisperSTTProvider())
    if settings.gemini_api_key:
        providers.append(GeminiSTTProvider())
    return providers


def stt_configured() -> bool:
    """True si al menos un proveedor STT está configurado."""
    for p in _get_stt_providers():
        if p.available():
            return True
    return False


def get_available_stt_providers() -> list[dict[str, object]]:
    """Devuelve lista de proveedores STT disponibles."""
    result: list[dict[str, object]] = []
    for p in _get_stt_providers():
        result.append({
            "name": p.name,
            "available": p.available(),
        })
    return result


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str,
    language: str = "es",
    provider: str = "auto",
) -> str:
    """Transcribe audio con el proveedor elegido.

    Args:
        audio_bytes: Audio como bytes.
        mime_type: MIME type del audio (ej: audio/webm).
        language: Código de idioma (es, en, etc.).
        provider: "auto" (mejor disponible), "gemini", "whisper".

    Returns:
        Texto transcrito.
    """
    providers = _get_stt_providers()

    if provider != "auto":
        selected = next((p for p in providers if p.name == provider), None)
        if not selected:
            raise HTTPException(400, detail=STT_UNAVAILABLE)
        if not selected.available():
            raise HTTPException(503, detail=STT_UNAVAILABLE)
    else:
        available = [p for p in providers if p.available()]
        if not available:
            raise HTTPException(503, detail=STT_UNAVAILABLE)
        selected = available[0]

    log.info(
        "stt transcribe provider=%s bytes=%s lang=%s",
        selected.name, len(audio_bytes), language,
    )

    try:
        text = await selected.transcribe(audio_bytes, mime_type, language)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("stt transcribe unexpected error provider=%s", selected.name)
        raise HTTPException(500, detail=STT_FAILED) from exc

    log.info(
        "stt transcribe ok provider=%s chars=%s",
        selected.name, len(text),
    )
    return text
