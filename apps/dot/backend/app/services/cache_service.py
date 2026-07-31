"""Cache persistente con SQLite para respuestas de API y LLM.

Reemplaza el cache en memoria anterior que se perdia al reiniciar.
Usa SQLite como backend: persistente, sin dependencias externas.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

log = logging.getLogger("dot.cache_service")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cache.db"


def _json_cache_value(value: Any) -> Any:
    """Convierte Pydantic y otros tipos no serializables para persistir en cache."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


class PersistentCache:
    """Cache persistente con SQLite.

    Caracteristicas:
    - Persistente entre reinicios del servidor
    - TTL configurable por entrada
    - Invalidez por patron (prefix match)
    - Thread-safe
    - Automatic cleanup de entradas expiradas
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_expires
                ON cache(expires_at)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, key: str) -> Any | None:
        """Obtiene un valor del cache. Retorna None si no existe o expiro."""
        now = time.monotonic()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        value, expires_at = row["value"], row["expires_at"]
        if now > expires_at:
            self.delete(key)
            return None

        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: int = 60) -> None:
        """Guarda un valor en el cache con TTL."""
        expires_at = time.monotonic() + ttl_seconds
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(_json_cache_value(value)), expires_at),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        """Elimina una entrada del cache."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()

    def invalidate_pattern(self, pattern: str) -> int:
        """Invalida todas las entradas que contengan el patron."""
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "DELETE FROM cache WHERE key LIKE ?",
                (f"%{pattern}%",),
            )
            conn.commit()
            return result.rowcount

    def clear_expired(self) -> int:
        """Limpia entradas expiradas. Retorna cantidad de eliminadas."""
        now = time.monotonic()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "DELETE FROM cache WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
            return result.rowcount

    def clear_all(self) -> None:
        """Limpia todo el cache."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cache")
            conn.commit()

    def size(self) -> int:
        """Cantidad de entradas en cache."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM cache").fetchone()
            return row["cnt"] if row else 0


# Instancia global del cache
_cache = PersistentCache()


# ─── Funciones de acceso directo (compatibilidad) ───────


def get_cached(key: str) -> Any | None:
    return _cache.get(key)


def set_cached(key: str, value: Any, ttl_seconds: int = 60) -> None:
    _cache.set(key, value, ttl_seconds)


def invalidate_key(key: str) -> None:
    _cache.delete(key)


def invalidate_pattern(pattern: str) -> None:
    _cache.invalidate_pattern(pattern)


# ─── Decorador para endpoints ──────────────────────────


def _extract_request(args: tuple, kwargs: dict) -> Any | None:
    request = kwargs.get("request")
    if request is None:
        for a in args:
            if hasattr(a, "url"):
                request = a
                break
    return request


def _build_cache_key(request: Any, **kwargs: Any) -> str:
    """Genera clave de cache: path:usuario_id"""

    claims = kwargs.get("claims", {})
    if isinstance(claims, dict):
        usuario_id = claims.get("sub", "anon")
    elif hasattr(request, "state") and hasattr(request.state, "usuario_id"):
        usuario_id = request.state.usuario_id
    else:
        usuario_id = "anon"
    return f"{request.url.path}:{usuario_id}"


def cached(ttl_seconds: int = 60):
    """Decorador que cachea la respuesta de un endpoint por TTL segundos.

    La clave de cache se genera como f'{request.url.path}:{usuario_id}'.
    El cache es persistente (SQLite), no se pierde al reiniciar.
    """
    def decorator(func: Callable) -> Callable:
        import asyncio

        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                request = _extract_request(args, kwargs)
                if request:
                    cache_key = _build_cache_key(request, **{k: v for k, v in kwargs.items() if k != "request"})
                    cached_val = get_cached(cache_key)
                    if cached_val is not None:
                        return cached_val
                    result = await func(*args, **kwargs)
                    set_cached(cache_key, result, ttl_seconds)
                    return result
                return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                request = _extract_request(args, kwargs)
                if request:
                    cache_key = _build_cache_key(request, **{k: v for k, v in kwargs.items() if k != "request"})
                    cached_val = get_cached(cache_key)
                    if cached_val is not None:
                        return cached_val
                    result = func(*args, **kwargs)
                    set_cached(cache_key, result, ttl_seconds)
                    return result
                return func(*args, **kwargs)
            return sync_wrapper
    return decorator
