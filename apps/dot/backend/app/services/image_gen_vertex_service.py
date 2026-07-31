"""Servicio Vertex AI Imagen para generación texto → imagen."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO

from fastapi import HTTPException
from google.api_core import exceptions as google_exceptions
from google.auth.exceptions import DefaultCredentialsError

from app.services.image_generation_service import IMAGE_GENERATION_UNAVAILABLE_MESSAGE

log = logging.getLogger("dot.image_gen.vertex")

DEFAULT_IMAGEN_MODEL = "imagen-3.0-generate-002"


@dataclass(frozen=True)
class GeneratedImage:
    mime_type: str
    data_base64: str
    width: int
    height: int


def _load_vertex_modules():
    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel
    except ImportError as exc:  # pragma: no cover
        log.error("Vertex AI SDK no está instalado", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_generation_unavailable",
                "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
            },
        ) from exc
    return vertexai, ImageGenerationModel


def _resolve_model(model_name: str | None) -> str:
    resolved = (model_name or DEFAULT_IMAGEN_MODEL).strip()
    return resolved or DEFAULT_IMAGEN_MODEL


def _extract_google_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    raw_message = getattr(exc, "message", None)
    if raw_message:
        message = str(raw_message).strip() or message
    return message


def _is_model_access_error(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "not visible to the current project",
        "does not have access to it",
        "was not found or your project",
        "publisher model",
    )
    return any(marker in lowered for marker in markers)


def _handle_model_access_error(
    exc: Exception,
    *,
    model: str,
    project: str,
) -> HTTPException:
    google_msg = _extract_google_error_message(exc)
    log.error(
        "Vertex Imagen model access error project=%s model=%s: %s",
        project,
        model,
        google_msg,
    )
    return HTTPException(
        status_code=503,
        detail={
            "code": "image_generation_unavailable",
            "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        },
    )


def _handle_permission_error(
    exc: Exception,
    *,
    model: str,
    project: str,
) -> HTTPException:
    google_msg = _extract_google_error_message(exc)
    if _is_model_access_error(google_msg):
        return _handle_model_access_error(exc, model=model, project=project)

    log.error("Vertex Imagen permission denied: %s", exc)
    return HTTPException(
        status_code=503,
        detail={
            "code": "image_generation_unavailable",
            "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        },
    )


def _handle_credentials_error(exc: Exception) -> HTTPException:
    log.error("Vertex Imagen credentials error: %s", exc)
    return HTTPException(
        status_code=503,
        detail={
            "code": "image_generation_unavailable",
            "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        },
    )


def _handle_generic_error(exc: Exception) -> HTTPException:
    log.error("Vertex Imagen inesperado: %s", exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail="Error interno al generar la imagen. Intenta de nuevo más tarde.",
    )


def _image_to_base64(image, *, width: int, height: int) -> GeneratedImage:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return GeneratedImage(
        mime_type="image/png",
        data_base64=encoded,
        width=width,
        height=height,
    )


def generate_images(
    prompt: str,
    *,
    count: int,
    aspect_ratio: str,
    project: str,
    location: str | None,
    model_name: str | None = None,
    width: int = 1024,
    height: int = 1024,
) -> list[GeneratedImage]:
    if not project:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "image_generation_unavailable",
                "message": IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
            },
        )

    vertexai, ImageGenerationModel = _load_vertex_modules()
    resolved_location = (location or "us-central1").strip() or "us-central1"
    resolved_model = _resolve_model(model_name)
    number_of_images = max(1, int(count))

    try:
        vertexai.init(project=project, location=resolved_location)
        model = ImageGenerationModel.from_pretrained(resolved_model)
        response = model.generate_images(
            prompt=prompt,
            number_of_images=number_of_images,
            aspect_ratio=aspect_ratio,
        )
        raw_images = getattr(response, "images", None) or []
        if not raw_images:
            raise HTTPException(
                status_code=500,
                detail="El proveedor no devolvió imágenes.",
            )
        return [_image_to_base64(img, width=width, height=height) for img in raw_images]
    except HTTPException:
        raise
    except google_exceptions.NotFound as exc:
        raise _handle_model_access_error(
            exc,
            model=resolved_model,
            project=project,
        )
    except google_exceptions.PermissionDenied as exc:
        raise _handle_permission_error(
            exc,
            model=resolved_model,
            project=project,
        )
    except google_exceptions.Forbidden as exc:
        raise _handle_permission_error(
            exc,
            model=resolved_model,
            project=project,
        )
    except DefaultCredentialsError as exc:
        raise _handle_credentials_error(exc)
    except Exception as exc:  # pragma: no cover
        raise _handle_generic_error(exc)
