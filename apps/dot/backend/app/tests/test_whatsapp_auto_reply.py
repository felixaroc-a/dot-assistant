"""Tests B1: auto-reply WA → mismo cerebro → outbound."""
from __future__ import annotations

from app.application.whatsapp.auto_reply_service import (
    clear_replied_ids_for_tests,
    resolve_reply_to,
    run_whatsapp_auto_reply,
)
from app.domain.whatsapp.message import InboundWhatsAppMessage


def test_resolve_reply_to_prefers_chat_jid_group():
    msg = InboundWhatsAppMessage(
        message_id="m1",
        from_phone="+580000000001",
        to_phone="+580000000099",
        text="@DOT hola",
        timestamp="2026-07-16T12:00:00Z",
        is_group=True,
        chat_jid="120363@g.us",
        group_name="DOT",
    )
    assert resolve_reply_to(msg) == "120363@g.us"


def test_resolve_reply_to_falls_back_to_from_phone():
    msg = InboundWhatsAppMessage(
        message_id="m2",
        from_phone="+580000000001",
        to_phone="+580000000099",
        text="hola",
        timestamp="2026-07-16T12:00:00Z",
        is_group=False,
    )
    assert resolve_reply_to(msg) == "+580000000001"


def test_run_whatsapp_auto_reply_calls_same_brain_and_outbound(monkeypatch):
    clear_replied_ids_for_tests()
    uid = "11111111-1111-1111-1111-111111111111"
    msg = InboundWhatsAppMessage(
        message_id="msg-auto-01",
        from_phone="+580000000001",
        to_phone="+580000000099",
        text="@DOT resume mi día",
        timestamp="2026-07-16T12:00:00Z",
        is_group=True,
        chat_jid="12036399@g.us",
        group_name="DOT",
    )

    monkeypatch.setattr(
        "app.application.whatsapp.auto_reply_service._check_usage_or_block_message",
        lambda _uid: None,
    )
    monkeypatch.setattr(
        "app.services.chat_context.build_system_prompt",
        lambda _uid, _query=None: "SYSTEM",
    )

    class _AI:
        content = "Respuesta DOT de prueba"
        usage = {}
        model = "deepseek-chat"

    monkeypatch.setattr(
        "app.services.provider_router.route_chat_detailed",
        lambda *a, **k: _AI(),
    )

    sent: list[tuple[str, str]] = []

    async def _fake_send(to: str, text: str):
        sent.append((to, text))
        return True, "wa_out_test"

    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        _fake_send,
    )
    monkeypatch.setattr(
        "app.application.whatsapp.auto_reply_service._persist_assistant_to_chat_history",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.application.whatsapp.auto_reply_service._record_chat_usage",
        lambda *a, **k: None,
    )

    # Evitar historial DB
    class _NoDB:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def first(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        "app.billing_db.get_session_factory",
        lambda: (lambda: _NoDB()),
    )

    result = run_whatsapp_auto_reply(uid=uid, message=msg, message_id="msg-auto-01")
    assert result["ok"] is True
    assert sent == [("12036399@g.us", "Respuesta DOT de prueba")]

    # Dedupe: segunda llamada no reenvía
    result2 = run_whatsapp_auto_reply(uid=uid, message=msg, message_id="msg-auto-01")
    assert result2["ok"] is False
    assert result2["error"] == "already_replied"
    assert len(sent) == 1
