"""Tests para el endpoint de generacion de documentos /v1/documents/generate."""
from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi.testclient import TestClient

from app.tests.conftest import seed_cliente


def _get_token(client: TestClient, db_session: Session) -> str:
    """Helper: hace login y devuelve access_token (usa BD de prueba en memoria)."""
    seed_cliente(db_session)
    resp = client.post(
        "/v1/auth/login",
        json={
            "cedula": "1234567890",
            "password": "test123",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestGenerateDocument:
    """POST /v1/documents/generate"""

    def test_generate_docx(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "docx",
                "title": "Test Word",
                "content": "# Titulo\n\nEste es un documento de prueba.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["document_type"] == "docx"
        assert "Test Word" in data["filename"]
        assert data["size_bytes"] > 0

    def test_generate_xlsx(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "xlsx",
                "title": "Test Excel",
                "content": "Nombre|Edad|Ciudad\nAna|30|Bogota\nLuis|25|Medellin",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["document_type"] == "xlsx"
        assert "Test Excel" in data["filename"]
        assert data["size_bytes"] > 0

    def test_generate_txt(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "txt",
                "title": "Test TXT",
                "content": "Contenido de texto plano para pruebas.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["document_type"] == "txt"
        assert "Test TXT" in data["filename"]
        assert data["size_bytes"] > 0

    def test_generate_pdf(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "pdf",
                "title": "Reporte PDF",
                "content": "Resumen ejecutivo\n\n- Punto 1\n- Punto 2",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["document_type"] == "pdf"
        assert data["filename"].endswith(".pdf")
        assert data["size_bytes"] > 100

    def test_generate_invalid_type(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "png",
                "title": "Invalid",
                "content": "Contenido",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "no soportado" in data["detail"].lower()

    def test_generate_without_auth(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "docx",
                "title": "No Auth",
                "content": "Contenido",
            },
        )
        assert resp.status_code == 401

    def test_generate_with_empty_content(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "txt",
                "title": "Empty",
                "content": "",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_generate_with_folder(self, client: TestClient, db_session: Session) -> None:
        token = _get_token(client, db_session)
        resp = client.post(
            "/v1/documents/generate",
            json={
                "document_type": "docx",
                "title": "Con Carpeta",
                "content": "Documento en carpeta personalizada.",
                "folder": "Documentos",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["document_type"] == "docx"
