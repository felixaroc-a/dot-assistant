"""Tests de health/db: detección de tablas chat faltantes."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.billing_models import Base
from app import chat_models  # noqa: F401
from app.services.db_schema_checklist import BILLING_TABLES, engine_from_database_url


from app.tests.conftest import reset_billing_db_singleton


@pytest.fixture
def billing_only_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Cliente con BD solo billing (sin tablas chat) para simular hallazgo C1."""
    db = tmp_path / "health_billing_only.db"
    url = f"sqlite+pysqlite:///{db.as_posix()}"
    engine = engine_from_database_url(url)
    Base.metadata.create_all(
        bind=engine,
        tables=[Base.metadata.tables[name] for name in BILLING_TABLES],
    )
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setattr("app.settings.settings.database_url", url)
    reset_billing_db_singleton()

    from app.main import app

    with TestClient(app) as client:
        yield client

    reset_billing_db_singleton()


def test_health_db_ok_with_full_schema(client: TestClient) -> None:
    resp = client.get("/health/db")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["chat"] == "ok"


def test_health_db_fails_when_chat_tables_missing(billing_only_client: TestClient) -> None:
    resp = billing_only_client.get("/health/db")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert "chat_conversations" in data["detail"] or "chat_messages" in data["detail"]
    assert "missing_chat" in data
    assert set(data["missing_chat"]) == {"chat_conversations", "chat_messages"}
