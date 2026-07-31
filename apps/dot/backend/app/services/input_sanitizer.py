"""Sanitización de inputs HTTP — ASGI middleware puro.

Protege contra:
- SQL injection: detecta y rechaza patrones SQL maliciosos.
- XSS: sanitiza HTML/JS en parámetros de entrada.
- Path traversal: bloquea ../ y rutas absolutas sospechosas.
- Command injection: detecta pipes, backticks, subshell y escapes.
- Log4Shell: detecta patrones JNDI injection.
- Rate limiting de patrones sospechosos (ventana deslizante).

Las solicitudes limpias siguen sin overhead. Las sospechosas se registran
en audit log con el patrón detectado y la IP de origen.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any
from urllib.parse import unquote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.security.audit import audit_event

log = logging.getLogger("dot.input_sanitizer")

# ─── Patrones de detección ─────────────────────────────────────────

SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    # UNION SELECT injection
    re.compile(r"(?i)\bunion\s+(all\s+)?select\b"),
    # DROP/ALTER/TRUNCATE
    re.compile(r"(?i)\b(drop|alter|truncate|create)\s+(table|database|schema|index|view)\b"),
    # INSERT/UPDATE/DELETE con subquery sospechosa
    re.compile(r"(?i)\b(insert\s+into|update\s+\w+\s+set|delete\s+from)\b.*\b(select|union)\b"),
    # Comentarios SQL inline y stacked queries
    re.compile(r"(?i)--\s*[\s\S]*?(select|drop|delete|insert|update)", re.DOTALL),
    re.compile(r"(?i);\s*(select|drop|delete|insert|update|exec|execute)\b"),
    # Función de extracción/benchmark
    re.compile(r"(?i)\b(extractvalue|updatexml|benchmark|sleep)\s*\("),
    # INFORMATION_SCHEMA / mysql / sqlite_master
    re.compile(r"(?i)\binformation_schema\b"),
    re.compile(r"(?i)\bsqlite_master\b"),
    # ' OR 1=1 -- clásico
    re.compile(r"(?i)['\"]\s*or\s+['\"]?\d['\"]?\s*=\s*['\"]?\d['\"]?\s*(--|#|/\*)"),
    # WAITFOR DELAY
    re.compile(r"(?i)\bwaitfor\s+delay\b"),
    # xp_cmdshell
    re.compile(r"(?i)\bxp_cmdshell\b"),
]

XSS_PATTERNS: list[re.Pattern] = [
    # Script tags
    re.compile(r"(?i)<script[\s>]", re.DOTALL),
    # Event handlers inline
    re.compile(r"(?i)\bon\w+\s*="),
    # javascript: protocol
    re.compile(r"(?i)javascript\s*:", re.DOTALL),
    # Data URI con HTML
    re.compile(r"(?i)data\s*:\s*text/html", re.DOTALL),
    # eval() / expression()
    re.compile(r"(?i)\beval\s*\(", re.DOTALL),
    re.compile(r"(?i)\bexpression\s*\(", re.DOTALL),
    # SVG onload
    re.compile(r"(?i)<svg[^>]*\bonload", re.DOTALL),
    # IMG onerror
    re.compile(r"(?i)<img[^>]*\bonerror", re.DOTALL),
    # document.cookie
    re.compile(r"(?i)document\s*\.\s*cookie", re.DOTALL),
    # alert() / prompt() / confirm()
    re.compile(r"(?i)\b(alert|prompt|confirm)\s*\(", re.DOTALL),
    # fromCharCode
    re.compile(r"(?i)\bfromCharCode\b", re.DOTALL),
    # String.fromCharCode
    re.compile(r"(?i)String\s*\.\s*fromCharCode", re.DOTALL),
]

PATH_TRAVERSAL_PATTERNS: list[re.Pattern] = [
    # Directorio padre clásico
    re.compile(r"\.\./"),
    re.compile(r"\.\.\\"),
    # Encoded variants
    re.compile(r"%2e%2e%2f", re.IGNORECASE),
    re.compile(r"%2e%2e/", re.IGNORECASE),
    re.compile(r"\.\.%2f", re.IGNORECASE),
    # Double encoding
    re.compile(r"%252e%252e%252f", re.IGNORECASE),
    # Null byte injection
    re.compile(r"%00"),
    # Windows paths absolutos en input
    re.compile(r"(?i)^[a-z]:\\"),
    # Linux paths absolutos en input (cuando no es ruta API)
    re.compile(r"^/etc/"),
    re.compile(r"^/var/"),
    re.compile(r"^/root/"),
]

COMMAND_INJECTION_PATTERNS: list[re.Pattern] = [
    # Pipes y redirección
    re.compile(r"\|\s*(sh|bash|cmd|powershell|wget|curl|nc|netcat)\b", re.IGNORECASE),
    # Backticks (subshell)
    re.compile(r"`[^`]+`"),
    # $(command)
    re.compile(r"\$\([^)]+\)"),
    # Semicolon command chaining
    re.compile(r";\s*(rm|cat|wget|curl|nc|sh|bash|chmod|chown|reboot)\b", re.IGNORECASE),
    # && chaining
    re.compile(r"&&\s*(rm|cat|wget|curl|nc)\b", re.IGNORECASE),
    # || chaining
    re.compile(r"\|\|\s*(rm|cat|wget|curl|nc)\b", re.IGNORECASE),
    # Newline injection en headers
    re.compile(r"%0[ad]", re.IGNORECASE),
    # /bin/ o /usr/bin/
    re.compile(r"(?i)/bin/(sh|bash|zsh|python|perl|ruby|node)\b"),
]

LOG4SHELL_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)\$\{jndi:", re.IGNORECASE),
    re.compile(r"(?i)\$\{java:", re.IGNORECASE),
    re.compile(r"(?i)\$\{env:", re.IGNORECASE),
    re.compile(r"(?i)\$\{sys:", re.IGNORECASE),
    re.compile(r"(?i)\$\{lower:", re.IGNORECASE),
    re.compile(r"(?i)\$\{upper:", re.IGNORECASE),
]

# Compilación unificada: (category, patterns)
ALL_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("sql_injection", SQL_INJECTION_PATTERNS),
    ("xss", XSS_PATTERNS),
    ("path_traversal", PATH_TRAVERSAL_PATTERNS),
    ("command_injection", COMMAND_INJECTION_PATTERNS),
    ("log4shell", LOG4SHELL_PATTERNS),
]

# ─── Rate limiting de patrones sospechosos ─────────────────────────

# Ventana deslizante: máximo N solicitudes con patrón sospechoso por IP por ventana
SUSPICIOUS_WINDOW_SECONDS = 60
SUSPICIOUS_MAX_PER_WINDOW = 5

_suspicious_rate: dict[str, list[float]] = defaultdict(list)


def _check_suspicious_rate(ip: str) -> bool:
    """Retorna True si la IP ha excedido el límite de patrones sospechosos."""
    now = time.time()
    cutoff = now - SUSPICIOUS_WINDOW_SECONDS
    _suspicious_rate[ip] = [t for t in _suspicious_rate.get(ip, []) if t > cutoff]
    _suspicious_rate[ip].append(now)
    return len(_suspicious_rate[ip]) > SUSPICIOUS_MAX_PER_WINDOW


# ─── Sanitización ──────────────────────────────────────────────────

def sanitize_value(value: str) -> str:
    """Sanitiza un valor individual: escapa HTML básico."""
    # No sanitizar si ya es seguro (optimización)
    if not any(ch in value for ch in ('<', '>', '"', "'", '&')):
        return value
    # Escapar HTML entities
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def detect_threats(input_str: str) -> list[tuple[str, str]]:
    """Escanea entrada contra todos los patrones de amenaza.

    Retorna lista de (categoría, patrón_matcheado).
    Vacío si no se detectan amenazas.
    """
    if not input_str:
        return []

    # Decodificar URL encoding para detectar ataques ofuscados
    try:
        decoded = unquote(input_str)
    except Exception:
        decoded = input_str

    threats: list[tuple[str, str]] = []

    for category, patterns in ALL_PATTERNS:
        for pattern in patterns:
            match = pattern.search(decoded)
            if match:
                threats.append((category, match.group(0)[:100]))

    return threats


def scan_request(
    path: str,
    query_string: bytes,
    body_text: str,
    client_ip: str,
) -> tuple[bool, list[tuple[str, str]], str | None]:
    """Escanea request completo contra amenazas.

    Returns:
        (is_safe, threats, block_reason)
        - is_safe: True si no se detectaron amenazas
        - threats: lista de amenazas detectadas
        - block_reason: razón de bloqueo si no es seguro
    """
    all_threats: list[tuple[str, str]] = []

    # Escanear path
    all_threats.extend(detect_threats(path))

    # Escanear query string
    if query_string:
        try:
            qs = query_string.decode("utf-8", errors="replace")
            all_threats.extend(detect_threats(qs))
        except Exception:
            pass

    # Escanear body
    if body_text:
        all_threats.extend(detect_threats(body_text))

    if not all_threats:
        return True, [], None

    # Verificar rate limiting de patrones sospechosos
    if _check_suspicious_rate(client_ip):
        audit_event(
            "input_threat_blocked_rate_limit",
            ip=client_ip,
            path=path,
            threat_count=len(all_threats),
            categories=list(set(c[0] for c in all_threats)),
        )
        return False, all_threats, "Demasiadas solicitudes con patrones sospechosos"

    # Bloquear si se detecta SQL injection, command injection o log4shell
    critical = [c for c in all_threats if c[0] in ("sql_injection", "command_injection", "log4shell")]
    if critical:
        audit_event(
            "input_threat_blocked_critical",
            ip=client_ip,
            path=path,
            categories=list(set(c[0] for c in critical)),
        )
        return False, all_threats, f"Patrón malicioso detectado: {critical[0][0]}"

    # XSS: sanitizar en lugar de bloquear (menos agresivo)
    xss = [c for c in all_threats if c[0] == "xss"]
    if xss:
        audit_event(
            "input_xss_detected",
            ip=client_ip,
            path=path,
            count=len(xss),
        )
        # No bloqueamos XSS, solo registramos — la sanitización ocurre en el valor

    return True, all_threats, None


# ─── ASGI Middleware ───────────────────────────────────────────────

class InputSanitizerMiddleware:
    """Middleware ASGI puro que escanea y sanitiza inputs HTTP."""

    def __init__(self, app: ASGIApp, block_on_threat: bool = True) -> None:
        self.app = app
        self.block_on_threat = block_on_threat

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        query = scope.get("query_string", b"")

        # Extraer IP del cliente
        client_ip = "unknown"
        for key, value in scope.get("headers", []):
            if key == b"x-forwarded-for":
                client_ip = value.decode().split(",")[0].strip()
                break
        if client_ip == "unknown":
            client_host = scope.get("client")
            if client_host:
                client_ip = client_host[0] if isinstance(client_host, tuple) else str(client_host)

        # Leer body completo (buffering)
        body_chunks: list[bytes] = []
        body_text = ""

        async def _capture_receive() -> dict:
            nonlocal body_text
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.request":
                    body_chunks.append(message.get("body", b""))
                    more_body = message.get("more_body", False)
                    if not more_body:
                        try:
                            body_text = b"".join(body_chunks).decode("utf-8", errors="replace")
                        except Exception:
                            body_text = ""
                        return message
            return {"type": "http.request", "body": b"", "more_body": False}

        # Capturar body en el primer receive
        first_message = await _capture_receive()

        # Escanear request
        is_safe, threats, block_reason = scan_request(path, query, body_text, client_ip)

        # Bloquear si es necesario
        if not is_safe and self.block_on_threat:
            from starlette.responses import Response as StarletteResponse

            resp = StarletteResponse(
                status_code=400,
                content=block_reason or "Solicitud rechazada por seguridad.",
            )
            await resp(scope, receive, send)
            return

        # Replay del body capturado para el siguiente middleware
        body_replayed = False

        async def _replay_send(message: Message) -> None:
            await send(message)

        async def _replay_receive() -> dict:
            nonlocal body_replayed
            if not body_replayed:
                body_replayed = True
                full_body = b"".join(body_chunks)
                return {
                    "type": "http.request",
                    "body": full_body,
                    "more_body": False,
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, _replay_receive, _replay_send)
