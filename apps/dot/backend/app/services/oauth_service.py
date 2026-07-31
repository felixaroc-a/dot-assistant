"""Flujo OAuth Google: inicio, callback y persistencia de tokens."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from firebase_admin import auth as fb_auth
from google_auth_oauthlib.flow import Flow

from app import crypto_tokens, jwt_util
from app.auth_deps import claims_uid
from app.firebase_db import (
    FIRESTORE_AVAILABLE,
    delete_user_google_tokens,
    get_user_google_tokens_doc_data,
    get_user_profile,
    save_oauth_pending_state,
    save_user_google_tokens,
    take_oauth_pending_state,
)
from app.jwt_keys import get_jwt_signing_config
from app.schemas.oauth import GoogleOAuthStartBody, GoogleOAuthStatusResponse
from app.settings import settings
from app.token_revocation import TokenRevokedError, assert_not_revoked

log = logging.getLogger("dot.oauth_service")

VALID_AI_PROVIDERS = frozenset({"deepseek", "gemini", "chatgpt"})
AI_CREDENTIALS_FIELD = "ai_credentials_ciphertext"


def _normalize_ai_provider_id(provider_id: str) -> str:
    value = (provider_id or "").strip().lower()
    if value not in VALID_AI_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"ai_credentials.provider_id invalido: {provider_id!r}",
        )
    return value


def encrypt_ai_credentials(
    *,
    provider_id: str,
    username: str | None,
    password: str | None,
) -> str:
    normalized_provider = _normalize_ai_provider_id(provider_id)
    clean_username = (username or "").strip() or None
    clean_password = (password or "").strip() or None
    return crypto_tokens.encrypt_token_blob(
        {
            "provider_id": normalized_provider,
            "username": clean_username,
            "password": clean_password,
        }
    )


def decrypt_ai_credentials_blob(ciphertext: str) -> dict[str, str | None]:
    raw = crypto_tokens.decrypt_token_blob(ciphertext)
    provider_id = _normalize_ai_provider_id(str(raw.get("provider_id") or ""))
    username = str(raw.get("username") or "").strip() or None
    password = str(raw.get("password") or "").strip() or None
    return {
        "provider_id": provider_id,
        "username": username,
        "password": password,
    }


def sanitize_ai_credentials(ciphertext: str) -> dict[str, str | bool | None]:
    creds = decrypt_ai_credentials_blob(ciphertext)
    return {
        "provider_id": creds["provider_id"],
        "username": creds["username"],
        "has_password": bool(creds["password"]),
    }


def get_user_ai_credentials(user_id: str) -> dict[str, str | None] | None:
    profile = get_user_profile(user_id) or {}
    ciphertext = profile.get(AI_CREDENTIALS_FIELD)
    if not isinstance(ciphertext, str) or not ciphertext.strip():
        return None
    return decrypt_ai_credentials_blob(ciphertext)


def decode_access_for_oauth(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    raw = authorization[7:].strip()
    if not raw:
        return None
    try:
        claims = jwt_util.decode_product_token(raw, get_jwt_signing_config())
        if claims.get("token_use") != "access":
            return None
        assert_not_revoked(claims)
        return claims_uid(claims)
    except TokenRevokedError:
        return None
    except Exception:
        log.warning("Error decodificando access token para OAuth", exc_info=True)
        return None


def resolve_oauth_user_id(body: GoogleOAuthStartBody, authorization: str | None) -> str:
    user_id = decode_access_for_oauth(authorization)

    if not user_id and body.firebase_id_token:
        try:
            decoded = fb_auth.verify_id_token(body.firebase_id_token)
            legacy = decoded.get("uid")
            user_id = str(legacy) if legacy else None
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token Firebase invalido: {e!s}") from e
    elif not user_id and settings.allow_dev_oauth and body.dev_user_id:
        user_id = body.dev_user_id.strip()

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail=(
                "Encabezado Authorization: Bearer <access_token> (JWT DOT), o "
                "firebase_id_token en el cuerpo (legacy), o (solo dev) dev_user_id."
            ),
        )
    return user_id


def normalize_integrations(raw: list[str] | None) -> list[str]:
    integrations = [
        i.strip().lower()
        for i in (raw or [])
        if i.strip().lower() in settings.valid_google_integrations
    ]
    if raw and not integrations:
        raise HTTPException(
            status_code=400,
            detail='integrations debe incluir "gmail" y/o "google-calendar".',
        )
    return integrations


def start_google_oauth(body: GoogleOAuthStartBody, authorization: str | None) -> dict[str, str]:
    user_id = resolve_oauth_user_id(body, authorization)
    integrations = normalize_integrations(body.integrations)
    oauth_scopes = settings.google_scopes_for_integrations(integrations or None)

    state = secrets.token_urlsafe(32)
    save_oauth_pending_state(state, user_id, oauth_scopes)

    flow = Flow.from_client_secrets_file(
        str(settings.google_client_secrets_path),
        scopes=oauth_scopes,
        redirect_uri=settings.oauth_redirect_uri,
        autogenerate_code_verifier=False,
    )
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {"authorization_url": authorization_url, "state": state}


def complete_google_oauth_callback(code: str, state: str) -> None:
    pending = take_oauth_pending_state(state)
    if not pending:
        raise HTTPException(
            status_code=400,
            detail="Estado OAuth invalido o expirado. Reinicia el flujo desde tu app.",
        )
    user_id, oauth_scopes = pending

    flow = Flow.from_client_secrets_file(
        str(settings.google_client_secrets_path),
        scopes=oauth_scopes,
        redirect_uri=settings.oauth_redirect_uri,
        autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google no devolvio refresh_token. Prueba revocando el acceso en "
                "https://myaccount.google.com/permissions y vuelve a vincular."
            ),
        )

    blob = crypto_tokens.encrypt_token_blob(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else oauth_scopes,
        }
    )
    save_user_google_tokens(user_id, blob)


def oauth_success_html() -> str:
    path = Path(__file__).resolve().parent.parent / "templates" / "oauth_success.html"
    return path.read_text(encoding="utf-8")


def _scope_to_integration(scope: str) -> str | None:
    """Convierte un scope URL de Google al nombre corto de integracion."""
    if scope == settings.scope_gmail:
        return "gmail"
    if scope == settings.scope_calendar:
        return "google-calendar"
    if scope == settings.scope_drive:
        return "google-drive"
    return None


def get_google_oauth_status(user_id: str) -> GoogleOAuthStatusResponse:
    """Retorna el estado de la vinculacion OAuth Google para un usuario.

    Lee `user_google_tokens/{uid}` en Firestore y descifra el blob para
    determinar si hay refresh_token valido y que scopes estan cubiertos.
    """
    if not FIRESTORE_AVAILABLE:
        log.info("get_google_oauth_status: Firestore no disponible")
        return GoogleOAuthStatusResponse(
            configured=False,
            integrations=[],
            expires_at=None,
            scopes_ok=False,
        )
    doc = get_user_google_tokens_doc_data(user_id)
    if not doc:
        return GoogleOAuthStatusResponse(
            configured=False,
            integrations=[],
            expires_at=None,
            scopes_ok=False,
        )

    ciphertext = doc.get("ciphertext")
    if not ciphertext:
        return GoogleOAuthStatusResponse(
            configured=False,
            integrations=[],
            expires_at=None,
            scopes_ok=False,
        )

    try:
        token_data = crypto_tokens.decrypt_token_blob(str(ciphertext))
    except Exception:
        log.warning("Error descifrando token OAuth para uid=%s", user_id[:8], exc_info=True)
        return GoogleOAuthStatusResponse(
            configured=False,
            integrations=[],
            expires_at=None,
            scopes_ok=False,
        )

    refresh_token = token_data.get("refresh_token")
    configured = bool(refresh_token and str(refresh_token).strip())

    stored_scopes: list[str] = token_data.get("scopes") or []
    integrations = sorted(
        {
            s
            for scope_url in stored_scopes
            if (s := _scope_to_integration(scope_url)) is not None
        }
    )

    # scopes_ok: los scopes almacenados cubren gmail y google-calendar
    expected_scopes = {settings.scope_gmail, settings.scope_calendar}
    scopes_ok = configured and expected_scopes.issubset(set(stored_scopes))

    # expires_at: updated_at + 1 hora (vida tipica del access token de Google)
    updated_at = doc.get("updated_at")
    expires_at_val: datetime | None = None
    if isinstance(updated_at, datetime):
        expires_at_val = updated_at + timedelta(hours=1)
    elif hasattr(updated_at, "timestamp"):
        # Firestore Timestamp object con metodo timestamp()
        ts = updated_at.timestamp()
        expires_at_val = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=1)

    return GoogleOAuthStatusResponse(
        configured=configured,
        integrations=integrations,
        expires_at=expires_at_val,
        scopes_ok=scopes_ok,
    )


def is_google_connected(user_id: str) -> bool:
    """Verifica si el usuario tiene tokens OAuth Google vigentes."""
    doc = get_user_google_tokens_doc_data(user_id)
    if not doc:
        return False
    ciphertext = doc.get("ciphertext")
    if not ciphertext:
        return False
    try:
        token_data = crypto_tokens.decrypt_token_blob(str(ciphertext))
        refresh_token = token_data.get("refresh_token")
        return bool(refresh_token and str(refresh_token).strip())
    except Exception:
        log.debug("Error descifrando token OAuth en is_google_connected para uid=%s", user_id[:8], exc_info=True)
        return False


def revoke_google_access(user_id: str) -> dict[str, str | bool]:
    """Revoca el acceso OAuth Google de un usuario.

    1. Opcional: llama a la API de Google para revocar el token.
    2. Elimina el documento de tokens de Firestore.

    Returns:
        dict con 'ok' (bool) y 'message' (str).
    """
    # Leer tokens antes de borrar (para revocar en Google)
    doc = get_user_google_tokens_doc_data(user_id)
    revocation_details: dict[str, str | bool] = {"revoked_remotely": False}

    if doc:
        ciphertext = doc.get("ciphertext")
        if ciphertext:
            try:
                token_data = crypto_tokens.decrypt_token_blob(str(ciphertext))
                access_token = token_data.get("token")
                if access_token and str(access_token).strip():
                    # Revocación remota opcional en Google
                    import urllib.error
                    import urllib.parse
                    import urllib.request

                    url = f"https://oauth2.googleapis.com/revoke?token={urllib.parse.quote(str(access_token))}"
                    req = urllib.request.Request(url, method="POST")
                    try:
                        urllib.request.urlopen(req, timeout=5)
                        revocation_details["revoked_remotely"] = True
                    except urllib.error.HTTPError:
                        # Si el token ya expiró o fue revocado, Google responde 400
                        revocation_details["revoked_remotely"] = True
                    except Exception:
                        # Timeout u otro error de red: no crítico
                        # best-effort: no bloquear revocación por error de red
                        log.debug("Timeout o error de red en revocación remota Google", exc_info=True)
            except Exception:
                # best-effort: no podemos descifrar, borramos igual
                log.debug("Error descifrando token al revocar acceso Google para uid=%s", user_id[:8], exc_info=True)

    # Eliminar documento de Firestore
    delete_user_google_tokens(user_id)
    revocation_details["ok"] = True
    revocation_details["message"] = "Acceso Google revocado exitosamente."
    return revocation_details
