"""Preferencias del briefing matutino proactivo."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services.morning_briefing_service import (
    MorningBriefingSettings,
    load_settings,
    maybe_run_on_boot,
    save_settings,
    sync_morning_briefing_cron,
)

log = logging.getLogger("dot.briefing_router")

router = APIRouter(prefix="/v1/briefing", tags=["briefing"])


class MorningBriefingSettingsDto(BaseModel):
    enabled: bool = True
    hour: str = Field(default="08:00", pattern=r"^\d{1,2}:\d{2}$")
    timezone: str = "America/Caracas"
    notify_app: bool = True
    notify_whatsapp: bool = False


class MorningBriefingSettingsPatch(BaseModel):
    enabled: bool | None = None
    hour: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    timezone: str | None = None
    notify_app: bool | None = None
    notify_whatsapp: bool | None = None


def _to_dto(settings: MorningBriefingSettings) -> MorningBriefingSettingsDto:
    data = settings.to_dict()
    return MorningBriefingSettingsDto(
        enabled=bool(data["enabled"]),
        hour=str(data["hour"]),
        timezone=str(data["timezone"]),
        notify_app=bool(data["notify_app"]),
        notify_whatsapp=bool(data["notify_whatsapp"]),
    )


@router.get("/settings", response_model=MorningBriefingSettingsDto)
def get_briefing_settings(claims: dict = Depends(require_product_jwt)) -> MorningBriefingSettingsDto:
    uid = claims_uid(claims)
    return _to_dto(load_settings(uid))


@router.patch("/settings", response_model=MorningBriefingSettingsDto)
def patch_briefing_settings(
    body: MorningBriefingSettingsPatch,
    claims: dict = Depends(require_product_jwt),
    request: Request = None,
) -> MorningBriefingSettingsDto:
    uid = claims_uid(claims)
    current = load_settings(uid)
    patch = body.model_dump(exclude_none=True)

    updated = MorningBriefingSettings(
        enabled=patch.get("enabled", current.enabled),
        hour=patch.get("hour", current.hour),
        timezone_name=patch.get("timezone", current.timezone_name),
        notify_app=patch.get("notify_app", current.notify_app),
        notify_whatsapp=patch.get("notify_whatsapp", current.notify_whatsapp),
    )
    save_settings(uid, updated)

    try:
        sync_morning_briefing_cron(uid, updated)
    except Exception:
        log.warning("Error sincronizando cron briefing uid=%s", uid[:8], exc_info=True)

    _ = request
    return _to_dto(updated)


class MorningBriefingBootResponse(BaseModel):
    ran: bool
    reason: str | None = None
    preview: str | None = None


@router.post("/maybe-run-on-boot", response_model=MorningBriefingBootResponse)
def post_briefing_maybe_run_on_boot(
    claims: dict = Depends(require_product_jwt),
) -> MorningBriefingBootResponse:
    """Entrega el briefing al abrir DOT si corresponde (máximo una vez al día)."""
    uid = claims_uid(claims)
    result = maybe_run_on_boot(uid)
    return MorningBriefingBootResponse(
        ran=bool(result.get("ran")),
        reason=str(result.get("reason") or "") or None,
        preview=str(result.get("preview") or "") or None,
    )
