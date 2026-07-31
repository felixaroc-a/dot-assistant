"""Music Generation — Suno, Udio, y fallback Edge TTS.

Proveedores:
  - Suno: API de generación de música con IA (SUNO_API_KEY)
  - Udio: API de generación de música con IA (UDIO_API_KEY)
  - Edge TTS: fallback gratuito que genera spoken word "musical"

Autoselección:
  auto → Suno > Udio > Edge TTS (mejor calidad primero)
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx
from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger("dot.music")

MAX_PROMPT_CHARS = 1200
MAX_DURATION = 120
MIN_DURATION = 10
DEFAULT_DURATION = 60

GENRES = [
    "pop", "rock", "hip-hop", "electronic", "lo-fi", "jazz", "classical",
    "ambient", "reggaeton", "salsa", "bachata", "ranchera", "cumbia",
    "vallenato", "reggae", "r&b", "trap", "dance", "folk",
]

MUSIC_COST_USD = 0.05  # costo estimado por generación


# ─── Proveedores ────────────────────────────────────────────────────────


class MusicProvider(ABC):
    """Proveedor base de generación de música."""

    name: ClassVar[str] = "base"

    @abstractmethod
    async def generate(self, prompt: str, duration: int, genre: str) -> dict:
        """Genera música y devuelve {"audio_base64", "format", "duration", "provider"}."""

    def available(self) -> bool:
        """True si el proveedor está configurado."""
        return True


class SunoProvider(MusicProvider):
    """Generación de música vía Suno API."""

    name: ClassVar[str] = "suno"
    SUNO_API_URL: ClassVar[str] = "https://api.suno.ai/v1"

    def available(self) -> bool:
        return bool((settings.suno_api_key or "").strip())

    async def generate(self, prompt: str, duration: int, genre: str) -> dict:
        api_key = (settings.suno_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="SUNO_API_KEY no configurada")

        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Prompt vacío para generación de música")

        duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))

        async with httpx.AsyncClient(timeout=120) as client:
            # Suno usa endpoint generate/v2 que retorna IDs, luego polling
            gen_resp = await client.post(
                f"{self.SUNO_API_URL}/generate",
                json={
                    "prompt": sanitized,
                    "duration": duration_clamped,
                    "genre": genre,
                    "make_instrumental": False,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if gen_resp.status_code == 401:
                raise HTTPException(503, detail="SUNO_API_KEY inválida")
            if gen_resp.status_code == 429:
                raise HTTPException(429, detail="Cuota Suno agotada")
            if gen_resp.status_code != 200:
                detail = gen_resp.text[:400]
                log.error("suno generate http=%s detail=%s", gen_resp.status_code, detail)
                raise HTTPException(502, detail="Error en Suno API")

            gen_data = gen_resp.json()
            clip_ids = gen_data.get("clips", [])
            if not clip_ids:
                raise HTTPException(502, detail="Suno no devolvió clips")

            # Polling hasta que el clip esté listo
            clip_id = clip_ids[0].get("id", "")
            for _poll in range(20):
                poll_resp = await client.get(
                    f"{self.SUNO_API_URL}/clips/{clip_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if poll_resp.status_code != 200:
                    await _httpx_sleep(3)
                    continue

                poll_data = poll_resp.json()
                status = poll_data.get("status", "")
                if status == "complete":
                    audio_url = poll_data.get("audio_url", "")
                    if audio_url:
                        audio_resp = await client.get(audio_url)
                        if audio_resp.status_code == 200:
                            return {
                                "audio_base64": base64.b64encode(audio_resp.content).decode("ascii"),
                                "format": "mp3",
                                "duration": duration_clamped,
                                "provider": "suno",
                            }
                    break
                elif status == "failed":
                    break
                await _httpx_sleep(5)

            raise HTTPException(502, detail="Suno no completó la generación a tiempo")


class UdioProvider(MusicProvider):
    """Generación de música vía Udio API."""

    name: ClassVar[str] = "udio"
    UDIO_API_URL: ClassVar[str] = "https://api.udio.com/v1"

    def available(self) -> bool:
        return bool((settings.udio_api_key or "").strip())

    async def generate(self, prompt: str, duration: int, genre: str) -> dict:
        api_key = (settings.udio_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="UDIO_API_KEY no configurada")

        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Prompt vacío para generación de música")

        duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.UDIO_API_URL}/generate",
                json={
                    "prompt": sanitized,
                    "duration": duration_clamped,
                    "genre": genre,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 401:
                raise HTTPException(503, detail="UDIO_API_KEY inválida")
            if resp.status_code == 429:
                raise HTTPException(429, detail="Cuota Udio agotada")
            if resp.status_code != 200:
                detail = resp.text[:400]
                log.error("udio generate http=%s detail=%s", resp.status_code, detail)
                raise HTTPException(502, detail="Error en Udio API")

            data = resp.json()
            audio_b64 = data.get("audio_base64", data.get("audio", ""))
            if not audio_b64:
                raise HTTPException(502, detail="Udio no devolvió audio")

            return {
                "audio_base64": audio_b64,
                "format": data.get("format", "mp3"),
                "duration": duration_clamped,
                "provider": "udio",
            }


class EdgeTTSMusicProvider(MusicProvider):
    """Fallback: genera spoken word 'musical' con Edge TTS.

    No es música real, pero permite probar el flujo sin APIs de pago.
    """

    name: ClassVar[str] = "edge_tts"

    async def generate(self, prompt: str, duration: int, genre: str) -> dict:
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Prompt vacío")

        # Construir un texto hablado descriptivo
        tts_text = (
            f"Esto es una simulación de música. "
            f"Género: {genre}. "
            f"Prompt: {sanitized}. "
            f"Para música real, configura SUNO_API_KEY o UDIO_API_KEY."
        )

        try:
            import edge_tts  # type: ignore[import-untyped]

            voice = "es-CO-SalomeNeural"
            communicate = edge_tts.Communicate(tts_text, voice)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            audio_bytes = b"".join(chunks)

            return {
                "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "format": "mp3",
                "duration": duration or DEFAULT_DURATION,
                "provider": "edge_tts",
            }
        except ImportError:
            log.error("edge-tts no instalado. Ejecuta: pip install edge-tts")
            raise HTTPException(
                503, detail="Ningún proveedor de música configurado. Instala edge-tts o configura SUNO_API_KEY."
            ) from None
        except Exception as exc:
            log.exception("edge_tts music fallback error")
            raise HTTPException(502, detail=f"Error en fallback TTS: {exc}") from exc


# ─── Registro de proveedores ─────────────────────────────────────────────


def _get_music_providers() -> list[MusicProvider]:
    """Devuelve proveedores ordenados por prioridad: Suno > Udio > Edge TTS."""
    providers: list[MusicProvider] = []
    if settings.suno_api_key:
        providers.append(SunoProvider())
    if settings.udio_api_key:
        providers.append(UdioProvider())
    providers.append(EdgeTTSMusicProvider())
    return providers


def music_configured() -> bool:
    """True si al menos un proveedor de música está disponible."""
    for p in _get_music_providers():
        if p.available():
            return True
    return False


def get_available_music_providers() -> list[dict[str, object]]:
    """Devuelve lista de proveedores con estado."""
    result: list[dict[str, object]] = []
    for p in _get_music_providers():
        result.append({
            "name": p.name,
            "available": p.available(),
        })
    return result


def get_genres() -> list[str]:
    """Devuelve géneros disponibles."""
    return sorted(GENRES)


async def _httpx_sleep(seconds: float) -> None:
    """Sleep asíncrono para polling."""
    import asyncio
    await asyncio.sleep(seconds)


async def generate_music(
    prompt: str,
    duration: int = DEFAULT_DURATION,
    genre: str = "pop",
    provider: str = "auto",
) -> dict:
    """Genera un clip de música con el proveedor elegido.

    Args:
        prompt: Descripción de la música deseada.
        duration: Duración en segundos (10-120, default 60).
        genre: Género musical (pop, rock, electronic, etc.).
        provider: "auto", "suno", "udio", "edge_tts".

    Returns:
        dict con {"audio_base64", "format", "duration", "provider", "genre", "prompt_used"}
    """
    providers = _get_music_providers()

    if provider != "auto":
        selected = next((p for p in providers if p.name == provider), None)
        if not selected:
            raise HTTPException(400, detail=f"Proveedor '{provider}' no disponible")
        if not selected.available():
            raise HTTPException(503, detail=f"Proveedor '{provider}' no configurado")
    else:
        available = [p for p in providers if p.available()]
        if not available:
            raise HTTPException(
                503,
                detail="Ningún proveedor de música configurado. Instala edge-tts o configura SUNO_API_KEY.",
            )
        selected = available[0]

    duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))
    genre_sanitized = genre.strip().lower() if genre else "pop"
    if genre_sanitized not in GENRES:
        genre_sanitized = "pop"

    log.info(
        "music generate provider=%s genre=%s duration=%s chars=%s",
        selected.name, genre_sanitized, duration_clamped, len(prompt),
    )

    try:
        result = await selected.generate(prompt, duration_clamped, genre_sanitized)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("music generate unexpected error provider=%s", selected.name)
        raise HTTPException(500, detail=f"Error interno de música ({selected.name})") from exc

    result["genre"] = genre_sanitized
    result["prompt_used"] = (prompt or "").strip()[:MAX_PROMPT_CHARS]

    return result
