"""Resolución de número de teléfono a UID de usuario."""
from __future__ import annotations

import logging
import re

log = logging.getLogger("dot.whatsapp.phone_resolver")


def normalize_phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-15:] if digits else ""


def to_e164(phone: str | None, *, default_region: str = "VE") -> str | None:
    """
    Normaliza a E.164.

    Ejemplos (default_region=VE):
    - 04141234567 → +584141234567
    - 4141234567 → +584141234567
    - 584141234567 → +584141234567
    - +584141234567 → +584141234567
    """
    raw = (phone or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if digits.startswith("00") and len(digits) > 2:
        return f"+{digits[2:]}"

    region = (default_region or "VE").upper()
    if region == "VE":
        if digits.startswith("0") and len(digits) == 11:
            return f"+58{digits[1:]}"
        if digits.startswith("58") and 11 <= len(digits) <= 15:
            return f"+{digits}"
        if len(digits) == 10 and digits.startswith("4"):
            return f"+58{digits}"

    if 8 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def phones_match(stored: str, incoming: str) -> bool:
    a = normalize_phone_digits(to_e164(stored) or stored)
    b = normalize_phone_digits(to_e164(incoming) or incoming)
    if not a or not b:
        return False
    return a.endswith(b[-10:]) or b.endswith(a[-10:])


def resolve_uid_by_phone(phone: str) -> str | None:
    """
    Busca en Firestore el usuario cuyo canal WhatsApp tenga phone_number coincidente.
    """
    if not (phone or "").strip():
        return None
    try:
        from app.firebase_db import get_db

        db = get_db()
        for user in db.collection("users").stream():
            uid = user.id
            snap = (
                db.collection("users")
                .document(uid)
                .collection("whatsapp_channel")
                .document("data")
                .get()
            )
            if not snap.exists:
                continue
            data = snap.to_dict() or {}
            stored_phone = str(data.get("phone_number") or "")
            if stored_phone and phones_match(stored_phone, phone):
                return uid
    except RuntimeError:
        log.warning("Firestore no disponible para resolve_uid_by_phone")
    except Exception:
        log.exception("Error resolviendo uid por telefono")

    # Fallback memoria (whatsapp_link mantiene estado local en dev sin Firestore)
    try:
        from app.services.whatsapp_link import _channel_states

        for uid, state in _channel_states.items():
            if state.phone_number and phones_match(state.phone_number, phone):
                return uid
    except Exception:
        log.debug("Fallback memoria no disponible para resolve_uid_by_phone")

    return None


def resolve_uid_by_to_phone(to_phone: str) -> str | None:
    """Alias explícito: el inbound resuelve UID por el número vinculado (campo `to`)."""
    return resolve_uid_by_phone(to_phone)
