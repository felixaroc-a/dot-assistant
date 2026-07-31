"""Mapeo Firestore users → DTO de perfil."""
from __future__ import annotations

from app.firebase_db import get_user_profile, merge_user_profile
from app.schemas.profile import (
    AiCredentialsResponse,
    SavedAutomationDto,
    UserProfilePatch,
    UserProfileResponse,
)
from app.services import oauth_service


def doc_to_profile(raw: dict) -> UserProfileResponse:
    ints = raw.get("integrations")
    if ints is not None and not isinstance(ints, list):
        ints = None
    saved_raw = raw.get("saved_automations")
    saved: list[SavedAutomationDto] | None = None
    ai_credentials: AiCredentialsResponse | None = None
    if isinstance(saved_raw, list):
        parsed: list[SavedAutomationDto] = []
        for item in saved_raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(SavedAutomationDto.model_validate(item))
            except Exception:
                continue
        saved = parsed or None
    ciphertext = raw.get(oauth_service.AI_CREDENTIALS_FIELD)
    if isinstance(ciphertext, str) and ciphertext.strip():
        try:
            ai_credentials = AiCredentialsResponse(
                **oauth_service.sanitize_ai_credentials(ciphertext)
            )
        except Exception:
            ai_credentials = None
    return UserProfileResponse(
        display_name=raw.get("display_name"),
        channel_id=raw.get("channel_id"),
        ai_provider_id=raw.get("ai_provider_id"),
        integrations=[str(x) for x in ints] if ints else None,
        automation_summary=raw.get("automation_summary"),
        onboarding_completed=raw.get("onboarding_completed"),
        ai_credentials=ai_credentials,
        saved_automations=saved,
        pending_automation_results=raw.get("pending_automation_results"),
        memory_summary=raw.get("memory_summary"),
        reasoning_enabled=bool(raw.get("reasoning_enabled", False)),
        reasoning_level=(
            str(raw.get("reasoning_level") or "auto")
            if str(raw.get("reasoning_level") or "auto") in ("low", "medium", "high", "auto")
            else "auto"
        ),  # type: ignore[arg-type]
    )


def get_profile(user_id: str) -> UserProfileResponse:
    raw = get_user_profile(user_id)
    if not raw:
        return UserProfileResponse()
    return doc_to_profile(raw)


def patch_profile(user_id: str, body: UserProfilePatch) -> UserProfileResponse:
    patch = body.model_dump(exclude_none=True)
    ai_credentials = body.ai_credentials
    patch.pop("ai_credentials", None)
    if ai_credentials is not None:
        username = (ai_credentials.username or "").strip() or None
        password = (ai_credentials.password or "").strip() or None
        if not username and not password:
            patch[oauth_service.AI_CREDENTIALS_FIELD] = None
        else:
            patch[oauth_service.AI_CREDENTIALS_FIELD] = oauth_service.encrypt_ai_credentials(
                provider_id=ai_credentials.provider_id,
                username=username,
                password=password,
            )
    merge_user_profile(user_id, patch)
    raw = get_user_profile(user_id) or {}
    return doc_to_profile(raw)
