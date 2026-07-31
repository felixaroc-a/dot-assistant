"""Tools MercadoLibre API — M2S3-A.

5 tools reales para MercadoLibre usando API oficial (gratis, 1000 req/h):
  - ml_search: buscar productos por query
  - ml_product_detail: detalle de un producto por item_id
  - ml_my_products: listar productos del vendedor (requiere token)
  - ml_price_comparison: comparar precios de un producto
  - ml_seller_reputation: reputacion de un vendedor

Rate limit: ~1 req/seg. Sin API keys → mensaje claro, no alucina.

Variables de entorno:
  MERCADOLIBRE_ACCESS_TOKEN → para ml_my_products (OAuth, opcional)
"""

from __future__ import annotations

import logging
import os
import statistics
import time
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.mercadolibre")

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 1.0) -> None:
    """Espera si es necesario para respetar rate limit."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _env(key: str) -> str:
    """Lee variable de entorno, sin default — si no existe, retorna ''."""
    return (os.getenv(key) or "").strip()


def _check_token() -> str | None:
    """Retorna mensaje de error si MERCADOLIBRE_ACCESS_TOKEN no configurado."""
    token = _env("MERCADOLIBRE_ACCESS_TOKEN")
    if not token:
        return (
            "MercadoLibre API requiere token de acceso. "
            "Solicita al usuario que configure MERCADOLIBRE_ACCESS_TOKEN en Ajustes "
            "(obtenlo vinculando tu cuenta en https://developers.mercadolibre.com)."
        )
    return None


# ──────────────────────────────────────────────
#  Formateo de precios
# ──────────────────────────────────────────────

def _fmt_price(price: float, currency_id: str = "VES") -> str:
    """Formatea precio con separadores de miles."""
    currency_symbols = {"VES": "Bs.", "USD": "US$", "COP": "COP$", "ARS": "AR$", "MXN": "MX$"}
    symbol = currency_symbols.get(currency_id, currency_id)
    if price >= 1_000_000:
        return f"{symbol} {price:,.0f}"
    return f"{symbol} {price:,.2f}"


# ──────────────────────────────────────────────
#  1. ml_search — Buscar productos
# ──────────────────────────────────────────────

def ml_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca productos en MercadoLibre por palabra clave. Retorna titulo, precio, thumbnail y enlace."""
    try:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query de busqueda.")

        site = str(arguments.get("site") or "MLV").strip().upper()
        limit = min(int(arguments.get("limit") or 10), 50)

        _rate_limit("ml_search")
        url = f"https://api.mercadolibre.com/sites/{site}/search"
        params: dict[str, str | int] = {
            "q": query,
            "limit": limit,
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Sitio '{site}' no encontrado. Usa MLV (Venezuela), MLA (Argentina), MCO (Colombia), etc.",
                )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return ToolResult(
                ok=True,
                output=f"🛒 No se encontraron productos para '{query}' en {site}.",
            )

        lines = [f"🛒 MercadoLibre — '{query}' en {site} ({len(results)} resultados):\n"]
        for i, item in enumerate(results[:10], 1):
            title = (item.get("title") or "Sin titulo")[:100]
            price = item.get("price", 0)
            currency = item.get("currency_id", "VES")
            thumbnail = item.get("thumbnail", "")
            permalink = item.get("permalink", "")
            condition = item.get("condition", "?")

            lines.append(
                f"{i}. {title}\n"
                f"   Precio: {_fmt_price(price, currency)} | Estado: {condition}\n"
                f"   {permalink}"
            )

        return ToolResult(
            ok=True,
            output="\n".join(lines) + f"\n\nFuente: MercadoLibre API ({site})",
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al buscar en MercadoLibre: {e}")
    except Exception as e:
        log.exception("ml_search uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. ml_product_detail — Detalle de producto
# ──────────────────────────────────────────────

def ml_product_detail_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene todos los detalles de un producto de MercadoLibre por su ID. Incluye atributos, condicion y vendedor."""
    try:
        item_id = str(arguments.get("item_id") or "").strip()
        if not item_id:
            return ToolResult(ok=False, output="", error="Falta item_id del producto.")

        # Limpiar prefijo MLV/MLA/etc. si viene en la URL
        item_id = item_id.split("/")[-1]

        _rate_limit("ml_product_detail")
        url = f"https://api.mercadolibre.com/items/{item_id}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Producto con ID '{item_id}' no encontrado en MercadoLibre.",
                )
            resp.raise_for_status()
            data = resp.json()

        title = data.get("title", "Sin titulo")
        price = data.get("price", 0)
        currency = data.get("currency_id", "VES")
        condition = data.get("condition", "?")
        available = "Disponible" if data.get("available_quantity", 0) > 0 else "Agotado"
        sold = data.get("sold_quantity", 0)
        seller_id = data.get("seller_id", "?")
        permalink = data.get("permalink", "")
        warranty = data.get("warranty", "No especificada")
        pictures_count = len(data.get("pictures", []))

        # Atributos
        attributes = data.get("attributes", [])
        attrs_lines = ""
        if attributes:
            attrs_lines = "\nAtributos:\n"
            for attr in attributes[:8]:
                name = attr.get("name", "?")
                value = attr.get("value_name", attr.get("value", "?"))
                attrs_lines += f"  • {name}: {value}\n"

        return ToolResult(
            ok=True,
            output=(
                f"📦 {title}\n"
                f"Precio: {_fmt_price(price, currency)}\n"
                f"Estado: {condition} | Disponibilidad: {available} ({sold} vendidos)\n"
                f"Garantia: {warranty}\n"
                f"Fotos: {pictures_count}\n"
                f"Vendedor ID: {seller_id}\n"
                f"Link: {permalink}"
                f"{attrs_lines}\n"
                f"Fuente: MercadoLibre API"
            ),
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al consultar producto: {e}")
    except Exception as e:
        log.exception("ml_product_detail uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  3. ml_my_products — Listar productos del vendedor
# ──────────────────────────────────────────────

def ml_my_products_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los productos publicados por el vendedor autenticado. Requiere MERCADOLIBRE_ACCESS_TOKEN."""
    try:
        err_token = _check_token()
        if err_token:
            return ToolResult(ok=False, output="", error=err_token)

        token = _env("MERCADOLIBRE_ACCESS_TOKEN")
        limit = min(int(arguments.get("limit") or 10), 50)

        _rate_limit("ml_my_products")
        url = "https://api.mercadolibre.com/users/me/items/search"
        params: dict[str, str | int] = {
            "access_token": token,
            "limit": limit,
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="Token de MercadoLibre invalido o expirado. Solicita al usuario que reconfigure MERCADOLIBRE_ACCESS_TOKEN en Ajustes.",
                )
            if resp.status_code == 403:
                return ToolResult(
                    ok=False, output="",
                    error="Permisos insuficientes. El token necesita scope 'read' sobre tus publicaciones. Revisa en developers.mercadolibre.com.",
                )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return ToolResult(
                ok=True,
                output="🛒 No tienes productos publicados en MercadoLibre.",
            )

        # Obtener detalles de cada item
        items_output: list[str] = []
        with httpx.Client(timeout=20) as client:
            for i, item_id in enumerate(results[:limit], 1):
                try:
                    time.sleep(0.1)  # Gentil con la API
                    detail_resp = client.get(f"https://api.mercadolibre.com/items/{item_id}")
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        title = detail.get("title", "?")[:100]
                        price = detail.get("price", 0)
                        currency = detail.get("currency_id", "VES")
                        available = detail.get("available_quantity", 0)
                        status = detail.get("status", "?")
                        items_output.append(
                            f"{i}. {title}\n"
                            f"   ID: {item_id} | {_fmt_price(price, currency)} | Stock: {available} | Estado: {status}"
                        )
                except Exception as e:
                    items_output.append(f"{i}. ID: {item_id} (error al obtener detalle: {e})")

        return ToolResult(
            ok=True,
            output=(
                f"🛒 Tus productos en MercadoLibre ({len(results)} publicaciones):\n\n"
                + "\n".join(items_output)
                + "\n\nFuente: MercadoLibre API"
            ),
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al consultar MercadoLibre: {e}")
    except Exception as e:
        log.exception("ml_my_products uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  4. ml_price_comparison — Comparar precios
# ──────────────────────────────────────────────

def ml_price_comparison_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca un producto en MercadoLibre y compara sus precios: minimo, maximo, promedio y mediana."""
    try:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query del producto a comparar.")

        site = str(arguments.get("site") or "MLV").strip().upper()
        limit = min(int(arguments.get("limit") or 50), 50)

        _rate_limit("ml_price_comparison")
        url = f"https://api.mercadolibre.com/sites/{site}/search"
        params: dict[str, str | int] = {
            "q": query,
            "limit": limit,
            "sort": "price_asc",  # Ordenar por precio para obtener min/max
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return ToolResult(
                ok=True,
                output=f"📊 No se encontraron productos para '{query}' en {site}. No hay precios que comparar.",
            )

        # Extraer precios
        prices: list[float] = []
        samples: list[dict[str, Any]] = []
        currency = "VES"

        for item in results[:limit]:
            price = item.get("price", 0)
            if price > 0:
                currency = item.get("currency_id", "VES")
                prices.append(price)
                samples.append({
                    "title": (item.get("title") or "?")[:80],
                    "price": price,
                    "permalink": item.get("permalink", ""),
                    "condition": item.get("condition", "?"),
                })

        if not prices:
            return ToolResult(
                ok=True,
                output=f"📊 No se encontraron precios validos para '{query}' en {site}.",
            )

        price_min = min(prices)
        price_max = max(prices)
        price_avg = statistics.mean(prices)
        price_median = statistics.median(prices)
        count = len(prices)

        # Armar salida
        lines = [
            f"📊 Comparacion de precios — '{query}' en {site}",
            "",
            f"📈 Resumen ({count} productos):",
            f"  Precio minimo:    {_fmt_price(price_min, currency)}",
            f"  Precio maximo:    {_fmt_price(price_max, currency)}",
            f"  Precio promedio:  {_fmt_price(price_avg, currency)}",
            f"  Precio mediana:   {_fmt_price(price_median, currency)}",
            "",
            "📋 Muestras:",
        ]

        # Mostrar 3 mas baratos, 3 mas caros
        sorted_samples = sorted(samples, key=lambda x: x["price"])
        lines.append("  -- Mas baratos --")
        for s in sorted_samples[:3]:
            lines.append(f"  • {s['title'][:60]}")
            lines.append(f"    {_fmt_price(s['price'], currency)} | {s['condition']} | {s['permalink']}")

        if len(sorted_samples) > 3:
            lines.append("  -- Mas caros --")
            for s in sorted_samples[-3:]:
                lines.append(f"  • {s['title'][:60]}")
                lines.append(f"    {_fmt_price(s['price'], currency)} | {s['condition']} | {s['permalink']}")

        lines.append(f"\nFuente: MercadoLibre API ({site})")

        return ToolResult(ok=True, output="\n".join(lines))

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al comparar precios: {e}")
    except Exception as e:
        log.exception("ml_price_comparison uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  5. ml_seller_reputation — Reputacion de vendedor
# ──────────────────────────────────────────────

def ml_seller_reputation_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene la reputacion de un vendedor de MercadoLibre: nivel, transacciones, tasa de cancelacion."""
    try:
        seller_id = str(arguments.get("seller_id") or "").strip()
        if not seller_id:
            return ToolResult(ok=False, output="", error="Falta seller_id del vendedor.")

        _rate_limit("ml_seller_reputation")
        url = f"https://api.mercadolibre.com/users/{seller_id}"

        with httpx.Client(timeout=15) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Vendedor con ID '{seller_id}' no encontrado en MercadoLibre.",
                )
            resp.raise_for_status()
            data = resp.json()

        nickname = data.get("nickname", "?")
        seller_reputation = data.get("seller_reputation", {})
        level = seller_reputation.get("level_id", "Sin calificar")
        power_seller = seller_reputation.get("power_seller_status", "N/A")
        transactions = seller_reputation.get("transactions", {})
        total_tx = transactions.get("total", 0)
        completed = transactions.get("completed", 0)
        canceled = transactions.get("canceled", 0)

        # Calcular tasa de cancelacion
        canceled_rate = 0.0
        if completed + canceled > 0:
            canceled_rate = (canceled / (completed + canceled)) * 100

        # Metricas adicionales de reputacion
        metrics = seller_reputation.get("metrics", {})
        claims = metrics.get("claims", {}).get("rate", "N/A")
        sales = metrics.get("sales", {}).get("period", "N/A")
        delayed = metrics.get("delayed_handling_time", {}).get("rate", "N/A")

        # Nivel traducido
        level_names = {
            "5_green": "🏆 MercadoLíder Platinum",
            "4_green": "⭐ MercadoLíder Gold",
            "3_yellow": "✅ MercadoLíder",
            "2_orange": "⚠️ Vendedor regular",
            "1_red": "🔴 Baja reputacion",
        }
        level_display = level_names.get(level, level)

        return ToolResult(
            ok=True,
            output=(
                f"👤 Reputacion — {nickname} (ID: {seller_id})\n\n"
                f"Nivel: {level_display}\n"
                f"Power Seller: {power_seller}\n\n"
                f"📊 Transacciones:\n"
                f"  Total: {total_tx}\n"
                f"  Completadas: {completed}\n"
                f"  Canceladas: {canceled} ({canceled_rate:.1f}%)\n\n"
                f"📈 Metricas:\n"
                f"  Reclamos: {claims}\n"
                f"  Ventas en periodo: {sales}\n"
                f"  Entregas con demora: {delayed}\n\n"
                f"Fuente: MercadoLibre API"
            ),
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al consultar reputacion: {e}")
    except Exception as e:
        log.exception("ml_seller_reputation uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("ml_search", ml_search_handler),
    ("ml_product_detail", ml_product_detail_handler),
    ("ml_my_products", ml_my_products_handler),
    ("ml_price_comparison", ml_price_comparison_handler),
    ("ml_seller_reputation", ml_seller_reputation_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parametros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "ml_search": {
        "description": "Busca productos en MercadoLibre por palabra clave. Retorna titulo, precio, thumbnail y enlace de compra.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Palabra clave del producto a buscar (ej: 'zapatos', 'laptop', 'iphone')",
                },
                "site": {
                    "type": "string",
                    "description": "Codigo del sitio de MercadoLibre (default: 'MLV' Venezuela). MLV=Venezuela, MLA=Argentina, MCO=Colombia, MLM=Mexico. Mas: https://api.mercadolibre.com/sites",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de resultados (default 10, max 50)",
                },
            },
            "required": ["query"],
        },
        "category": "shopping",
        "capability": "B",
    },
    "ml_product_detail": {
        "description": "Obtiene los detalles completos de un producto de MercadoLibre: precio, condicion, stock, atributos y vendedor.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "ID del producto en MercadoLibre (ej: 'MLV1234567890'). Se obtiene del resultado de ml_search o de la URL del producto.",
                },
            },
            "required": ["item_id"],
        },
        "category": "shopping",
        "capability": "B",
    },
    "ml_my_products": {
        "description": "Lista tus productos publicados en MercadoLibre. Requiere MERCADOLIBRE_ACCESS_TOKEN configurado en Ajustes.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de productos a listar (default 10, max 50)",
                },
            },
        },
        "category": "shopping",
        "capability": "B",
    },
    "ml_price_comparison": {
        "description": "Compara precios de un producto en MercadoLibre: minimo, maximo, promedio y mediana. Util para investigacion de mercado.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Producto a comparar precios (ej: 'TV Samsung 50 pulgadas')",
                },
                "site": {
                    "type": "string",
                    "description": "Codigo del sitio (default: 'MLV'). MLV=Venezuela, MLA=Argentina, MCO=Colombia, etc.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de productos a analizar (default 50, max 50)",
                },
            },
            "required": ["query"],
        },
        "category": "shopping",
        "capability": "B",
    },
    "ml_seller_reputation": {
        "description": "Muestra la reputacion de un vendedor de MercadoLibre: nivel, transacciones completadas, tasa de cancelacion y metricas.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "seller_id": {
                    "type": "string",
                    "description": "ID del vendedor en MercadoLibre. Se obtiene del campo seller_id en ml_product_detail.",
                },
            },
            "required": ["seller_id"],
        },
        "category": "shopping",
        "capability": "B",
    },
}
