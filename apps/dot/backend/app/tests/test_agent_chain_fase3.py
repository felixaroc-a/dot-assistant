"""FASE 3 — encadenamiento ≥2 tools en un solo pedido (D-PC-2)."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_chain_web_search_then_writefile(monkeypatch):
    """D-PC-2 unitario: web_search → writeFile → texto final humano."""
    from app.application.agent.tools import local_files, web_search as ws

    monkeypatch.setattr(ws.settings, "enable_web_search", True)
    monkeypatch.setattr(
        "app.services.web_search.search_and_format_sync",
        lambda q: f"RESUMEN_WEB:{q}",
    )

    written: dict = {}

    def fake_bridge(operation, *, path="", content=None):
        assert operation == "writeFile"
        written["path"] = path
        written["content"] = content
        return {"ok": True, "path": r"C:\Users\X\Escritorio\resumen-dot.txt"}

    monkeypatch.setattr(local_files, "execute_local_tool_via_bridge", fake_bridge)

    reg = build_default_registry(include_web_search=True)
    turns = [
        _FakeAI(
            content='{"tool_calls":[{"name":"web_search","arguments":{"query":"noticias IA"}}]}'
        ),
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"writeFile","arguments":'
                '{"path":"~/Desktop/resumen-dot.txt","content":"cinco lineas"}}]}'
            )
        ),
        _FakeAI(
            content="Listo: busqué noticias de IA y guardé un resumen de 5 líneas en tu Escritorio."
        ),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="busca en la web noticias IA, resume en 5 líneas y guarda resumen en Escritorio",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=6,
        local_tools=False,
    )

    tool_calls_from_trace = [t["tool"] for t in result.tool_trace]
    assert "web_search" in tool_calls_from_trace
    assert "writeFile" in tool_calls_from_trace
    assert len(result.tool_trace) >= 2


def test_agentic_hint_in_system_prompt():
    from app.services.chat_context import AGENTIC_RESULTS_HINT

    assert "RESULTADOS" in AGENTIC_RESULTS_HINT
    # build_system_prompt puede fallar sin DB; el hint está en el módulo
    assert "encadena" in AGENTIC_RESULTS_HINT.lower() or "varios pasos" in AGENTIC_RESULTS_HINT
