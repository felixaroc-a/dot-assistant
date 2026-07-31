"""Tests FREE-A05: gmail send con adjuntos."""
from __future__ import annotations

import base64
from email import message_from_bytes

from app.services.gmail_service import (
    _build_email_mime,
    _normalize_attachments,
    _resolve_attachment_spec,
    send_message,
)


def test_build_email_mime_plain_without_attachments():
    mime = _build_email_mime(
        to="a@example.com",
        subject="Hola",
        body="Texto plano",
    )
    assert mime.get_content_type() == "text/plain"
    assert mime["to"] == "a@example.com"
    assert mime["subject"] == "Hola"
    assert mime.get_payload() == "Texto plano"


def test_build_email_mime_multipart_with_attachment():
    mime = _build_email_mime(
        to="a@example.com",
        subject="Con adjunto",
        body="Mira el archivo",
        attachments=[("nota.txt", b"hola adjunto")],
    )
    assert mime.get_content_type() == "multipart/mixed"
    parts = mime.get_payload()
    assert len(parts) == 2
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_disposition() == "attachment"
    assert parts[1].get_filename() == "nota.txt"


def test_resolve_attachment_spec_from_base64():
    payload = base64.b64encode(b"pdf-bytes").decode("ascii")
    filename, content = _resolve_attachment_spec(
        {"filename": "cv.pdf", "content_base64": payload}
    )
    assert filename == "cv.pdf"
    assert content == b"pdf-bytes"


def test_normalize_attachments_rejects_invalid_item():
    try:
        _normalize_attachments(["not-a-dict"])
        assert False, "expected GmailIntegrationError"
    except Exception as exc:
        assert "objeto JSON" in str(exc)


def test_send_message_plain_still_uses_text_mime(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeUsers:
        def messages(self):
            return self

        def send(self, *, userId, body):
            captured["userId"] = userId
            captured["body"] = body
            return self

        def execute(self):
            return {"id": "msg-123", "threadId": "thr-1"}

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr("app.services.gmail_service._gmail_service", lambda _uid: _FakeService())

    sent = send_message(
        "11111111-1111-1111-1111-111111111111",
        to="dest@example.com",
        subject="Asunto",
        body="Cuerpo",
    )
    assert sent["id"] == "msg-123"
    raw = base64.urlsafe_b64decode(str(captured["body"]["raw"]))
    parsed = message_from_bytes(raw)
    assert parsed.get_content_type() == "text/plain"
    assert parsed.get_payload() == "Cuerpo"


def test_send_message_with_attachment_uses_multipart(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeUsers:
        def messages(self):
            return self

        def send(self, *, userId, body):
            captured["body"] = body
            return self

        def execute(self):
            return {"id": "msg-456", "threadId": "thr-2"}

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr("app.services.gmail_service._gmail_service", lambda _uid: _FakeService())

    payload = base64.b64encode(b"contenido-adjunto").decode("ascii")
    send_message(
        "11111111-1111-1111-1111-111111111111",
        to="dest@example.com",
        subject="Adjunto",
        body="Va adjunto",
        attachments=[{"filename": "doc.txt", "content_base64": payload}],
    )
    raw = base64.urlsafe_b64decode(str(captured["body"]["raw"]))
    parsed = message_from_bytes(raw)
    assert parsed.get_content_type() == "multipart/mixed"
    parts = parsed.get_payload()
    assert len(parts) == 2
    assert parts[1].get_filename() == "doc.txt"
