"""Fail-closed: scrapers factuales VE no deben caer en route_chat."""

from unittest.mock import patch

from app.application.agent.tools.monitor_tools import (
    get_dollar_rate_handler,
    monitor_dollar_rate_handler,
    monitor_news_keyword_handler,
    monitor_job_opening_handler,
)


def test_get_dollar_rate_fail_closed_when_scraper_empty():
    with patch(
        "app.application.agent.tools.monitor_tools._fetch_dollar_rates",
        return_value=({}, "?"),
    ):
        result = get_dollar_rate_handler("uid-test", {})
    assert result.ok is False
    assert "No pude obtener la tasa ahora" in (result.error or "")


def test_monitor_dollar_rate_fail_closed_when_scraper_empty():
    with patch(
        "app.application.agent.tools.monitor_tools._fetch_dollar_rates",
        return_value=({}, "?"),
    ):
        result = monitor_dollar_rate_handler("uid-test", {})
    assert result.ok is False
    assert "No pude obtener la tasa ahora" in (result.error or "")


def test_monitor_news_fail_closed_on_scraper_error():
    with patch("worker.scraper.scrape_news", return_value=None):
        result = monitor_news_keyword_handler("uid-test", {"keyword": "venezuela"})
    assert result.ok is False
    assert "No pude obtener noticias ahora" in (result.error or "")


def test_monitor_jobs_fail_closed_on_scraper_error():
    with patch("worker.scraper.scrape_jobs", return_value=None):
        result = monitor_job_opening_handler("uid-test", {"query": "contador"})
    assert result.ok is False
    assert "No pude consultar ofertas de empleo ahora" in (result.error or "")
