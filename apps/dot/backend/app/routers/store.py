"""C05 — DOT Store: skills comunitarias (Firestore) + catálogo curado local."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.application.store.curated_skills import get_curated_skill, list_curated_skills
from app.auth_deps import claims_uid, require_product_jwt
from app.dependencies.limiter import limiter
from app.firebase_db import FIRESTORE_AVAILABLE, get_db, get_user_profile, merge_user_profile
from app.settings import settings

log = logging.getLogger("dot.store")

router = APIRouter(prefix="/v1/store", tags=["store"])


class StoreSkillItem(BaseModel):
    id: str
    name: str
    description: str
    instruction: str
    author_name: str
    installs_count: int
    rating: float
    created_at: str
    category: str = "General"
    backend_provisioned: bool = False
    requires_user_api_key: bool = False
    ready_to_use: bool = True


class StoreSkillListResponse(BaseModel):
    skills: list[StoreSkillItem]


class InstallSkillResponse(BaseModel):
    ok: bool
    skill_id: str
    skill_name: str
    auto_id: str


class UninstallSkillResponse(BaseModel):
    ok: bool
    skill_id: str


def _skill_ready_to_use(data: dict) -> bool:
    """Skills con clave del servidor: listas al instalar si el backend está provisionado."""
    if data.get("requires_user_api_key"):
        return False
    backend_key = str(data.get("backend_key") or "").strip().lower()
    if backend_key == "openweather":
        return bool((settings.openweather_api_key or "").strip())
    if backend_key == "newsapi":
        # NewsAPI opcional; RSS fallback siempre disponible.
        return True
    return True


def _item_from_dict(data: dict, skill_id: str) -> StoreSkillItem:
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        created_str = created_at.isoformat()
    elif isinstance(created_at, str):
        created_str = created_at
    else:
        created_str = datetime.now(timezone.utc).isoformat()
    requires_user_key = bool(data.get("requires_user_api_key"))
    backend_provisioned = bool(data.get("backend_provisioned"))
    return StoreSkillItem(
        id=skill_id,
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        instruction=str(data.get("instruction", "")),
        author_name=str(data.get("author_name", "DOT")),
        installs_count=int(data.get("installs_count", 0) or 0),
        rating=float(data.get("rating", 0.0) or 0),
        created_at=created_str,
        category=str(data.get("category", "General")),
        backend_provisioned=backend_provisioned,
        requires_user_api_key=requires_user_key,
        ready_to_use=_skill_ready_to_use(data) if not requires_user_key else False,
    )


@router.get("/skills", response_model=StoreSkillListResponse)
def list_store_skills(
    request: Request,
    category: str | None = None,
    search: str | None = None,
    claims: dict = Depends(require_product_jwt),
):
    """Lista skills (Firestore si hay; si no, catálogo curado ≥5)."""
    _ = claims_uid(claims)
    skills: list[StoreSkillItem] = []

    if not FIRESTORE_AVAILABLE:
        log.info("list_store_skills: Firestore no disponible, usando catalogo curado")
        docs: list = []
    else:
        try:
            db = get_db()
            query = db.collection("store_skills").order_by(
                "installs_count", direction="DESCENDING"
            ).limit(50)
            docs = list(query.stream())
        except Exception as e:
            log.warning("Firestore store_skills no disponible (%s); catálogo curado", e)
            docs = []

    for doc in docs:
        data = doc.to_dict() or {}
        skill_id = str(data.get("id") or doc.id)
        if not skill_id:
            continue
        skill_category = str(data.get("category", "General"))
        skill_name = str(data.get("name", ""))
        skill_description = str(data.get("description", ""))
        if category and category != "todas" and skill_category.lower() != category.lower():
            continue
        if search:
            q = search.lower()
            if q not in skill_name.lower() and q not in skill_description.lower():
                continue
        skills.append(_item_from_dict(data, skill_id))

    if not skills:
        for data in list_curated_skills(category=None if category == "todas" else category, search=search):
            skills.append(_item_from_dict(data, str(data["id"])))

    return StoreSkillListResponse(skills=skills)


@router.post("/skills/{skill_id}/install", response_model=InstallSkillResponse)
@limiter.limit("30/minute")
def install_store_skill(
    request: Request,
    skill_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Instala skill → saved_automations (Firestore o catálogo curado)."""
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        log.info("install_store_skill: Firestore no disponible")
        raise HTTPException(status_code=503, detail="Store no disponible: Firebase no inicializado.")
    skill_data: dict | None = None

    try:
        db = get_db()
        skill_doc = db.collection("store_skills").document(skill_id).get()
        if skill_doc.exists:
            skill_data = skill_doc.to_dict() or {}
    except Exception as e:
        log.warning("Firestore install lookup falló (%s); probando curado", e)
        db = None

    if skill_data is None:
        skill_data = get_curated_skill(skill_id)
        if skill_data is None:
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} no encontrada en la Store.")

    skill_name = str(skill_data.get("name", "Skill sin nombre"))
    skill_instruction = str(skill_data.get("instruction", ""))
    auto_id = str(uuid.uuid4())
    new_automation = {
        "id": auto_id,
        "name": skill_name,
        "integration_id": str(skill_data.get("integration_id", "third-option")),
        "instruction": skill_instruction,
        "active": True,
        "output_type": str(skill_data.get("output_type", "notify")),
        "schedule": str(skill_data.get("schedule", "manual")),
        "description": str(skill_data.get("description", "")),
        "source": "store",
        "source_skill_id": skill_id,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        profile = get_user_profile(uid) or {}
        existing = profile.get("saved_automations", [])
        if not isinstance(existing, list):
            existing = []
        for auto in existing:
            if isinstance(auto, dict) and auto.get("source_skill_id") == skill_id:
                return InstallSkillResponse(
                    ok=True,
                    skill_id=skill_id,
                    skill_name=skill_name,
                    auto_id=str(auto.get("id", "")),
                )
        existing.append(new_automation)
        merge_user_profile(uid, {"saved_automations": existing})
    except Exception as e:
        log.error("Error guardando automatizacion uid=%s: %s", uid, e)
        raise HTTPException(status_code=500, detail="Error al instalar la skill en tu perfil.")

    if db is not None:
        try:
            current_installs = int(skill_data.get("installs_count", 0) or 0)
            db.collection("store_skills").document(skill_id).update(
                {"installs_count": current_installs + 1}
            )
        except Exception as e:
            log.debug("No se incrementó installs_count (%s)", e)

    return InstallSkillResponse(
        ok=True,
        skill_id=skill_id,
        skill_name=skill_name,
        auto_id=auto_id,
    )


@router.post("/skills/{skill_id}/uninstall", response_model=UninstallSkillResponse)
@limiter.limit("30/minute")
def uninstall_store_skill(
    request: Request,
    skill_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Quita una skill instalada desde la Tienda (por source_skill_id)."""
    uid = claims_uid(claims)
    if not FIRESTORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Store no disponible: Firebase no inicializado.")

    try:
        profile = get_user_profile(uid) or {}
        existing = profile.get("saved_automations", [])
        if not isinstance(existing, list):
            existing = []

        filtered = [
            auto for auto in existing
            if not (isinstance(auto, dict) and auto.get("source_skill_id") == skill_id)
        ]
        if len(filtered) == len(existing):
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} no está instalada.")

        merge_user_profile(uid, {"saved_automations": filtered})
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error quitando skill uid=%s skill=%s: %s", uid, skill_id, e)
        raise HTTPException(status_code=500, detail="Error al quitar la skill de tu perfil.")

    return UninstallSkillResponse(ok=True, skill_id=skill_id)
