"""Hint de páginas web condicionado al toggle del usuario."""

from __future__ import annotations

from unittest.mock import patch

from app.services.chat_context import (
    BROWSER_WEB_DISABLED_HINT,
    BROWSER_WEB_RUNTIME_HINT,
    build_system_prompt,
)


def test_build_system_prompt_browser_hint_when_enabled():
    with patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=True,
    ), patch(
        "app.services.chat_context.build_user_context_block",
        return_value="",
    ), patch(
        "app.services.memory_service.build_memory_prompt_block",
        return_value="",
    ):
        prompt = build_system_prompt("uid-1", "entra a example.com")
    assert BROWSER_WEB_RUNTIME_HINT.splitlines()[0] in prompt
    assert BROWSER_WEB_DISABLED_HINT.splitlines()[0] not in prompt


def test_build_system_prompt_browser_hint_when_disabled():
    with patch(
        "app.services.tool_policy_service.is_browser_web_enabled",
        return_value=False,
    ), patch(
        "app.services.chat_context.build_user_context_block",
        return_value="",
    ), patch(
        "app.services.memory_service.build_memory_prompt_block",
        return_value="",
    ):
        prompt = build_system_prompt("uid-1", "entra a example.com")
    assert BROWSER_WEB_DISABLED_HINT.splitlines()[0] in prompt
    assert "browser_navigate" in prompt
    assert "NO uses browser_navigate" in prompt
