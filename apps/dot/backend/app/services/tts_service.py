"""TTS multi-proveedor — Gemini, Edge (gratis), ElevenLabs.

Proveedores:
  - Gemini: Google Cloud Text-to-Speech REST API (GEMINI_API_KEY)
  - Edge: Microsoft Edge TTS (edge-tts, FREE, sin API key)
  - ElevenLabs: ElevenLabs API (ELEVENLABS_API_KEY, opcional)

Autoselección:
  auto → ElevenLabs > Edge > Gemini (gratis primero si hay opción)
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx
from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger("dot.tts")

GEMINI_TTS_URL = "https://texttospeech.googleapis.com/v1"
MAX_CHARS = 5000

# Voces disponibles por proveedor
VOICE_CATALOG: dict[str, list[str]] = {
    "gemini": [
        "es-ES-Standard-A", "es-ES-Standard-B", "es-ES-Standard-C",
        "es-ES-Standard-D", "es-ES-Wavenet-A", "es-ES-Wavenet-B",
        "es-ES-Wavenet-C", "es-ES-Wavenet-D", "es-US-Standard-A",
        "es-US-Wavenet-A", "en-US-Standard-A", "en-US-Wavenet-A",
    ],
    "edge": [
        "es-CO-SalomeNeural", "es-CO-GonzaloNeural",
        "es-MX-DaliaNeural", "es-MX-JorgeNeural",
        "es-ES-AlvaroNeural", "es-ES-ElviraNeural",
        "es-AR-ElenaNeural", "es-AR-TomasNeural",
        "es-CL-CatalinaNeural", "es-CL-LorenzoNeural",
        "es-PE-CamilaNeural", "es-PE-AlexNeural",
        "es-VE-PaolaNeural", "es-VE-SebastianNeural",
        "es-US-AlonsoNeural", "es-US-PalomaNeural",
        "en-US-AriaNeural", "en-US-GuyNeural",
        "en-US-JennyNeural", "en-GB-SoniaNeural",
        "en-GB-RyanNeural", "en-AU-NatashaNeural",
    ],
    "elevenlabs": [
        "rachel", "adam", "antoni", "josh", "bella",
        "nicole", "arnold", "dorothy", "mimi",
    ],
}

DEFAULT_GEMINI_VOICE = "es-ES-Standard-A"
DEFAULT_EDGE_VOICE = "es-CO-SalomeNeural"
DEFAULT_ELEVENLABS_VOICE = "rachel"


# ─── Proveedores ────────────────────────────────────────────────────────


class TTSProvider(ABC):
    """Proveedor base de TTS."""

    name: ClassVar[str] = "base"

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> bytes:
        """Devuelve audio MP3 como bytes."""

    def available(self) -> bool:
        """True si el proveedor está configurado y usable."""
        return True


class GeminiTTSProvider(TTSProvider):
    """TTS via Google Cloud Text-to-Speech REST API."""

    name: ClassVar[str] = "gemini"

    def available(self) -> bool:
        return bool((settings.gemini_api_key or "").strip())

    async def synthesize(self, text: str, voice: str) -> bytes:
        api_key = (settings.gemini_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="GEMINI_API_KEY no configurada para TTS")

        sanitized = (text or "").strip()[:MAX_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Texto vacío para sintetizar")

        voice_name = voice if voice.strip() else DEFAULT_GEMINI_VOICE
        parts = voice_name.rsplit("-", 1)
        language_code = parts[0] if len(parts) == 2 else "es-ES"

        payload = {
            "input": {"text": sanitized},
            "voice": {"languageCode": language_code, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3"},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GEMINI_TTS_URL}/text:synthesize",
                json=payload,
                params={"key": api_key},
            )
            if resp.status_code != 200:
                detail = resp.text[:400]
                log.error("tts gemini http=%s detail=%s", resp.status_code, detail)
                if resp.status_code in (401, 403):
                    raise HTTPException(503, detail="GEMINI_API_KEY inválida para TTS")
                if resp.status_code == 429:
                    raise HTTPException(429, detail="Cuota Google TTS agotada")
                raise HTTPException(502, detail="Error en síntesis Gemini TTS")

            data = resp.json()
            audio_b64 = data.get("audioContent", "")
            if not audio_b64:
                raise HTTPException(502, detail="TTS sin audio en respuesta")
            return base64.b64decode(audio_b64)


class EdgeTTSProvider(TTSProvider):
    """TTS gratuito via Microsoft Edge (edge-tts)."""

    name: ClassVar[str] = "edge"

    async def synthesize(self, text: str, voice: str) -> bytes:
        sanitized = (text or "").strip()[:MAX_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Texto vacío para sintetizar")

        voice_name = voice if voice.strip() else DEFAULT_EDGE_VOICE

        try:
            import edge_tts  # type: ignore[import-untyped]

            communicate = edge_tts.Communicate(sanitized, voice_name)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)
        except ImportError:
            log.error("edge-tts no instalado. Ejecuta: pip install edge-tts")
            raise HTTPException(503, detail="Edge TTS no disponible (librería no instalada)")
        except Exception as exc:
            log.exception("edge_tts synthesize error")
            raise HTTPException(502, detail=f"Error en Edge TTS: {exc}") from exc


class ElevenLabsTTSProvider(TTSProvider):
    """TTS via ElevenLabs API."""

    name: ClassVar[str] = "elevenlabs"

    ELEVENLABS_URL: ClassVar[str] = "https://api.elevenlabs.io/v1"

    def available(self) -> bool:
        return bool((settings.elevenlabs_api_key or "").strip())

    async def synthesize(self, text: str, voice: str) -> bytes:
        api_key = (settings.elevenlabs_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="ELEVENLABS_API_KEY no configurada")

        sanitized = (text or "").strip()[:MAX_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Texto vacío para sintetizar")

        voice_id = voice if voice.strip() else DEFAULT_ELEVENLABS_VOICE

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.ELEVENLABS_URL}/text-to-speech/{voice_id}",
                json={
                    "text": sanitized,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
            )
            if resp.status_code != 200:
                detail = resp.text[:400]
                log.error("tts elevenlabs http=%s detail=%s", resp.status_code, detail)
                if resp.status_code == 401:
                    raise HTTPException(503, detail="ELEVENLABS_API_KEY inválida")
                if resp.status_code == 429:
                    raise HTTPException(429, detail="Cuota ElevenLabs agotada")
                raise HTTPException(502, detail="Error en ElevenLabs TTS")
            return resp.content


# ─── Registro de proveedores ─────────────────────────────────────────────


def _get_tts_providers() -> list[TTSProvider]:
    """Devuelve proveedores ordenados por prioridad de selección.

    Prioridad: ElevenLabs > Edge > Gemini (gratis primero si disponible).
    """
    providers: list[TTSProvider] = []
    # ElevenLabs (si hay key)
    if settings.elevenlabs_api_key:
        providers.append(ElevenLabsTTSProvider())
    # Edge (siempre disponible, gratis)
    providers.append(EdgeTTSProvider())
    # Gemini (si hay key)
    if settings.gemini_api_key:
        providers.append(GeminiTTSProvider())
    return providers


def tts_configured() -> bool:
    """True si al menos un proveedor TTS está configurado."""
    for p in _get_tts_providers():
        if p.available():
            return True
    return False


def get_available_tts_providers() -> list[dict[str, object]]:
    """Devuelve lista de proveedores disponibles con sus voces."""
    result: list[dict[str, object]] = []
    for p in _get_tts_providers():
        result.append({
            "name": p.name,
            "available": p.available(),
            "voices": VOICE_CATALOG.get(p.name, []),
        })
    return result


async def synthesize_speech(
    text: str,
    voice: str = "auto",
    provider: str = "auto",
) -> dict:
    """Sintetiza texto a voz con el proveedor elegido.

    Args:
        text: Texto a sintetizar (máx ~5000 caracteres).
        voice: Nombre de la voz o "auto" para usar default del proveedor.
        provider: "auto" (mejor disponible), "gemini", "edge", "elevenlabs".

    Returns:
        dict con {"audio_base64": str, "format": "mp3", "provider": str}
    """
    providers = _get_tts_providers()

    if provider != "auto":
        selected = next((p for p in providers if p.name == provider), None)
        if not selected:
            raise HTTPException(400, detail=f"Proveedor TTS '{provider}' no disponible")
        if not selected.available():
            raise HTTPException(503, detail=f"Proveedor TTS '{provider}' no configurado")
    else:
        available = [p for p in providers if p.available()]
        if not available:
            raise HTTPException(503, detail="Ningún proveedor TTS configurado. Instala edge-tts o configura GEMINI_API_KEY.")
        selected = available[0]

    resolved_voice: str
    if voice == "auto":
        defaults = {
            "gemini": DEFAULT_GEMINI_VOICE,
            "edge": DEFAULT_EDGE_VOICE,
            "elevenlabs": DEFAULT_ELEVENLABS_VOICE,
        }
        resolved_voice = defaults.get(selected.name, "auto")
    else:
        resolved_voice = voice

    log.info(
        "tts synthesize provider=%s voice=%s chars=%s",
        selected.name, resolved_voice, len(text),
    )

    try:
        audio_bytes = await selected.synthesize(text, resolved_voice)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("tts synthesize unexpected error provider=%s", selected.name)
        raise HTTPException(500, detail=f"Error interno TTS ({selected.name})") from exc

    return {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "mp3",
        "provider": selected.name,
    }
