"""FREE-I03: cliente Redis opcional con fail-soft.

Si REDIS_URL está vacío o Redis no responde, get_redis() devuelve None
y el backend sigue funcionando (WS en memoria, sin cache distribuido).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.settings import settings

if TYPE_CHECKING:
    from redis import Redis

log = logging.getLogger("dot.redis")

_redis_client: Redis | None = None
_redis_attempted: bool = False


def get_redis() -> Redis | None:
    """Cliente Redis síncrono o None si no está configurado o no conecta."""
    global _redis_client, _redis_attempted

    if _redis_attempted:
        return _redis_client

    _redis_attempted = True
    url = (settings.redis_url or "").strip()
    if not url:
        log.debug("REDIS_URL vacío; Redis deshabilitado")
        _redis_client = None
        return None

    try:
        import redis

        client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        _redis_client = client
        log.info("Redis conectado: %s", url)
        return client
    except Exception as exc:
        log.warning("Redis no disponible (%s); continuando sin Redis", exc)
        _redis_client = None
        return None


def redis_health_check() -> dict:
    """Health check para Redis: devuelve estado, versión y métricas básicas.

    Útil para el endpoint /health y monitoreo (Grafana/Prometheus).
    Siempre retorna un dict (nunca lanza excepción), incluso si Redis no
    está configurado o no responde.
    """
    client = get_redis()
    if client is None:
        return {"status": "disabled", "reason": "REDIS_URL no configurado o Redis no disponible"}

    try:
        info = client.info("server")
        memory = client.info("memory")
        dbsize = client.dbsize()
        return {
            "status": "connected",
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_days": info.get("uptime_in_days", 0),
            "used_memory_human": memory.get("used_memory_human", "unknown"),
            "connected_clients": info.get("connected_clients", 0),
            "total_keys": dbsize,
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
