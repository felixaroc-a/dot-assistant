"""DTOs de OAuth Google."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GoogleOAuthStartBody(BaseModel):
    integrations: list[str] | None = Field(
        None,
        description='Integraciones Google: "gmail" y/o "google-calendar" (scopes por separado).',
    )
    firebase_id_token: str | None = Field(
        None,
        description="Opcional/desaconsejado: ID token Firebase. Preferir Bearer JWT DOT.",
    )
    dev_user_id: str | None = Field(
        None,
        description="Solo si ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH=1 -- ej. UUID de cliente de prueba.",
    )


class GoogleOAuthStatusResponse(BaseModel):
    configured: bool = Field(
        ..., description="True si hay refresh_token cifrado válido para las integraciones solicitadas."
    )
    integrations: list[str] = Field(
        ..., description="Lista de integraciones activas: gmail, google-calendar."
    )
    expires_at: datetime | None = Field(
        None, description="Fecha ISO de expiración del token de acceso (null si no configurado)."
    )
    scopes_ok: bool = Field(
        ..., description="True si los scopes almacenados cubren todas las integraciones solicitadas."
    )
