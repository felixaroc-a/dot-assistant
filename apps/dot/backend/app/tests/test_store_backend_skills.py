"""Tests Tienda DOT — skills con claves del servidor."""
from __future__ import annotations

from app import settings as app_settings
from app.application.store.curated_skills import CURATED_STORE_SKILLS, get_curated_skill
from app.routers.store import _skill_ready_to_use


def test_curated_weather_and_news_skills_backend_provisioned():
    weather = get_curated_skill("skill_clima_diario")
    news = get_curated_skill("skill_noticias_diarias")
    assert weather is not None
    assert news is not None
    assert weather.get("backend_provisioned") is True
    assert news.get("backend_provisioned") is True
    assert weather.get("requires_user_api_key") is False
    assert news.get("requires_user_api_key") is False


def test_no_curated_skill_requires_user_api_key():
    for skill in CURATED_STORE_SKILLS:
        assert not skill.get("requires_user_api_key"), skill["id"]


def test_news_skill_ready_without_newsapi_key(monkeypatch):
    monkeypatch.setattr(app_settings.settings, "openweather_api_key", "", raising=False)
    monkeypatch.setattr(app_settings.settings, "newsapi_key", "", raising=False)
    news = get_curated_skill("skill_noticias_diarias")
    assert _skill_ready_to_use(news or {}) is True


def test_weather_skill_not_ready_without_openweather_key(monkeypatch):
    monkeypatch.setattr(app_settings.settings, "openweather_api_key", "", raising=False)
    weather = get_curated_skill("skill_clima_diario")
    assert _skill_ready_to_use(weather or {}) is False

    monkeypatch.setattr(app_settings.settings, "openweather_api_key", "test-key", raising=False)
    assert _skill_ready_to_use(weather or {}) is True
