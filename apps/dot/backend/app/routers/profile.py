"""Perfil de usuario en Firestore."""
import logging

from fastapi import APIRouter, Depends, Request

from app.auth_deps import claims_uid, require_product_jwt
from app.firebase_db import FIRESTORE_AVAILABLE, get_db as get_firestore_client
from app.repositories import profile_repository
from app.schemas.profile import UserProfilePatch, UserProfileResponse
from app.services.automation_scheduler import AutomationScheduler
from app.dependencies.limiter import limiter

log = logging.getLogger("dot.profile_router")

router = APIRouter(prefix="/users/me", tags=["profile"])


@router.get("/profile", response_model=UserProfileResponse)
def get_user_profile_route(request: Request, claims: dict = Depends(require_product_jwt)):
    if not FIRESTORE_AVAILABLE:
        return UserProfileResponse()
    return profile_repository.get_profile(claims_uid(claims))


@router.patch("/profile", response_model=UserProfileResponse)
@limiter.limit("10/minute")
def patch_user_profile_route(
    request: Request,
    body: UserProfilePatch,
    claims: dict = Depends(require_product_jwt),
):
    # v1: solo DeepSeek — se ignora lo que el cliente envíe en ai_provider_id o ai_credentials
    normalized = body.model_copy(update={"ai_provider_id": "deepseek"})

    uid = claims_uid(claims)

    if not FIRESTORE_AVAILABLE:
        log.info("perfil no persistido (modo offline)")
        return UserProfileResponse()

    result = profile_repository.patch_profile(uid, normalized)

    # T-ML-002/003: Recargar automatizaciones cuando se actualizan
    if body.saved_automations is not None:
        try:
            plan = str(claims.get("plan", "mensual"))
            scheduler: AutomationScheduler = request.app.state.auto_scheduler
            scheduler.reload_user_automations(uid=uid, plan=plan)
        except Exception:
            log.warning("Error recargando automatizaciones tras PATCH perfil", exc_info=True)

    # Auto-activar briefing matutino (cron sin IA) si es primer onboarding
    if body.onboarding_completed:
        try:
            from app.services.morning_briefing_service import ensure_default_onboarding

            ensure_default_onboarding(uid)
            db_fs = get_firestore_client()
            if db_fs is not None:
                db_fs.collection("users").document(uid).set(
                    {"briefing_skill_installed": True},
                    merge=True,
                )
            log.info("Briefing matutino activado para uid=%s (onboarding)", uid[:8])
        except Exception as e:
            log.warning("No se pudo activar briefing matutino: %s", e)

        try:
            from app.services.proactive_triggers_service import ensure_default_onboarding as ensure_proactive_defaults

            ensure_proactive_defaults(uid)
            log.info("Disparadores proactivos activados para uid=%s (onboarding)", uid[:8])
        except Exception as e:
            log.warning("No se pudieron activar disparadores proactivos: %s", e)

    return result
