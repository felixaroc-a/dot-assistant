"""Rate limit simple por uid para ejecución de tools (FASE 6 / R6)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)

# Ventana deslizante: máx N tools por uid por minuto
DEFAULT_LIMIT = 30
WINDOW_SEC = 60.0


def allow_tool_call(uid: str, *, limit: int = DEFAULT_LIMIT) -> bool:
    """True si el uid puede ejecutar otra tool ahora."""
    key = (uid or "").strip() or "anonymous"
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and (now - q[0]) > WINDOW_SEC:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()
