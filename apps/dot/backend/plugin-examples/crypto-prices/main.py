"""Crypto Prices Plugin — precios de criptomonedas vía CoinGecko API gratuita.

Demuestra:
  - Herramienta con llamada HTTP externa
  - Manejo de errores de red
  - Múltiples parámetros con defaults
  - Formateo de respuesta rico
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.plugin_sdk import plugin_tool

# Símbolos comunes y sus IDs en CoinGecko
_COIN_IDS: dict[str, str] = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "tether": "tether",
    "usdt": "tether",
    "bnb": "binancecoin",
    "binance": "binancecoin",
    "solana": "solana",
    "sol": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "usdc": "usd-coin",
    "cardano": "cardano",
    "ada": "cardano",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "polkadot": "polkadot",
    "dot": "polkadot",
    "matic": "matic-network",
    "polygon": "matic-network",
    "dai": "dai",
    "litecoin": "litecoin",
    "ltc": "litecoin",
    "chainlink": "chainlink",
    "link": "chainlink",
    "uniswap": "uniswap",
    "uni": "uniswap",
    "avalanche": "avalanche-2",
    "avax": "avalanche-2",
}


def _resolve_coin_id(query: str) -> str | None:
    """Resuelve nombre/símbolo → coin_id de CoinGecko."""
    q = query.lower().strip()
    # Coincidencia exacta
    if q in _COIN_IDS:
        return _COIN_IDS[q]
    # Búsqueda parcial
    for key, cid in _COIN_IDS.items():
        if q in key:
            return cid
    return None


def _fetch_crypto_prices(coin_ids: list[str], currency: str = "usd") -> dict[str, Any] | None:
    """Llama a CoinGecko simple/price API (gratis, sin API key)."""
    ids_param = ",".join(coin_ids)
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids_param}"
        f"&vs_currencies={currency}"
        f"&include_24hr_change=true"
        f"&include_market_cap=true"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception as e:
        return None


@plugin_tool(
    name="crypto_price",
    description=(
        "Consulta el precio actual de criptomonedas usando CoinGecko (API gratuita). "
        "Soporta Bitcoin, Ethereum, Solana, XRP, Cardano, Dogecoin, y 15+ más. "
        "Retorna precio USD, cambio 24h y capitalización de mercado."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "coin": {
                "type": "string",
                "description": (
                    "Nombre o símbolo de la criptomoneda. Ej: bitcoin, eth, sol, ada, doge. "
                    "Si no se especifica, retorna Bitcoin."
                ),
            },
            "currency": {
                "type": "string",
                "description": "Moneda fiat para el precio (usd, eur, ars, cop, etc.). Default: usd.",
            },
        },
    },
)
def crypto_price(uid: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handler de la tool crypto_price."""
    coin_query = arguments.get("coin", "bitcoin")
    currency = arguments.get("currency", "usd").lower()

    coin_id = _resolve_coin_id(coin_query)
    if coin_id is None:
        return {
            "ok": False,
            "output": "",
            "error": (
                f"Criptomoneda '{coin_query}' no reconocida. "
                f"Soportadas: {', '.join(sorted(_COIN_IDS.keys()))}"
            ),
            "artifacts": [],
        }

    data = _fetch_crypto_prices([coin_id], currency)
    if data is None or coin_id not in data:
        return {
            "ok": False,
            "output": "",
            "error": f"No se pudo obtener el precio de {coin_id}. Verifica tu conexión o intenta más tarde.",
            "artifacts": [],
        }

    coin_data = data[coin_id]
    price = coin_data.get(currency)
    change_24h = coin_data.get(f"{currency}_24h_change")
    market_cap = coin_data.get(f"{currency}_market_cap")

    if price is None:
        return {
            "ok": False,
            "output": "",
            "error": f"No se encontró precio en {currency.upper()} para {coin_id}.",
            "artifacts": [],
        }

    # Formatear salida
    name = coin_query.upper() if len(coin_query) <= 5 else coin_query.title()
    lines = [
        f"   {name} ({coin_id})",
        f"   Precio: {price:,.4f} {currency.upper()}",
    ]
    if change_24h is not None:
        direction = "  " if change_24h >= 0 else "  "
        lines.append(f"   24h: {direction}{change_24h:+.2f}%")
    if market_cap is not None:
        if market_cap >= 1_000_000_000:
            lines.append(f"   Market Cap: ${market_cap / 1_000_000_000:,.2f}B {currency.upper()}")
        elif market_cap >= 1_000_000:
            lines.append(f"   Market Cap: ${market_cap / 1_000_000:,.2f}M {currency.upper()}")
        else:
            lines.append(f"   Market Cap: ${market_cap:,.0f} {currency.upper()}")

    output = "\n".join(lines)
    return {
        "ok": True,
        "output": output,
        "error": None,
        "artifacts": [],
    }
