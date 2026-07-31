"""Router unificado de Media — música, video, imágenes mejoradas.

Endpoints:
  GET  /v1/media/status          — estado de todos los proveedores
  POST /v1/media/music/generate  — generación de música
  POST /v1/media/video/generate  — generación de video
  POST /v1/media/images/generate — generación de imágenes (multi-proveedor)
  POST /v1/media/images/img2img  — image-to-image
  POST /v1/media/images/inpaint  — inpainting
  POST /v1/media/images/upscale  — upscale
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import check_usage_limit, claims_cliente_id
from app.billing_db import get_billing_db
from app.services.image_gen_multi_service import (
    generate_image_to_image as _gen_img2img,
)
from app.services.image_gen_multi_service import (
    generate_images_multi as _gen_images_multi,
)
from app.services.image_gen_multi_service import (
    generate_inpaint as _gen_inpaint,
)
from app.services.image_gen_multi_service import (
    generate_upscale as _gen_upscale,
)
from app.services.image_gen_multi_service import (
    get_available_image_providers,
    image_providers_configured,
)
from app.services.music_service import (
    generate_music as _gen_music,
)
from app.services.music_service import (
    get_available_music_providers,
    get_genres,
    music_configured,
)
from app.services.usage_service import (
    OPERATION_IMAGE_GEN,
    calc_image_gen_cost_usd,
    record_usage,
)
from app.services.video_service import (
    generate_video as _gen_video,
)
from app.services.video_service import (
    get_available_video_providers,
    video_configured,
)
from app.settings import settings

log = logging.getLogger("dot.media")

router = APIRouter(prefix="/v1/media", tags=["media"])


# ─── Schemas ────────────────────────────────────────────────────────────


class MusicGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1200)
    duration: int = Field(default=60, ge=10, le=120)
    genre: str = Field(default="pop")
    provider: str = Field(default="auto")


class MusicGenerateResponse(BaseModel):
    audio_base64: str
    format: str
    duration: int
    provider: str
    genre: str
    prompt_used: str


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    duration: int = Field(default=10, ge=4, le=30)
    provider: str = Field(default="auto")


class VideoGenerateResponse(BaseModel):
    video_base64: str
    audio_base64: str = ""
    format: str
    duration: int
    provider: str
    prompt_used: str
    frames: int = 0


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    count: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    provider: str = Field(default="auto")
    aspect_ratio: str | None = None
    negative_prompt: str | None = None


class ImageResultResponse(BaseModel):
    mime_type: str
    data_base64: str


class ImageGenerateResponse(BaseModel):
    images: list[ImageResultResponse]
    count: int
    provider: str
    prompt_used: str


class ImageToImageRequest(BaseModel):
    image_base64: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    count: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    provider: str = Field(default="auto")


class InpaintRequest(BaseModel):
    image_base64: str
    mask_base64: str
    prompt: str = Field(..., min_length=1, max_length=4000)
    count: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    provider: str = Field(default="auto")


class UpscaleRequest(BaseModel):
    image_base64: str
    scale: int = Field(default=2, ge=2, le=8)
    provider: str = Field(default="auto")


class UpscaleResponse(BaseModel):
    image: ImageResultResponse
    scale: int
    provider: str


# ─── Status ─────────────────────────────────────────────────────────────


@router.get("/status")
def media_status(claims: dict = Depends(check_usage_limit)):
    """Estado de todos los proveedores de media."""
    _ = claims
    music_ok = music_configured()
    video_ok = video_configured()
    image_ok = image_providers_configured() or settings.image_generation_enabled

    return {
        "ok": music_ok or video_ok or image_ok,
        "music": "ready" if music_ok else "needs_api_key",
        "video": "ready" if video_ok else "needs_api_key",
        "images": "ready" if image_ok else "needs_api_key",
        "providers": {
            "music": get_available_music_providers(),
            "video": get_available_video_providers(),
            "images": get_available_image_providers(),
        },
        "genres": get_genres(),
        "detail": (
            None
            if (music_ok or video_ok or image_ok)
            else "Configura SUNO_API_KEY, UDIO_API_KEY, RUNWAY_API_KEY, OPENAI_API_KEY o REPLICATE_API_KEY para activar media."
        ),
    }


# ─── Music ──────────────────────────────────────────────────────────────


@router.post("/music/generate", response_model=MusicGenerateResponse)
async def media_music_generate(
    body: MusicGenerateRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Genera un clip de música con IA."""
    if not settings.music_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "music_generation_unavailable",
                "message": "La generación de música está deshabilitada en este entorno.",
            },
        )

    result = await _gen_music(
        prompt=body.prompt,
        duration=body.duration,
        genre=body.genre,
        provider=body.provider,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result.get("provider", "music"),
        cost_usd=0.05,  # MUSIC_COST_USD
        operation=OPERATION_IMAGE_GEN,
    )

    return MusicGenerateResponse(
        audio_base64=result["audio_base64"],
        format=result["format"],
        duration=result["duration"],
        provider=result["provider"],
        genre=result["genre"],
        prompt_used=result["prompt_used"],
    )


# ─── Video ──────────────────────────────────────────────────────────────


@router.post("/video/generate", response_model=VideoGenerateResponse)
async def media_video_generate(
    body: VideoGenerateRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Genera un video corto con IA."""
    if not settings.video_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "video_generation_unavailable",
                "message": "La generación de video está deshabilitada en este entorno.",
            },
        )

    result = await _gen_video(
        prompt=body.prompt,
        duration=body.duration,
        provider=body.provider,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result.get("provider", "video"),
        cost_usd=0.15,  # VIDEO_COST_USD
        operation=OPERATION_IMAGE_GEN,
    )

    return VideoGenerateResponse(
        video_base64=result["video_base64"],
        audio_base64=result.get("audio_base64", ""),
        format=result["format"],
        duration=result["duration"],
        provider=result["provider"],
        prompt_used=result["prompt_used"],
        frames=result.get("frames", 0),
    )


# ─── Images (enhanced) ──────────────────────────────────────────────────


@router.post("/images/generate", response_model=ImageGenerateResponse)
async def media_images_generate(
    body: ImageGenerateRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Genera imágenes con el proveedor configurado (auto, vertex, dalle, stable_diffusion)."""
    if not settings.image_generation_enabled and not image_providers_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_generation_unavailable",
                "message": "La generación de imágenes está deshabilitada.",
            },
        )

    provider = settings.image_generation_provider if settings.image_generation_provider != "auto" else body.provider

    kwargs = {}
    if body.aspect_ratio:
        kwargs["aspect_ratio"] = body.aspect_ratio
    if body.negative_prompt:
        kwargs["negative_prompt"] = body.negative_prompt

    result = await _gen_images_multi(
        prompt=body.prompt,
        count=body.count,
        size=body.size,
        provider=provider,
        **kwargs,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result["provider"],
        cost_usd=calc_image_gen_cost_usd(result["count"]),
        operation=OPERATION_IMAGE_GEN,
    )

    return ImageGenerateResponse(
        images=[
            ImageResultResponse(mime_type=img["mime_type"], data_base64=img["data_base64"])
            for img in result["images"]
        ],
        count=result["count"],
        provider=result["provider"],
        prompt_used=result["prompt_used"],
    )


@router.post("/images/img2img", response_model=ImageGenerateResponse)
async def media_images_img2img(
    body: ImageToImageRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Modifica una imagen existente según el prompt (image-to-image)."""
    result = await _gen_img2img(
        image_base64=body.image_base64,
        prompt=body.prompt,
        count=body.count,
        size=body.size,
        provider=body.provider,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result["provider"],
        cost_usd=calc_image_gen_cost_usd(result["count"]),
        operation=OPERATION_IMAGE_GEN,
    )

    return ImageGenerateResponse(
        images=[
            ImageResultResponse(mime_type=img["mime_type"], data_base64=img["data_base64"])
            for img in result["images"]
        ],
        count=result["count"],
        provider=result["provider"],
        prompt_used=result["prompt_used"],
    )


@router.post("/images/inpaint", response_model=ImageGenerateResponse)
async def media_images_inpaint(
    body: InpaintRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Rellena o remueve partes de una imagen usando una máscara (inpainting)."""
    result = await _gen_inpaint(
        image_base64=body.image_base64,
        mask_base64=body.mask_base64,
        prompt=body.prompt,
        count=body.count,
        size=body.size,
        provider=body.provider,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result["provider"],
        cost_usd=calc_image_gen_cost_usd(result["count"]),
        operation=OPERATION_IMAGE_GEN,
    )

    return ImageGenerateResponse(
        images=[
            ImageResultResponse(mime_type=img["mime_type"], data_base64=img["data_base64"])
            for img in result["images"]
        ],
        count=result["count"],
        provider=result["provider"],
        prompt_used=result["prompt_used"],
    )


@router.post("/images/upscale", response_model=UpscaleResponse)
async def media_images_upscale(
    body: UpscaleRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Mejora la resolución de una imagen (upscale)."""
    result = await _gen_upscale(
        image_base64=body.image_base64,
        scale=body.scale,
        provider=body.provider,
    )

    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=result["provider"],
        cost_usd=calc_image_gen_cost_usd(1),
        operation=OPERATION_IMAGE_GEN,
    )

    img = result["image"]
    return UpscaleResponse(
        image=ImageResultResponse(
            mime_type=img.get("mime_type", "image/png"),
            data_base64=img["data_base64"],
        ),
        scale=result["scale"],
        provider=result["provider"],
    )
