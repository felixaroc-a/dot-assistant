"""Audit logging de eventos de seguridad.

Versión mejorada: todos los eventos se escriben tanto en el logger estructurado
como en el SIEM audit log de Firestore (colección siem_audit_log).

Integración transparente: los endpoints de auth, admin, y tools siguen usando
audit_event() sin cambios; internamente se enriquece con metadata y se persiste.
"""

from __future__ import annotations

import logging
from typing import Any

audit_log = logging.getLogger("dot.audit")


def audit_event(event: str, **fields: Any) -> None:
    """Registro estructurado sin datos sensibles (sin passwords ni tokens completos).

    Además del log tradicional, también persiste en el SIEM audit log de Firestore
    para búsqueda forense y exportación a plataformas SIEM externas.
    """
    safe = {k: v for k, v in fields.items() if k not in ("password", "token", "refresh_token", "access_token")}
    audit_log.info("security_event=%s %s", event, safe)

    # Bridge al SIEM audit log (best-effort, no bloquear si falla)
    _bridge_to_siem(event, safe)


def _bridge_to_siem(event: str, fields: dict[str, Any]) -> None:
    """Redirige eventos de auditoría al SIEM audit service."""
    try:
        from app.services.tool_audit_service import (
            log_auth_event,
            log_admin_action,
            log_security_event,
        )

        # Mapeo de eventos de auditoría a categorías SIEM
        auth_events = {
            "login_success": ("auth_login", True),
            "login_failed": ("auth_login_failed", False),
            "login_subscription_expired": ("auth_login", False),
            "logout": ("auth_logout", True),
            "refresh_success": ("auth_refresh", True),
            "refresh_token_reuse_detected": ("auth_token_reuse", False),
        }

        admin_events = {
            "admin_revoke_user_tokens": "admin_revoke_tokens",
            "secret_rotation_requested": "secret_rotation",
        }

        if event in auth_events:
            category, success = auth_events[event]
            user_id = fields.get("cliente_id") or fields.get("cedula")
            ip = fields.get("ip")
            log_auth_event(
                event=category,  # type: ignore[arg-type]
                user_id=str(user_id) if user_id else None,
                ip_address=str(ip) if ip else None,
                success=success,
                details={"original_event": event},
            )

        elif event in admin_events:
            category = admin_events[event]
            ip = fields.get("ip")
            log_admin_action(
                action=category,
                admin_id="admin",
                ip_address=str(ip) if ip else None,
                target_user_id=str(fields.get("target_uid")) if fields.get("target_uid") else None,
                details={"original_event": event, **{k: v for k, v in fields.items() if k not in ("ip", "target_uid")}},
            )

        else:
            # Evento genérico de seguridad
            ip = fields.get("ip")
            log_security_event(
                event="permission_denied" if "denied" in event else "config_change",  # type: ignore[arg-type]
                ip_address=str(ip) if ip else None,
                details={"original_event": event, **fields},
            )

    except ImportError:
        pass  # SIEM service no disponible (ej. durante import circular)
    except Exception:
        pass  # Best-effort: no bloquear la operación principal
