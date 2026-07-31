"""Cadena Gmail leído → resumen → notify_whatsapp_owner."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_force_wa_notify_after_gmail_read(monkeypatch):
    notified: dict = {}

    def fake_gmail_read(uid, arguments):
        from app.application.agent.ports import ToolResult

        return ToolResult(
            ok=True,
            output="Asunto: Factura\nDe: banco@example.com\n\nTu pago fue recibido.",
        )

    from types import SimpleNamespace

    async def fake_wa_send(phone: str, message: str):
        notified["message"] = message
        return True, None

    monkeypatch.setattr(
        "app.services.gmail_service.read_message",
        lambda uid, msg_id: "Asunto: Factura\nDe: banco@example.com\n\nTu pago fue recibido.",
    )
    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda uid: SimpleNamespace(linked=True, phone_number="+584121234567"),
    )
    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        fake_wa_send,
    )

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content='{"tool_calls":[{"name":"gmail_read_message","arguments":{"message_id":"m1"}}]}'
        ),
        _FakeAI(
            content=(
                "Resumen del correo:\n"
                "• Pago recibido\n"
                "• Monto confirmado\n"
                "Fin del resumen."
            )
        ),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if idx["i"] < len(turns):
            out = turns[idx["i"]]
            idx["i"] += 1
            return out
        return _FakeAI(content="Listo, enviado.")

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="Lee el último correo del banco y mándame un resumen por WhatsApp",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
        local_tools=False,
    )

    wa_tools = [t for t in result.tool_trace if t.get("tool") == "notify_whatsapp_owner"]
    assert wa_tools, f"Esperado notify forzado. Trace: {result.tool_trace}"
    assert notified.get("message")
