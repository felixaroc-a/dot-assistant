"""Tests D1: gmail_send en lenguaje natural."""
from __future__ import annotations

from app.application.whatsapp.gmail_action import (
    apply_gmail_send_if_present,
    execute_gmail_send,
    parse_gmail_send_action,
)


def test_parse_gmail_send_action():
    text = (
        '{"action":"gmail_send","to":"a@example.com",'
        '"subject":"Prueba","body":"Hola DOT"}'
    )
    action = parse_gmail_send_action(text)
    assert action is not None
    assert action["to"] == "a@example.com"
    assert action["subject"] == "Prueba"
    assert action["body"] == "Hola DOT"


def test_parse_gmail_send_action_with_attachments():
    text = (
        '{"action":"gmail_send","to":"a@example.com","subject":"CV",'
        '"body":"Adjunto CV","attachments":[{"filename":"cv.pdf","path":"~/Desktop/cv.pdf"}]}'
    )
    action = parse_gmail_send_action(text)
    assert action is not None
    assert action["attachments"] == [
        {"filename": "cv.pdf", "path": "~/Desktop/cv.pdf"}
    ]


def test_execute_gmail_send_with_attachments_passes_through(monkeypatch):
    captured: dict[str, object] = {}

    def _send(uid, *, to, subject, body, body_html=None, attachments=None):
        captured["to"] = to
        captured["attachments"] = attachments
        return {"id": "msg-att", "thread_id": "t-att"}

    monkeypatch.setattr("app.services.gmail_service.send_message", _send)
    msg = execute_gmail_send(
        "11111111-1111-1111-1111-111111111111",
        {
            "to": "a@example.com",
            "subject": "X",
            "body": "Y",
            "attachments": [{"filename": "f.txt", "content_base64": "aGk="}],
        },
    )
    assert captured["attachments"] == [{"filename": "f.txt", "content_base64": "aGk="}]
    assert "adjunto" in msg.lower()


def test_execute_gmail_send_without_oauth_is_human(monkeypatch):
    from app.services.gmail_service import MissingGmailCredentialsError

    def _boom(*_a, **_k):
        raise MissingGmailCredentialsError("no oauth")

    monkeypatch.setattr("app.services.gmail_service.send_message", _boom)
    msg = execute_gmail_send(
        "11111111-1111-1111-1111-111111111111",
        {"to": "a@example.com", "subject": "X", "body": "Y"},
    )
    assert "conectar" in msg.lower() or "Google" in msg


def test_apply_gmail_send_if_present_success(monkeypatch):
    monkeypatch.setattr(
        "app.services.gmail_service.send_message",
        lambda *_a, **_k: {"id": "msg-1", "thread_id": "t1"},
    )
    out = apply_gmail_send_if_present(
        "11111111-1111-1111-1111-111111111111",
        '{"action":"gmail_send","to":"b@example.com","subject":"Hi","body":"Body"}',
    )
    assert "enviado" in out.lower()
    assert "b@example.com" in out
    assert "gmail_send" not in out
