"""Agregador de DTOs Pydantic para generación de tipos TypeScript."""
from __future__ import annotations

from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
    SuscripcionClienteDto,
)
from app.schemas.profile import (
    AiCredentialsPatch,
    AiCredentialsResponse,
    SavedAutomationDto,
    UserProfilePatch,
    UserProfileResponse,
)

__all__ = [
    "AiCredentialsPatch",
    "AiCredentialsResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutRequest",
    "MeResponse",
    "RefreshRequest",
    "RefreshResponse",
    "SavedAutomationDto",
    "SuscripcionClienteDto",
    "UserProfilePatch",
    "UserProfileResponse",
]
