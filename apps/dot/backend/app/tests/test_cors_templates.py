"""
CORS: preflight DELETE en /v1/templates y DELETE autenticado.

Verificación manual (Vite :5173 + backend :8000):
1. Iniciar backend y `npm run dev` en frontend.
2. DevTools → Network; eliminar una plantilla desde el modal de documentos.
3. Confirmar OPTIONS a `/v1/templates/{id}` con `Access-Control-Allow-Methods`
   que incluya DELETE, y que el DELETE devuelva 200 (no bloqueado por CORS).

pytest: `pytest frontend/backend/app/tests/test_cors_templates.py -q`
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth_deps import require_product_jwt
from app.tests.test_templates import _FakeTemplateService


def test_cors_preflight_delete_templates(client: TestClient) -> None:
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
    assert resp.headers.get("access-control-allow-origin") == origin
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "DELETE" in allow_methods.upper()


def test_delete_template_with_cors_origin_header(client: TestClient) -> None:
    fake = _FakeTemplateService()
    client.app.state.template_service = fake
    client.app.dependency_overrides[require_product_jwt] = lambda: {"sub": "uid-cors-test"}
    origin = "http://localhost:5173"

    deleted = client.delete(
        "/v1/templates/tpl-1",
        headers={
            "Authorization": "Bearer test-token",
            "Origin": origin,
        },
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
    assert fake.deleted == ["tpl-1"]
