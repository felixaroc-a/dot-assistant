"""Preferencias de disparadores proactivos («avísame cuando…»)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth_deps import claims_uid, require_product_jwt
from app.services.proactive_triggers_service import (
    ProactiveTriggersSettings,
    load_settings,
    save_settings,
)

log = logging.getLogger("dot.proactive_triggers_router")

router = APIRouter(prefix="/v1/automations/proactive", tags=["automations-proactive"])


class ProactiveTriggersSettingsDto(BaseModel):
    heartbeat_enabled: bool = False
    wa_triggers_enabled: bool = False
    calendar_triggers_enabled: bool = False
    composite_enabled: bool = False


class ProactiveTriggersSettingsPatch(BaseModel):
    heartbeat_enabled: bool | None = None
    wa_triggers_enabled: bool | None = None
    calendar_triggers_enabled: bool | None = None
    composite_enabled: bool | None = None


def _to_dto(proactive: ProactiveTriggersSettings) -> ProactiveTriggersSettingsDto:
    data = proactive.to_dict()
    return ProactiveTriggersSettingsDto(
        heartbeat_enabled=bool(data["heartbeat_enabled"]),
        wa_triggers_enabled=bool(data["wa_triggers_enabled"]),
        calendar_triggers_enabled=bool(data["calendar_triggers_enabled"]),
        composite_enabled=bool(data["composite_enabled"]),
    )


@router.get("/settings", response_model=ProactiveTriggersSettingsDto)
def get_proactive_settings(claims: dict = Depends(require_product_jwt)) -> ProactiveTriggersSettingsDto:
    uid = claims_uid(claims)
    return _to_dto(load_settings(uid))


@router.patch("/settings", response_model=ProactiveTriggersSettingsDto)
def patch_proactive_settings(
    body: ProactiveTriggersSettingsPatch,
    claims: dict = Depends(require_product_jwt),
) -> ProactiveTriggersSettingsDto:
    uid = claims_uid(claims)
    current = load_settings(uid)
    patch = body.model_dump(exclude_none=True)

    updated = ProactiveTriggersSettings(
        heartbeat_enabled=patch.get("heartbeat_enabled", current.heartbeat_enabled),
        wa_triggers_enabled=patch.get("wa_triggers_enabled", current.wa_triggers_enabled),
        calendar_triggers_enabled=patch.get(
            "calendar_triggers_enabled", current.calendar_triggers_enabled
        ),
        composite_enabled=patch.get("composite_enabled", current.composite_enabled),
    )
    save_settings(uid, updated)
    log.info(
        "Proactive triggers actualizados uid=%s heartbeat=%s wa=%s cal=%s composite=%s",
        uid[:8],
        updated.heartbeat_enabled,
        updated.wa_triggers_enabled,
        updated.calendar_triggers_enabled,
        updated.composite_enabled,
    )
    return _to_dto(updated)
