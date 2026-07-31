"""OAuth: scopes de start deben persistirse para el callback."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.settings import settings


def test_google_scopes_for_gmail_only():
    scopes = settings.google_scopes_for_integrations(["gmail"])
    assert settings.scope_gmail in scopes
    assert settings.scope_drive in scopes
    assert settings.scope_calendar not in scopes


def test_google_scopes_for_calendar_only():
    scopes = settings.google_scopes_for_integrations(["google-calendar"])
    assert settings.scope_calendar in scopes
    assert settings.scope_gmail not in scopes


@patch("app.firebase_db.get_db")
def test_save_and_take_oauth_pending_preserves_scopes(mock_get_db):
    from app.firebase_db import save_oauth_pending_state, take_oauth_pending_state

    doc_ref = MagicMock()
    collection = MagicMock()
    collection.document.return_value = doc_ref
    db = MagicMock()
    db.collection.return_value = collection
    mock_get_db.return_value = db

    gmail_only = [settings.scope_gmail]
    save_oauth_pending_state("st1", "user-1", gmail_only)

    set_payload = doc_ref.set.call_args[0][0]
    assert set_payload["scopes"] == gmail_only

    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "user_id": "user-1",
        "scopes": gmail_only,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }
    doc_ref.get.return_value = snap

    result = take_oauth_pending_state("st1")
    assert result == ("user-1", gmail_only)


@patch("app.services.oauth_service.take_oauth_pending_state")
@patch("app.services.oauth_service.Flow")
@patch("app.services.oauth_service.save_user_google_tokens")
@patch("app.services.oauth_service.crypto_tokens.encrypt_token_blob", return_value="blob")
def test_callback_uses_scopes_from_pending(
    _enc, _save_tokens, mock_flow_cls, mock_take_pending
):
    from app.services.oauth_service import complete_google_oauth_callback

    gmail_only = [settings.scope_gmail]
    mock_take_pending.return_value = ("user-1", gmail_only)
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.refresh_token = "rt"
    mock_creds.token = "t"
    mock_creds.token_uri = "uri"
    mock_creds.client_id = "cid"
    mock_creds.client_secret = "sec"
    mock_creds.scopes = gmail_only
    mock_flow.credentials = mock_creds
    mock_flow_cls.from_client_secrets_file.return_value = mock_flow

    complete_google_oauth_callback("code", "state")

    call_kwargs = mock_flow_cls.from_client_secrets_file.call_args.kwargs
    assert call_kwargs["scopes"] == gmail_only
