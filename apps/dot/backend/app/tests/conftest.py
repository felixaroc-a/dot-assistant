"""Configuracion de pytest: SQLite aislado por test (sin dot_dev.sqlite)."""
from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date, timedelta
from uuid import uuid4

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# --- Entorno de test (antes de importar la app) ---
_TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"
_TEST_ADMIN_API_KEY = "test-admin-key"

os.environ["DOT_ENV"] = "testing"
os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long-for-hs256!!"
os.environ["TOKEN_ENCRYPTION_KEY"] = "ySmbGdhaPWIrdHxlbm4tFcmnvFiXQ4lrEVTN0wOFZIQ="
os.environ["ADMIN_API_KEY"] = _TEST_ADMIN_API_KEY
os.environ["ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH"] = "1"
os.environ["HARDWARE_TOKEN_PEPPER"] = "test-pepper-32-chars-minimum!!!!"
os.environ["DEEPSEEK_API_KEY"] = "sk-test-deepseek-key"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = "sk-test-gemini-key"
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"
os.environ["ENABLE_IMAGE_GENERATION"] = "true"
os.environ["ENABLE_WEB_SEARCH"] = "true"

from app import chat_models  # noqa: F401 — tablas chat en create_all
import app.billing_db as billing_db_module
from app.billing_db import get_billing_db
from app.billing_models import Base, ClienteORM, PlanSuscripcionORM, UsageTokenORM  # noqa: F401
from app.dependencies.limiter import limiter
from app.main import app
from app.refresh_store import clear_memory_families
from app.settings import settings
from app.token_revocation import clear_memory_revocations

# Evita que backend/.env apunte a dot_dev.sqlite durante pytest
settings.database_url = _TEST_DATABASE_URL
settings.admin_api_key = _TEST_ADMIN_API_KEY
settings.testing = "1"

# Snapshot de valores por defecto para restaurar entre módulos de test.
# Esto evita contaminación de estado cuando un módulo monkeypatchea settings
# y el siguiente módulo espera los defaults.
_SETTINGS_DEFAULTS = {
    "database_url": _TEST_DATABASE_URL,
    "admin_api_key": _TEST_ADMIN_API_KEY,
    "testing": "1",
    "deepseek_api_key": "sk-test-deepseek-key",
    "gemini_api_key": "sk-test-gemini-key",
    "google_cloud_project": "test-project",
    "google_cloud_location": "us-central1",
    "gemini_provider": "api_key",
    "gemini_model": "gemini-2.5-flash",
    "gemini_vertex_model": "gemini-2.5-flash",
    "enable_image_generation": True,
    "enable_new_integration": False,
    "enable_web_search": True,
    "ai_usage_limit_enabled": False,
    "ai_usage_monthly_limit_usd": 7.5,
    "image_gen_max_images_per_request": 4,
    "image_gen_default_resolution": "1024x1024",
    "image_gen_enable_1080p": False,
    "imagen_vertex_model": "imagen-3.0-generate-002",
    "whatsapp_reply_policy": "dot_group_mention",
    "whatsapp_reply_require_mention": True,
    "whatsapp_reply_require_self": True,
    "whatsapp_webhook_secret": "",
    "whatsapp_bridge_secret": "",
    "google_translate_api_key": "",
    "chat_encryption_key": "",
    "default_chat_model": "deepseek-chat",
    "default_chat_provider": "default",
    "enable_chat": False,
    "openai_api_key": "",
    "anthropic_api_key": "",
    "groq_api_key": "",
    "model_routing_enabled": True,
    "ai_cost_deepseek_input_per_1m": 0.14,
    "ai_cost_deepseek_output_per_1m": 0.28,
    "ai_cost_gemini_vision_per_request": 0.001,
    "ai_cost_imagen_per_image": 0.04,
}


def _restore_settings_defaults() -> None:
    """Restaura todas las claves de settings a sus valores de test por defecto."""
    for key, value in _SETTINGS_DEFAULTS.items():
        try:
            setattr(settings, key, value)
        except Exception:
            pass


def reset_billing_db_singleton() -> None:
    """Limpia engine/sesiones cacheados (p. ej. tras monkeypatch de DATABASE_URL)."""
    billing_db_module._engine = None
    billing_db_module._session_factory = None


def create_billing_test_engine(
    database_url: str = _TEST_DATABASE_URL,
) -> tuple[Engine, sessionmaker[Session]]:
    """Motor SQLite con esquema billing+chat; aislado por invocacion."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, factory


@pytest.fixture
def admin_api_headers() -> dict[str, str]:
    """Cabecera X-Admin-Key alineada con ADMIN_API_KEY de test."""
    return {"X-Admin-Key": _TEST_ADMIN_API_KEY}


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Limpia el state del rate limiter entre tests."""
    limiter.reset()


@pytest.fixture(autouse=True)
def _reset_app_state() -> Generator[None, None, None]:
    """Limpia app.state entre tests para evitar contaminacion de auto_scheduler.

    test_automations_results.py setea app.state.auto_scheduler y no lo limpia,
    lo que causa que auth_login intente usar asyncio.get_running_loop()
    en un worker thread (RuntimeError) porque scheduler is not None.
    """
    prev_scheduler = getattr(app.state, "auto_scheduler", None)
    yield
    app.state.auto_scheduler = prev_scheduler


@pytest.fixture(scope="module", autouse=True)
def _reset_settings_after_module() -> Generator[None, None, None]:
    """Restaura settings al default de test después de cada módulo.

    Previene contaminación entre módulos cuando tests monkeypatchean
    el singleton de settings (ej. test_health_db cambia database_url,
    test_whatsapp_inbound_auth cambia testing="0", etc.).
    """
    yield
    _restore_settings_defaults()


@pytest.fixture(autouse=True)
def _setup_db() -> Generator[None, None, None]:
    """SQLite :memory: por test; override de get_billing_db para TestClient."""
    prev_engine = billing_db_module._engine
    prev_factory = billing_db_module._session_factory

    reset_billing_db_singleton()
    engine, TestSession = create_billing_test_engine()
    billing_db_module._engine = engine
    billing_db_module._session_factory = TestSession

    def _override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_billing_db] = _override_db
    clear_memory_revocations()
    clear_memory_families()
    yield
    app.dependency_overrides.clear()
    billing_db_module._engine = prev_engine
    billing_db_module._session_factory = prev_factory
    clear_memory_revocations()
    clear_memory_families()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    reset_billing_db_singleton()


@pytest.fixture
def db_session(_setup_db) -> Generator[Session, None, None]:
    """Sesion SQLAlchemy alineada con Depends(get_billing_db) en rutas."""
    override = app.dependency_overrides[get_billing_db]
    gen = override()
    session = next(gen)
    try:
        yield session
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


@pytest.fixture
def billing_db_file(tmp_path) -> Generator[tuple[str, sessionmaker[Session]], None, None]:
    """BD SQLite en tmp_path (un archivo por test); para escenarios tipo health/db."""
    db_path = tmp_path / "billing_test.db"
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine, factory = create_billing_test_engine(url)
    try:
        yield url, factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def seed_cliente(session, **overrides) -> ClienteORM:
    """Crea un cliente de prueba en la sesion."""
    plain = overrides.pop("password", "test123")
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    defaults = {
        "id": uuid4(),
        "nombre": "Cliente Test",
        "cedula": "1234567890",
        "clave_acceso": hashed,
        "correo": "test@example.com",
        "telefono": "+584121234567",
        "fecha_vencimiento": date.today() + timedelta(days=30),
        "plan": PlanSuscripcionORM.mensual,
    }
    defaults.update(overrides)
    row = ClienteORM(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
