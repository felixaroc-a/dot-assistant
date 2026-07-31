"""Tests confirmación humana antes de acciones destructivas (Loop-12)."""

from __future__ import annotations

from unittest.mock import patch

from app.application.agent.ports import ToolResult
from app.application.agent.registry import ToolRegistry
from app.services.destructive_confirm_service import (
    check_destructive_confirmation,
    destructive_confirm_scope,
    list_destructive_tools,
    requires_destructive_confirmation,
    strip_confirm_argument,
)


def test_delete_file_requires_confirm_without_flag():
    allowed, msg = check_destructive_confirmation(
        "deleteFile",
        {"path": "~/Desktop/test.txt"},
    )
    assert not allowed
    assert "CONFIRMACIÓN REQUERIDA" in msg
    assert "deleteFile" in msg
    assert "confirm: true" in msg


def test_delete_file_allowed_with_confirm():
    allowed, msg = check_destructive_confirmation(
        "deleteFile",
        {"path": "~/Desktop/test.txt", "confirm": True},
    )
    assert allowed
    assert msg == ""


def test_mandate_bypass_skips_confirm():
    with destructive_confirm_scope("automation"):
        assert not requires_destructive_confirmation("deleteFile", {"path": "x.txt"})
        allowed, _ = check_destructive_confirmation("gmail_send", {"to": "a@b.com"})
        assert allowed


def test_write_file_no_confirm_for_new_file():
    with patch(
        "app.services.destructive_confirm_service._target_file_exists",
        return_value=False,
    ):
        assert not requires_destructive_confirmation(
            "writeFile",
            {"path": "~/Desktop/nuevo.txt", "content": "hola"},
        )


def test_write_file_requires_confirm_when_overwriting():
    with patch(
        "app.services.destructive_confirm_service._target_file_exists",
        return_value=True,
    ):
        allowed, msg = check_destructive_confirmation(
            "writeFile",
            {"path": "~/Desktop/existente.txt", "content": "nuevo"},
        )
        assert not allowed
        assert "sobrescribir" in msg


def test_strip_confirm_removes_flag():
    cleaned = strip_confirm_argument({"path": "x", "confirm": True, "content": "a"})
    assert "confirm" not in cleaned
    assert cleaned["path"] == "x"


def test_gmail_auto_reply_requires_confirm():
    allowed, msg = check_destructive_confirmation(
        "gmail_auto_reply",
        {"message_id": "m1", "body": "Gracias"},
    )
    assert not allowed
    assert "CONFIRMACIÓN REQUERIDA" in msg
    assert "gmail_auto_reply" in msg


def test_gmail_archive_requires_confirm():
    allowed, msg = check_destructive_confirmation(
        "gmail_archive",
        {"message_id": "m1"},
    )
    assert not allowed
    assert "archivar" in msg.lower()


def test_gmail_auto_reply_allowed_with_confirm():
    allowed, msg = check_destructive_confirmation(
        "gmail_auto_reply",
        {"message_id": "m1", "body": "Gracias", "confirm": True},
    )
    assert allowed
    assert msg == ""


def test_registry_blocks_delete_without_confirm():
    reg = ToolRegistry()

    def _delete_handler(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, output=f"deleted {arguments.get('path')}")

    from app.application.agent.ports import ToolSpec

    reg.register(
        ToolSpec(name="deleteFile", description="test", parameters_schema={}),
        _delete_handler,
    )

    with patch("app.application.agent.registry._check_policy", return_value=(True, "")):
        blocked = reg.execute("uid-1", "deleteFile", {"path": "a.txt"})
        assert not blocked.ok
        assert "CONFIRMACIÓN REQUERIDA" in (blocked.error or "")

        ok = reg.execute("uid-1", "deleteFile", {"path": "a.txt", "confirm": True})
        assert ok.ok
        assert "deleted a.txt" in ok.output


def test_mass_whatsapp_campaign_requires_confirm():
    allowed, msg = check_destructive_confirmation(
        "send_whatsapp_campaign",
        {
            "contacts": ["+581", "+582"],
            "template": "Hola {name}",
            "auto_id": "auto-1",
        },
    )
    assert not allowed
    assert "campaña masiva" in msg.lower() or "masiva" in msg.lower()


def test_list_destructive_tools_includes_core():
    inv = list_destructive_tools()
    assert "deleteFile" in inv["always_confirm"]
    assert "send_whatsapp_campaign" in inv["always_confirm"]
    assert "writeFile" in inv["overwrite_when_exists"]
