"""Tests Google Drive tools con OAuth por usuario (no env GOOGLE_ACCESS_TOKEN)."""
from __future__ import annotations

from app.application.agent.tools.gdrive_tools import (
    DRIVE_SCOPE_MISSING_USER_MESSAGE,
    drive_search_handler,
)
from app.services.gmail_service import GmailIntegrationError, MissingGmailCredentialsError


def test_drive_search_without_oauth_human_error(monkeypatch):
    def _boom(_uid):
        raise MissingGmailCredentialsError("no oauth")

    monkeypatch.setattr("app.application.agent.tools.gdrive_tools.get_refreshed_access_token", _boom)
    result = drive_search_handler(
        "11111111-1111-1111-1111-111111111111",
        {"name": "informe"},
    )
    assert result.ok is False
    assert "Google" in (result.error or "")
    assert "Configuración" in (result.error or "")


def test_drive_search_missing_scope_human_error(monkeypatch):
    class _FakeResp:
        status_code = 403
        text = '{"error":{"message":"Request had insufficient authentication scopes."}}'

        def json(self):
            return {"error": {"message": "Request had insufficient authentication scopes."}}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return _FakeResp()

    monkeypatch.setattr(
        "app.application.agent.tools.gdrive_tools.get_refreshed_access_token",
        lambda _uid: "token",
    )
    monkeypatch.setattr("app.application.agent.tools.gdrive_tools.httpx.Client", _FakeClient)
    result = drive_search_handler(
        "11111111-1111-1111-1111-111111111111",
        {"name": "informe"},
    )
    assert result.ok is False
    assert result.error == DRIVE_SCOPE_MISSING_USER_MESSAGE
    assert "desvincula y vuelve a conectar" in (result.error or "")


def test_oauth_scope_exception_maps_to_reconnect_message():
    from app.application.agent.tools.gdrive_tools import _oauth_error_message

    msg = _oauth_error_message(GmailIntegrationError("insufficient scope"))
    assert "Configuración → Google" in msg
    assert "desvincula y vuelve a conectar" in msg
