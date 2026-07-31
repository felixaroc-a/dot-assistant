"\"\"\"Servicio Vertex Vision con GenerativeModel de Vertex AI.\"\"\""
from __future__ import annotations

import logging

from fastapi import HTTPException
from google.api_core import exceptions as google_exceptions
from google.auth.exceptions import DefaultCredentialsError

log = logging.getLogger("dot.vision.vertex")

DEFAULT_VERTEX_MODEL = "gemini-2.5-flash"


def _load_vertex_modules():
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
    except ImportError as exc:  # pragma: no cover - entorno necesita instalar vertexai
        log.error("Vertex AI SDK no está instalado", exc_info=True)
        raise HTTPException(
            503,
            detail=(
                "Vision Vertex no disponible porque el SDK de Vertex AI "
                "no está instalado. Instala el paquete `vertexai` y vuelve a intentarlo."
            ),
        ) from exc
    return vertexai, GenerativeModel, Part


def _resolve_model(model_name: str | None) -> str:
    resolved = (model_name or DEFAULT_VERTEX_MODEL).strip()
    return resolved or DEFAULT_VERTEX_MODEL


def _normalize_mime_type(mime_type: str | None) -> str:
    normalized = (mime_type or "image/jpeg").strip().lower()
    return normalized or "image/jpeg"


def _handle_permission_error(exc: Exception) -> HTTPException:
    detail = (
        "Vertex AI rechazó la solicitud (403) al modelo Gemini Vision. Causas posibles:\n"
        "1) La API 'Vertex AI API' no está habilitada en tu proyecto GCP.\n"
        "   → Ir a https://console.cloud.google.com/apis/library/aiplatform.googleapis.com\n"
        "2) La cuenta de servicio no tiene el rol 'Vertex AI User' (roles/aiplatform.user).\n"
        "   → Ir a https://console.cloud.google.com/iam-admin/iam y verificar los roles.\n"
        "3) Las credenciales en GOOGLE_APPLICATION_CREDENTIALS no corresponden al proyecto.\n"
        "Consulta docs/GCP-SETUP.md para instrucciones detalladas."
    )
    log.error("Vertex permission denied: %s", exc)
    return HTTPException(status_code=403, detail=detail)


def _handle_credentials_error(exc: Exception) -> HTTPException:
    detail = (
        "Credenciales de Google faltantes o inválidas. "
        "Configura `GOOGLE_APPLICATION_CREDENTIALS` o ejecuta "
        "`gcloud auth application-default login` con la cuenta correcta."
    )
    log.error("Vertex credentials error: %s", exc)
    return HTTPException(status_code=503, detail=detail)


def _handle_generic_error(exc: Exception) -> HTTPException:
    log.error("Vertex visión inesperado: %s", exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail="Error interno al procesar la imagen con Vertex Vision. Intenta de nuevo más tarde.",
    )


def analyze_image(
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    project: str,
    location: str | None,
    model_name: str | None = None,
) -> str:
    """Analiza una imagen usando Gemini Vision en Vertex AI."""
    if not project:
        raise HTTPException(
            status_code=503,
            detail="Vision Vertex no está configurado: falta GOOGLE_CLOUD_PROJECT.",
        )

    vertexai, GenerativeModel, Part = _load_vertex_modules()

    resolved_location = (location or "us-central1").strip() or "us-central1"
    resolved_model = _resolve_model(model_name)
    resolved_mime = _normalize_mime_type(mime_type)

    try:
        vertexai.init(project=project, location=resolved_location)
        model = GenerativeModel(model_name=resolved_model)
        image_part = Part.from_data(image_bytes, mime_type=resolved_mime)
        response = model.generate_content([image_part, prompt])
        text = getattr(response, "text", "")
        return text or "[Vertex Vision no generó contenido]"
    except google_exceptions.PermissionDenied as exc:
        raise _handle_permission_error(exc)
    except google_exceptions.Forbidden as exc:
        raise _handle_permission_error(exc)
    except DefaultCredentialsError as exc:
        raise _handle_credentials_error(exc)
    except Exception as exc:  # pragma: no cover - errores de Vertex en producción
        raise _handle_generic_error(exc)
