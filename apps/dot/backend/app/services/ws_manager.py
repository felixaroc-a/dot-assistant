"""Gestor de conexiones WebSocket para notificaciones push."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import WebSocket

from app.services.redis_client import get_redis

log = logging.getLogger("dot.ws")

# { usuario_id: [WebSocket, ...] }
_connections: dict[str, list[WebSocket]] = {}

_WS_USER_CHANNEL_PREFIX = "dot:ws:user:"
_WS_BROADCAST_CHANNEL = "dot:ws:broadcast"

_loop: asyncio.AbstractEventLoop | None = None
_stop_event: threading.Event | None = None
_listener_thread: threading.Thread | None = None


async def connect(usuario_id: str, ws: WebSocket) -> AsyncGenerator[None, None]:
    await ws.accept()
    _connections.setdefault(usuario_id, []).append(ws)
    log.info(
        "WS conectado: usuario=%s, total_conexiones=%s",
        usuario_id,
        len(_connections[usuario_id]),
    )
    try:
        yield
    finally:
        _connections[usuario_id].remove(ws)
        if not _connections[usuario_id]:
            del _connections[usuario_id]
        log.info("WS desconectado: usuario=%s", usuario_id)


async def _send_local_user(usuario_id: str, payload: str) -> None:
    for ws in _connections.get(usuario_id, []):
        try:
            await ws.send_text(payload)
        except Exception:
            log.debug(
                "Error enviando notificación WS a usuario=%s",
                usuario_id[:8],
                exc_info=True,
            )


async def _send_local_all(payload: str) -> None:
    for uid, sockets in list(_connections.items()):
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                log.debug("Error en broadcast WS a uid=%s", uid[:8], exc_info=True)


def _schedule_local_user(usuario_id: str, payload: str) -> None:
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_send_local_user(usuario_id, payload), _loop)


def _schedule_local_all(payload: str) -> None:
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_send_local_all(payload), _loop)


def _redis_listen_loop(stop_event: threading.Event) -> None:
    redis = get_redis()
    if redis is None:
        return

    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.psubscribe(f"{_WS_USER_CHANNEL_PREFIX}*")
        pubsub.subscribe(_WS_BROADCAST_CHANNEL)
        log.info("WS fanout Redis: escuchando pub/sub")

        while not stop_event.is_set():
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue

            msg_type = message.get("type")
            if msg_type == "pmessage":
                channel = str(message.get("channel", ""))
                if not channel.startswith(_WS_USER_CHANNEL_PREFIX):
                    continue
                usuario_id = channel[len(_WS_USER_CHANNEL_PREFIX) :]
                payload = message.get("data")
                if usuario_id and isinstance(payload, str):
                    _schedule_local_user(usuario_id, payload)
            elif msg_type == "message":
                channel = str(message.get("channel", ""))
                if channel != _WS_BROADCAST_CHANNEL:
                    continue
                payload = message.get("data")
                if isinstance(payload, str):
                    _schedule_local_all(payload)
    except Exception:
        log.warning("WS fanout Redis: listener detenido por error", exc_info=True)
    finally:
        try:
            pubsub.close()
        except Exception:
            log.debug("Error cerrando pubsub WS", exc_info=True)


def start_redis_fanout(loop: asyncio.AbstractEventLoop) -> None:
    """Inicia suscriptor Redis en background (no-op si Redis no está disponible)."""
    global _loop, _stop_event, _listener_thread

    if _listener_thread is not None and _listener_thread.is_alive():
        return

    redis = get_redis()
    if redis is None:
        log.debug("WS fanout Redis: deshabilitado (sin Redis)")
        return

    _loop = loop
    _stop_event = threading.Event()
    _listener_thread = threading.Thread(
        target=_redis_listen_loop,
        args=(_stop_event,),
        daemon=True,
        name="ws-redis-fanout",
    )
    _listener_thread.start()


def stop_redis_fanout() -> None:
    """Detiene el suscriptor Redis de fanout WS."""
    global _loop, _stop_event, _listener_thread

    if _stop_event is not None:
        _stop_event.set()
    if _listener_thread is not None:
        _listener_thread.join(timeout=3.0)
    _loop = None
    _stop_event = None
    _listener_thread = None


async def notify_user(usuario_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Envia notificacion a todas las conexiones de un usuario."""
    payload = json.dumps({"type": event_type, "data": data})
    redis = get_redis()
    if redis is not None:
        channel = f"{_WS_USER_CHANNEL_PREFIX}{usuario_id}"
        try:
            await asyncio.to_thread(redis.publish, channel, payload)
            return
        except Exception:
            log.warning(
                "WS fanout Redis: publish falló para usuario=%s; fallback local",
                usuario_id[:8],
                exc_info=True,
            )
    await _send_local_user(usuario_id, payload)


async def notify_all(event_type: str, data: dict[str, Any]) -> None:
    """Envia notificacion a TODOS los usuarios conectados."""
    payload = json.dumps({"type": event_type, "data": data})
    redis = get_redis()
    if redis is not None:
        try:
            await asyncio.to_thread(redis.publish, _WS_BROADCAST_CHANNEL, payload)
            return
        except Exception:
            log.warning("WS fanout Redis: broadcast publish falló; fallback local", exc_info=True)
    await _send_local_all(payload)


async def notify_whatsapp_inbound(uid: str, message_data: dict[str, Any]) -> None:
    """B3: Notifica a todas las conexiones WS de un usuario que llego un mensaje WhatsApp.

    Payload esperado: { from_phone, text, timestamp, message_id }
    """
    await notify_user(uid, "whatsapp:inbound", message_data)


def count_connections() -> int:
    return sum(len(v) for v in _connections.values())
