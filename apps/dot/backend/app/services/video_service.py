"""Video Generation — RunwayML y fallback slideshow con TTS.

Proveedores:
  - RunwayML: generación de video con IA (RUNWAY_API_KEY)
  - Slideshow: fallback que genera secuencia de imágenes + narración TTS

Autoselección:
  auto → RunwayML > Slideshow
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx
from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger("dot.video")

MAX_PROMPT_CHARS = 2000
MIN_DURATION = 4
MAX_DURATION = 30
DEFAULT_DURATION = 10

VIDEO_COST_USD = 0.15  # costo estimado por generación


# ─── Proveedores ────────────────────────────────────────────────────────


class VideoProvider(ABC):
    """Proveedor base de generación de video."""

    name: ClassVar[str] = "base"

    @abstractmethod
    async def generate(self, prompt: str, duration: int) -> dict:
        """Genera video y devuelve {"video_base64", "format", "duration", "provider"}."""

    def available(self) -> bool:
        """True si el proveedor está configurado."""
        return True


class RunwayMLProvider(VideoProvider):
    """Generación de video vía RunwayML API (Gen-3)."""

    name: ClassVar[str] = "runwayml"
    RUNWAY_API_URL: ClassVar[str] = "https://api.runwayml.com/v1"

    def available(self) -> bool:
        return bool((settings.runway_api_key or "").strip())

    async def generate(self, prompt: str, duration: int) -> dict:
        api_key = (settings.runway_api_key or "").strip()
        if not api_key:
            raise HTTPException(503, detail="RUNWAY_API_KEY no configurada")

        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Prompt vacío para generación de video")

        duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))

        async with httpx.AsyncClient(timeout=180) as client:
            # Iniciar generación
            gen_resp = await client.post(
                f"{self.RUNWAY_API_URL}/generate",
                json={
                    "prompt": sanitized,
                    "duration": duration_clamped,
                    "model": "gen3",
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if gen_resp.status_code == 401:
                raise HTTPException(503, detail="RUNWAY_API_KEY inválida")
            if gen_resp.status_code == 429:
                raise HTTPException(429, detail="Cuota RunwayML agotada")
            if gen_resp.status_code != 200:
                detail = gen_resp.text[:400]
                log.error("runwayml generate http=%s detail=%s", gen_resp.status_code, detail)
                raise HTTPException(502, detail="Error en RunwayML API")

            gen_data = gen_resp.json()
            task_id = gen_data.get("task_id", gen_data.get("id", ""))

            if not task_id:
                raise HTTPException(502, detail="RunwayML no devolvió task_id")

            # Polling hasta completar
            import asyncio
            for _poll in range(30):
                await asyncio.sleep(5)
                poll_resp = await client.get(
                    f"{self.RUNWAY_API_URL}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if poll_resp.status_code != 200:
                    continue

                poll_data = poll_resp.json()
                status = poll_data.get("status", "")
                if status == "completed":
                    video_url = poll_data.get("video_url", poll_data.get("output_url", ""))
                    if video_url:
                        video_resp = await client.get(video_url)
                        if video_resp.status_code == 200:
                            return {
                                "video_base64": base64.b64encode(video_resp.content).decode("ascii"),
                                "format": "mp4",
                                "duration": duration_clamped,
                                "provider": "runwayml",
                            }
                    break
                elif status == "failed":
                    error_msg = poll_data.get("error", "desconocido")
                    log.error("runwayml task failed: %s", error_msg)
                    break

            raise HTTPException(502, detail="RunwayML no completó la generación a tiempo")


class SlideshowProvider(VideoProvider):
    """Fallback: genera un video slideshow con imágenes placeholder + narración TTS.

    Usa Edge TTS para narración y coloca una imagen estática como video.
    """

    name: ClassVar[str] = "slideshow"

    async def generate(self, prompt: str, duration: int) -> dict:
        sanitized = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not sanitized:
            raise HTTPException(400, detail="Prompt vacío para slideshow")

        duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))

        # Generar narración TTS del prompt
        try:
            import edge_tts  # type: ignore[import-untyped]

            voice = "es-CO-SalomeNeural"
            communicate = edge_tts.Communicate(sanitized, voice)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            audio_bytes = b"".join(chunks)
        except ImportError:
            log.error("edge-tts no instalado para slideshow")
            audio_bytes = b""
        except Exception as exc:
            log.warning("edge-tts falló en slideshow: %s", exc)
            audio_bytes = b""

        # Generar placeholder (un pixel negro PNG mínimo como "video frame")
        # En producción, aquí se generaría una imagen real con DALL-E/Imagen
        pixel = _generate_placeholder_frame()

        # Empaquetar como "video" (audio + frame como placeholder)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else ""
        frame_b64 = base64.b64encode(pixel).decode("ascii")

        return {
            "video_base64": frame_b64,
            "audio_base64": audio_b64,
            "format": "slideshow",
            "duration": duration_clamped,
            "provider": "slideshow",
            "frames": 1,
        }


def _generate_placeholder_frame() -> bytes:
    """Genera un frame negro 640x480 como placeholder."""
    import struct
    import zlib

    # PNG mínimo 640x480 negro
    width, height = 640, 480

    def _make_png(w: int, h: int) -> bytes:
        def chunk(ctype: bytes, data: bytes) -> bytes:
            c = ctype + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        header = b"\x89PNG\r\n\x1a\n"
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        raw = b""
        for y in range(h):
            raw += b"\x00" + b"\x00\x00\x00" * w  # filter byte + RGB negro
        idat = chunk(b"IDAT", zlib.compress(raw))
        iend = chunk(b"IEND", b"")
        return header + ihdr + idat + iend

    return _make_png(width, height)


# ─── Registro de proveedores ─────────────────────────────────────────────


def _get_video_providers() -> list[VideoProvider]:
    """Devuelve proveedores ordenados: RunwayML > Slideshow."""
    providers: list[VideoProvider] = []
    if settings.runway_api_key:
        providers.append(RunwayMLProvider())
    providers.append(SlideshowProvider())
    return providers


def video_configured() -> bool:
    """True si al menos un proveedor de video está disponible."""
    for p in _get_video_providers():
        if p.available():
            return True
    return False


def get_available_video_providers() -> list[dict[str, object]]:
    """Devuelve lista de proveedores con estado."""
    result: list[dict[str, object]] = []
    for p in _get_video_providers():
        result.append({
            "name": p.name,
            "available": p.available(),
        })
    return result


async def generate_video(
    prompt: str,
    duration: int = DEFAULT_DURATION,
    provider: str = "auto",
) -> dict:
    """Genera un video corto con el proveedor elegido.

    Args:
        prompt: Descripción del video deseado.
        duration: Duración en segundos (4-30, default 10).
        provider: "auto", "runwayml", "slideshow".

    Returns:
        dict con {"video_base64", "format", "duration", "provider", "prompt_used"}
    """
    providers = _get_video_providers()

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
                detail="Ningún proveedor de video disponible. Configura RUNWAY_API_KEY.",
            )
        selected = available[0]

    duration_clamped = max(MIN_DURATION, min(duration or DEFAULT_DURATION, MAX_DURATION))

    log.info(
        "video generate provider=%s duration=%s chars=%s",
        selected.name, duration_clamped, len(prompt),
    )

    try:
        result = await selected.generate(prompt, duration_clamped)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("video generate unexpected error provider=%s", selected.name)
        raise HTTPException(500, detail=f"Error interno de video ({selected.name})") from exc

    result["prompt_used"] = (prompt or "").strip()[:MAX_PROMPT_CHARS]

    return result
