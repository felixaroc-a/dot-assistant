"""Tests descarga adjuntos Gmail → Escritorio vía bridge."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock

from app.services.gmail_service import download_attachments


def test_download_attachments_saves_via_bridge(monkeypatch):
    captured: dict[str, str] = {}

    class _FakeAttachments:
        def get(self, *, userId, messageId, id):
            _ = (userId, messageId)
            return self

        def execute(self):
            payload = base64.urlsafe_b64encode(b"hola-adjunto").decode("ascii")
            return {"data": payload}

    class _FakeMessages:
        def get(self, *, userId, id, format):
            _ = (userId, id, format)
            return self

        def attachments(self):
            return _FakeAttachments()

        def execute(self):
            return {
                "payload": {
                    "parts": [
                        {
                            "filename": "factura.pdf",
                            "body": {"attachmentId": "att-1"},
                        }
                    ]
                }
            }

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    def _fake_bridge(operation, *, path, content):
        captured["operation"] = operation
        captured["path"] = path
        captured["content"] = content
        return {"ok": True, "path": "C:\\Users\\X\\Desktop\\factura.pdf", "bytes": 12}

    monkeypatch.setattr("app.services.gmail_service._gmail_service", lambda _uid: _FakeService())
    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        _fake_bridge,
    )

    saved = download_attachments(
        "11111111-1111-1111-1111-111111111111",
        "msg-1",
        download_dir="~/Desktop",
    )
    assert saved == ["C:\\Users\\X\\Desktop\\factura.pdf"]
    assert captured["operation"] == "writeFileBytes"
    assert captured["path"] == "~/Desktop/factura.pdf"
    assert base64.b64decode(captured["content"]) == b"hola-adjunto"


def test_download_attachments_empty_when_no_parts(monkeypatch):
    class _FakeMessages:
        def get(self, *, userId, id, format):
            _ = (userId, id, format)
            return self

        def execute(self):
            return {"payload": {"parts": []}}

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    monkeypatch.setattr(
        "app.services.gmail_service._gmail_service",
        lambda _uid: MagicMock(users=lambda: _FakeUsers()),
    )
    saved = download_attachments("uid", "msg-empty")
    assert saved == []
