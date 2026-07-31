"""Tool de generación de imágenes vía Vertex Imagen (chat agent)."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.application.agent.ports import ToolResult
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
    USAGE_LIMIT_EXCEEDED_MESSAGE,
    assert_ai_usage_allowed,
    calc_image_gen_cost_usd,
    record_usage,
)
from app.settings import settings

log = logging.getLogger("dot.agent.tools.image")


def generate_image_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera una o más imágenes desde una descripción de texto."""
    if not settings.image_generation_enabled:
        return ToolResult(
            ok=False,
            output="",
            error=IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        )

    if not (settings.google_cloud_project or "").strip():
        return ToolResult(
            ok=False,
            output="",
            error=IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        )

    raw_prompt = str(arguments.get("prompt") or "").strip()
    if not raw_prompt:
        return ToolResult(ok=False, output="", error="Falta el prompt para generar la imagen.")

    try:
        prompt_used = validate_prompt(strip_intent_prefix(raw_prompt))
    except ValueError:
        return ToolResult(ok=False, output="", error="El prompt no es válido.")

    explicit_count = arguments.get("count")
    count = parse_image_count(
        prompt_used,
        int(explicit_count) if explicit_count is not None else None,
    )
    width, height, aspect_ratio = resolve_resolution(
        str(arguments.get("resolution") or "").strip() or None,
    )
    if arguments.get("aspect_ratio"):
        aspect_ratio = str(arguments["aspect_ratio"]).strip() or aspect_ratio

    from app.billing_db import get_session_factory

    factory = get_session_factory()
    db = factory()
    try:
        cliente_id = UUID(uid)
        try:
            assert_ai_usage_allowed(db, cliente_id)
        except HTTPException:
            return ToolResult(
                ok=False,
                output="",
                error=USAGE_LIMIT_EXCEEDED_MESSAGE,
            )

        try:
            generated = generate_images(
                prompt_used,
                count=count,
                aspect_ratio=aspect_ratio,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
                model_name=settings.imagen_vertex_model,
                width=width,
                height=height,
            )
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                message = str(detail.get("message") or IMAGE_GENERATION_UNAVAILABLE_MESSAGE)
            else:
                message = IMAGE_GENERATION_UNAVAILABLE_MESSAGE
            return ToolResult(ok=False, output="", error=message)

        model = settings.imagen_vertex_model
        cost_usd = calc_image_gen_cost_usd(len(generated))
        record_usage(
            db,
            cliente_id=cliente_id,
            modelo=model,
            cost_usd=cost_usd,
            operation=OPERATION_IMAGE_GEN,
        )
        db.commit()
    finally:
        db.close()

    artifacts: list[dict[str, Any]] = []
    for index, image in enumerate(generated, start=1):
        artifacts.append(
            {
                "type": "image",
                "mime": image.mime_type,
                "data": image.data_base64,
                "width": image.width,
                "height": image.height,
                "name": f"imagen-generada-{index}.png",
            }
        )

    label = (
        f"Generé {len(generated)} imágenes para: {prompt_used}"
        if len(generated) > 1
        else f"Imagen generada: {prompt_used}"
    )
    log.info(
        "generate_image OK uid=%s count=%d model=%s",
        uid[:8],
        len(generated),
        model,
    )
    return ToolResult(ok=True, output=label, artifacts=artifacts)
