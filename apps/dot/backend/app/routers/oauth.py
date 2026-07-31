"""OAuth Google: inicio de flujo, callback y status."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.auth_deps import claims_uid, require_product_jwt
from app.schemas.oauth import GoogleOAuthStartBody
from app.services import oauth_service
from app.services.oauth_service import decode_access_for_oauth
from app.settings import settings
from app.dependencies.limiter import limiter

router = APIRouter(prefix="/oauth/google", tags=["oauth"])


@router.post("/start")
@limiter.limit("15/minute")
def oauth_google_start(
    request: Request,
    body: GoogleOAuthStartBody,
    authorization: str | None = Header(None),
):
    return oauth_service.start_google_oauth(body, authorization)


@router.get("/callback")
def oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google devolvio error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Faltan query params code y/o state.")

    oauth_service.complete_google_oauth_callback(code, state)
    return HTMLResponse(content=oauth_service.oauth_success_html())


@router.get("/status")
@limiter.limit("40/minute")
def oauth_google_status(
    request: Request,
    authorization: str | None = Header(None),
    dev_user_id: str | None = Query(None),
):
    """Retorna el estado de la vinculacion OAuth Google del usuario autenticado."""
    user_id = decode_access_for_oauth(authorization)
    if not user_id and settings.allow_dev_oauth and dev_user_id:
        user_id = dev_user_id.strip()
    if not user_id:
        claims = require_product_jwt(authorization=authorization)
        user_id = claims_uid(claims)
    return oauth_service.get_google_oauth_status(user_id)


@router.post("/revoke")
def oauth_google_revoke(
    request: Request,
    claims: dict[str, object] = Depends(require_product_jwt),
):
    """Revoca la vinculacion OAuth Google del usuario autenticado.

    Elimina los tokens de Firestore y opcionalmente llama a la API
    de Google para revocar el token de acceso.
    """
    user_id = claims_uid(claims)
    return oauth_service.revoke_google_access(user_id)
