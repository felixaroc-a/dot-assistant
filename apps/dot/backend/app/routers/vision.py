"""Router de Vision — análisis de imágenes con Gemini o Vertex."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.auth_deps import claims_cliente_id, claims_uid, check_usage_limit
from app.billing_db import get_billing_db
from app.services.usage_service import OPERATION_VISION, calc_vision_cost_usd, record_usage
from app.services.vision_service import analyze_image, is_image_content

log = logging.getLogger("dot.vision")

router = APIRouter(prefix="/v1/vision", tags=["vision"])


@router.post("/analyze")
async def vision_analyze(
    file: UploadFile = File(...),
    prompt: str = Form("Describe esta imagen en detalle."),
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Analiza una imagen usando Gemini Vision API.
    
    DeepSeek no soporta imagenes, asi que delegamos a Gemini cuando
    el frontend sube una foto. El usuario debe estar autenticado.
    """
    usuario_id = claims_uid(claims)

    if not is_image_content(file.content_type or ""):
        raise HTTPException(400, detail="Solo se aceptan imagenes")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB max
        raise HTTPException(400, detail="Imagen muy grande. Maximo 10MB.")

    result = await analyze_image(
        contents,
        file.content_type or "image/jpeg",
        prompt=prompt,
    )

    log.info("Vision analyze OK usuario=%s len=%d", usuario_id[:8], len(result))

    from app.settings import settings

    model = settings.gemini_vertex_model if settings.normalized_gemini_provider == "vertex" else settings.gemini_model
    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=model,
        cost_usd=calc_vision_cost_usd(),
        operation=OPERATION_VISION,
    )

    return {"result": result}
