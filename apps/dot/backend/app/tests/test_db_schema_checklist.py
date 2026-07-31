from __future__ import annotations

from pathlib import Path

from app.billing_models import Base
from app import chat_models  # noqa: F401
from app import refresh_store  # noqa: F401
from app.services.db_schema_checklist import (
    CHAT_TABLES,
    BILLING_TABLES,
    compare_service_database_urls,
    engine_from_database_url,
    missing_tables,
    normalize_database_url,
    parse_database_url_from_env_file,
)


def test_normalize_database_url_postgres_variants() -> None:
    a = normalize_database_url("postgresql+psycopg://user:pass@127.0.0.1:5432/dot_billing")
    b = normalize_database_url("postgresql://user:pass@127.0.0.1:5432/dot_billing")
    assert a == b


def test_missing_tables_after_create_all(tmp_path: Path) -> None:
    db = tmp_path / "schema.db"
    engine = engine_from_database_url(f"sqlite:///{db}")
    Base.metadata.create_all(bind=engine)
    report = missing_tables(engine, check_chat=True)
    assert report.ok_all
    engine.dispose()


def test_missing_tables_detects_chat(tmp_path: Path) -> None:
    db = tmp_path / "billing_only.db"
    engine = engine_from_database_url(f"sqlite:///{db}")
    Base.metadata.create_all(
        bind=engine,
        tables=[Base.metadata.tables[name] for name in BILLING_TABLES],
    )
    report = missing_tables(engine, check_chat=True)
    assert report.ok_billing_full
    assert not report.ok_chat
    assert set(report.missing_chat) == set(CHAT_TABLES)
    engine.dispose()


def test_parse_database_url_from_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nDATABASE_URL=postgresql+psycopg://u:p@localhost/db\n",
        encoding="utf-8",
    )
    assert parse_database_url_from_env_file(env) == "postgresql+psycopg://u:p@localhost/db"


def test_compare_service_database_urls_detects_drift(tmp_path: Path) -> None:
    backend_env = tmp_path / "frontend" / "backend"
    backend_env.mkdir(parents=True)
    (backend_env / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/dot_a\n",
        encoding="utf-8",
    )
    report = compare_service_database_urls(tmp_path)
    assert report.is_consistent
