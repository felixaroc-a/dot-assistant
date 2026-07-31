"""Noticias vía NewsAPI (servidor) con fallback RSS — sin clave del usuario."""
from __future__ import annotations

import logging

from app.application.agent.tools.real_apis import monitor_news_keyword_handler
from app.firebase_db import get_user_profile

log = logging.getLogger("dot.skills.news")

_DEFAULT_KEYWORD = "Venezuela"


def _resolve_news_keyword(uid: str) -> str:
    profile = get_user_profile(uid) or {}
    for key in ("news_keyword", "news_interest", "news_topic"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    return _DEFAULT_KEYWORD


def get_news_summary(uid: str, keyword: str | None = None, limit: int = 5) -> str:
    """Resumen breve de noticias para el briefing diario."""
    resolved = (keyword or "").strip() or _resolve_news_keyword(uid)
    result = monitor_news_keyword_handler(
        uid,
        {"keyword": resolved, "limit": min(max(limit, 1), 10)},
    )
    if result.ok:
        return result.output
    log.warning("Noticias no disponibles uid=%s keyword=%s", uid[:8], resolved)
    return result.error or "Noticias no disponibles en este momento."

