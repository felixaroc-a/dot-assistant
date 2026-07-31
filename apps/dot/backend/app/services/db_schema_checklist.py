"""Checklist canónico de tablas (billing + chat) para preflight, ensure_schema y Alembic."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

# --- Tablas por dominio (fuente única; alineado con infra/billing/schema.sql y migraciones) ---
# alembic bee4011b0d3e: dot_billing.models (create_all)
BILLING_TABLES: tuple[str, ...] = (
    "clientes_suscripcion",
    "subscription_reminder_outbox",
    "usage_tokens",
)

# alembic 8a3f2c1e5b7d: app.chat_models
CHAT_TABLES: tuple[str, ...] = (
    "chat_conversations",
    "chat_messages",
)

# refresh_store.RefreshTokenFamilyORM (misma Base que billing)
AUTH_TABLES: tuple[str, ...] = ("refresh_token_families",)

BACKEND_ALL_TABLES: tuple[str, ...] = BILLING_TABLES + CHAT_TABLES + AUTH_TABLES

# Mínimo para auth / panel / Chatbot sobre la misma Postgres de billing
BILLING_MINIMUM_TABLES: tuple[str, ...] = ("clientes_suscripcion",)

SERVICE_ENV_FILES: tuple[tuple[str, str], ...] = (
    ("frontend/backend", ".env"),
    ("auto-venta1", ".env"),
)


@dataclass(frozen=True)
class MissingTablesReport:
    present: frozenset[str] = frozenset()
    missing_billing: tuple[str, ...] = ()
    missing_chat: tuple[str, ...] = ()
    missing_auth: tuple[str, ...] = ()

    @property
    def ok_billing_minimum(self) -> bool:
        return "clientes_suscripcion" not in self.missing_billing

    @property
    def ok_billing_full(self) -> bool:
        return len(self.missing_billing) == 0

    @property
    def ok_chat(self) -> bool:
        return len(self.missing_chat) == 0

    @property
    def ok_auth(self) -> bool:
        return len(self.missing_auth) == 0

    @property
    def ok_all(self) -> bool:
        return self.ok_billing_full and self.ok_chat and self.ok_auth


@dataclass(frozen=True)
class DatabaseUrlConsistencyReport:
    """Comparación opcional entre .env de servicios (no impone una sola BD)."""

    urls_by_service: dict[str, str | None] = field(default_factory=dict)
    normalized_by_service: dict[str, str | None] = field(default_factory=dict)
    distinct_normalized: tuple[str, ...] = ()

    @property
    def is_consistent(self) -> bool:
        return len(self.distinct_normalized) <= 1


def engine_from_database_url(raw: str) -> Engine:
    """Motor efímero para preflight (no usa singleton de billing_db)."""
    url = raw.strip()
    if url.startswith("sqlite:///") and not url.startswith("sqlite+pysqlite"):
        url = "sqlite+pysqlite:///" + url.removeprefix("sqlite:///")
    connect_args: dict[str, bool] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def missing_tables(engine: Engine, *, check_chat: bool = True, check_auth: bool = True) -> MissingTablesReport:
    names = set(inspect(engine).get_table_names())
    missing_billing = tuple(t for t in BILLING_TABLES if t not in names)
    missing_chat: tuple[str, ...] = ()
    if check_chat:
        missing_chat = tuple(t for t in CHAT_TABLES if t not in names)
    missing_auth: tuple[str, ...] = ()
    if check_auth:
        missing_auth = tuple(t for t in AUTH_TABLES if t not in names)
    return MissingTablesReport(
        present=frozenset(names),
        missing_billing=missing_billing,
        missing_chat=missing_chat,
        missing_auth=missing_auth,
    )


def normalize_database_url(raw: str | None) -> str | None:
    """Normaliza URLs SQLAlchemy para comparar entre servicios (sin credenciales en salida)."""
    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith("sqlite"):
        path = value.split("///", 1)[-1] if "///" in value else value
        return f"sqlite:///{Path(path).resolve().as_posix().lower()}"

    normalized = value
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
        if normalized.startswith(prefix):
            normalized = "postgresql://" + normalized[len(prefix) :]
            break

    parsed = urlparse(normalized)
    if not parsed.scheme:
        return None
    host = (parsed.hostname or "localhost").lower()
    port = parsed.port or (5432 if parsed.scheme.startswith("postgres") else "")
    port_part = f":{port}" if port else ""
    db = (parsed.path or "").strip("/").lower()
    netloc = f"{host}{port_part}"
    return urlunparse((parsed.scheme.lower(), netloc, db, "", "", ""))


def parse_database_url_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if not stripped.upper().startswith("DATABASE_URL"):
            continue
        _, _, rhs = stripped.partition("=")
        value = rhs.strip().strip('"').strip("'")
        return value or None
    return None


def compare_service_database_urls(
    repo_root: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> DatabaseUrlConsistencyReport:
    """Lee DATABASE_URL de .env por servicio; no exige una sola BD entre procesos."""
    urls: dict[str, str | None] = {}
    if extra_env and (extra_env.get("DATABASE_URL") or "").strip():
        urls["frontend/backend (proceso actual)"] = (extra_env.get("DATABASE_URL") or "").strip()

    for service_dir, env_name in SERVICE_ENV_FILES:
        label = service_dir.replace("/", " / ")
        if label in urls:
            continue
        env_path = repo_root / service_dir / env_name
        urls[label] = parse_database_url_from_env_file(env_path)

    normalized = {k: normalize_database_url(v) for k, v in urls.items() if v}
    distinct = tuple(sorted({v for v in normalized.values() if v}))
    return DatabaseUrlConsistencyReport(
        urls_by_service=urls,
        normalized_by_service=normalized,
        distinct_normalized=distinct,
    )


def format_missing_tables_hint(report: MissingTablesReport, *, enable_chat: bool) -> str:
    parts: list[str] = []
    if report.missing_billing:
        parts.append(
            "Tablas billing faltantes: "
            + ", ".join(report.missing_billing)
            + ". Ejecuta: npm run billing:ensure-schema o alembic upgrade head."
        )
    if enable_chat and report.missing_chat:
        parts.append(
            "Tablas chat faltantes: "
            + ", ".join(report.missing_chat)
            + ". Migración 8a3f2c1e5b7d: alembic upgrade head o billing:ensure-schema con chat_models cargado."
        )
    if report.missing_auth:
        parts.append(
            "Tablas auth faltantes: "
            + ", ".join(report.missing_auth)
            + ". Reinicia el backend o ejecuta billing:ensure-schema (refresh_store debe estar importado)."
        )
    return " ".join(parts)
