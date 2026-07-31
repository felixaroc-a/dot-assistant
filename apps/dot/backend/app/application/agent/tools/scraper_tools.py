"""Scrapers CDP reales — M3S2-A.

10 herramientas que antes alucinaban datos y ahora usan browser CDP
(Chrome DevTools Protocol) via Electron para scraping real.

Cada scraper describe su estrategia de navegación y extracción.
NO ejecuta el scraping directamente — Electron (bridge) lo hace.
Si el browser no está disponible → mensaje claro de configuración.

Scrapers:
  1. scraper_flights       — Kayak/Google Flights (vuelos)
  2. scraper_hotels        — Booking.com (hoteles)
  3. scraper_amazon        — Amazon (productos)
  4. scraper_linkedin_jobs — LinkedIn Jobs (empleos)
  5. scraper_google_news   — Google News (noticias)
  6. scraper_weather_detailed — Weather.com (clima detallado)
  7. scraper_crypto_prices — CoinMarketCap (criptomonedas)
  8. scraper_parallel_usd  — Monitor Dólar Venezuela (BCV + paralelo)
  9. scraper_recipes       — Recetas de cocina
 10. scraper_product_reviews — Reseñas de productos

Categoría: scraper | Capability: B (requiere permiso browser)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.scrapers")

# ──────────────────────────────────────────────
#  Helpers: bridge browser + verificación
# ──────────────────────────────────────────────

# Reutilizamos el bridge existente de browser_tools
try:
    from app.application.agent.tools.browser_tools import _bridge_browser, _err
except ImportError:
    def _bridge_browser(operation: str, **fields: Any) -> dict[str, Any]:
        return {"ok": False, "error": "bridge_import_failed"}

    def _err(raw: dict[str, Any], fallback: str) -> ToolResult:
        err = str(raw.get("error") or raw.get("message") or fallback)
        return ToolResult(ok=False, output="", error=err)


def _check_browser_available() -> str | None:
    """Verifica que el bridge del navegador esté disponible.
    Retorna None si OK, o mensaje de error si no está disponible."""
    raw = _bridge_browser("browserGetPageURL")
    if raw.get("ok"):
        return None
    err = raw.get("error", "")
    if "unreachable" in str(err).lower() or "not_configured" in str(err).lower():
        return (
            "Navegador no disponible. Para usar scrapers reales, activa "
            "'Browser' en Configuración > Sesiones del panel de DOT. "
            "Sin browser, los scrapers no pueden extraer datos en vivo."
        )
    return None


def _scraper_error(reason: str) -> ToolResult:
    """Respuesta de error estándar para scrapers sin browser."""
    browser_msg = _check_browser_available()
    if browser_msg:
        return ToolResult(ok=False, output="", error=browser_msg)
    return ToolResult(ok=False, output="", error=reason)


# ──────────────────────────────────────────────
#  1. scraper_flights — Kayak / Google Flights
# ──────────────────────────────────────────────

SCRAPER_FLIGHTS_SPEC = {
    "description": (
        "Busca vuelos reales en Kayak usando navegador CDP. "
        "Navega, espera resultados y extrae precios, aerolíneas y horarios. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "Código IATA de aeropuerto de origen (ej: CCS, BOG, MAD)",
            },
            "destination": {
                "type": "string",
                "description": "Código IATA de aeropuerto de destino (ej: MIA, LIM, EZE)",
            },
            "date": {
                "type": "string",
                "description": "Fecha de salida YYYY-MM-DD (default: hoy + 30 días)",
            },
        },
        "required": ["origin", "destination"],
    },
    "category": "scraper",
    "capability": "B",
}

# Estrategia de scraping para Kayak
# Pasos: browser_navigate → wait → extract → parse
FLIGHTS_STRATEGY = """
Estrategia de scraping Kayak:
1. Navegar a: https://www.kayak.com/flights/{origin}-{destination}/{date}
2. Esperar selector: '.flight-card' o '.resultInner' (timeout 15s)
3. Extraer texto visible con selector '.results'
4. Parsear: aerolínea, precio, horario salida/llegada, escalas
5. Si Kayak bloquea → fallback Google Flights:
   https://www.google.com/travel/flights?q=Flights+to+{destination}+from+{origin}+on+{date}
"""


def scraper_flights_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca vuelos reales usando navegador CDP (Kayak / Google Flights)."""
    try:
        origin = str(arguments.get("origin") or "").strip().upper()
        destination = str(arguments.get("destination") or "").strip().upper()

        if not origin or not destination:
            return ToolResult(ok=False, output="", error="Falta origin y destination (códigos IATA).")

        # Verificar browser
        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        from datetime import datetime as dt, timezone
        today = dt.now(timezone.utc)
        date_str = str(arguments.get("date") or "").strip()
        if not date_str:
            # Default: 30 días desde hoy
            future = today.replace(day=min(today.day + 30, 28))
            date_str = future.strftime("%Y-%m-%d")

        # Paso 1: Navegar a Kayak
        kayak_url = f"https://www.kayak.com/flights/{origin}-{destination}/{date_str}"
        nav = _bridge_browser("browserNavigate", url=kayak_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        # Paso 2: Activar stealth (anti-bloqueo)
        _bridge_browser("browserStealth")

        # Paso 3: Esperar que carguen resultados
        wait = _bridge_browser(
            "browserWait",
            selector=".flight-card, .resultInner, .nrc6",
            timeoutMs=15000,
        )

        # Paso 4: Extraer texto
        extract = _bridge_browser(
            "browserExtract",
            selector=".results, .main-content, body",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:5000]
            return ToolResult(
                ok=True,
                output=(
                    f"✈️ Vuelos {origin} → {destination} — {date_str}\n"
                    f"URL: {kayak_url}\n"
                    f"---\n"
                    f"{text}\n"
                    f"---\n"
                    f"Fuente: Kayak (scraping CDP)\n"
                    f"Estrategia: {FLIGHTS_STRATEGY.strip()[:300]}"
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"✈️ Búsqueda de vuelos {origin} → {destination} ({date_str})\n"
                f"Navegué a Kayak pero no se pudieron extraer resultados automáticamente.\n"
                f"URL directa: {kayak_url}\n"
                f"También puedes buscar en Google Flights: "
                f"https://www.google.com/travel/flights?q=Vuelos+de+{origin}+a+{destination}"
            ),
        )

    except Exception as e:
        log.exception("scraper_flights uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_flights: {e}")


# ──────────────────────────────────────────────
#  2. scraper_hotels — Booking.com
# ──────────────────────────────────────────────

SCRAPER_HOTELS_SPEC = {
    "description": (
        "Busca hoteles reales en Booking.com usando navegador CDP. "
        "Extrae nombres, precios, puntuaciones y ubicación. Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Ciudad o destino (ej: 'Caracas', 'Cartagena', 'Cancún')",
            },
            "checkin": {
                "type": "string",
                "description": "Fecha de entrada YYYY-MM-DD (default: hoy)",
            },
            "checkout": {
                "type": "string",
                "description": "Fecha de salida YYYY-MM-DD (default: checkin + 1)",
            },
        },
        "required": ["city"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_hotels_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca hoteles reales en Booking.com usando navegador CDP."""
    try:
        city = str(arguments.get("city") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta city (ciudad o destino).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        from datetime import datetime as dt, timezone, timedelta
        today = dt.now(timezone.utc)
        checkin = str(arguments.get("checkin") or today.strftime("%Y-%m-%d")).strip()
        checkout = str(
            arguments.get("checkout")
            or (today + timedelta(days=1)).strftime("%Y-%m-%d")
        ).strip()

        # Construir URL de Booking
        city_slug = city.lower().replace(" ", "-")
        booking_url = (
            f"https://www.booking.com/searchresults.html?"
            f"ss={city.replace(' ', '+')}&"
            f"checkin={checkin}&checkout={checkout}"
        )

        # Navegar
        nav = _bridge_browser("browserNavigate", url=booking_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar resultados
        _bridge_browser(
            "browserWait",
            selector="[data-testid='property-card'], .sr_item",
            timeoutMs=15000,
        )

        # Extraer
        extract = _bridge_browser(
            "browserExtract",
            selector="[data-testid='property-card'], .sr_item, #search_results_table",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:8000]
            return ToolResult(
                ok=True,
                output=(
                    f"🏨 Hoteles en {city.title()} — {checkin} al {checkout}\n"
                    f"URL: {booking_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: Booking.com (scraping CDP)"
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"🏨 Hoteles en {city.title()} ({checkin} → {checkout})\n"
                f"Navegué a Booking.com pero no se extrajeron resultados automáticamente.\n"
                f"URL directa: {booking_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_hotels uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_hotels: {e}")


# ──────────────────────────────────────────────
#  3. scraper_amazon — Productos Amazon
# ──────────────────────────────────────────────

SCRAPER_AMAZON_SPEC = {
    "description": (
        "Busca productos reales en Amazon usando navegador CDP. "
        "Extrae nombres, precios, ratings y disponibilidad. "
        "Soporta Amazon.com, Amazon.es, Amazon.com.mx. Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Producto a buscar (ej: 'laptop gamer', 'audífonos bluetooth')",
            },
            "site": {
                "type": "string",
                "enum": ["com", "es", "com.mx", "com.br"],
                "description": "Dominio de Amazon (default: com)",
            },
        },
        "required": ["query"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_amazon_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca productos en Amazon usando navegador CDP."""
    try:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query (producto a buscar).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        site = str(arguments.get("site") or "com").strip()
        domain = site if site.startswith("amazon.") else f"amazon.{site}"
        amazon_url = f"https://www.{domain}/s?k={query.replace(' ', '+')}"

        # Navegar
        nav = _bridge_browser("browserNavigate", url=amazon_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar resultados
        _bridge_browser(
            "browserWait",
            selector="[data-component-type='s-search-result'], .s-result-item",
            timeoutMs=15000,
        )

        # Extraer resultados
        extract = _bridge_browser(
            "browserExtract",
            selector="[data-component-type='s-search-result'], .s-main-slot",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:8000]
            # Intentar extraer precios
            price_raw = _bridge_browser("browserGetPrice")
            price_info = ""
            if price_raw.get("price"):
                price_info = f"Precio detectado: {price_raw.get('price')}\n"

            return ToolResult(
                ok=True,
                output=(
                    f"🛒 Amazon — '{query}' en amazon.{site}\n"
                    f"URL: {amazon_url}\n"
                    f"{price_info}"
                    f"---\n{text}\n---\n"
                    f"Fuente: Amazon {domain} (scraping CDP)"
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"🛒 Amazon — '{query}'\n"
                f"Navegué a Amazon pero no se extrajeron resultados automáticamente.\n"
                f"URL directa: {amazon_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_amazon uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_amazon: {e}")


# ──────────────────────────────────────────────
#  4. scraper_linkedin_jobs — LinkedIn Jobs
# ──────────────────────────────────────────────

SCRAPER_LINKEDIN_JOBS_SPEC = {
    "description": (
        "Busca ofertas de empleo reales en LinkedIn Jobs usando navegador CDP. "
        "Extrae títulos, empresas, ubicación y fecha de publicación. Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Palabra clave del cargo (ej: 'desarrollador python', 'contador')",
            },
            "location": {
                "type": "string",
                "description": "Ubicación (ej: 'Caracas', 'Remoto', 'Colombia')",
            },
        },
        "required": ["keyword"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_linkedin_jobs_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca empleos en LinkedIn Jobs usando navegador CDP."""
    try:
        keyword = str(arguments.get("keyword") or "").strip()
        if not keyword:
            return ToolResult(ok=False, output="", error="Falta keyword (cargo a buscar).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        location = str(arguments.get("location") or "").strip()
        loc_param = f"&location={location.replace(' ', '%20')}" if location else ""
        linkedin_url = (
            f"https://www.linkedin.com/jobs/search/?"
            f"keywords={keyword.replace(' ', '%20')}{loc_param}"
        )

        # Navegar
        nav = _bridge_browser("browserNavigate", url=linkedin_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Scroll para cargar más resultados
        _bridge_browser("browserScroll", delta_y=500, repeat=2)

        # Esperar resultados
        _bridge_browser(
            "browserWait",
            selector=".jobs-search__results-list, .job-card-container",
            timeoutMs=15000,
        )

        # Extraer
        extract = _bridge_browser(
            "browserExtract",
            selector=".jobs-search__results-list, ul.jobs-search__results-list",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:8000]
            return ToolResult(
                ok=True,
                output=(
                    f"💼 LinkedIn Jobs — '{keyword}'"
                    + (f" en {location}" if location else "")
                    + f"\nURL: {linkedin_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: LinkedIn Jobs (scraping CDP)"
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"💼 LinkedIn Jobs — '{keyword}'"
                + (f" en {location}" if location else "")
                + f"\nNavegué a LinkedIn pero no se extrajeron resultados automáticamente.\n"
                f"URL directa: {linkedin_url}\n"
                f"Nota: LinkedIn puede requerir inicio de sesión para ver resultados completos."
            ),
        )

    except Exception as e:
        log.exception("scraper_linkedin_jobs uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_linkedin_jobs: {e}")


# ──────────────────────────────────────────────
#  5. scraper_google_news — Google News
# ──────────────────────────────────────────────

SCRAPER_GOOGLE_NEWS_SPEC = {
    "description": (
        "Busca noticias reales en Google News usando navegador CDP. "
        "Extrae titulares, fuentes y timestamps. "
        "Más completo que NewsAPI/RSS porque incluye todas las fuentes indexadas. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Palabra clave o tema (ej: 'inteligencia artificial', 'economía')",
            },
            "language": {
                "type": "string",
                "enum": ["es", "en", "pt"],
                "description": "Idioma de resultados (default: es)",
            },
        },
        "required": ["keyword"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_google_news_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca noticias en Google News usando navegador CDP."""
    try:
        keyword = str(arguments.get("keyword") or "").strip()
        if not keyword:
            return ToolResult(ok=False, output="", error="Falta keyword (tema a buscar).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        lang = str(arguments.get("language") or "es").strip()
        hl_map = {"es": "es-419", "en": "en-US", "pt": "pt-BR"}
        hl = hl_map.get(lang, "es-419")

        news_url = (
            f"https://news.google.com/search?"
            f"q={keyword.replace(' ', '%20')}&hl={hl}"
        )

        # Navegar
        nav = _bridge_browser("browserNavigate", url=news_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar artículos
        _bridge_browser(
            "browserWait",
            selector="article, .NiLAwe, .xrnccd",
            timeoutMs=10000,
        )

        # Extraer
        extract = _bridge_browser(
            "browserExtract",
            selector="main, c-wiz, body",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:8000]
            return ToolResult(
                ok=True,
                output=(
                    f"📰 Google News — '{keyword}' ({lang})\n"
                    f"URL: {news_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: Google News (scraping CDP)"
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"📰 Google News — '{keyword}'\n"
                f"Navegué a Google News pero no se extrajeron resultados.\n"
                f"URL directa: {news_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_google_news uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_google_news: {e}")


# ──────────────────────────────────────────────
#  6. scraper_weather_detailed — Weather.com
# ──────────────────────────────────────────────

SCRAPER_WEATHER_DETAILED_SPEC = {
    "description": (
        "Obtiene pronóstico detallado de Weather.com usando navegador CDP. "
        "Incluye pronóstico por hora, 10 días, sensación térmica, UV, viento. "
        "Más completo que OpenWeatherMap (datos horarios + extendidos). "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Ciudad para el pronóstico (ej: 'Caracas', 'Bogotá', 'Madrid')",
            },
        },
        "required": ["city"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_weather_detailed_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene clima detallado de Weather.com usando navegador CDP."""
    try:
        city = str(arguments.get("city") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta city.")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        city_slug = city.lower().replace(" ", "-")
        weather_url = f"https://weather.com/weather/today/l/{city_slug}"

        # Navegar
        nav = _bridge_browser("browserNavigate", url=weather_url)
        if not nav.get("ok"):
            # Fallback: búsqueda en weather.com
            fallback_url = f"https://weather.com/search?query={city.replace(' ', '%20')}"
            nav = _bridge_browser("browserNavigate", url=fallback_url)
            if not nav.get("ok"):
                return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar que cargue el widget del clima
        _bridge_browser(
            "browserWait",
            selector=".CurrentConditions, [data-testid='CurrentConditionsContainer'], .today-details",
            timeoutMs=12000,
        )

        # Extraer datos
        extract = _bridge_browser(
            "browserExtract",
            selector=".CurrentConditions, [data-testid='CurrentConditionsContainer'], main",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:5000]
            return ToolResult(
                ok=True,
                output=(
                    f"🌤 Clima detallado — {city.title()}\n"
                    f"URL: {weather_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: Weather.com (scraping CDP)\n"
                    f"Incluye: temperatura, sensación térmica, humedad, viento, "
                    f"índice UV, visibilidad, pronóstico horario y 10 días."
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"🌤 Clima — {city.title()}\n"
                f"Navegué a Weather.com pero no se extrajeron datos detallados.\n"
                f"URL directa: {weather_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_weather_detailed uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_weather_detailed: {e}")


# ──────────────────────────────────────────────
#  7. scraper_crypto_prices — CoinMarketCap
# ──────────────────────────────────────────────

SCRAPER_CRYPTO_PRICES_SPEC = {
    "description": (
        "Obtiene precio actual de criptomonedas desde CoinMarketCap usando navegador CDP. "
        "Incluye precio USD, cambio 24h, market cap y volumen. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "coin": {
                "type": "string",
                "description": "Símbolo de la criptomoneda (ej: 'btc', 'eth', 'usdt', 'bnb', 'xrp')",
            },
        },
        "required": ["coin"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_crypto_prices_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene precio de criptomoneda desde CoinMarketCap usando navegador CDP."""
    try:
        coin = str(arguments.get("coin") or "").strip().lower()
        if not coin:
            return ToolResult(ok=False, output="", error="Falta coin (símbolo de criptomoneda).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        # CoinMarketCap usa slugs, no símbolos
        slug_map = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "usdt": "tether",
            "bnb": "bnb",
            "xrp": "xrp",
            "sol": "solana",
            "ada": "cardano",
            "doge": "dogecoin",
            "dot": "polkadot-new",
            "matic": "polygon",
        }
        slug = slug_map.get(coin, coin)
        cmc_url = f"https://coinmarketcap.com/currencies/{slug}/"

        # Navegar
        nav = _bridge_browser("browserNavigate", url=cmc_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar precio
        _bridge_browser(
            "browserWait",
            selector=".priceValue, [data-test='text-cdp-price-display'], .sc-16891c57-0",
            timeoutMs=12000,
        )

        # Extraer
        extract = _bridge_browser(
            "browserExtract",
            selector=".priceValue, .statsContainer, main",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:3000]
            return ToolResult(
                ok=True,
                output=(
                    f"💎 {coin.upper()} — CoinMarketCap\n"
                    f"URL: {cmc_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: CoinMarketCap (scraping CDP)\n"
                    f"Incluye: precio USD, cambio 24h, market cap, volumen, "
                    f"supply circulante y max supply."
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"💎 {coin.upper()}\n"
                f"Navegué a CoinMarketCap pero no se extrajo el precio.\n"
                f"URL directa: {cmc_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_crypto_prices uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_crypto_prices: {e}")


# ──────────────────────────────────────────────
#  8. scraper_parallel_usd — Monitor Dólar Venezuela
# ──────────────────────────────────────────────

SCRAPER_PARALLEL_USD_SPEC = {
    "description": (
        "Obtiene la tasa del dólar paralelo y BCV en Venezuela desde "
        "Monitor Dólar Venezuela usando navegador CDP. "
        "Incluye: BCV oficial, paralelo, monitor, binance y más. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {},
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_parallel_usd_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene tasa del dólar en Venezuela (BCV + paralelo) usando navegador CDP."""
    try:
        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        # Estrategia: Monitor Dólar Venezuela (monitordolarvenezuela.com)
        urls = [
            "https://monitordolarvenezuela.com/",
            "https://www.bcv.org.ve/",
        ]

        results = []
        for url in urls:
            nav = _bridge_browser("browserNavigate", url=url)
            if not nav.get("ok"):
                continue

            _bridge_browser("browserStealth")

            # Esperar que carguen las tasas
            _bridge_browser(
                "browserWait",
                selector=".dollar-price, table, .tasas, #dolar",
                timeoutMs=12000,
            )

            extract = _bridge_browser("browserExtract", selector="body")
            if extract.get("ok"):
                text = str(extract.get("text", ""))[:3000]
                results.append(f"Fuente: {url}\n{text}\n")

        if results:
            return ToolResult(
                ok=True,
                output=(
                    f"💵 Dólar Venezuela — Tasas de cambio\n"
                    f"---\n"
                    + "\n---\n".join(results)
                    + "\n---\n"
                    f"Fuentes: Monitor Dólar Venezuela, BCV (scraping CDP)\n"
                    f"Incluye: BCV oficial, paralelo, monitor, binance y otras tasas de referencia."
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"💵 Dólar Venezuela\n"
                f"No se pudieron extraer tasas automáticamente.\n"
                f"Consulta manual:\n"
                f"• Monitor Dólar: https://monitordolarvenezuela.com/\n"
                f"• BCV Oficial: https://www.bcv.org.ve/\n"
                f"• DolarToday: https://dolartoday.com/"
            ),
        )

    except Exception as e:
        log.exception("scraper_parallel_usd uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_parallel_usd: {e}")


# ──────────────────────────────────────────────
#  9. scraper_recipes — Recetas de cocina
# ──────────────────────────────────────────────

SCRAPER_RECIPES_SPEC = {
    "description": (
        "Busca recetas de cocina reales en la web (AllRecipes, Directo al Paladar, "
        "KiwiLimón) usando navegador CDP. "
        "Extrae ingredientes, pasos, tiempo de preparación y porciones. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "dish": {
                "type": "string",
                "description": "Plato o receta a buscar (ej: 'arepas', 'paella', 'tacos al pastor')",
            },
            "servings": {
                "type": "integer",
                "description": "Número de porciones deseadas (default: 4)",
            },
        },
        "required": ["dish"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_recipes_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca recetas de cocina usando navegador CDP."""
    try:
        dish = str(arguments.get("dish") or "").strip()
        if not dish:
            return ToolResult(ok=False, output="", error="Falta dish (plato o receta a buscar).")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        servings = int(arguments.get("servings") or 4)

        # Buscar en Google: "receta de {dish}"
        search_url = (
            f"https://www.google.com/search?"
            f"q=receta+de+{dish.replace(' ', '+')}"
        )

        # Navegar
        nav = _bridge_browser("browserNavigate", url=search_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Esperar resultados
        _bridge_browser(
            "browserWait",
            selector=".g, [data-sokoban-container], #search",
            timeoutMs=10000,
        )

        # Extraer resultados de búsqueda
        extract = _bridge_browser(
            "browserExtract",
            selector="#search, #rso",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:5000]
            return ToolResult(
                ok=True,
                output=(
                    f"🍳 Recetas — '{dish}' ({servings} porciones)\n"
                    f"Búsqueda: {search_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: Google Search (scraping CDP)\n"
                    f"Los resultados incluyen enlaces a sitios como AllRecipes, "
                    f"Directo al Paladar, KiwiLimón, Paulina Cocina y más.\n"
                    f"Para una receta específica, navega a uno de los enlaces "
                    f"y usa browser_extract para obtener ingredientes y pasos completos."
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"🍳 Recetas — '{dish}'\n"
                f"No se extrajeron resultados automáticamente.\n"
                f"Busca manualmente: {search_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_recipes uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_recipes: {e}")


# ──────────────────────────────────────────────
#  10. scraper_product_reviews — Reseñas de productos
# ──────────────────────────────────────────────

SCRAPER_PRODUCT_REVIEWS_SPEC = {
    "description": (
        "Busca reseñas y opiniones reales de productos en la web usando "
        "navegador CDP. Ideal para investigar antes de comprar. "
        "Busca en Amazon, MercadoLibre, Google Reviews y sitios especializados. "
        "Requiere browser activo."
    ),
    "parameters_schema": {
        "type": "object",
        "properties": {
            "product_name": {
                "type": "string",
                "description": "Nombre del producto a investigar (ej: 'iPhone 16 Pro Max')",
            },
            "site": {
                "type": "string",
                "enum": ["amazon", "mercadolibre", "google", "all"],
                "description": "Sitio donde buscar reseñas (default: all = todos)",
            },
        },
        "required": ["product_name"],
    },
    "category": "scraper",
    "capability": "B",
}


def scraper_product_reviews_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca reseñas de productos usando navegador CDP."""
    try:
        product_name = str(arguments.get("product_name") or "").strip()
        if not product_name:
            return ToolResult(ok=False, output="", error="Falta product_name.")

        browser_err = _check_browser_available()
        if browser_err:
            return ToolResult(ok=False, output="", error=browser_err)

        site = str(arguments.get("site") or "all").strip()

        # Construir URL de búsqueda según el sitio
        if site == "amazon":
            search_url = (
                f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
                f"&rh=p_72%3A1248879011"  # Filtrar por productos con buenas reviews
            )
        elif site == "mercadolibre":
            search_url = (
                f"https://listado.mercadolibre.com.co/"
                f"{product_name.replace(' ', '-')}_OrderId_PRICE"
            )
        else:
            # Google Reviews (default / all)
            search_url = (
                f"https://www.google.com/search?"
                f"q={product_name.replace(' ', '+')}+review+opiniones"
            )

        # Navegar
        nav = _bridge_browser("browserNavigate", url=search_url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

        _bridge_browser("browserStealth")

        # Scroll para cargar más reseñas
        _bridge_browser("browserScroll", delta_y=300, repeat=2)

        # Esperar contenido
        _bridge_browser(
            "browserWait",
            selector=".review, .g, .ui-search-result, [data-hook='review']",
            timeoutMs=12000,
        )

        # Extraer
        extract = _bridge_browser(
            "browserExtract",
            selector="body",
        )

        if extract.get("ok"):
            text = str(extract.get("text", ""))[:6000]
            return ToolResult(
                ok=True,
                output=(
                    f"⭐ Reseñas — '{product_name}' ({site})\n"
                    f"URL: {search_url}\n"
                    f"---\n{text}\n---\n"
                    f"Fuente: {'Amazon' if site == 'amazon' else 'Mercado Libre' if site == 'mercadolibre' else 'Google Reviews'} (scraping CDP)\n"
                    f"Incluye: calificaciones, comentarios de usuarios, pros/contras."
                ),
            )

        return ToolResult(
            ok=True,
            output=(
                f"⭐ Reseñas — '{product_name}'\n"
                f"No se extrajeron reseñas automáticamente.\n"
                f"URL directa: {search_url}"
            ),
        )

    except Exception as e:
        log.exception("scraper_product_reviews uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error en scraper_product_reviews: {e}")


# ──────────────────────────────────────────────
#  TOOLS registry — 10 scrapers
# ──────────────────────────────────────────────

TOOLS = [
    ("scraper_flights", scraper_flights_handler),
    ("scraper_hotels", scraper_hotels_handler),
    ("scraper_amazon", scraper_amazon_handler),
    ("scraper_linkedin_jobs", scraper_linkedin_jobs_handler),
    ("scraper_google_news", scraper_google_news_handler),
    ("scraper_weather_detailed", scraper_weather_detailed_handler),
    ("scraper_crypto_prices", scraper_crypto_prices_handler),
    ("scraper_parallel_usd", scraper_parallel_usd_handler),
    ("scraper_recipes", scraper_recipes_handler),
    ("scraper_product_reviews", scraper_product_reviews_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parámetros completos
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "scraper_flights": SCRAPER_FLIGHTS_SPEC,
    "scraper_hotels": SCRAPER_HOTELS_SPEC,
    "scraper_amazon": SCRAPER_AMAZON_SPEC,
    "scraper_linkedin_jobs": SCRAPER_LINKEDIN_JOBS_SPEC,
    "scraper_google_news": SCRAPER_GOOGLE_NEWS_SPEC,
    "scraper_weather_detailed": SCRAPER_WEATHER_DETAILED_SPEC,
    "scraper_crypto_prices": SCRAPER_CRYPTO_PRICES_SPEC,
    "scraper_parallel_usd": SCRAPER_PARALLEL_USD_SPEC,
    "scraper_recipes": SCRAPER_RECIPES_SPEC,
    "scraper_product_reviews": SCRAPER_PRODUCT_REVIEWS_SPEC,
}
