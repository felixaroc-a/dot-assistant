"""Tests for BR02-BR06 deep improvements: retry, session management, error handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.agent.tools.browser_tools import (
    BrowserErrorCode,
    _BrowserErrorInfo,
    _BRIDGE_RETRY_BACKOFF_BASE,
    _BRIDGE_RETRY_MAX,
    _bridge_browser_with_retry,
    _browser_sessions,
    _classify_browser_error,
    _cleanup_expired_sessions,
    _generate_selectors,
    _is_retryable_error,
    _remove_session,
    _suggest_recovery,
    _track_session,
    browser_close_all_handler,
    browser_compare_screenshots_handler,
    browser_fill_form_advanced_handler,
    browser_list_sessions_handler,
    browser_screenshot_element_handler,
)


# ============================================================================
# BR02 — Retry logic
# ============================================================================


class TestIsRetryableError:
    def test_connect_error_is_retryable(self):
        assert _is_retryable_error(httpx.ConnectError("refused")) is True

    def test_timeout_is_retryable(self):
        assert _is_retryable_error(httpx.TimeoutException("timeout")) is True

    def test_5xx_status_is_retryable(self):
        assert _is_retryable_error(ValueError("unrelated"), status_code=500) is True
        assert _is_retryable_error(ValueError("unrelated"), status_code=502) is True

    def test_4xx_status_is_not_retryable(self):
        assert _is_retryable_error(ValueError("unrelated"), status_code=404) is False

    def test_generic_error_not_retryable(self):
        assert _is_retryable_error(ValueError("something")) is False


class TestBridgeBrowserWithRetry:
    def test_success_first_attempt(self):
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            return_value={"ok": True, "url": "https://x.com", "title": "X"},
        ):
            result = _bridge_browser_with_retry("browserNavigate", url="https://x.com")
        assert result["ok"] is True
        assert result["url"] == "https://x.com"

    def test_retry_on_connect_error_then_succeed(self):
        side_effects = [
            httpx.ConnectError("refused"),
            {"ok": True, "url": "https://x.com", "title": "X"},
        ]
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ), patch("app.application.agent.tools.browser_tools.time.sleep", return_value=None):
            result = _bridge_browser_with_retry("browserNavigate", url="https://x.com")
        assert result["ok"] is True

    def test_retry_on_timeout_then_succeed(self):
        side_effects = [
            httpx.TimeoutException("timeout"),
            {"ok": True, "url": "https://x.com", "title": "X"},
        ]
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ), patch("app.application.agent.tools.browser_tools.time.sleep", return_value=None):
            result = _bridge_browser_with_retry("browserNavigate", url="https://x.com")
        assert result["ok"] is True

    def test_exhaust_retries_on_connect_error(self):
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=httpx.ConnectError("refused"),
        ), patch("app.application.agent.tools.browser_tools.time.sleep", return_value=None):
            result = _bridge_browser_with_retry(
                "browserNavigate", url="https://x.com", max_retries=2, backoff_base=0.01,
            )
        assert result["ok"] is False
        assert "bridge_unreachable_after" in result.get("error", "")

    def test_exhaust_retries_on_5xx(self):
        side_effects = [
            {"ok": False, "error": "500_server_error"},
            {"ok": False, "error": "502_bad_gateway"},
            {"ok": False, "error": "503_service_unavailable"},
        ]
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ), patch("app.application.agent.tools.browser_tools.time.sleep", return_value=None):
            result = _bridge_browser_with_retry(
                "browserNavigate", url="https://x.com", max_retries=2, backoff_base=0.01,
            )
        assert result["ok"] is False
        assert "503" in result.get("error", "")

    def test_no_retry_on_4xx(self):
        """4xx errors should NOT trigger retry."""
        call_count = [0]

        def bridge_side_effect(*args, **kwargs):
            call_count[0] += 1
            return {"ok": False, "error": "bridge_unauthorized"}

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=bridge_side_effect,
        ):
            result = _bridge_browser_with_retry("browserNavigate", url="https://x.com", max_retries=3)
        assert result["ok"] is False
        assert call_count[0] == 1  # solo 1 intento, sin reintentos

    def test_backoff_increases(self):
        """Verifica que el backoff crece exponencialmente."""
        sleep_times: list[float] = []

        side_effects = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            {"ok": True, "url": "https://x.com", "title": "X"},
        ]

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ), patch("app.application.agent.tools.browser_tools.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda s: sleep_times.append(s)
            _bridge_browser_with_retry(
                "browserNavigate", url="https://x.com", max_retries=2, backoff_base=1,
            )

        # primer sleep: backoff_base * 2^0 = 1, segundo: backoff_base * 2^1 = 2
        assert len(sleep_times) == 2
        assert sleep_times[0] == pytest.approx(1.0)
        assert sleep_times[1] == pytest.approx(2.0)


# ============================================================================
# BR03 — Session management
# ============================================================================


class TestSessionTracking:
    def setup_method(self):
        _browser_sessions.clear()

    def test_track_new_session(self):
        _track_session("user1", url="https://example.com")
        assert "user1" in _browser_sessions
        assert _browser_sessions["user1"].url == "https://example.com"

    def test_track_updates_existing_session(self):
        _track_session("user1", url="https://example.com")
        first_last_used = _browser_sessions["user1"].last_used
        time.sleep(0.01)
        _track_session("user1", url="https://new.com")
        assert _browser_sessions["user1"].url == "https://new.com"
        assert _browser_sessions["user1"].last_used > first_last_used

    def test_track_preserves_url_if_empty(self):
        _track_session("user1", url="https://original.com")
        _track_session("user1", url="")
        assert _browser_sessions["user1"].url == "https://original.com"

    def test_remove_session_exists(self):
        _track_session("user1", url="https://example.com")
        assert _remove_session("user1") is True
        assert "user1" not in _browser_sessions

    def test_remove_session_not_exists(self):
        assert _remove_session("nonexistent") is False

    def test_cleanup_expired_sessions(self):
        # Insertar directamente en el dict sin pasar por _track_session (que ya limpia)
        from app.application.agent.tools.browser_tools import _SessionInfo
        _browser_sessions["old_user"] = _SessionInfo(uid="old_user", url="https://old.com")
        _browser_sessions["old_user"].last_used = time.time() - 3600  # 1 hora atrás
        _browser_sessions["fresh_user"] = _SessionInfo(uid="fresh_user", url="https://fresh.com")
        removed = _cleanup_expired_sessions()
        assert removed >= 1
        assert "old_user" not in _browser_sessions
        assert "fresh_user" in _browser_sessions

    def test_cleanup_keeps_recent_sessions(self):
        _track_session("recent", url="https://recent.com")
        removed = _cleanup_expired_sessions()
        assert removed == 0
        assert "recent" in _browser_sessions


class TestListSessionsHandler:
    def setup_method(self):
        _browser_sessions.clear()

    def test_no_sessions(self):
        result = browser_list_sessions_handler("user1", {})
        assert result.ok
        assert "No hay sesiones activas" in result.output

    def test_lists_own_sessions(self):
        _track_session("user1", url="https://a.com")
        _track_session("user1_sub", url="https://b.com")
        _track_session("user2", url="https://c.com")
        result = browser_list_sessions_handler("user1", {})
        assert result.ok
        assert "user1" in result.output
        assert "user1_sub" in result.output
        assert "user2" not in result.output

    def test_excludes_expired_sessions(self):
        _track_session("user1", url="https://old.com")
        _browser_sessions["user1"].last_used = time.time() - 3600
        result = browser_list_sessions_handler("user1", {})
        assert result.ok
        assert "No hay sesiones" in result.output


class TestCloseAllHandler:
    def setup_method(self):
        _browser_sessions.clear()

    def test_no_sessions_to_close(self):
        result = browser_close_all_handler("user1", {})
        assert result.ok
        assert "No hay sesiones activas" in result.output

    def test_closes_all_sessions(self):
        _track_session("user1", url="https://a.com")
        _track_session("user1_sesion2", url="https://b.com")
        _track_session("user2", url="https://c.com")

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            return_value={"ok": True},
        ):
            result = browser_close_all_handler("user1", {})
        assert result.ok
        assert "Todas las sesiones cerradas" in result.output
        assert "user1" not in _browser_sessions
        assert "user1_sesion2" not in _browser_sessions
        assert "user2" in _browser_sessions  # no se cierra sesión de otro user

    def test_reports_partial_failures(self):
        _track_session("user1", url="https://a.com")
        _track_session("user1_b", url="https://b.com")

        side_effects = [
            {"ok": True},
            {"ok": False, "error": "close_session_failed"},
        ]
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ):
            result = browser_close_all_handler("user1", {})
        assert not result.ok
        assert "Cerradas 1/2" in (result.error or "")


# ============================================================================
# BR04 — Form autofill advanced
# ============================================================================


class TestGenerateSelectors:
    def test_text_selectors(self):
        selectors = _generate_selectors("nombre", "text")
        assert any('nombre' in s for s in selectors)
        assert len(selectors) > 0

    def test_email_selectors(self):
        selectors = _generate_selectors("correo", "email")
        assert any('email' in s for s in selectors)

    def test_password_selectors(self):
        selectors = _generate_selectors("clave", "password")
        assert any('password' in s.lower() for s in selectors)

    def test_select_type_selectors(self):
        selectors = _generate_selectors("pais", "select")
        assert any('select' in s for s in selectors)

    def test_checkbox_selectors(self):
        selectors = _generate_selectors("terms", "checkbox")
        assert any('checkbox' in s for s in selectors)
        # checkbox no debe tener fallback aria-label
        assert not any('aria-label' in s for s in selectors)

    def test_unknown_type_falls_back_to_text(self):
        selectors = _generate_selectors("campo", "unknown_type")
        assert len(selectors) > 0


class TestFillFormAdvancedHandler:
    def test_missing_field_schema(self):
        result = browser_fill_form_advanced_handler("u", {"field_values": {"a": "b"}})
        assert not result.ok
        assert "field_schema" in (result.error or "")

    def test_missing_field_values(self):
        result = browser_fill_form_advanced_handler(
            "u", {"field_schema": {"name": "text"}}
        )
        assert not result.ok
        assert "field_values" in (result.error or "")

    def test_fills_all_fields(self):
        schema = {"name": "text", "email_addr": "email"}
        values = {"name": "Juan", "email_addr": "juan@mail.com"}

        def fake_bridge(operation, **fields):
            if operation == "browserFillFormAdvanced":
                return {
                    "ok": True,
                    "selector_used": fields.get("selectors", ["N/A"])[0],
                }
            return {"ok": True}

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=fake_bridge,
        ):
            result = browser_fill_form_advanced_handler(
                "u", {"field_schema": schema, "field_values": values}
            )
        assert result.ok
        assert "2/2" in result.output

    def test_reports_failures(self):
        schema = {"name": "text", "email": "email"}
        values = {"name": "Juan", "email": "juan@mail.com"}

        side_effects = [
            {"ok": True, "selector_used": "#name"},
            {"ok": False, "error": "selector_no_encontrado"},
        ]

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ):
            result = browser_fill_form_advanced_handler(
                "u", {"field_schema": schema, "field_values": values}
            )
        assert not result.ok
        assert "1/2" in result.output
        assert "Fallidos" in result.output

    def test_submit_selector(self):
        schema = {"name": "text"}
        values = {"name": "Juan"}

        side_effects = [
            {"ok": True, "selector_used": "#name"},
            {"ok": True},  # click submit
        ]

        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            side_effect=side_effects,
        ):
            result = browser_fill_form_advanced_handler(
                "u",
                {
                    "field_schema": schema,
                    "field_values": values,
                    "submit_selector": "#submit-btn",
                },
            )
        assert result.ok
        assert "Formulario enviado" in result.output


# ============================================================================
# BR05 — Screenshot enhancement
# ============================================================================


class TestScreenshotElementHandler:
    def test_missing_selector(self):
        result = browser_screenshot_element_handler("u", {})
        assert not result.ok
        assert "selector" in (result.error or "").lower()

    def test_successful_screenshot(self):
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            return_value={
                "ok": True,
                "screenshot_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk",
                "width": 300,
                "height": 200,
                "url": "https://example.com",
            },
        ):
            result = browser_screenshot_element_handler("u", {"selector": "#main"})
        assert result.ok
        assert "#main" in result.output
        assert "300x200" in result.output

    def test_screenshot_element_failed(self):
        with patch(
            "app.application.agent.tools.browser_tools._bridge_browser",
            return_value={"ok": False, "error": "elemento_no_encontrado"},
        ):
            result = browser_screenshot_element_handler("u", {"selector": "#missing"})
        assert not result.ok
        assert "Sugerencia:" in (result.error or "")


class TestCompareScreenshotsHandler:
    def test_missing_selectors(self):
        result = browser_compare_screenshots_handler("u", {})
        assert not result.ok
        assert "baseline_selector" in (result.error or "")

    def test_placeholder_response(self):
        result = browser_compare_screenshots_handler(
            "u", {"baseline_selector": "#old", "current_selector": "#new"}
        )
        assert result.ok
        assert "no implementada" in result.output.lower()
        assert "#old" in result.output
        assert "#new" in result.output


# ============================================================================
# BR06 — Error handling
# ============================================================================


class TestBrowserErrorCode:
    def test_enum_values_distinct(self):
        """All error codes should be unique."""
        values = [e.value for e in BrowserErrorCode]
        assert len(values) == len(set(values))

    def test_unknown_is_zero(self):
        assert BrowserErrorCode.UNKNOWN.value == 0

    def test_ranges(self):
        """Verify error code ranges for different categories."""
        # Bridge connectivity errors: 1xxx
        assert 1000 < BrowserErrorCode.BRIDGE_UNREACHABLE.value < 2000
        # Timeout/navigation errors: 2xxx
        assert 2000 < BrowserErrorCode.TIMEOUT.value < 3000
        # Selector/interaction errors: 3xxx
        assert 3000 < BrowserErrorCode.SELECTOR_NOT_FOUND.value < 4000
        # Session errors: 4xxx
        assert 4000 < BrowserErrorCode.SESSION_FAILED.value < 5000
        # Generic errors: 5xxx
        assert 5000 < BrowserErrorCode.INVALID_RESPONSE.value < 6000


class TestClassifyBrowserError:
    def test_classify_bridge_unreachable(self):
        info = _classify_browser_error("bridge_unreachable")
        assert info.code == BrowserErrorCode.BRIDGE_UNREACHABLE
        assert "Electron" in info.suggestion

    def test_classify_timeout(self):
        info = _classify_browser_error("wait_timeout")
        assert info.code == BrowserErrorCode.TIMEOUT
        assert "tiempo" in info.suggestion.lower()

    def test_classify_selector_not_found(self):
        info = _classify_browser_error("selector_not_found_in_page")
        assert info.code == BrowserErrorCode.SELECTOR_NOT_FOUND
        assert "browser_extract" in info.suggestion

    def test_classify_click_failed(self):
        info = _classify_browser_error("click_failed: element not visible")
        assert info.code == BrowserErrorCode.CLICK_FAILED

    def test_classify_session_error(self):
        info = _classify_browser_error("close_session_failed: no such session")
        assert info.code == BrowserErrorCode.SESSION_CLOSE_FAILED

    def test_classify_unknown(self):
        info = _classify_browser_error("something_completely_unexpected_xyz")
        assert info.code == BrowserErrorCode.UNKNOWN
        assert info.suggestion != ""

    def test_classify_bridge_disabled(self):
        info = _classify_browser_error("browser_agent_deshabilitado")
        assert info.code == BrowserErrorCode.BRIDGE_DISABLED


class TestSuggestRecovery:
    def test_all_codes_have_suggestions(self):
        """Every error code should have a non-empty recovery suggestion."""
        for code in BrowserErrorCode:
            suggestion = _suggest_recovery(code)
            assert isinstance(suggestion, str)
            assert len(suggestion) > 0, f"Missing suggestion for {code.name}"

    def test_unknown_has_suggestion(self):
        suggestion = _suggest_recovery(BrowserErrorCode.UNKNOWN)
        assert "logs" in suggestion.lower() or "desconocido" in suggestion.lower()

    def test_recovery_not_empty(self):
        for code in [
            BrowserErrorCode.BRIDGE_UNREACHABLE,
            BrowserErrorCode.NAVIGATION_FAILED,
            BrowserErrorCode.SCREENSHOT_FAILED,
            BrowserErrorCode.SESSION_FAILED,
        ]:
            suggestion = _suggest_recovery(code)
            assert len(suggestion) > 10, f"Recovery too short for {code.name}: {suggestion}"


class TestBrowserErrorInfo:
    def test_dataclass_fields(self):
        info = _BrowserErrorInfo(
            code=BrowserErrorCode.BRIDGE_UNREACHABLE,
            raw_error="connection refused",
            suggestion="Check Electron",
        )
        assert info.code == BrowserErrorCode.BRIDGE_UNREACHABLE
        assert info.raw_error == "connection refused"
        assert "Electron" in info.suggestion


class TestErrIntegration:
    """Test that _err helper integrates error classification properly."""

    def test_err_appends_suggestion_for_known_error(self):
        from app.application.agent.tools.browser_tools import _err
        raw = {"error": "bridge_unreachable"}
        result = _err(raw, "fallback_error")
        assert not result.ok
        assert "Sugerencia:" in (result.error or "")

    def test_err_appends_suggestion_for_fallback(self):
        from app.application.agent.tools.browser_tools import _err
        raw = {"error": "navigate_failed", "message": "DNS error"}
        result = _err(raw, "fallback")
        assert not result.ok
        assert "Sugerencia:" in (result.error or "")

    def test_err_unknown_error_still_has_suggestion(self):
        from app.application.agent.tools.browser_tools import _err
        raw = {}
        result = _err(raw, "custom_fallback_error")
        assert not result.ok
        assert "Sugerencia:" in (result.error or "")
