"""Cadena calendario: crear evento → notify_whatsapp_owner forzado."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_force_wa_notify_after_calendar_create(monkeypatch):
    notified: dict = {}

    from types import SimpleNamespace

    async def fake_wa_send(phone: str, message: str):
        notified["message"] = message
        return True, None

    monkeypatch.setattr(
        "app.services.calendar_service.create_event",
        lambda uid, **kwargs: {
            "id": "evt-1",
            "summary": kwargs.get("summary", "Reunión"),
            "start": kwargs["start_dt"].isoformat(),
            "end": kwargs["end_dt"].isoformat(),
        },
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
            content=(
                '{"tool_calls":[{"name":"calendar_create_event","arguments":'
                '{"summary":"Reunión con Juan","start":"2026-07-25T10:00:00",'
                '"duration_minutes":60}}]}'
            )
        ),
        _FakeAI(content="Listo, agendé la reunión con Juan mañana a las 10."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if idx["i"] < len(turns):
            out = turns[idx["i"]]
            idx["i"] += 1
            return out
        return _FakeAI(content="Hecho.")

    result = run_agent(
        uid="22222222-2222-2222-2222-222222222222",
        channel="pc",
        text="Agenda reunión con Juan mañana a las 10am y avísame",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=8,
        local_tools=False,
    )

    wa_tools = [t for t in result.tool_trace if t.get("tool") == "notify_whatsapp_owner"]
    assert wa_tools, f"Esperado notify forzado. Trace: {result.tool_trace}"
    assert notified.get("message")
    assert "Reunión" in notified["message"] or "Juan" in notified["message"]


def test_wants_smart_calendar_detects_spanish_phrase():
    from app.application.agent.runtime import _wants_smart_calendar

    assert _wants_smart_calendar("Agenda reunión con Pedro mañana 10am y avísame")
    assert _wants_smart_calendar("Programa cita con la doctora el lunes y recuérdame")
    assert not _wants_smart_calendar("¿Qué tengo en el calendario hoy?")
