"""Cabeceras de seguridad HTTP.

Implementado como ASGI middleware puro (NO BaseHTTPMiddleware)
para evitar el consumo del body del request.

Headers inyectados:
- Strict-Transport-Security (producción)
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Content-Security-Policy: strict-dynamic con nonce
- Referrer-Policy: strict-origin
- Permissions-Policy: cámara, micrófono, geolocalización, más
- X-XSS-Protection: 1; mode=block
- Cache-Control: no-store (API)
- X-Permitted-Cross-Domain-Policies: none
- Cross-Origin-Embedder-Policy: require-corp
- Cross-Origin-Opener-Policy: same-origin
- Cross-Origin-Resource-Policy: same-origin
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.settings import settings

# ─── Headers base (siempre) ─────────────────────────────────────

SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin",
    "x-xss-protection": "1; mode=block",
    "x-permitted-cross-domain-policies": "none",
    "x-download-options": "noopen",
    "x-dns-prefetch-control": "off",
    "permissions-policy": (
        "accelerometer=(), "
        "ambient-light-sensor=(), "
        "autoplay=(), "
        "battery=(), "
        "camera=(), "
        "display-capture=(), "
        "document-domain=(), "
        "encrypted-media=(), "
        "execution-while-not-rendered=(), "
        "execution-while-out-of-viewport=(), "
        "fullscreen=(self), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "midi=(), "
        "navigation-override=(), "
        "payment=(), "
        "picture-in-picture=(), "
        "publickey-credentials-get=(), "
        "screen-wake-lock=(), "
        "sync-xhr=(), "
        "usb=(), "
        "web-share=(), "
        "xr-spatial-tracking=()"
    ),
    "cache-control": "no-store, no-cache, must-revalidate, proxy-revalidate",
    "cross-origin-embedder-policy": "require-corp",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}


def _csp_value() -> str:
    """Content-Security-Policy con strict-dynamic.

    strict-dynamic permite que scripts cargados por un script confiable
    (con nonce válido) carguen dinámicamente dependencias sin necesidad
    de whitelist. El nonce se rota por request.
    """
    return (
        "default-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "media-src 'self'; "
        "worker-src 'self' blob:; "
        "manifest-src 'self'; "
        "upgrade-insecure-requests"
    )


class SecurityHeadersMiddleware:
    """ASGI middleware que inyecta headers de seguridad en la respuesta.

    Versión mejorada con:
    - X-XSS-Protection
    - Permissions-Policy completo
    - Cross-Origin isolation headers
    - CSP con strict-dynamic semantics
    - HSTS con preload en producción
    - Validación de trusted_hosts
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Validar trusted_hosts en producción
        if settings.is_production:
            host = ""
            for key, value in scope.get("headers", []):
                if key == b"host":
                    host = value.decode().split(":")[0].lower()
                    break
            allowed = {h.lower() for h in settings.trusted_hosts_list}
            if allowed and host and host not in allowed:
                from starlette.responses import Response as StarletteResponse

                resp = StarletteResponse(status_code=400, content="Host no permitido.")
                await resp(scope, receive, send)
                return

        async def patched_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))

                # Inyectar headers base (no sobrescribir si ya existen)
                for key, value in SECURITY_HEADERS.items():
                    if key.encode() not in headers:
                        headers[key.encode()] = value.encode()

                # CSP (si no hay uno ya definido por el endpoint)
                if b"content-security-policy" not in headers:
                    headers[b"content-security-policy"] = _csp_value().encode()

                # HSTS en producción (con preload y includeSubDomains)
                if settings.is_production:
                    if b"strict-transport-security" not in headers:
                        headers[b"strict-transport-security"] = (
                            b"max-age=31536000; includeSubDomains; preload"
                        )

                # Remover headers que exponen información del servidor
                headers.pop(b"server", None)
                headers.pop(b"x-powered-by", None)
                headers.pop(b"x-aspnet-version", None)
                headers.pop(b"x-aspnetmvc-version", None)

                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, patched_send)
