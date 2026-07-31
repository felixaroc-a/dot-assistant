"""Tests de hardening Fase 5 (Día 6)."""
from __future__ import annotations

from starlette.requests import Request

from app.dependencies import limiter as limiter_module
from app.main import app
from app.services.chat_crypto import CHAT_ENC_PREFIX, decrypt_message, encrypt_message


def test_pendrive_verify_route_registered() -> None:
    has_route = any(
        route.path == "/v1/pendrive/verify" and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )
    assert has_route


def test_rate_limit_key_uses_jwt_sub(monkeypatch) -> None:
    monkeypatch.setattr(limiter_module, "jwt_configured", lambda: True)
    monkeypatch.setattr(limiter_module, "get_jwt_signing_config", lambda: object())
    monkeypatch.setattr(
        limiter_module.jwt_util,
        "decode_product_token",
        lambda token, cfg: {"sub": "uid-hardening-test"},
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/me",
            "headers": [(b"authorization", b"Bearer token-test")],
            "client": ("10.10.0.25", 1234),
            "scheme": "http",
            "query_string": b"",
        }
    )

    assert limiter_module._rate_limit_key(request) == "user:uid-hardening-test"


def test_chat_content_is_encrypted_when_key_available() -> None:
    encrypted = encrypt_message("mensaje secreto de prueba")
    assert encrypted.startswith(CHAT_ENC_PREFIX)
    assert decrypt_message(encrypted) == "mensaje secreto de prueba"
