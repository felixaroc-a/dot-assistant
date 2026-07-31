"""Tools de web e internet — F6d."""
from __future__ import annotations

import logging
import math
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.web")

# FREE-A02b: límites defensivos (httpx sync, sin Playwright cloud).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 DOT/1.0"
)
_DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
}
_FETCH_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=8.0, pool=8.0)
_MAX_RESPONSE_BYTES = 512_000
_MAX_OUTPUT_CHARS = 8000
_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _validate_http_url(url: str) -> str | None:
    """Devuelve mensaje de error o None si la URL es válida para fetch."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return "Solo se permiten URLs http(s)."
    if not parsed.netloc:
        return "URL invalida (sin host)."
    return None


def _read_limited_text(resp: httpx.Response, max_bytes: int) -> tuple[str, bool]:
    """Lee el cuerpo con tope de bytes; evita cargar páginas enormes en RAM."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in resp.iter_bytes():
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    encoding = resp.encoding or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return text, truncated


def _fetch_url_safe(
    url: str,
    *,
    max_output_chars: int = _MAX_OUTPUT_CHARS,
) -> tuple[bool, str, str | None]:
    """GET http(s) con timeouts, UA y límites de tamaño.

    Returns:
        (ok, output, error) — non-2xx devuelve ok=False con detalle HTTP, sin excepción.
    """
    url_err = _validate_http_url(url)
    if url_err:
        return False, "", url_err

    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            headers=_DEFAULT_HEADERS,
        ) as client:
            resp = client.get(url)
    except httpx.TimeoutException:
        return False, "", "Timeout al obtener la URL (15s lectura max)."
    except httpx.TooManyRedirects:
        return False, "", f"Demasiados redirects (max {_MAX_REDIRECTS})."
    except httpx.ConnectError as e:
        return False, "", f"No se pudo conectar: {e}"
    except httpx.RequestError as e:
        log.warning("web_fetch request error url=%s err=%s", url[:120], e)
        return False, "", f"Error de red: {e}"

    status = resp.status_code
    body, truncated = _read_limited_text(resp, _MAX_RESPONSE_BYTES)
    snippet = body[:max_output_chars]

    if status >= 400:
        preview = snippet.strip()[:500]
        detail = f"HTTP {status}"
        if preview:
            detail += f" — fragmento: {preview}"
        return False, "", detail

    output = snippet
    notes: list[str] = []
    if truncated or len(body) > max_output_chars:
        notes.append("[Nota] Contenido truncado por límite de tamaño.")
    low = output.lower()
    if "amazon." in url.lower() or "captcha" in low or len(output.strip()) < 400:
        notes.append(
            "[Nota] Esta página puede requerir JS. "
            "Si el contenido es incompleto, usa browser_navigate y browser_get_price/browser_extract."
        )
    if notes:
        output = output + "\n\n" + "\n".join(notes)
    return True, output, None


def web_fetch_page_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene HTML/texto de una URL via HTTP (sin JS). Para Amazon/SPAs usa browser_navigate + browser_get_price."""
    url = str(arguments.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="URL invalida.")
    if not url.startswith("http"):
        return ToolResult(ok=False, output="", error="URL invalida (debe empezar con http:// o https://).")

    ok, output, error = _fetch_url_safe(url)
    if ok:
        return ToolResult(ok=True, output=output)
    hint = " Si es una SPA/Amazon, usa browser_navigate + browser_get_price."
    return ToolResult(ok=False, output="", error=f"{error}{hint}")

def web_translate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Traduce texto entre idiomas usando DeepSeek."""
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or "").strip()
        to_lang = str(arguments.get("to") or arguments.get("target") or "es").strip()
        from_lang = str(arguments.get("from") or arguments.get("source") or "auto").strip()

        if not text:
            return ToolResult(ok=False, output="", error="Falta texto a traducir.")

        result = route_chat(
            f"Traduce al {to_lang} (desde {from_lang}):\n\n{text[:3000]}",
            provider_id="deepseek",
            system_prompt=f"Traduce al {to_lang}. Responde solo con la traduccion, sin explicacion.",
        )
        return ToolResult(ok=True, output=result.strip())
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_get_weather_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene clima actual por ciudad."""
    try:
        city = str(arguments.get("city") or arguments.get("location") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta ciudad.")

        from app.services.provider_router import route_chat

        result = route_chat(
            f"Clima actual y pronostico para {city}. Responde con temperatura, humedad, condiciones y pronostico 3 dias.",
            provider_id="deepseek",
            system_prompt="Eres un meteorologo. Responde en espanol con datos concretos y breves.",
        )
        return ToolResult(ok=True, output=result.strip())
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_get_news_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca noticias recientes por tema."""
    try:
        query = str(arguments.get("query") or arguments.get("topic") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta tema de busqueda.")

        from app.services.provider_router import route_chat

        result = route_chat(
            f"Busca las 5 noticias mas recientes sobre '{query}'. "
            f"Incluye titulo, fuente, fecha y resumen de 1 frase por noticia.",
            provider_id="deepseek",
            system_prompt="Eres un periodista. Responde en espanol, formato lista, datos reales o indica si no puedes buscar noticias actuales.",
        )
        return ToolResult(ok=True, output=result.strip())
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_currency_convert_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte entre monedas."""
    try:
        amount = float(arguments.get("amount") or 1)
        from_cur = str(arguments.get("from") or "USD").upper()
        to_cur = str(arguments.get("to") or "VES").upper()

        from app.services.provider_router import route_chat

        result = route_chat(
            f"Convierte {amount} {from_cur} a {to_cur} con la tasa de cambio actual aproximada. "
            f"Responde solo con el numero y la moneda.",
            provider_id="deepseek",
            system_prompt="Responde solo con el monto convertido. Se breve.",
        )
        return ToolResult(ok=True, output=result.strip())
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_extract_article_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae texto limpio de un articulo/noticia."""
    url = str(arguments.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="Falta URL.")

    ok, html, error = _fetch_url_safe(url, max_output_chars=_MAX_RESPONSE_BYTES)
    if not ok:
        return ToolResult(ok=False, output="", error=error or "No se pudo obtener la URL.")

    # Limpiar tags HTML basico
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:4000]
    if not cleaned:
        return ToolResult(ok=False, output="", error="No se extrajo texto util de la pagina.")
    return ToolResult(ok=True, output=cleaned)


def web_calculate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Realiza calculos matematicos."""
    try:
        expression = str(arguments.get("expression") or arguments.get("formula") or "").strip()
        if not expression:
            return ToolResult(ok=False, output="", error="Falta expresion matematica.")

        # Solo operaciones seguras
        allowed = set("0123456789+-*/().,^% ")
        if not all(c in allowed for c in expression.replace("sqrt", "").replace("pi", "").replace("abs", "")):
            return ToolResult(ok=False, output="", error="Expresion con caracteres no permitidos.")

        ns = {
            "sqrt": math.sqrt, "pi": math.pi, "abs": abs, "pow": pow,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log10": math.log10, "exp": math.exp,
            "ceil": math.ceil, "floor": math.floor, "round": round,
        }
        result = eval(expression.replace("^", "**"), {"__builtins__": {}}, ns)
        return ToolResult(ok=True, output=f"{expression} = {result}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_geocode_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte direccion a coordenadas GPS."""
    try:
        address = str(arguments.get("address") or arguments.get("location") or "").strip()
        if not address:
            return ToolResult(ok=False, output="", error="Falta direccion.")

        from app.services.provider_router import route_chat

        result = route_chat(
            f"Cuales son las coordenadas GPS aproximadas de: {address}? "
            f"Responde solo con latitud y longitud en formato: lat,lon",
            provider_id="deepseek",
            system_prompt="Responde solo con coordenadas. Se breve.",
        )
        return ToolResult(ok=True, output=result.strip())
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def web_validate_url_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Valida si una URL es accesible."""
    try:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, output="", error="Falta URL.")

        with httpx.Client(timeout=10) as client:
            resp = client.head(url, follow_redirects=True)
            return ToolResult(
                ok=True,
                output=f"URL accesible (status {resp.status_code}, {len(resp.text)} bytes).",
            )
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"URL no accesible: {e}")


def web_check_website_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Verifica si un sitio esta online."""
    try:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, output="", error="Falta URL.")

        with httpx.Client(timeout=10) as client:
            resp = client.get(url, follow_redirects=True)
            return ToolResult(ok=True, output=f"Online (HTTP {resp.status_code}).")
    except Exception:
        return ToolResult(ok=True, output="Sitio no responde o esta caido.")

TOOLS = [
    ("web_fetch_page", web_fetch_page_handler),
    # ⚠️ FAKE: web_translate alucina traducciones sin API de traducción real (route_chat)
    # ("web_translate", web_translate_handler),
    # ⚠️ web_get_weather → migrado a real_apis.py (OpenWeatherMap real)
    # ⚠️ web_get_news → migrado a real_apis.py (NewsAPI + Google News RSS real)
    # ⚠️ web_currency_convert → migrado a real_apis.py (ExchangeRate API real)
    # ⚠️ web_geocode → migrado a real_apis.py (Nominatim/OpenStreetMap real)
    ("web_extract_article", web_extract_article_handler),
    ("web_calculate", web_calculate_handler),
    ("web_validate_url", web_validate_url_handler),
    ("web_check_website", web_check_website_handler),
]
