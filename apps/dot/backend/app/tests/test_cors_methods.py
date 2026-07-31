"""CORS: allow_methods alineado con rutas reales del API."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import CORS_ALLOW_METHODS


def test_cors_allow_methods_includes_api_verbs() -> None:
    configured = {m.upper() for m in CORS_ALLOW_METHODS}
    # Uso real: GET/POST (auth, chat), PATCH (profile), DELETE (templates, pendrive recovery)
    assert {"GET", "POST", "PATCH", "DELETE", "OPTIONS"}.issubset(configured)


def test_cors_preflight_delete_allowed(client: TestClient) -> None:
    origin = "http://127.0.0.1:5173"
    resp = client.options(
        "/v1/templates/tpl-1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    allow_methods = resp.headers.get("access-control-allow-methods", "").upper()
    assert "DELETE" in allow_methods
