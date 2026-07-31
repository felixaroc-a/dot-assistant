"""URL Shortener Plugin — acorta URLs usando TinyURL API gratuita.

Demuestra:
  - Herramienta con llamada HTTP externa
  - Validación de entrada
  - Fallback entre servicios
  - Formateo de respuesta simple
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.plugin_sdk import plugin_tool


def _is_valid_url(url: str) -> bool:
    """Valida que la URL tenga un formato básico aceptable."""
    parsed = urllib.parse.urlparse(url)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def _shorten_tinyurl(long_url: str) -> str | None:
    """Acorta una URL usando TinyURL (sin API key)."""
    try:
        api_url = f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(long_url, safe='')}"
        req = urllib.request.Request(api_url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            short = resp.read().decode().strip()
            if short and short.startswith("http"):
                return short
    except Exception:
        pass
    return None


def _shorten_isgd(long_url: str) -> str | None:
    """Fallback: is.gd (API gratuita)."""
    try:
        api_url = f"https://is.gd/create.php?format=json&url={urllib.parse.quote(long_url, safe='')}"
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            short = data.get("shorturl")
            if short:
                return short
    except Exception:
        pass
    return None


@plugin_tool(
    name="shorten_url",
    description=(
        "Acorta una URL larga usando TinyURL (gratis, sin API key). "
        "Ideal para compartir enlaces en WhatsApp o mensajes donde los URLs largos son incómodos. "
        "Retorna la URL acortada lista para copiar y pegar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "La URL larga que quieres acortar. Debe empezar con http:// o https://",
            },
        },
        "required": ["url"],
    },
)
def shorten_url(uid: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handler de la tool shorten_url."""
    long_url = arguments.get("url", "").strip()

    if not long_url:
        return {
            "ok": False,
            "output": "",
            "error": "Debes proporcionar una URL para acortar.",
            "artifacts": [],
        }

    # Asegurar que tenga esquema
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    if not _is_valid_url(long_url):
        return {
            "ok": False,
            "output": "",
            "error": f"URL inválida: '{long_url}'. Debe ser una URL completa con http:// o https://",
            "artifacts": [],
        }

    # Intentar TinyURL
    short = _shorten_tinyurl(long_url)

    # Fallback a is.gd
    if short is None:
        short = _shorten_isgd(long_url)

    if short is None:
        return {
            "ok": False,
            "output": "",
            "error": "No se pudo acortar la URL. Verifica tu conexión o intenta más tarde.",
            "artifacts": [],
        }

    # Medir reducción
    original_len = len(long_url)
    short_len = len(short)
    reduction = int((1 - short_len / original_len) * 100) if original_len > 0 else 0

    output = f"URL acortada: {short}\nLongitud original: {original_len} caracteres → {short_len} caracteres ({reduction}% más corta)"
    return {
        "ok": True,
        "output": output,
        "error": None,
        "artifacts": [],
    }
