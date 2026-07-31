"""Tool audit log — registra cada ejecución de herramienta del agente.

Persiste en Firestore: users/{uid}/tool_audit/{timestamp}.
TTL: 90 días (limpieza vía scheduled job en retention_service).

Las entradas son inmutables — append-only para debugging y detección de abuso.

## Mejoras de seguridad (v2):
- Auth event logging (login, logout, refresh, failed attempts)
- Admin action logging (todas las acciones administrativas)
- Secret rotation logging
- Config change logging
- Export a formato SIEM (JSON + CEF)
"""

from __future__ import annotations

import json
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Any, Literal

from app.firebase_db import get_db

log = logging.getLogger("dot.tool_audit")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

AUDIT_TTL_DAYS = 90
MAX_ARG_LENGTH = 200
MAX_ARGS_KEYS = 20
SENSITIVE_ARG_SUBSTRINGS = (
    "password", "token", "secret", "api_key", "apikey", "credential",
    "pass", "pwd",
)

# Colecciones de Firestore para auditoría
SIEM_AUDIT_COLLECTION = "siem_audit_log"

# Tipos de eventos de auditoría
EventCategory = Literal[
    "auth_login",
    "auth_login_failed",
    "auth_logout",
    "auth_refresh",
    "auth_token_reuse",
    "admin_action",
    "admin_revoke_tokens",
    "secret_rotation",
    "config_change",
    "tool_execution",
    "input_threat_blocked",
    "rate_limit_exceeded",
    "permission_denied",
]

# Niveles de severidad SIEM
Severity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]


# ---------------------------------------------------------------------------
# Sanitización de argumentos
# ---------------------------------------------------------------------------

def _sanitize_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Elimina valores sensibles y trunca argumentos largos para el audit log."""
    if not args:
        return {}
    safe: dict[str, Any] = {}
    for key, val in list(args.items())[:MAX_ARGS_KEYS]:
        key_lower = key.lower()
        if any(s in key_lower for s in SENSITIVE_ARG_SUBSTRINGS):
            safe[key] = "[REDACTED]"
            continue
        str_val = str(val)
        if len(str_val) > MAX_ARG_LENGTH:
            safe[key] = str_val[:MAX_ARG_LENGTH] + "..."
        else:
            safe[key] = str_val
    return safe


# ---------------------------------------------------------------------------
# Escritura del log de auditoría de herramientas
# ---------------------------------------------------------------------------

def log_tool_execution(
    uid: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    result_ok: bool = False,
    error: str | None = None,
    duration_ms: int = 0,
) -> bool:
    """Registra una ejecución de herramienta en el audit log de Firestore."""
    db = get_db()
    if db is None:
        return False

    from firebase_admin import firestore

    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        doc_id = now_iso.replace(":", "-").replace(".", "-")

        safe_args = _sanitize_args(arguments)

        payload: dict[str, Any] = {
            "uid": uid,
            "tool_name": tool_name,
            "arguments": safe_args,
            "result": "success" if result_ok else "failure",
            "error": error,
            "duration_ms": duration_ms,
            "created_at": firestore.SERVER_TIMESTAMP,
            "expires_at": firestore.SERVER_TIMESTAMP,
            "iso_timestamp": now_iso,
        }

        (
            db.collection("users")
            .document(uid)
            .collection("tool_audit")
            .document(doc_id)
            .set(payload)
        )

        # También registrar en SIEM
        _write_siem_event(
            category="tool_execution",
            severity="INFO" if result_ok else "ERROR",
            user_id=uid,
            details={
                "tool_name": tool_name,
                "result": "success" if result_ok else "failure",
                "error": error,
                "duration_ms": duration_ms,
            },
        )

        return True
    except Exception as e:
        log.warning(
            "Error registrando tool audit para uid=%s tool=%s: %s",
            uid[:8], tool_name, e, exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Lectura del log de auditoría de herramientas
# ---------------------------------------------------------------------------

def get_user_audit_log(
    uid: str,
    limit: int = 50,
    tool_name: str | None = None,
) -> list[dict[str, Any]]:
    """Obtiene el log de auditoría del usuario desde Firestore."""
    db = get_db()
    if db is None:
        return []

    from firebase_admin import firestore

    limit = min(max(1, limit), 200)

    try:
        query = (
            db.collection("users")
            .document(uid)
            .collection("tool_audit")
        )

        if tool_name:
            query = query.where("tool_name", "==", tool_name.strip())

        query = query.order_by(
            "created_at", direction=firestore.Query.DESCENDING,
        ).limit(limit)

        docs = query.stream()
        return [doc.to_dict() or {} for doc in docs]
    except Exception as e:
        log.warning(
            "Error leyendo tool_audit para uid=%s: %s",
            uid[:8], e, exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Auth event logging
# ---------------------------------------------------------------------------

def log_auth_event(
    event: EventCategory,
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> bool:
    """Registra un evento de autenticación en el SIEM audit log.

    Args:
        event: Tipo de evento (auth_login, auth_logout, etc.)
        user_id: ID del usuario afectado
        ip_address: IP del cliente
        user_agent: User-Agent del cliente
        success: True si el evento fue exitoso
        details: Metadatos adicionales

    Returns:
        True si se registró correctamente
    """
    severity: Severity = "INFO"
    if not success:
        severity = "WARNING"
    if event in ("auth_token_reuse",):
        severity = "CRITICAL"

    return _write_siem_event(
        category=event,
        severity=severity,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        details=details,
    )


# ---------------------------------------------------------------------------
# Admin action logging
# ---------------------------------------------------------------------------

def log_admin_action(
    action: str,
    admin_id: str = "admin",
    ip_address: str | None = None,
    target_user_id: str | None = None,
    details: dict[str, Any] | None = None,
    success: bool = True,
) -> bool:
    """Registra una acción administrativa en el SIEM audit log.

    Args:
        action: Descripción de la acción (ej. "revoke_user_tokens")
        admin_id: Identificador del admin
        ip_address: IP del admin
        target_user_id: Usuario afectado por la acción
        details: Metadatos adicionales
        success: True si la acción fue exitosa

    Returns:
        True si se registró correctamente
    """
    return _write_siem_event(
        category="admin_action",
        severity="WARNING" if not success else "INFO",
        user_id=target_user_id,
        ip_address=ip_address,
        details={
            "action": action,
            "admin_id": admin_id,
            **(details or {}),
        },
        success=success,
    )


# ---------------------------------------------------------------------------
# Secret rotation logging
# ---------------------------------------------------------------------------

def log_secret_rotation(
    secret_type: str,
    rotation_id: str,
    initiator: str = "system",
    success: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Registra una rotación de secreto en el SIEM audit log.

    Args:
        secret_type: Tipo de secreto (jwt, fernet, api_keys)
        rotation_id: ID único de la rotación
        initiator: Quién inició la rotación
        success: True si la rotación fue exitosa
        error: Mensaje de error si falló
        metadata: Metadatos adicionales

    Returns:
        True si se registró correctamente
    """
    return _write_siem_event(
        category="secret_rotation",
        severity="INFO" if success else "ERROR",
        details={
            "secret_type": secret_type,
            "rotation_id": rotation_id,
            "initiator": initiator,
            "error": error,
            "metadata": metadata or {},
        },
        success=success,
    )


# ---------------------------------------------------------------------------
# Config change logging
# ---------------------------------------------------------------------------

def log_config_change(
    config_key: str,
    old_value_hash: str | None = None,
    new_value_hash: str | None = None,
    changed_by: str = "system",
    ip_address: str | None = None,
    reason: str | None = None,
) -> bool:
    """Registra un cambio de configuración en el SIEM audit log.

    Solo se almacenan hashes de los valores, nunca los valores reales.

    Args:
        config_key: Clave de configuración modificada
        old_value_hash: SHA-256 del valor anterior
        new_value_hash: SHA-256 del nuevo valor
        changed_by: Quién realizó el cambio
        ip_address: IP desde donde se realizó
        reason: Razón del cambio

    Returns:
        True si se registró correctamente
    """
    return _write_siem_event(
        category="config_change",
        severity="WARNING",
        ip_address=ip_address,
        details={
            "config_key": config_key,
            "old_value_hash": old_value_hash,
            "new_value_hash": new_value_hash,
            "changed_by": changed_by,
            "reason": reason,
        },
        success=True,
    )


# ---------------------------------------------------------------------------
# Security event logging (amenazas detectadas, rate limits, etc.)
# ---------------------------------------------------------------------------

def log_security_event(
    event: EventCategory,
    ip_address: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
    severity: Severity = "WARNING",
) -> bool:
    """Registra un evento de seguridad genérico en el SIEM audit log."""
    return _write_siem_event(
        category=event,
        severity=severity,
        user_id=user_id,
        ip_address=ip_address,
        details=details,
        success=False,
    )


# ---------------------------------------------------------------------------
# SIEM Core: escritura unificada con formato JSON + CEF
# ---------------------------------------------------------------------------

def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _write_siem_event(
    category: EventCategory,
    severity: Severity = "INFO",
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> bool:
    """Escribe un evento de auditoría SIEM en Firestore.

    Cada evento se almacena con formato dual: JSON estructurado y
    representación CEF (Common Event Format) compatible con SIEM.

    Returns:
        True si se registró correctamente
    """
    db = get_db()
    if db is None:
        log.debug("Firestore no disponible — SIEM event no persistido: %s", category)
        return False

    try:
        from firebase_admin import firestore

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        doc_id = now_iso.replace(":", "-").replace(".", "-")

        hostname = _get_hostname()

        # Payload JSON estructurado
        payload: dict[str, Any] = {
            "category": category,
            "severity": severity,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "iso_timestamp": now_iso,
            "hostname": hostname,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "success": success,
            "details": details or {},
        }

        # Representación CEF (Common Event Format)
        # Formato: CEF:Version|Device Vendor|Device Product|Device Version|Signature ID|Name|Severity|Extension
        cef_severity = {"INFO": "0", "WARNING": "5", "ERROR": "7", "CRITICAL": "10"}.get(severity, "0")
        cef_name = category.replace("_", " ")
        cef_extensions = []
        if user_id:
            cef_extensions.append(f"suser={user_id}")
        if ip_address:
            cef_extensions.append(f"src={ip_address}")
        cef_extensions.append(f"outcome={'success' if success else 'failure'}")
        if details:
            for k, v in details.items():
                safe_v = str(v).replace("=", "\\=").replace(" ", "\\s")[:200]
                cef_extensions.append(f"cs1Label={k} cs1={safe_v}")
                break  # Solo un par cs1 en CEF estándar

        payload["cef"] = (
            f"CEF:0|Nordik-IA|DOT-API|1.0|{category}|{cef_name}|{cef_severity}|"
            + " ".join(cef_extensions[:10])
        )

        (
            db.collection(SIEM_AUDIT_COLLECTION)
            .document(doc_id)
            .set(payload)
        )

        # También loguear en el logger estructurado para exportación a SIEM vía BetterStack/Logtail
        log.info(
            "SIEM|%s|%s|user=%s|ip=%s|success=%s|%s",
            category, severity,
            user_id or "-", ip_address or "-",
            success, json.dumps(details or {}, default=str),
        )

        return True
    except Exception as e:
        log.warning("Error escribiendo SIEM event %s: %s", category, e)
        return False


# ---------------------------------------------------------------------------
# Exportación de audit log a formato SIEM (JSON / CEF)
# ---------------------------------------------------------------------------

def export_siem_log(
    format: Literal["json", "cef"] = "json",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    category: EventCategory | None = None,
) -> list[dict[str, Any]] | str:
    """Exporta el audit log SIEM en formato JSON o CEF.

    Args:
        format: "json" o "cef"
        start_time: Filtro desde fecha (opcional)
        end_time: Filtro hasta fecha (opcional)
        limit: Máximo de entradas (default 1000, max 5000)
        category: Filtrar por categoría (opcional)

    Returns:
        Lista de eventos en formato JSON, o string multilínea en formato CEF
    """
    db = get_db()
    if db is None:
        return [] if format == "json" else ""

    from firebase_admin import firestore

    limit = min(max(1, limit), 5000)

    try:
        query = (
            db.collection(SIEM_AUDIT_COLLECTION)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )

        if category:
            query = query.where("category", "==", category)

        if start_time:
            query = query.where("timestamp", ">=", start_time)
        if end_time:
            query = query.where("timestamp", "<=", end_time)

        docs = query.stream()
        events = [doc.to_dict() or {} for doc in docs]

        if format == "json":
            return events
        else:
            # CEF multilínea
            lines = [
                e.get("cef", "")
                for e in events
                if e.get("cef")
            ]
            return "\n".join(lines)

    except Exception as e:
        log.warning("Error exportando SIEM log: %s", e)
        return [] if format == "json" else ""


def get_siem_stats(hours: int = 24) -> dict[str, Any]:
    """Obtiene estadísticas del SIEM audit log para las últimas N horas.

    Útil para dashboards de seguridad y monitoreo.
    """
    db = get_db()
    if db is None:
        return {"error": "Firestore no disponible"}

    from firebase_admin import firestore

    try:
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)

        docs = (
            db.collection(SIEM_AUDIT_COLLECTION)
            .where("timestamp", ">=", cutoff_dt)
            .stream()
        )

        stats: dict[str, Any] = {
            "total_events": 0,
            "by_category": {},
            "by_severity": {},
            "by_success": {"success": 0, "failure": 0},
            "hours": hours,
        }

        for doc in docs:
            data = doc.to_dict()
            if not data:
                continue
            stats["total_events"] += 1
            cat = data.get("category", "unknown")
            sev = data.get("severity", "INFO")
            ok = data.get("success", True)

            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
            stats["by_severity"][sev] = stats["by_severity"].get(sev, 0) + 1
            if ok:
                stats["by_success"]["success"] += 1
            else:
                stats["by_success"]["failure"] += 1

        return stats
    except Exception as e:
        log.warning("Error obteniendo SIEM stats: %s", e)
        return {"error": str(e)}
