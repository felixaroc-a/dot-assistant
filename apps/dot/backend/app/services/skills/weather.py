"""Clima vía OpenWeatherMap — clave del servidor, nunca del usuario."""
from __future__ import annotations

import logging
import re

from app.application.agent.tools.real_apis import web_get_weather_handler
from app.firebase_db import get_user_profile
from app.services.memory_service import get_memory_facts

log = logging.getLogger("dot.skills.weather")

_DEFAULT_CITY = "Caracas"
_CITY_FACT_PATTERN = re.compile(
    r"(?:vivo\s+en|soy\s+de|mi\s+ciudad\s+es|ciudad\s*:)\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s\-]+)",
    re.I,
)


def _resolve_user_city(uid: str) -> str:
    profile = get_user_profile(uid) or {}
    for key in ("city", "user_city", "default_city"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value

    try:
        for fact in get_memory_facts(uid, limit=80):
            content = str(fact.get("content") or fact.get("fact") or "")
            match = _CITY_FACT_PATTERN.search(content)
            if match:
                city = match.group(1).strip().rstrip(".,;")
                if city:
                    return city
    except Exception as e:
        log.debug("No se pudo leer memoria para ciudad uid=%s: %s", uid[:8], e)

    return _DEFAULT_CITY


def get_weather_for_user_city(uid: str, city: str | None = None) -> str:
    """Resumen de clima para la ciudad del usuario (OpenWeather vía backend)."""
    resolved = (city or "").strip() or _resolve_user_city(uid)
    result = web_get_weather_handler(uid, {"city": resolved})
    if result.ok:
        return result.output
    return result.error or "Clima no disponible en este momento."

