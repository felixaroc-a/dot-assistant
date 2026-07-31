"""Tests de bootstrap de esquema billing + chat."""
from __future__ import annotations

from pathlib import Path

from app.billing_models import Base
from app import chat_models  # noqa: F401
from app.services.db_schema_bootstrap import ensure_backend_schema
from app.services.db_schema_checklist import (
    BILLING_TABLES,
    CHAT_TABLES,
    engine_from_database_url,
)


def test_ensure_backend_schema_creates_chat_tables(tmp_path: Path) -> None:
    db = tmp_path / "bootstrap.db"
    engine = engine_from_database_url(f"sqlite:///{db}")
    Base.metadata.create_all(
        bind=engine,
        tables=[Base.metadata.tables[name] for name in BILLING_TABLES],
    )

    from sqlalchemy import inspect

    names_before = set(inspect(engine).get_table_names())
    assert set(CHAT_TABLES).isdisjoint(names_before)

    report, _applied = ensure_backend_schema(engine)
    names_after = set(inspect(engine).get_table_names())

    assert report.ok_all
    assert set(CHAT_TABLES).issubset(names_after)
    assert "refresh_token_families" in names_after
    engine.dispose()


def test_ensure_backend_schema_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "bootstrap_idempotent.db"
    engine = engine_from_database_url(f"sqlite:///{db}")

    first, _ = ensure_backend_schema(engine)
    second, applied = ensure_backend_schema(engine)

    assert first.ok_all
    assert second.ok_all
    assert applied == []
    engine.dispose()
