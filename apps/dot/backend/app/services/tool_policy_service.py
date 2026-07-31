"""Tool policy service — allow/deny per-agent via Firestore.

Políticas por usuario almacenadas en users/{uid}/tool_policies/_active.
Dangerous tools blocked by default (deny-by-default).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.firebase_db import get_db
from app.settings import settings

log = logging.getLogger("dot.tool_policy")

# ---------------------------------------------------------------------------
# Herramientas peligrosas — deny-by-default para todos los usuarios
# El usuario debe agregarlas explícitamente a su allow-list para usarlas.
# ---------------------------------------------------------------------------
DANGEROUS_TOOLS: set[str] = {
    "browser_navigate",
    "exec",
    "deleteFile",
    "send_whatsapp_campaign",
}

# Capa B — navegación web guiada (BR05). Solo browser_navigate está en deny-by-default.
BROWSER_WEB_GATE_TOOL = "browser_navigate"

BROWSER_WEB_TOGGLE_LABEL = "DOT puede usar webs"
BROWSER_WEB_SETTINGS_PATH = "Configuración → Privacidad"

BROWSER_WEB_DISABLED_MESSAGE = (
    f"Para que DOT entre en páginas web, actívalo en {BROWSER_WEB_SETTINGS_PATH} → "
    f"'{BROWSER_WEB_TOGGLE_LABEL}'."
)


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass
class ToolPolicy:
    """Política de herramientas de un usuario."""

    allow_list: set[str] = field(default_factory=set)
    deny_list: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def get_default_policies() -> dict[str, Any]:
    """Devuelve las políticas por defecto del sistema."""
    return {
        "dangerous_tools": sorted(DANGEROUS_TOOLS),
        "default_policy": "deny_dangerous",
        "policy_description": (
            "Por defecto, las herramientas peligrosas están bloqueadas. "
            "El usuario puede permitirlas individualmente agregándolas a su allow-list."
        ),
    }


# ---------------------------------------------------------------------------
# Lectura de política desde Firestore
# ---------------------------------------------------------------------------

def _get_user_policy(uid: str) -> ToolPolicy | None:
    """Lee la política del usuario desde Firestore.

    Retorna None si Firestore no está disponible (modo offline).
    """
    db = get_db()
    if db is None:
        return None
    try:
        doc = (
            db.collection("users")
            .document(uid)
            .collection("tool_policies")
            .document("_active")
            .get()
        )
        if doc.exists:
            data = doc.to_dict() or {}
            return ToolPolicy(
                allow_list=set(data.get("allow_list", [])),
                deny_list=set(data.get("deny_list", [])),
            )
    except Exception as e:
        log.warning(
            "Error leyendo tool_policy para uid=%s: %s", uid[:8], e, exc_info=True,
        )
    return None


# ---------------------------------------------------------------------------
# Check principal — llamado desde ToolRegistry antes de ejecutar
# ---------------------------------------------------------------------------

def check_tool_allowed(uid: str, tool_name: str) -> tuple[bool, str]:
    """Verifica si una herramienta está permitida para un usuario.

    Orden de evaluación:
      1. Deny-list del usuario → bloquea sin excepción.
      2. Allow-list del usuario → permite explícitamente (incluso dangerous).
      3. Dangerous tools → deny-by-default si no están en allow-list.
      4. Cualquier otra tool → permitida.

    Returns:
        (allowed: bool, reason: str) — reason vacío si allowed=True.
    """
    policy = _get_user_policy(uid)

    # Firestore no disponible
    if policy is None:
        if settings.is_production:
            # Fail closed en producción — seguridad ante todo
            return (
                False,
                "Servicio de políticas no disponible. Intenta más tarde.",
            )
        # Fail open en desarrollo — no bloquear al developer
        if tool_name in DANGEROUS_TOOLS:
            return (
                False,
                f"Herramienta '{tool_name}' bloqueada (peligrosa por defecto).",
            )
        return True, ""

    # 1. Deny-list prevalece sobre todo
    if tool_name in policy.deny_list:
        return (
            False,
            f"Herramienta '{tool_name}' bloqueada por tu política de denegación.",
        )

    # 2. Allow-list permite explícitamente (incluso dangerous tools)
    if tool_name in policy.allow_list:
        return True, ""

    # 3. Dangerous tools → deny-by-default
    if tool_name in DANGEROUS_TOOLS:
        if tool_name == BROWSER_WEB_GATE_TOOL:
            return False, BROWSER_WEB_DISABLED_MESSAGE
        return (
            False,
            f"Herramienta '{tool_name}' bloqueada (peligrosa por defecto). "
            "Agrégala a tu allow-list para usarla.",
        )

    # 4. Default: allow
    return True, ""


# ---------------------------------------------------------------------------
# Escritura de política en Firestore
# ---------------------------------------------------------------------------

def save_user_policy(
    uid: str,
    allow_list: list[str] | None = None,
    deny_list: list[str] | None = None,
) -> bool:
    """Guarda/actualiza la política de herramientas del usuario en Firestore.

    Args:
        uid: ID del usuario en Firestore.
        allow_list: Lista de nombres de herramientas permitidas (None = no modificar).
        deny_list: Lista de nombres de herramientas denegadas (None = no modificar).

    Returns:
        True si se guardó correctamente, False si hubo error.
    """
    db = get_db()
    if db is None:
        log.warning(
            "Firestore no disponible para guardar tool_policy de uid=%s", uid[:8],
        )
        return False

    from firebase_admin import firestore

    try:
        data: dict[str, Any] = {
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if allow_list is not None:
            data["allow_list"] = sorted(
                t.strip() for t in allow_list if t.strip()
            )
        if deny_list is not None:
            data["deny_list"] = sorted(
                t.strip() for t in deny_list if t.strip()
            )

        (
            db.collection("users")
            .document(uid)
            .collection("tool_policies")
            .document("_active")
            .set(data, merge=True)
        )
        log.info(
            "tool_policy guardada para uid=%s: allow=%d, deny=%d",
            uid[:8],
            len(data.get("allow_list", [])),
            len(data.get("deny_list", [])),
        )
        return True
    except Exception as e:
        log.warning(
            "Error guardando tool_policy para uid=%s: %s",
            uid[:8], e, exc_info=True,
        )
        return False


def get_user_policy_raw(uid: str) -> dict[str, Any] | None:
    """Devuelve la política del usuario como dict para endpoints REST.

    Retorna None si no hay política guardada o Firestore no disponible.
    """
    policy = _get_user_policy(uid)
    if policy is None and get_db() is None:
        return None  # Firestore offline
    if policy is None:
        # Sin política guardada — devolver defaults vacíos
        return {
            "allow_list": [],
            "deny_list": [],
            "dangerous_tools": sorted(DANGEROUS_TOOLS),
            "defaults": get_default_policies(),
        }
    return {
        "allow_list": sorted(policy.allow_list),
        "deny_list": sorted(policy.deny_list),
        "dangerous_tools": sorted(DANGEROUS_TOOLS),
        "defaults": get_default_policies(),
    }


def is_browser_web_enabled(uid: str) -> bool:
    """True si el usuario activó navegación web en Configuración."""
    policy = _get_user_policy(uid)
    if policy is None:
        return False
    return BROWSER_WEB_GATE_TOOL in policy.allow_list


def set_browser_web_enabled(uid: str, enabled: bool) -> bool:
    """Activa o desactiva la capa B de navegación web para el usuario."""
    policy = _get_user_policy(uid)
    allow = set(policy.allow_list if policy else [])
    deny = set(policy.deny_list if policy else [])

    if enabled:
        allow.add(BROWSER_WEB_GATE_TOOL)
        deny.discard(BROWSER_WEB_GATE_TOOL)
    else:
        allow.discard(BROWSER_WEB_GATE_TOOL)

    return save_user_policy(
        uid=uid,
        allow_list=sorted(allow),
        deny_list=sorted(deny),
    )
