"""DTOs de perfil de usuario."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AiCredentialsPatch(BaseModel):
    provider_id: str
    username: str | None = None
    password: str | None = None


class AiCredentialsResponse(BaseModel):
    provider_id: str
    username: str | None = None
    has_password: bool = False


class SavedAutomationDto(BaseModel):
    """AutomationDTO del contrato v1 — snake_case en JSON de API y Firestore."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=False)

    id: str
    name: str
    integration_id: str = Field(
        validation_alias=AliasChoices("integration_id", "integrationId"),
    )
    instruction: str
    active: bool = True
    output_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("output_type", "outputType"),
    )
    schedule: str | None = None
    description: str | None = None
    """T-ML-013: Descripción visible en UI «De qué trata esta automatización»."""
    source_skill_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_skill_id", "sourceSkillId"),
    )
    source: str | None = None


class UserProfileResponse(BaseModel):
    display_name: str | None = None
    channel_id: str | None = None
    ai_provider_id: str | None = None
    integrations: list[str] | None = None
    automation_summary: str | None = None
    onboarding_completed: bool | None = None
    ai_credentials: AiCredentialsResponse | None = None
    saved_automations: list[SavedAutomationDto] | None = None
    pending_automation_results: dict[str, Any] | None = None
    memory_summary: dict[str, Any] | None = None
    reasoning_enabled: bool = False
    reasoning_level: Literal["low", "medium", "high", "auto"] = "auto"


class UserProfilePatch(BaseModel):
    display_name: str | None = None
    channel_id: str | None = None
    ai_provider_id: str | None = None
    integrations: list[str] | None = None
    automation_summary: str | None = None
    onboarding_completed: bool | None = None
    ai_credentials: AiCredentialsPatch | None = None
    saved_automations: list[SavedAutomationDto] | None = None
    memory_summary: dict[str, Any] | None = None
    reasoning_enabled: bool | None = None
    reasoning_level: Literal["low", "medium", "high", "auto"] | None = None
