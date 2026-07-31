"""Cadena Gmail: listar → responder / archivar con nudges en runtime."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.runtime import (
    _wants_gmail_bulk_archive,
    _wants_gmail_inbox,
    _wants_gmail_reply,
    run_agent,
)
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_wants_gmail_reply_detects_spanish():
    assert _wants_gmail_reply("Responde al correo de Juan diciendo que sí")
    assert _wants_gmail_reply("Contesta este email con un gracias")
    assert not _wants_gmail_reply("¿Qué correos sin leer tengo?")


def test_wants_gmail_bulk_archive_detects_spanish():
    assert _wants_gmail_bulk_archive("Archiva los correos de spam")
    assert _wants_gmail_bulk_archive("Limpia la bandeja de promociones")
    assert not _wants_gmail_bulk_archive("Lee el correo de facturación")


def test_wants_gmail_inbox_detects_spanish():
    assert _wants_gmail_inbox("¿Qué correos sin leer tengo?")
    assert _wants_gmail_inbox("Muéstrame mi bandeja de Gmail")
    assert not _wants_gmail_inbox("Envía un correo a cliente@empresa.com")


def test_gmail_reply_nudge_after_list(monkeypatch):
    listed = {"called": False}

    def fake_list_unread(uid, arguments):
        from app.application.agent.ports import ToolResult

        listed["called"] = True
        return ToolResult(
            ok=True,
            output=(
                "Correos no leídos (1):\n"
                "- Factura | De: banco@example.com | ID: msg-99"
            ),
        )

    from app.application.agent import registry as reg_mod

    original_execute = reg_mod.ToolRegistry.execute

    def patched_execute(self, uid, name, arguments=None):
        if name == "gmail_list_unread":
            return fake_list_unread(uid, arguments or {})
        return original_execute(self, uid, name, arguments)

    monkeypatch.setattr(reg_mod.ToolRegistry, "execute", patched_execute)

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content='{"tool_calls":[{"name":"gmail_list_unread","arguments":{}}]}'
        ),
        _FakeAI(content="Vi un correo del banco sobre la factura."),
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"gmail_auto_reply","arguments":'
                '{"message_id":"msg-99","body":"Recibido, gracias.","confirm":true}}]}'
            )
        ),
        _FakeAI(content="Listo, respondí al banco confirmando que recibí la factura."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if idx["i"] < len(turns):
            out = turns[idx["i"]]
            idx["i"] += 1
            return out
        return _FakeAI(content="Hecho.")

    def fake_reply(uid, message_id, body, *, attachments=None):
        return {"id": "sent-1", "thread_id": "t1"}

    monkeypatch.setattr("app.services.gmail_service.reply", fake_reply)

    result = run_agent(
        uid="33333333-3333-3333-3333-333333333333",
        channel="pc",
        text="Responde al correo del banco diciendo que recibí la factura",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
        local_tools=False,
    )

    reply_tools = [t for t in result.tool_trace if t.get("tool") == "gmail_auto_reply"]
    assert listed["called"]
    assert reply_tools, f"Esperado gmail_auto_reply. Trace: {result.tool_trace}"
