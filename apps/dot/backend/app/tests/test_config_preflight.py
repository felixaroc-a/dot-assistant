from __future__ import annotations

from pathlib import Path

from app.billing_models import Base
from app import chat_models  # noqa: F401
from app.services.config_preflight import run_config_preflight
from app.services.db_schema_checklist import engine_from_database_url


def _prepare_sqlite_database_url(tmp_path: Path) -> str:
    db = tmp_path / "preflight.db"
    url = f"sqlite:///{db}"
    engine = engine_from_database_url(url)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    return url


def _base_env(database_url: str) -> dict[str, str]:
    return {
        "DOT_ENV": "production",
        "DATABASE_URL": database_url,
        "JWT_SECRET": "jwt-secret-super-largo",
        "TOKEN_ENCRYPTION_KEY": "token-enc-key-super-larga",
        "CHAT_ENCRYPTION_KEY": "chat-enc-key-super-larga",
        "ADMIN_API_KEY": "admin-key-super-segura",
        "HARDWARE_TOKEN_PEPPER": "pepper-super-seguro-1234567890-abcdef",
        "TRUSTED_HOSTS": "dot.local,api.dot.local",
        "REFRESH_USE_FIRESTORE_ONLY": "1",
        "ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH": "0",
        "ENABLE_CHAT": "true",
        "DEEPSEEK_API_KEY": "sk-deepseek-test",
        "OAUTH_REDIRECT_URI": "https://api.dot.local/oauth/google/callback",
    }


def test_preflight_ok_con_env_produccion(tmp_path: Path) -> None:
    env = _base_env(_prepare_sqlite_database_url(tmp_path))
    firebase_json = tmp_path / "firebase.json"
    client_secret_json = tmp_path / "client_secret.json"
    firebase_json.write_text("{}", encoding="utf-8")
    client_secret_json.write_text("{}", encoding="utf-8")
    env["FIREBASE_SERVICE_ACCOUNT_PATH"] = str(firebase_json)
    env["GOOGLE_CLIENT_SECRETS_PATH"] = str(client_secret_json)

    report = run_config_preflight(env)

    assert report["ok"] is True
    assert report["errors"] == []


def test_preflight_detecta_campos_criticos_faltantes() -> None:
    report = run_config_preflight({"DOT_ENV": "development"})

    assert report["ok"] is False
    errors = report["errors"]
    keys = {item["key"] for item in errors}
    assert "DATABASE_URL" in keys
    assert "TOKEN_ENCRYPTION_KEY" in keys
    assert "CHAT_ENCRYPTION_KEY" in keys
    assert "ADMIN_API_KEY" in keys
    assert "HARDWARE_TOKEN_PEPPER" in keys
    assert "JWT_SECRET/JWT_PRIVATE_KEY_PEM" in keys


def test_preflight_bloquea_flags_peligrosos_en_produccion(tmp_path: Path) -> None:
    env = _base_env(_prepare_sqlite_database_url(tmp_path))
    env["ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH"] = "1"
    env["TRUSTED_HOSTS"] = "*"
    env["REFRESH_USE_FIRESTORE_ONLY"] = "0"

    report = run_config_preflight(env)

    assert report["ok"] is False
    errors = {item["key"]: item["message"] for item in report["errors"]}
    assert "ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH" in errors
    assert "TRUSTED_HOSTS" in errors
    assert "REFRESH_USE_FIRESTORE_ONLY" in errors


def test_preflight_path_faltante_es_error_en_produccion(tmp_path: Path) -> None:
    env = _base_env(_prepare_sqlite_database_url(tmp_path))
    env["FIREBASE_SERVICE_ACCOUNT_PATH"] = "C:/inexistente/firebase.json"
    env["GOOGLE_CLIENT_SECRETS_PATH"] = "C:/inexistente/client_secret.json"

    report = run_config_preflight(env)

    assert report["ok"] is False
    error_keys = {item["key"] for item in report["errors"]}
    assert "FIREBASE_SERVICE_ACCOUNT_PATH" in error_keys
    assert "GOOGLE_CLIENT_SECRETS_PATH" in error_keys


def test_preflight_advierte_tablas_chat_faltantes(tmp_path: Path) -> None:
    db = tmp_path / "billing_only.db"
    url = f"sqlite:///{db}"
    engine = engine_from_database_url(url)
    from app.services.db_schema_checklist import BILLING_TABLES

    Base.metadata.create_all(
        bind=engine,
        tables=[Base.metadata.tables[name] for name in BILLING_TABLES],
    )
    engine.dispose()

    env = _base_env(url)
    env["DOT_ENV"] = "development"
    env["ENABLE_CHAT"] = "true"

    report = run_config_preflight(env)
    warning_keys = {item["key"] for item in report["warnings"]}
    assert "DATABASE_SCHEMA" in warning_keys


def test_preflight_error_chat_faltante_en_produccion(tmp_path: Path) -> None:
    db = tmp_path / "billing_only_prod.db"
    url = f"sqlite:///{db}"
    engine = engine_from_database_url(url)
    from app.services.db_schema_checklist import BILLING_TABLES

    Base.metadata.create_all(
        bind=engine,
        tables=[Base.metadata.tables[name] for name in BILLING_TABLES],
    )
    engine.dispose()

    env = _base_env(url)
    env["ENABLE_CHAT"] = "true"

    report = run_config_preflight(env)
    error_keys = {item["key"] for item in report["errors"]}
    assert "DATABASE_SCHEMA" in error_keys
