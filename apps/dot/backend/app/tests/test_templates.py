"""Tests de endpoints para plantillas reutilizables."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.billing_db import get_billing_db
from app.tests.conftest import seed_cliente


def _get_token(client: TestClient) -> str:
    session = next(get_billing_db())
    seed_cliente(session)
    session.close()
    resp = client.post(
        "/v1/auth/login",
        json={
            "cedula": "1234567890",
            "password": "test123",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class _FakeTemplateService:
    def __init__(self):
        self.deleted: list[str] = []

    def list_templates(self, uid: str):
        return [
            {
                "id": "tpl-1",
                "name": "Carta formal",
                "document_type": "docx",
                "structure": "Asunto: {{asunto}}\nCuerpo: {{cuerpo}}",
                "created_at": "2030-01-01T10:00:00Z",
                "updated_at": "2030-01-01T10:10:00Z",
            }
        ]

    def create_template(self, uid: str, name: str, document_type: str, structure: str):
        return {
            "id": "tpl-2",
            "name": name,
            "document_type": document_type,
            "structure": structure,
            "created_at": "2030-01-01T11:00:00Z",
            "updated_at": "2030-01-01T11:00:00Z",
        }

    def delete_template(self, uid: str, template_id: str):
        self.deleted.append(template_id)
        return True

    def render_template(self, uid: str, template_id: str, user_input: str, provider_id: str | None):
        return {
            "template_id": template_id,
            "template_name": "Carta formal",
            "document_type": "docx",
            "title": "Carta formal 20300101",
            "content": "Contenido final generado",
        }


def test_templates_crud_and_render(client: TestClient) -> None:
    token = _get_token(client)
    fake = _FakeTemplateService()
    client.app.state.template_service = fake

    listing = client.get(
        "/v1/templates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    assert listing.json()["templates"][0]["id"] == "tpl-1"

    created = client.post(
        "/v1/templates",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Factura simple",
            "document_type": "txt",
            "structure": "Cliente: {{cliente}}\nValor: {{valor}}",
        },
    )
    assert created.status_code == 200
    assert created.json()["id"] == "tpl-2"

    rendered = client.post(
        "/v1/templates/tpl-1/render",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_input": "Cliente ACME, valor 1200", "provider": "deepseek"},
    )
    assert rendered.status_code == 200
    assert rendered.json()["document_type"] == "docx"
    assert "Contenido final" in rendered.json()["content"]

    deleted = client.delete(
        "/v1/templates/tpl-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
    assert fake.deleted == ["tpl-1"]
