"""Heartbeat de actividad de usuario (`last_active_at`) para retención D5."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from app.firebase_db import merge_user_profile
from app.settings import settings

log = logging.getLogger("dot.activity_service")

_lock = threading.Lock()
_last_touch_monotonic: dict[str, float] = {}


def parse_last_active_at(value: object) -> datetime | None:
    """Normaliza `last_active_at` desde Firestore/ISO a datetime UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # Firestore Timestamp
    to_dt = getattr(value, "to_datetime", None)
    if callable(to_dt):
        try:
            dt = to_dt()
        except Exception:
            log.debug("Error convirtiendo Firestore Timestamp a datetime", exc_info=True)
            return None
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return None


def _throttle_allows(uid: str, *, force: bool) -> bool:
    throttle = max(0, int(settings.retention_activity_throttle_seconds))
    if force or throttle <= 0:
        return True
    now = time.monotonic()
    with _lock:
        previous = _last_touch_monotonic.get(uid)
        if previous is not None and (now - previous) < throttle:
            return False
        _last_touch_monotonic[uid] = now
    return True


def touch_last_active(uid: str, *, force: bool = False) -> bool:
    """Actualiza `last_active_at` en Firestore. Devuelve True si escribió."""
    clean = (uid or "").strip()
    if not clean:
        return False
    if not _throttle_allows(clean, force=force):
        return False

    now = datetime.now(timezone.utc)
    merge_user_profile(
        clean,
        {
            "last_active_at": now.isoformat(),
            "retention_purged_at": None,
        },
    )
    return True


def touch_last_active_best_effort(uid: str, *, force: bool = False) -> None:
    """Igual que touch_last_active, pero nunca propaga errores al request."""
    try:
        touch_last_active(uid, force=force)
    except Exception:
        log.debug("No se pudo actualizar last_active_at uid=%s", (uid or "")[:8], exc_info=True)
