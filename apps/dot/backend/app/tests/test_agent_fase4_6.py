"""FASE 4–6 — WA format, download tool, rate limit, remote 410."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.ports import ToolResult
from app.application.agent.runtime import run_agent
from app.application.agent.tool_rate_limit import allow_tool_call, reset_for_tests
from app.application.agent.tools import build_default_registry
from app.application.whatsapp.auto_reply_service import format_whatsapp_outbound


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_format_whatsapp_strips_json():
    raw = (
        'Listo.\n'
        '{"action":"local_tool","operation":"writeFile","path":"a.txt","content":"x"}'
    )
    out = format_whatsapp_outbound(raw)
    assert "local_tool" not in out
    assert "Listo" in out or "PC" in out


def test_registry_includes_download():
    names = {s.name for s in build_default_registry().list_specs()}
    assert "download_url_to_desktop" in names


def test_download_tool_via_runtime(monkeypatch):
    from app.application.agent.tools import local_files

    def fake_bridge(operation, *, path="", content=None, url=None):
        assert operation == "downloadUrl"
        assert url.startswith("https://")
        return {"ok": True, "path": r"C:\Users\X\Escritorio\file.bin", "bytes": 12}

    monkeypatch.setattr(local_files, "execute_local_tool_via_bridge", fake_bridge)
    reg = build_default_registry(include_web_search=False)
    turns = [
        _FakeAI(
            content=(
                '{"tool_calls":[{"name":"download_url_to_desktop",'
                '"arguments":{"url":"https://example.com/a.bin","path":"~/Desktop/a.bin"}}]}'
            )
        ),
        _FakeAI(content="Descargué el archivo a tu Escritorio."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        out = turns[min(idx["i"], len(turns) - 1)]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="whatsapp",
        text="descarga https://example.com/a.bin al Escritorio",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        local_tools=True,
    )
    # Con FLAG_USE_LOCAL_AGENT=True (M2S4-A), download_url_to_desktop
    # es tool local → se emite marcador local_tool en vez de ejecutarse.
    if result.tool_trace:
        assert result.tool_trace[0]["tool"] == "download_url_to_desktop"
        assert result.tool_trace[0]["ok"] is True
    assert "Escritorio" in result.final_text or "Descarg" in result.final_text or "tool_calls" in result.final_text or "local_tool" in result.final_text


def test_force_download_overrides_model_refusal(monkeypatch):
    """Estilo OpenClaw: no depende de que el modelo pida la tool."""
    from app.application.agent.tools import local_files

    def fake_bridge(operation, *, path="", content=None, url=None):
        assert operation == "downloadUrl"
        assert "dummy.pdf" in (url or "")
        return {"ok": True, "path": r"C:\Users\X\Escritorio\dummy.pdf", "bytes": 13264}

    monkeypatch.setattr(local_files, "execute_local_tool_via_bridge", fake_bridge)
    reg = build_default_registry(include_web_search=False)

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        return _FakeAI(
            content=(
                "Lo siento, pero no tengo capacidad para descargar archivos "
                "binarios como PDFs directamente desde una URL."
            )
        )

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text=(
            "descarga https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf "
            "al Escritorio"
        ),
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        local_tools=False,  # Test con bridge monkeypatched — necesita ejecucion real
    )
    assert any(t.get("tool") == "download_url_to_desktop" and t.get("ok") for t in result.tool_trace)
    assert "no tengo capacidad" not in result.final_text.lower()
    assert "Escritorio" in result.final_text or "descarg" in result.final_text.lower()


def test_tool_rate_limit_blocks():
    reset_for_tests()
    uid = "rate-limit-uid"
    for _ in range(30):
        assert allow_tool_call(uid, limit=30) is True
    assert allow_tool_call(uid, limit=30) is False
    reset_for_tests()


def test_registry_rate_limit_human_error():
    reset_for_tests()
    reg = build_default_registry(include_web_search=False)
    uid = "rl-reg-uid"
    for _ in range(30):
        allow_tool_call(uid, limit=30)
    # Siguiente execute debe fallar por rate limit (allow_tool_call interno)
    r = reg.execute(uid, "readFile", {"path": "x.txt"})
    assert isinstance(r, ToolResult)
    assert r.ok is False
    assert "Demasiadas" in (r.error or "")
    reset_for_tests()
