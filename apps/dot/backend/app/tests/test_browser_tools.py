"""Tests browser tools potentes — BR02-BR06 incluidos."""
from __future__ import annotations

from unittest.mock import patch

from app.application.agent.tools import build_default_registry
from app.application.agent.tools.browser_tools import (
    browser_click_handler,
    browser_close_handler,
    browser_do_handler,
    browser_fill_handler,
    browser_get_price_handler,
    browser_navigate_handler,
    browser_open_handler,
    browser_pdf_handler,
    browser_screenshot_handler,
    browser_type_handler,
    browser_wait_handler,
)


def test_all_browser_tools_registered():
    names = {s.name for s in build_default_registry(include_web_search=False).list_specs()}
    for n in (
        "browser_navigate",
        "browser_extract",
        "browser_click",
        "browser_type",
        "browser_wait",
        "browser_get_price",
        "browser_screenshot",
        "browser_pdf",
        "browser_fill",
        "browser_open",
        "browser_do",
        "browser_close",
    ):
        assert n in names, f"{n} must be in registry"


def test_browser_navigate_disabled_stub():
    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ):
        r = browser_navigate_handler("u", {"url": "https://example.com"})
    assert not r.ok
    assert "Configuración" in (r.error or "")
    assert "Privacidad" in (r.error or "")


def test_browser_get_price_bridge():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "url": "https://example.com/p",
            "title": "Producto",
            "price": "$19.99",
            "money_in_page": ["$19.99"],
            "candidates": [],
        },
    ):
        r = browser_get_price_handler("u", {})
    assert r.ok
    assert "$19.99" in r.output


def test_browser_click_type_wait():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={"ok": True, "clicked": "Buy", "url": "https://x", "chars": 3, "waited_ms": 100},
    ):
        assert browser_click_handler("u", {"selector": "#btn"}).ok
        assert browser_type_handler("u", {"selector": "#q", "text": "hola"}).ok
        assert browser_wait_handler("u", {"text_contains": "hola"}).ok
        assert browser_navigate_handler("u", {"url": "https://example.com"}).ok


# ---------------------------------------------------------------------------
# BR02 — browser_screenshot
# ---------------------------------------------------------------------------

def test_browser_screenshot_disabled():
    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ):
        r = browser_screenshot_handler("u", {})
    assert not r.ok
    assert "Configuración" in (r.error or "")
    assert "Privacidad" in (r.error or "")


def test_browser_screenshot_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "screenshot_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk",
            "format": "png",
            "url": "https://example.com",
            "title": "Home",
            "saved_to": "C:/Users/test/Desktop/dot-captura-example-com-2026-07-24.png",
            "relative_path": "~/Desktop/dot-captura-example-com-2026-07-24.png",
            "size_bytes": 1024,
        },
    ):
        r = browser_screenshot_handler("u", {"full_page": True})
    assert r.ok
    assert "Escritorio" in r.output
    assert "dot-captura" in r.output
    assert "Home" in r.output


def test_browser_screenshot_passes_filepath():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={"ok": True, "saved_to": "C:/Users/test/Desktop/mi-captura.png"},
    ) as bridge:
        browser_screenshot_handler("u", {"filepath": "Escritorio/mi-captura.png"})
    bridge.assert_called_once()
    assert bridge.call_args.kwargs.get("filepath") == "Escritorio/mi-captura.png"


# ---------------------------------------------------------------------------
# BR02 — browser_pdf
# ---------------------------------------------------------------------------

def test_browser_pdf_disabled():
    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ):
        r = browser_pdf_handler("u", {})
    assert not r.ok
    assert "Configuración" in (r.error or "")
    assert "Privacidad" in (r.error or "")


def test_browser_pdf_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "url": "https://example.com",
            "title": "Example",
            "saved_to": "C:/Users/test/Desktop/dot-pdf-example-com-2026-07-24.pdf",
            "relative_path": "~/Desktop/dot-pdf-example-com-2026-07-24.pdf",
            "size_bytes": 2048,
        },
    ):
        r = browser_pdf_handler("u", {})
    assert r.ok
    assert "Escritorio" in r.output
    assert "dot-pdf" in r.output
    assert "Example" in r.output


def test_browser_pdf_navigates_when_url_given():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        side_effect=[
            {"ok": True, "url": "https://example.com", "title": "Example"},
            {
                "ok": True,
                "url": "https://example.com",
                "title": "Example",
                "saved_to": "C:/Users/test/Desktop/informe.pdf",
                "relative_path": "~/Desktop/informe.pdf",
            },
        ],
    ) as bridge:
        r = browser_pdf_handler("u", {"url": "https://example.com", "filepath": "informe.pdf"})
    assert r.ok
    assert bridge.call_count == 2
    assert bridge.call_args_list[0].args[0] == "browserNavigate"
    assert bridge.call_args_list[1].args[0] == "browserPdf"
    assert bridge.call_args_list[1].kwargs.get("filepath") == "informe.pdf"


# ---------------------------------------------------------------------------
# BR04 — browser_fill
# ---------------------------------------------------------------------------

def test_browser_fill_missing_args():
    r = browser_fill_handler("u", {})
    assert not r.ok
    assert "selector" in (r.error or "").lower()


def test_browser_fill_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "selector": "#email",
            "value": "a@b.com",
            "tag": "INPUT",
            "url": "https://example.com/form",
        },
    ):
        r = browser_fill_handler("u", {"selector": "#email", "value": "a@b.com"})
    assert r.ok
    assert "a@b.com" in r.output


# ---------------------------------------------------------------------------
# BR05 — session management (open / do / close)
# ---------------------------------------------------------------------------

def test_browser_open_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "url": "https://example.com",
            "host": "example.com",
            "title": "Home",
            "session_active": 1,
        },
    ):
        r = browser_open_handler("uid-1", {"url": "https://example.com"})
    assert r.ok
    assert "uid-1" in r.output
    assert "example.com" in r.output


def test_browser_open_missing_url():
    r = browser_open_handler("u", {})
    assert not r.ok
    assert "url" in (r.error or "").lower()


def test_browser_do_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "result": {"type": "string", "value": "42"},
            "uid": "uid-1",
            "url": "https://example.com",
        },
    ):
        r = browser_do_handler("uid-1", {"js_code": "return 42;"})
    assert r.ok
    assert "42" in r.output


def test_browser_do_missing_code():
    r = browser_do_handler("u", {})
    assert not r.ok
    assert "js_code" in (r.error or "").lower()


def test_browser_do_disabled():
    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ):
        r = browser_do_handler("u", {"js_code": "return 1;"})
    assert not r.ok
    assert "Configuración" in (r.error or "")
    assert "Privacidad" in (r.error or "")


# ---------------------------------------------------------------------------
# BR06 — browser_close structured extract
# ---------------------------------------------------------------------------

def test_browser_close_extract_ok():
    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "uid": "uid-1",
            "session_duration_ms": 2500,
            "extract": {
                "title": "Example Domain",
                "text_preview": "Example Domain. This domain is for use in illustrative examples...",
                "links_count": 5,
                "screenshot_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk",
            },
        },
    ):
        r = browser_close_handler("uid-1", {"uid": "uid-1"})
    assert r.ok
    assert "uid-1" in r.output
    assert "Example Domain" in r.output
    assert "5" in r.output
    assert "screenshot" in r.output.lower()


def test_browser_close_disabled():
    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ):
        r = browser_close_handler("u", {"uid": "u"})
    assert not r.ok
    assert "Configuración" in (r.error or "")
    assert "Privacidad" in (r.error or "")


def test_browser_bridge_user_policy_wins_over_global_off():
    """Política del usuario gana sobre BROWSER_AGENT_ENABLED=false."""
    from app.application.agent.browser_uid_context import browser_tool_uid_scope
    from app.application.agent.tools.browser_tools import _bridge_browser

    with patch(
        "app.application.agent.tools.browser_tools.settings.browser_agent_enabled",
        False,
    ), patch(
        "app.application.agent.tools.browser_tools.settings.testing",
        "1",
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=True,
    ), patch(
        "app.application.agent.tools.browser_tools.httpx.Client",
    ) as mock_client:
        mock_resp = mock_client.return_value.__enter__.return_value.post.return_value
        mock_resp.status_code = 200
        mock_resp.content = b'{"ok": true, "url": "https://example.com"}'
        mock_resp.json.return_value = {"ok": True, "url": "https://example.com"}

        with browser_tool_uid_scope("uid-policy-on"):
            raw = _bridge_browser("browserGetPageURL")

    assert raw.get("ok") is True
    mock_client.return_value.__enter__.return_value.post.assert_called_once()


def test_browser_extract_includes_title_from_bridge():
    from app.application.agent.tools.browser_tools import browser_extract_handler

    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        return_value={
            "ok": True,
            "url": "https://example.com",
            "title": "Example Domain",
            "text": "Body text",
            "chars": 9,
        },
    ):
        r = browser_extract_handler("u", {})
    assert r.ok
    assert "Example Domain" in r.output


def test_browser_tools_execute_via_bridge_when_local_tools_true():
    """browser_* no debe quedar como marcador local_tool sin ejecutar."""
    from dataclasses import dataclass

    from app.application.agent.runtime import run_agent

    @dataclass
    class _FakeAI:
        content: str

    bridge_calls: list[str] = []

    def fake_bridge(operation, **fields):
        bridge_calls.append(operation)
        if operation == "browserNavigate":
            return {"ok": True, "url": "https://example.com", "host": "example.com", "title": "Example"}
        if operation == "browserGetPrice":
            return {"ok": True, "url": "https://example.com", "price": "$9.99", "title": "Example"}
        return {"ok": False, "error": "unexpected"}

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"browser_navigate",'
                '"arguments":{"url":"https://example.com"}}]}'
            )
        ),
        _FakeAI(
            content='{"tool_calls":[{"name":"browser_get_price","arguments":{}}]}'
        ),
        _FakeAI(content="El precio es $9.99."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        out = turns[min(idx["i"], len(turns) - 1)]
        idx["i"] += 1
        return out

    with patch(
        "app.application.agent.tools.browser_tools._bridge_browser",
        side_effect=fake_bridge,
    ), patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=True,
    ), patch(
        "app.services.tool_policy_service.check_tool_allowed",
        return_value=(True, ""),
    ):
        result = run_agent(
            uid="uid-browser-on",
            channel="pc",
            text="Entra a https://example.com y dime el precio",
            system_prompt="Eres DOT.",
            registry=reg,
            model_fn=model_fn,
            local_tools=True,
        )

    assert "browserNavigate" in bridge_calls
    assert "browserGetPrice" in bridge_calls
    assert not any(
        isinstance(a, dict) and a.get("action") == "local_tool" and str(a.get("tool", "")).startswith("browser_")
        for a in result.artifacts
    )
    assert any(t.get("tool") == "browser_navigate" and t.get("ok") for t in result.tool_trace)
