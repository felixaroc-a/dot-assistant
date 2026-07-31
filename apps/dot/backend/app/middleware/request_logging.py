"""Middleware de logging con request_id para trazabilidad.

Implementado como ASGI middleware puro (NO BaseHTTPMiddleware)
para evitar el consumo del body del request.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("dot.api")


class RequestLoggingMiddleware:
    """ASGI middleware que inyecta request_id y logea cada request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:8]
        scope["state"] = {**scope.get("state", {}), "request_id": request_id}

        start = time.time()
        status_code = 500

        async def patched_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, patched_send)
        finally:
            elapsed_ms = int((time.time() - start) * 1000)
            path = scope.get("path", "?")
            method = scope.get("method", "?")
            log.info("req=%s %s %s %s %dms", request_id, method, path, status_code, elapsed_ms)
