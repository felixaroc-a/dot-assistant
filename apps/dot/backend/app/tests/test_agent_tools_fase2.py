"""Tests FASE 2 — tools registradas en el Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.ports import ToolResult
from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_build_default_registry_has_required_tools():
    reg = build_default_registry(include_web_search=True)
    names = {s.name for s in reg.list_specs()}
    assert {
        "gmail_send",
        "readFile",
        "writeFile",
        "listFiles",
        "deleteFile",
        "web_search",
        "download_url_to_desktop",
        "send_whatsapp_message",
    } <= names


def test_run_agent_writefile_via_registry(monkeypatch):
    from app.application.agent.tools import local_files

    def fake_bridge(operation, *, path="", content=None):
        assert operation == "writeFile"
        assert path == "~/Desktop/prueba-dot.txt"
        assert content == "hola"
        return {"ok": True, "path": r"C:\Users\X\Escritorio\prueba-dot.txt"}

    monkeypatch.setattr(local_files, "execute_local_tool_via_bridge", fake_bridge)

    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"writeFile",'
                '"arguments":{"path":"~/Desktop/prueba-dot.txt","content":"hola"}}]}'
            )
        ),
        _FakeAI(content="Listo, creé prueba-dot.txt en tu Escritorio con hola."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="crea prueba-dot.txt en mi Escritorio con hola",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
    )
    assert "Escritorio" in result.final_text or "prueba-dot" in result.final_text
    assert result.tool_trace[0]["tool"] == "writeFile"
    assert result.tool_trace[0]["ok"] is True


def test_gmail_send_handler_missing_to():
    from app.application.agent.tools.gmail_send import gmail_send_handler

    r = gmail_send_handler("11111111-1111-1111-1111-111111111111", {"body": "x"})
    assert r.ok is False
    assert "destinatario" in (r.error or "").lower()


def test_web_search_handler_uses_service(monkeypatch):
    from app.application.agent.tools import web_search as ws

    monkeypatch.setattr(ws.settings, "enable_web_search", True)
    monkeypatch.setattr(
        "app.services.web_search.search_and_format_sync",
        lambda q: f"RESULT:{q}",
    )
    r = ws.web_search_handler("u", {"query": "dot ai"})
    assert r.ok is True
    assert r.output == "RESULT:dot ai"


def test_unknown_tool_denied_by_registry():
    reg = build_default_registry(include_web_search=False)
    r = reg.execute("u", "shell_root", {})
    assert isinstance(r, ToolResult)
    assert r.ok is False
    assert "no disponible" in (r.error or "").lower()
