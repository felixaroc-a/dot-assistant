"""Preflight de configuración para hardening de producción."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from sqlalchemy.exc import SQLAlchemyError

from app.services.db_schema_checklist import (
    compare_service_database_urls,
    engine_from_database_url,
    format_missing_tables_hint,
    missing_tables,
)

TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[1]


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _is_truthy(value: str | None) -> bool:
    return _clean(value).lower() in TRUTHY_VALUES


def _is_falsy(value: str | None) -> bool:
    return _clean(value).lower() in FALSY_VALUES


def _resolve_path(raw_value: str) -> Path:
    raw = _clean(raw_value)
    p = Path(raw)
    if p.is_absolute():
        return p
    return (BACKEND_ROOT / p).resolve()


def run_config_preflight(env: Mapping[str, str] | None = None) -> dict[str, object]:
    source = env or {}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def get(key: str) -> str:
        return _clean(source.get(key))

    def add_error(key: str, message: str) -> None:
        errors.append({"key": key, "message": message})

    def add_warning(key: str, message: str) -> None:
        warnings.append({"key": key, "message": message})

    def require_non_empty(key: str, message: str) -> None:
        if not get(key):
            add_error(key, message)

    require_non_empty("DATABASE_URL", "DATABASE_URL es obligatorio para conectar billing/auth.")
    require_non_empty(
        "TOKEN_ENCRYPTION_KEY",
        "TOKEN_ENCRYPTION_KEY es obligatorio para cifrar secretos OAuth.",
    )
    require_non_empty(
        "CHAT_ENCRYPTION_KEY",
        "CHAT_ENCRYPTION_KEY es obligatorio para cifrar conversaciones de chat.",
    )
    require_non_empty("ADMIN_API_KEY", "ADMIN_API_KEY es obligatorio para endpoints internos admin.")
    require_non_empty(
        "HARDWARE_TOKEN_PEPPER",
        "HARDWARE_TOKEN_PEPPER es obligatorio para validar hardware token/pendrive.",
    )

    admin_api_key = get("ADMIN_API_KEY")
    if admin_api_key and len(admin_api_key) < 16:
        add_warning("ADMIN_API_KEY", "Se recomienda ADMIN_API_KEY con al menos 16 caracteres.")

    hardware_pepper = get("HARDWARE_TOKEN_PEPPER")
    if hardware_pepper and len(hardware_pepper) < 32:
        add_error(
            "HARDWARE_TOKEN_PEPPER",
            "HARDWARE_TOKEN_PEPPER debe tener mínimo 32 caracteres.",
        )

    has_hs = bool(get("JWT_SECRET"))
    has_rs = bool(get("JWT_PRIVATE_KEY_PEM") and get("JWT_PUBLIC_KEY_PEM"))
    if not (has_hs or has_rs):
        add_error(
            "JWT_SECRET/JWT_PRIVATE_KEY_PEM",
            "Configura JWT_SECRET (dev) o par RS256 JWT_PRIVATE_KEY_PEM/JWT_PUBLIC_KEY_PEM.",
        )

    enable_chat_raw = get("ENABLE_CHAT").lower()
    enable_chat = enable_chat_raw not in FALSY_VALUES
    if enable_chat and not (get("DEEPSEEK_API_KEY") or get("GEMINI_API_KEY") or get("OPENAI_API_KEY")):
        add_error(
            "DEEPSEEK_API_KEY/GEMINI_API_KEY/OPENAI_API_KEY",
            "Con ENABLE_CHAT activo necesitas al menos un proveedor IA configurado.",
        )

    dot_env = get("DOT_ENV").lower() or "development"
    is_production = dot_env == "production"

    if is_production:
        if _is_truthy(get("ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH")):
            add_error(
                "ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH",
                "No se permite ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH=1 en producción.",
            )

        trusted_hosts = [x.strip() for x in get("TRUSTED_HOSTS").split(",") if x.strip()]
        if not trusted_hosts:
            add_error("TRUSTED_HOSTS", "TRUSTED_HOSTS no puede estar vacío en producción.")
        elif "*" in trusted_hosts:
            add_error(
                "TRUSTED_HOSTS",
                "TRUSTED_HOSTS no debe usar '*' en producción.",
            )

        refresh_only = get("REFRESH_USE_FIRESTORE_ONLY")
        if _is_falsy(refresh_only):
            add_error(
                "REFRESH_USE_FIRESTORE_ONLY",
                "REFRESH_USE_FIRESTORE_ONLY no puede estar en falso en producción.",
            )
        elif not refresh_only:
            add_warning(
                "REFRESH_USE_FIRESTORE_ONLY",
                "Define REFRESH_USE_FIRESTORE_ONLY=1 explícitamente para endurecer configuración.",
            )

        redirect_uri = get("OAUTH_REDIRECT_URI").lower()
        if "localhost" in redirect_uri or "127.0.0.1" in redirect_uri:
            add_warning(
                "OAUTH_REDIRECT_URI",
                "OAUTH_REDIRECT_URI apunta a localhost; usa dominio HTTPS real en producción.",
            )

    for path_var in ("FIREBASE_SERVICE_ACCOUNT_PATH", "GOOGLE_CLIENT_SECRETS_PATH"):
        raw_path = get(path_var)
        if not raw_path:
            continue
        resolved = _resolve_path(raw_path)
        if not resolved.exists():
            message = f"No existe el archivo configurado en {path_var}: {resolved}"
            if is_production:
                add_error(path_var, message)
            else:
                add_warning(path_var, message)

    _check_database_url_consistency(source, add_warning, is_production=is_production)
    _check_database_schema(source, add_error, add_warning, enable_chat=enable_chat, is_production=is_production)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "meta": {
            "dot_env": dot_env,
            "is_production": is_production,
            "checked_keys": [
                "DATABASE_URL",
                "JWT_SECRET/JWT_PRIVATE_KEY_PEM",
                "TOKEN_ENCRYPTION_KEY",
                "CHAT_ENCRYPTION_KEY",
                "ADMIN_API_KEY",
                "HARDWARE_TOKEN_PEPPER",
                "ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH",
                "TRUSTED_HOSTS",
                "REFRESH_USE_FIRESTORE_ONLY",
                "OAUTH_REDIRECT_URI",
                "FIREBASE_SERVICE_ACCOUNT_PATH",
                "GOOGLE_CLIENT_SECRETS_PATH",
                "DEEPSEEK_API_KEY/GEMINI_API_KEY/OPENAI_API_KEY",
                "DATABASE_SCHEMA",
                "DATABASE_URL_CROSS_SERVICE",
            ],
        },
    }


def _check_database_url_consistency(
    source: Mapping[str, str],
    add_warning,
    *,
    is_production: bool,
) -> None:
    report = compare_service_database_urls(REPO_ROOT, extra_env=source)
    found = [k for k, v in report.urls_by_service.items() if v]
    if len(found) < 2:
        return
    if report.is_consistent:
        return
    services = ", ".join(f"{k}={v}" for k, v in report.urls_by_service.items() if v)
    message = (
        "DATABASE_URL difiere entre servicios detectados en .env "
        f"({services}). DOT no fusiona bases automáticamente: cada proceso usa su URL. "
        "En dev, alinea manualmente si auto-venta1 y backend deben compartir "
        "clientes_suscripcion y subscription_reminder_outbox."
    )
    if is_production:
        add_warning("DATABASE_URL_CROSS_SERVICE", message)
    else:
        add_warning("DATABASE_URL_CROSS_SERVICE", message)


def _check_database_schema(
    source: Mapping[str, str],
    add_error,
    add_warning,
    *,
    enable_chat: bool,
    is_production: bool,
) -> None:
    db_url = (source.get("DATABASE_URL") or "").strip()
    if not db_url:
        return
    try:
        from app import chat_models  # noqa: F401 — registra tablas en metadata

        engine = engine_from_database_url(db_url)
        with engine.connect():
            pass
        schema = missing_tables(engine, check_chat=True)
        engine.dispose()
    except (RuntimeError, SQLAlchemyError, OSError) as exc:
        msg = f"No se pudo verificar tablas en DATABASE_URL: {exc}"
        if is_production:
            add_error("DATABASE_SCHEMA", msg)
        else:
            add_warning("DATABASE_SCHEMA", msg)
        return

    if not schema.ok_billing_minimum:
        hint = format_missing_tables_hint(schema, enable_chat=False)
        add_error(
            "DATABASE_SCHEMA",
            f"Falta tabla crítica clientes_suscripcion en la BD del backend. {hint}",
        )
        return

    if not schema.ok_billing_full:
        hint = format_missing_tables_hint(schema, enable_chat=False)
        add_warning(
            "DATABASE_SCHEMA",
            f"Tablas billing incompletas (p. ej. recordatorios Chatbot). {hint}",
        )

    if enable_chat and not schema.ok_chat:
        hint = format_missing_tables_hint(schema, enable_chat=True)
        key = "DATABASE_SCHEMA"
        msg = f"ENABLE_CHAT activo pero faltan tablas de chat. {hint}"
        if is_production:
            add_error(key, msg)
        else:
            add_warning(key, msg)


def format_preflight_report(report: Mapping[str, object]) -> str:
    lines: list[str] = []
    ok = bool(report.get("ok"))
    lines.append("Preflight configuración DOT backend")
    lines.append(f"Estado: {'OK' if ok else 'FAIL'}")

    errors = list(report.get("errors") or [])
    warnings = list(report.get("warnings") or [])
    lines.append(f"Errores: {len(errors)}")
    lines.append(f"Warnings: {len(warnings)}")

    if errors:
        lines.append("")
        lines.append("Errores:")
        for item in errors:
            key = str(item.get("key") or "unknown")
            message = str(item.get("message") or "")
            lines.append(f"- [{key}] {message}")

    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for item in warnings:
            key = str(item.get("key") or "unknown")
            message = str(item.get("message") or "")
            lines.append(f"- [{key}] {message}")

    return "\n".join(lines).strip() + "\n"
