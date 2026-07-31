"""Auto-updater endpoint — D03."""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(tags=["updates"])
log = logging.getLogger("dot.updates")

# Versión del producto (debe sincronizarse con package.json del frontend)
_APP_VERSION = "0.0.0"

# URL base del bucket de releases (placeholder hasta que se configure GCS)
_RELEASES_BASE_URL = "https://storage.googleapis.com/nordik-releases"


class UpdateCheckResponse(BaseModel):
    """Respuesta del endpoint de actualización (D03)."""
    version: str
    url: str = ""
    sha256: str = ""
    release_notes: str = ""
    min_api_version: str = "1.0.0"


def _get_latest_yml_path(channel: str = "latest") -> str:
    """Devuelve la ruta al archivo latest.yml para el canal especificado."""
    channel = (channel or "latest").strip() or "latest"
    return f"{_RELEASES_BASE_URL}/{channel}.yml"


def _compute_sha256(data: bytes) -> str:
    """Calcula SHA-256 de un blob de bytes (placeholder)."""
    return hashlib.sha256(data).hexdigest()


@router.get("/v1/updates/check", response_model=UpdateCheckResponse)
async def check_updates(channel: Optional[str] = "latest"):
    """Devuelve la última versión disponible y su URL de descarga.

    Placeholder hasta que se configure el bucket GCS de releases.
    En producción, esto leería el archivo latest.yml del bucket.
    """
    ch = (channel or "latest").strip() or "latest"
    return UpdateCheckResponse(
        version=_APP_VERSION,
        url=f"{_RELEASES_BASE_URL}/DOT-Setup-{_APP_VERSION}.exe",
        sha256="",
        release_notes=f"Canal: {ch}. Configurar bucket GCS para releases reales.",
        min_api_version="1.0.0",
    )
