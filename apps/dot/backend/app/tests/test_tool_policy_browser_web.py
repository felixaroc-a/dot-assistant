"""Tests política de navegación web (capa B / BR05)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.tool_policy_service import (
    BROWSER_WEB_DISABLED_MESSAGE,
    BROWSER_WEB_GATE_TOOL,
    ToolPolicy,
    check_tool_allowed,
    is_browser_web_enabled,
    set_browser_web_enabled,
)


def test_browser_navigate_denied_by_default():
    with patch(
        "app.services.tool_policy_service._get_user_policy",
        return_value=ToolPolicy(),
    ):
        allowed, reason = check_tool_allowed("uid-1", BROWSER_WEB_GATE_TOOL)
    assert not allowed
    assert reason == BROWSER_WEB_DISABLED_MESSAGE


def test_browser_navigate_allowed_when_enabled():
    with patch(
        "app.services.tool_policy_service._get_user_policy",
        return_value=ToolPolicy(allow_list={BROWSER_WEB_GATE_TOOL}),
    ):
        allowed, reason = check_tool_allowed("uid-1", BROWSER_WEB_GATE_TOOL)
    assert allowed
    assert reason == ""


def test_set_browser_web_enabled_updates_allow_list():
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc

    with patch("app.services.tool_policy_service.get_db", return_value=mock_db), patch(
        "app.services.tool_policy_service._get_user_policy",
        side_effect=[ToolPolicy(), ToolPolicy(allow_list={BROWSER_WEB_GATE_TOOL})],
    ):
        ok = set_browser_web_enabled("uid-1", True)
        assert ok
        mock_doc.set.assert_called_once()
        assert is_browser_web_enabled("uid-1")
