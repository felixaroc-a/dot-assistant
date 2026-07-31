"""Tasa del dólar paralelo — scraping gratuito, sin API key."""
from __future__ import annotations

from typing import Any


def fetch_dollar_rate() -> dict[str, Any]:
    from worker.scraper import scrape_dollar_rate

    data = scrape_dollar_rate()
    rates = data.get("rates") or {}
    source = data.get("source") or "Monitor"
    if not rates:
        return {"source": source, "rates": {}, "summary": "No disponible"}
    parts = [f"{name}: {value:.2f} VES/USD" for name, value in rates.items()]
    summary = f"{source} — " + ", ".join(parts)
    return {"source": source, "rates": rates, "summary": summary}

