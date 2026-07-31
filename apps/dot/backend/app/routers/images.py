"""Router de generación de imágenes con Vertex Imagen."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_deps import check_usage_limit, claims_cliente_id
from app.billing_db import get_billing_db
from app.schemas.image_gen import (
    GeneratedImageResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    ImageGenerateUsageResponse,
)
from app.services.image_gen_vertex_service import generate_images
from app.services.image_generation_service import (
    IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
    parse_image_count,
    resolve_resolution,
    strip_intent_prefix,
    validate_prompt,
)
from app.services.usage_service import (
    OPERATION_IMAGE_GEN,
    calc_image_gen_cost_usd,
    record_usage,
)
from app.settings import settings

log = logging.getLogger("dot.images")

router = APIRouter(prefix="/v1/images", tags=["images"])


@router.post("/generate", response_model=ImageGenerateResponse)
def images_generate(
    body: ImageGenerateRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    if not settings.image_generation_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_generation_unavailable",
                "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
            },
        )

    if not (settings.google_cloud_project or "").strip():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_generation_unavailable",
                "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
            },
        )

    try:
        prompt_used = validate_prompt(strip_intent_prefix(body.prompt))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_prompt") from None

    width, height, aspect_ratio = resolve_resolution(body.resolution)
    if body.aspect_ratio:
        aspect_ratio = body.aspect_ratio.strip() or aspect_ratio

    image_count = parse_image_count(prompt_used, body.count)
    generated = generate_images(
        prompt_used,
        count=image_count,
        aspect_ratio=aspect_ratio,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        model_name=settings.imagen_vertex_model,
        width=width,
        height=height,
    )

    model = settings.imagen_vertex_model
    cost_usd = calc_image_gen_cost_usd(len(generated))
    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=model,
        cost_usd=cost_usd,
        operation=OPERATION_IMAGE_GEN,
    )

    log.info(
        "image generate OK cliente=%s count=%d model=%s",
        str(claims_cliente_id(claims))[:8],
        len(generated),
        model,
    )

    return ImageGenerateResponse(
        images=[
            GeneratedImageResponse(
                mime_type=item.mime_type,
                data_base64=item.data_base64,
                width=item.width,
                height=item.height,
            )
            for item in generated
        ],
        prompt_used=prompt_used,
        count=len(generated),
        usage=ImageGenerateUsageResponse(cost_usd=float(cost_usd), model=model),
    )
