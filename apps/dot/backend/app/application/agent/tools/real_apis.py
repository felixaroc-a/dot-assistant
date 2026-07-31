"""Tools con APIs reales — M1S3-B.

Reemplaza handlers fake (route_chat) con consultas reales a APIs gratuitas:
  - OpenWeatherMap (clima)
  - ExchangeRate API (divisas, sin key)
  - Alpha Vantage + fallback Yahoo (acciones)
  - Nominatim/OpenStreetMap (geocodificación, sin key)
  - Semantic Scholar (papers académicos, sin key)
  - Amadeus Self-Service (vuelos, test)
  - NewsAPI + fallback Google News RSS (noticias)
  - OpenRouteService + Nominatim (rutas)
  - Computrabajo scraper (empleos)
  - Bridge Electron (facturas)

Rate limit: 1 req/seg por tool. Cache simple: 5 min en memoria.
Si API key no configurada → mensaje claro, sin alucinar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import timezone
from datetime import datetime as dt
from pathlib import Path
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.real_apis")
_ERR_NEWS = "No pude obtener noticias ahora. Intenta en unos minutos."
_ERR_JOBS = "No pude consultar ofertas de empleo ahora. Intenta en unos minutos."

# ──────────────────────────────────────────────
#  Helpers: rate-limit + cache simple
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # 5 minutos


def _rate_limit(tool: str, min_interval: float = 1.0) -> float | None:
    """Espera si es necesario para respetar rate limit. Retorna None siempre."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()
    return None


def _cache_key(tool: str, *args: str) -> str:
    raw = f"{tool}:{'|'.join(args)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_get(tool: str, *args: str) -> Any | None:
    key = _cache_key(tool, *args)
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(tool: str, *args: str, value: Any) -> None:
    key = _cache_key(tool, *args)
    _cache[key] = (time.time(), value)


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


# ──────────────────────────────────────────────
#  1. web_get_weather → OpenWeatherMap
# ──────────────────────────────────────────────

def web_get_weather_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Clima actual por ciudad (OpenWeatherMap API real). Temperatura, humedad, descripción en español."""
    try:
        city = str(arguments.get("city") or arguments.get("location") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta ciudad.")

        api_key = _env("OPENWEATHER_API_KEY")
        if not api_key:
            return ToolResult(
                ok=False, output="",
                error="El servicio de clima no está disponible en este momento. Intenta más tarde.",
            )

        cached = _cache_get("weather", city.lower())
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        _rate_limit("weather")
        url = "https://api.openweathermap.org/data/2.5/weather"
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params={
                "q": city,
                "appid": api_key,
                "units": "metric",
                "lang": "es",
            })
            if resp.status_code == 401:
                return ToolResult(ok=False, output="", error="API key de OpenWeatherMap inválida.")
            if resp.status_code == 404:
                return ToolResult(ok=False, output="", error=f"Ciudad no encontrada: {city}")
            resp.raise_for_status()
            data = resp.json()

        temp = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        desc = data["weather"][0]["description"]
        wind = data.get("wind", {}).get("speed", "N/A")
        feels_like = data["main"]["feels_like"]
        country = data.get("sys", {}).get("country", "")

        output = (
            f"\u2600 {city.title()}, {country}\n"
            f"Temperatura: {temp:.1f}°C (sensacion {feels_like:.1f}°C)\n"
            f"Humedad: {humidity}%\n"
            f"Condicion: {desc}\n"
            f"Viento: {wind} m/s\n"
            f"Fuente: OpenWeatherMap"
        )
        _cache_set("weather", city.lower(), value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error al consultar OpenWeatherMap: {e}")
    except Exception as e:
        log.exception("web_get_weather uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. web_currency_convert → ExchangeRate API
# ──────────────────────────────────────────────

def web_currency_convert_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte entre monedas usando ExchangeRate API (gratis, sin API key)."""
    try:
        amount = float(arguments.get("amount") or 1)
        from_cur = str(arguments.get("from") or "USD").upper().strip()
        to_cur = str(arguments.get("to") or "VES").upper().strip()

        if from_cur == to_cur:
            return ToolResult(ok=True, output=f"{amount:.2f} {from_cur} = {amount:.2f} {to_cur}")

        cached = _cache_get("currency", from_cur, to_cur, str(amount))
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        _rate_limit("currency")
        url = f"https://api.exchangerate-api.com/v4/latest/{from_cur}"
        with httpx.Client(timeout=10) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        rates = data.get("rates", {})
        rate = rates.get(to_cur)
        if rate is None:
            return ToolResult(ok=False, output="", error=f"Moneda destino '{to_cur}' no encontrada en tasas disponibles.")

        converted = round(amount * rate, 4)
        ts = data.get("date", "?")

        output = f"{amount:.2f} {from_cur} = {converted:.4f} {to_cur} (tasa: 1 {from_cur} = {rate:.4f} {to_cur}, fecha: {ts})\nFuente: ExchangeRate API"
        _cache_set("currency", from_cur, to_cur, str(amount), value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error al consultar ExchangeRate API: {e}")
    except ValueError:
        return ToolResult(ok=False, output="", error="Monto invalido.")
    except Exception as e:
        log.exception("web_currency_convert uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  3. web_get_stock → Alpha Vantage + Yahoo fallback
# ──────────────────────────────────────────────

def web_get_stock_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Cotizacion de accion: Alpha Vantage (si hay key) o Yahoo Finance (fallback gratuito)."""
    try:
        symbol = str(arguments.get("symbol") or "").upper().strip()
        if not symbol:
            return ToolResult(ok=False, output="", error="Falta simbolo (ej: AAPL).")

        cached = _cache_get("stock", symbol)
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        api_key = _env("ALPHA_VANTAGE_API_KEY")
        output: str | None = None

        if api_key:
            _rate_limit("stock_av", 15.0)  # Alpha Vantage: 5 calls/min
            try:
                url_av = "https://www.alphavantage.co/query"
                with httpx.Client(timeout=10) as client:
                    resp = client.get(url_av, params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": symbol,
                        "apikey": api_key,
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        quote = data.get("Global Quote", {})
                        price = quote.get("05. price")
                        change = quote.get("09. change")
                        change_pct = quote.get("10. change percent")
                        if price:
                            output = (
                                f"📈 {symbol}: ${price}\n"
                                f"Cambio: {change} ({change_pct})\n"
                                f"Fuente: Alpha Vantage"
                            )
            except Exception as e:
                log.warning("Alpha Vantage fallo para %s: %s", symbol, e)

        # Fallback: Yahoo Finance via scraper
        if output is None:
            _rate_limit("stock_yahoo", 2.0)
            from worker.scraper import scrape_stock_price
            data = scrape_stock_price(symbol)
            if data.get("error"):
                return ToolResult(ok=False, output="", error=f"No se pudo obtener cotizacion de {symbol}: {data['error']}")

            price = data.get("price", "N/A")
            ch = data.get("change") or 0
            pct = data.get("change_percent") or 0
            sign = "+" if ch > 0 else ""
            output = (
                f"📈 {symbol}: ${price} {data.get('currency', 'USD')}\n"
                f"Cambio: {sign}{ch} ({sign}{pct}%)\n"
                f"Fuente: Yahoo Finance"
            )

        _cache_set("stock", symbol, value=output)
        return ToolResult(ok=True, output=output)

    except Exception as e:
        log.exception("web_get_stock uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  4. web_geocode → Nominatim / OpenStreetMap
# ──────────────────────────────────────────────

def web_geocode_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte direccion a coordenadas GPS usando Nominatim (OpenStreetMap, gratis)."""
    try:
        address = str(arguments.get("address") or arguments.get("location") or "").strip()
        if not address:
            return ToolResult(ok=False, output="", error="Falta direccion.")

        cached = _cache_get("geocode", address.lower())
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        _rate_limit("geocode", 1.2)  # Nominatim: max 1 req/seg
        url = "https://nominatim.openstreetmap.org/search"
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params={
                "q": address,
                "format": "json",
                "limit": 1,
            }, headers={
                "User-Agent": "DOT-Assistant/1.0 (Nordik-IA; contacto@nordik-ia.com)",
            })
            if resp.status_code == 403:
                return ToolResult(ok=False, output="", error="Nominatim bloqueo la solicitud (rate limit). Espera unos segundos.")
            resp.raise_for_status()
            results = resp.json()

        if not results:
            return ToolResult(ok=False, output="", error=f"No se encontraron coordenadas para: {address}")

        r = results[0]
        lat = r["lat"]
        lon = r["lon"]
        display = r.get("display_name", address)

        output = (
            f"📍 {display[:200]}\n"
            f"Latitud: {lat}\n"
            f"Longitud: {lon}\n"
            f"Fuente: OpenStreetMap/Nominatim"
        )
        _cache_set("geocode", address.lower(), value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error al consultar Nominatim: {e}")
    except Exception as e:
        log.exception("web_geocode uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  5. research_academic_papers → Semantic Scholar
# ──────────────────────────────────────────────

def research_academic_papers_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca papers academicos reales usando Semantic Scholar API (gratis, sin key)."""
    try:
        query = str(arguments.get("query") or arguments.get("topic") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta tema de busqueda.")

        limit = min(int(arguments.get("limit") or 5), 10)
        cached = _cache_get("academic", query.lower(), str(limit))
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        _rate_limit("academic")
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params={
                "query": query,
                "limit": limit,
                "fields": "title,authors,year,journal,citationCount,url",
            })
            resp.raise_for_status()
            data = resp.json()

        papers = data.get("data", [])
        if not papers:
            return ToolResult(ok=True, output=f"No se encontraron papers sobre '{query}' en Semantic Scholar.")

        lines = [f"📚 Papers academicos: '{query}' ({len(papers)} resultados)\n"]
        for i, p in enumerate(papers, 1):
            title = p.get("title", "Sin titulo")
            authors = ", ".join(a.get("name", "?") for a in p.get("authors", [])[:3])
            if len(p.get("authors", [])) > 3:
                authors += " et al."
            year = p.get("year", "?")
            journal = p.get("journal", {}).get("name", "") if p.get("journal") else ""
            citations = p.get("citationCount", 0)
            url_paper = p.get("url", "")
            lines.append(
                f"{i}. {title}\n"
                f"   Autores: {authors} | Ano: {year} | Citas: {citations}\n"
                f"   {'Journal: ' + journal + ' | ' if journal else ''}Link: {url_paper or 'N/A'}"
            )

        output = "\n".join(lines) + "\n\nFuente: Semantic Scholar API"
        _cache_set("academic", query.lower(), str(limit), value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error al consultar Semantic Scholar: {e}")
    except Exception as e:
        log.exception("research_academic_papers uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  6. monitor_flight_price → Amadeus test API
# ──────────────────────────────────────────────

def monitor_flight_price_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca vuelos reales usando Amadeus Self-Service API (test, gratis)."""
    try:
        origin = str(arguments.get("from") or arguments.get("origin") or "").strip().upper()
        destination = str(arguments.get("to") or arguments.get("destination") or "").strip().upper()
        date_str = str(arguments.get("date") or "").strip()

        if not origin or not destination:
            return ToolResult(ok=False, output="", error="Falta origen (from) y destino (to).")

        api_key = _env("AMADEUS_API_KEY")
        api_secret = _env("AMADEUS_API_SECRET")

        if not api_key or not api_secret:
            return ToolResult(
                ok=True,
                output=(
                    f"✈️ Vuelos {origin} → {destination}\n"
                    f"Amadeus API no configurada. Puedes buscar manualmente:\n"
                    f"👉 https://www.google.com/travel/flights?q=Vuelos+a+{destination}+desde+{origin}\n\n"
                    f"Para habilitar busqueda automatica: configura AMADEUS_API_KEY y AMADEUS_API_SECRET "
                    f"(gratis en developers.amadeus.com)."
                ),
            )

        cache_args = f"{origin}|{destination}|{date_str}"
        cached = _cache_get("flight", cache_args)
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        # Obtener token OAuth de Amadeus
        _rate_limit("flight_auth", 2.0)
        with httpx.Client(timeout=15) as client:
            token_resp = client.post(
                "https://test.api.amadeus.com/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": api_key,
                    "client_secret": api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al autenticar con Amadeus: {token_resp.status_code}. Verifica API key/secret."
                )
            token = token_resp.json().get("access_token", "")

        # Buscar vuelos
        _rate_limit("flight_search", 2.0)
        params: dict[str, str] = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": date_str or dt.now(timezone.utc).strftime("%Y-%m-%d"),
            "adults": "1",
            "max": "5",
        }

        with httpx.Client(timeout=20) as client:
            flight_resp = client.get(
                "https://test.api.amadeus.com/v2/shopping/flight-offers",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if flight_resp.status_code != 200:
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al buscar vuelos: {flight_resp.status_code}"
                )
            data = flight_resp.json()

        offers = data.get("data", [])
        if not offers:
            output = f"✈️ No se encontraron vuelos {origin} → {destination} para {params['departureDate']}."
        else:
            lines = [f"✈️ Vuelos {origin} → {destination} ({len(offers)} encontrados):\n"]
            for i, offer in enumerate(offers[:5], 1):
                price = offer.get("price", {}).get("grandTotal", "?")
                currency = offer.get("price", {}).get("currency", "USD")
                itineraries = offer.get("itineraries", [{}])
                segments = itineraries[0].get("segments", [{}]) if itineraries else [{}]
                airline = segments[0].get("carrierCode", "??") if segments else "??"
                dep = segments[0].get("departure", {}).get("at", "?") if segments else "?"
                arr = segments[-1].get("arrival", {}).get("at", "?") if segments else "?"
                stops = len(segments) - 1 if segments else 0
                lines.append(
                    f"{i}. {airline} — {price} {currency}\n"
                    f"   Sale: {dep[:16]} | Llega: {arr[:16]} | Escalas: {stops}"
                )
            output = "\n".join(lines) + "\n\nFuente: Amadeus Self-Service API"

        _cache_set("flight", cache_args, value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=True, output=f"Error de red al consultar Amadeus: {e}. Puedes buscar en Google Flights manualmente.")
    except Exception as e:
        log.exception("monitor_flight_price uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  7. monitor_job_opening → Scraper Computrabajo
# ──────────────────────────────────────────────

def monitor_job_opening_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca ofertas de empleo reales en Computrabajo Venezuela via scraper."""
    try:
        query = str(arguments.get("query") or arguments.get("cargo") or "").strip()
        city = str(arguments.get("city") or "").strip()
        limit = min(int(arguments.get("limit") or 10), 20)

        if not query:
            return ToolResult(ok=False, output="", error="Falta cargo o query.")

        cached = _cache_get("jobs", query.lower(), city.lower(), str(limit))
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        _rate_limit("jobs", 2.0)
        from worker.scraper import scrape_jobs
        jobs = scrape_jobs(query, city, limit)

        if jobs is None:
            return ToolResult(ok=False, output="", error=_ERR_JOBS)
        if not jobs:
            output = f"No se encontraron ofertas para '{query}' en Computrabajo."
        else:
            lines = [f"💼 Ofertas Computrabajo — {query}" + (f" en {city}" if city else "") + f" ({len(jobs)}):\n"]
            for j in jobs:
                lines.append(
                    f"• {j['title']}\n"
                    f"  Empresa: {j['company']} | Ubicacion: {j['location']} | Salario: {j.get('salary', 'No especificado')}\n"
                    f"  {j.get('link', '')}"
                )
            output = "\n".join(lines) + "\n\nFuente: Computrabajo Venezuela"

        _cache_set("jobs", query.lower(), city.lower(), str(limit), value=output)
        return ToolResult(ok=True, output=output)

    except Exception as e:
        log.exception("monitor_job_opening uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=_ERR_JOBS)


# ──────────────────────────────────────────────
#  8. monitor_news_keyword → NewsAPI + Google RSS
# ──────────────────────────────────────────────

def monitor_news_keyword_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca noticias reales: NewsAPI (si hay key) o Google News RSS (fallback gratuito)."""
    try:
        keyword = str(arguments.get("keyword") or "").strip()
        limit = min(int(arguments.get("limit") or 5), 15)

        if not keyword:
            return ToolResult(ok=False, output="", error="Falta keyword.")

        cached = _cache_get("news", keyword.lower(), str(limit))
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        api_key = _env("NEWSAPI_KEY")
        output: str | None = None

        if api_key:
            _rate_limit("news_api", 2.0)
            try:
                url_n = "https://newsapi.org/v2/everything"
                with httpx.Client(timeout=10) as client:
                    resp = client.get(url_n, params={
                        "q": keyword,
                        "apiKey": api_key,
                        "language": "es",
                        "pageSize": limit,
                        "sortBy": "publishedAt",
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        articles = data.get("articles", [])
                        lines = [f"📰 Noticias: '{keyword}' ({len(articles)} resultados)\n"]
                        for i, a in enumerate(articles, 1):
                            title = a.get("title", "Sin titulo")
                            source = a.get("source", {}).get("name", "?")
                            date = (a.get("publishedAt") or "")[:10]
                            url_a = a.get("url", "")
                            desc = (a.get("description") or "")[:120]
                            lines.append(
                                f"{i}. {title}\n"
                                f"   Fuente: {source} | Fecha: {date}\n"
                                f"   {desc}\n"
                                f"   {url_a}"
                            )
                        output = "\n".join(lines) + "\n\nFuente: NewsAPI"
                    elif resp.status_code == 401:
                        log.warning("NewsAPI key invalida, usando fallback RSS")
            except Exception as e:
                log.warning("NewsAPI fallo para '%s': %s", keyword, e)

        # Fallback: Google News RSS via scraper
        if output is None:
            _rate_limit("news_rss", 2.0)
            from worker.scraper import scrape_news
            articles = scrape_news(keyword, limit)
            if articles is None:
                return ToolResult(ok=False, output="", error=_ERR_NEWS)
            if not articles:
                return ToolResult(ok=True, output=f"No se encontraron noticias sobre '{keyword}'.")

            lines = [f"📰 Noticias: '{keyword}' ({len(articles)} resultados)\n"]
            for i, a in enumerate(articles, 1):
                lines.append(
                    f"{i}. {a['title']}\n"
                    f"   Fuente: {a['source']} | Fecha: {a['date']}\n"
                    f"   {a.get('link', '')}"
                )
            output = "\n".join(lines) + "\n\nFuente: Google News RSS"

        _cache_set("news", keyword.lower(), str(limit), value=output)
        return ToolResult(ok=True, output=output)

    except Exception as e:
        log.exception("monitor_news_keyword uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=_ERR_NEWS)


def web_get_news_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Noticias recientes por tema (NewsAPI si hay key, sino Google News RSS)."""
    keyword = str(
        arguments.get("query") or arguments.get("topic") or arguments.get("keyword") or ""
    ).strip()
    if not keyword:
        return ToolResult(ok=False, output="", error="Falta tema de busqueda (query/topic).")
    limit = arguments.get("limit", 5)
    return monitor_news_keyword_handler(uid, {"keyword": keyword, "limit": limit})


# ──────────────────────────────────────────────
#  9. finance_parse_invoice → bridge Electron
# ──────────────────────────────────────────────

def finance_parse_invoice_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae datos de factura (PDF/imagen) via bridge Electron + regex directo + fallback IA."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="finance_parse_invoice requiere path del archivo.")

        ext = Path(path).suffix.lower()
        supported = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif"}
        if ext not in supported:
            return ToolResult(
                ok=False, output="",
                error=f"Formato no soportado: {ext}. Usa PDF, PNG, JPG, WEBP o TIFF.",
            )

        # 1) Leer documento via bridge Electron (parseDocument maneja PDF e imagenes)
        raw = execute_local_tool_via_bridge("parseDocument", path=path)
        content_text = ""

        if raw.get("ok"):
            content_text = str(raw.get("text", raw.get("content", "")))
        else:
            raw2 = execute_local_tool_via_bridge("readFile", path=path)
            if raw2.get("ok"):
                content_text = str(raw2.get("content", ""))

        if not content_text.strip():
            return ToolResult(
                ok=False, output="",
                error="No se pudo extraer texto de la factura. Verifica que el archivo sea legible.",
            )

        body = content_text[:8000]

        # 2) Intentar parseo directo con regex (sin IA)
        direct_result = _try_parse_invoice_regex(body)
        if direct_result:
            return ToolResult(
                ok=True,
                output=json.dumps(direct_result, indent=2, ensure_ascii=False),
                artifacts=[{"type": "invoice_parsed", "path": path, "data": direct_result, "method": "regex"}],
            )

        # 3) Fallback: IA para parseo estructurado
        from app.services.provider_router import route_chat

        prompt = (
            "Extrae de esta factura los siguientes campos en JSON valido (solo el JSON, sin markdown):\n"
            '{\n'
            '  "monto_total": float,\n'
            '  "fecha": "YYYY-MM-DD",\n'
            '  "proveedor": "nombre del emisor",\n'
            '  "iva": float (monto del IVA o 0 si no aplica),\n'
            '  "concepto": "descripcion breve de lo facturado",\n'
            '  "moneda": "codigo ISO de 3 letras (USD/VES/EUR/etc.)",\n'
            '  "numero_factura": "numero o codigo de la factura si aparece"\n'
            '}\n\n'
            f"Texto de la factura:\n{body}"
        )

        result = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt="Eres un contador experto en extraccion de datos de facturas. Responde SOLO con JSON valido, sin explicaciones ni markdown.",
            include_document_action_prompt=False,
        )

        try:
            parsed = json.loads(result.strip().removeprefix("```json").removesuffix("```").strip())
            return ToolResult(
                ok=True,
                output=json.dumps(parsed, indent=2, ensure_ascii=False),
                artifacts=[{"type": "invoice_parsed", "path": path, "data": parsed, "method": "ia"}],
            )
        except json.JSONDecodeError:
            return ToolResult(
                ok=True,
                output=result.strip(),
                artifacts=[{"type": "invoice_parsed", "path": path, "raw_text": result.strip()[:3000]}],
            )

    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"Dependencia faltante: {e}")
    except Exception as e:
        log.exception("finance_parse_invoice uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error al procesar factura: {e}")


def _try_parse_invoice_regex(text: str) -> dict[str, Any] | None:
    """Intenta parsear campos de factura con regex antes de usar IA."""
    try:
        result: dict[str, Any] = {}

        # Monto total
        monto_patterns = [
            r'(?:total|monto|importe|a pagar|TOTAL)\s*[:\$]?\s*(\d[\d.,]+)',
            r'(?:Bs|USD|\$)\s*(\d[\d.,]+)\s*$',
        ]
        for pat in monto_patterns:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    result["monto_total"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    continue

        # Fecha
        date_patterns = [
            r'(?:fecha|date)[:\s]*(\d{4}[-/]\d{2}[-/]\d{2})',
            r'(\d{2}[-/]\d{2}[-/]\d{4})',
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["fecha"] = m.group(1).replace("/", "-")
                break

        # IVA
        iva_m = re.search(r'(?:IVA|impuesto|tax)[:\s]*(\d[\d.,]+)', text, re.IGNORECASE)
        if iva_m:
            try:
                result["iva"] = float(iva_m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Moneda
        if "USD" in text.upper() or "$" in text:
            result["moneda"] = "USD"
        elif "VES" in text.upper() or "Bs" in text:
            result["moneda"] = "VES"
        elif "EUR" in text.upper() or "\u20ac" in text:
            result["moneda"] = "EUR"

        # Numero de factura
        nro_m = re.search(r'(?:factura|invoice|nro|n\u00b0|#)\s*[:\s]*(\w[\w\s-]{2,20})', text, re.IGNORECASE)
        if nro_m:
            result["numero_factura"] = nro_m.group(1).strip()

        # Proveedor: primera linea en mayusculas
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
        for line in lines[:5]:
            if line.isupper() and not any(c.isdigit() for c in line) and len(line) > 5:
                result["proveedor"] = line
                break

        # Solo retornar si tenemos suficiente info
        if "monto_total" in result and "fecha" in result:
            return result
        if len(result) >= 3:
            return result

    except Exception:
        pass

    return None


# ──────────────────────────────────────────────
#  10. car_route_optimizer → OpenRouteService
# ──────────────────────────────────────────────

def car_route_optimizer_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Calcula ruta optima entre dos puntos usando OpenRouteService + geocodificacion Nominatim."""
    try:
        origin = str(arguments.get("origin") or "").strip()
        destination = str(arguments.get("destination") or "").strip()

        if not origin or not destination:
            return ToolResult(ok=False, output="", error="Falta origen y destino.")

        cached = _cache_get("route", origin.lower(), destination.lower())
        if cached is not None:
            return ToolResult(ok=True, output=cached)

        api_key = _env("OPENROUTE_API_KEY")
        if not api_key:
            return ToolResult(
                ok=True,
                output=(
                    f"🚗 Ruta {origin} → {destination}\n"
                    f"OpenRouteService API no configurada.\n"
                    f"Para habilitar rutas automaticas: configura OPENROUTE_API_KEY "
                    f"(gratis en openrouteservice.org).\n"
                    f"Mientras tanto, puedes buscar en Google Maps o Waze."
                ),
            )

        # Geocodificar origen y destino con Nominatim (sync)
        def _geocode(addr: str) -> tuple[float, float] | None:
            try:
                _rate_limit("route_geo", 1.2)
                with httpx.Client(timeout=10) as client:
                    resp = client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": addr, "format": "json", "limit": 1},
                        headers={"User-Agent": "DOT-Assistant/1.0 (Nordik-IA)"},
                    )
                    resp.raise_for_status()
                    results = resp.json()
                    if results:
                        return float(results[0]["lon"]), float(results[0]["lat"])
                    return None
            except Exception as e:
                log.warning("Geocodificacion fallo para '%s': %s", addr, e)
                return None

        origin_coords = _geocode(origin)
        dest_coords = _geocode(destination)

        if not origin_coords or not dest_coords:
            missing = []
            if not origin_coords:
                missing.append(f"origen '{origin}'")
            if not dest_coords:
                missing.append(f"destino '{destination}'")
            return ToolResult(
                ok=False, output="",
                error=f"No se pudo geocodificar: {', '.join(missing)}. Verifica las direcciones."
            )

        # Calcular ruta con OpenRouteService
        _rate_limit("route_ors", 1.5)
        ors_url = "https://api.openrouteservice.org/v2/directions/driving-car"
        body_ors = {
            "coordinates": [list(origin_coords), list(dest_coords)],
            "instructions": True,
            "units": "km",
        }

        with httpx.Client(timeout=20) as client:
            resp = client.post(
                ors_url,
                json=body_ors,
                headers={
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 403:
                return ToolResult(ok=False, output="", error="API key de OpenRouteService invalida o sin permisos.")
            resp.raise_for_status()
            data = resp.json()

        routes = data.get("routes", [])
        if not routes:
            return ToolResult(ok=False, output="", error="No se encontraron rutas entre los puntos dados.")

        route = routes[0]
        summary = route.get("summary", {})
        distance_km = round(summary.get("distance", 0) / 1000, 1)
        duration_min = round(summary.get("duration", 0) / 60, 1)

        # Extraer instrucciones
        segments = route.get("segments", [])
        steps = []
        for seg in segments[:1]:
            for step in seg.get("steps", [])[:8]:
                instruction = step.get("instruction", "")
                step_dist = round(step.get("distance", 0) / 1000, 1)
                if instruction:
                    steps.append(f"  • {instruction} ({step_dist} km)")

        output = (
            f"🚗 Ruta {origin} → {destination}\n"
            f"Distancia: {distance_km} km\n"
            f"Duracion estimada: {duration_min} min ({round(duration_min/60, 1)} h)\n"
            + ("\nInstrucciones:\n" + "\n".join(steps) if steps else "")
            + "\n\nFuente: OpenRouteService + OpenStreetMap"
        )
        _cache_set("route", origin.lower(), destination.lower(), value=output)
        return ToolResult(ok=True, output=output)

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error al consultar OpenRouteService: {e}")
    except Exception as e:
        log.exception("car_route_optimizer uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("web_get_weather", web_get_weather_handler),
    ("web_get_news", web_get_news_handler),
    ("web_currency_convert", web_currency_convert_handler),
    ("web_get_stock", web_get_stock_handler),
    ("web_geocode", web_geocode_handler),
    ("research_academic_papers", research_academic_papers_handler),
    ("monitor_flight_price", monitor_flight_price_handler),
    ("monitor_job_opening", monitor_job_opening_handler),
    ("monitor_news_keyword", monitor_news_keyword_handler),
    ("finance_parse_invoice", finance_parse_invoice_handler),
    ("car_route_optimizer", car_route_optimizer_handler),
]
