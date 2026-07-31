"""Tests Agent Runtime (FASE 1) — loop, tope max_steps, tool desconocida."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.agent.ports import ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry
from app.application.agent.runtime import run_agent
from app.application.agent.tool_protocol import parse_tool_calls


@dataclass
class _FakeAI:
    content: str
    usage: dict | None = None
    model: str = "fake"


def test_parse_tool_calls_strict_json():
    text = '{"tool_calls":[{"name":"echo","arguments":{"msg":"hola"}}]}'
    calls = parse_tool_calls(text)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments["msg"] == "hola"


def test_parse_tool_calls_none_on_plain_text():
    assert parse_tool_calls("Hola, ¿en qué te ayudo?") is None


def test_parse_tool_calls_xml_list_files():
    from app.application.agent.tool_protocol import strip_tool_calls_json

    text = (
        "Voy a listar la carpeta.\n"
        "<listFiles><path>C:\\Users\\Usuario\\OneDrive\\Escritorio\\Nordik-IA</path></listFiles>"
    )
    calls = parse_tool_calls(text)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0].name == "listFiles"
    assert "Nordik-IA" in calls[0].arguments["path"]
    spoken = strip_tool_calls_json(text)
    assert "listFiles" not in spoken
    assert "Voy a listar" in spoken


def test_run_agent_noop_empty_registry_one_model_turn():
    """tools=[] → un solo turno, sin tool_trace (comportamiento = hoy)."""
    calls = {"n": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        calls["n"] += 1
        assert "Nuevo mensaje" in user_text or "ping" in user_text
        return _FakeAI(content="pong", usage={"prompt_tokens": 1})

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="ping",
        system_prompt="Eres DOT.",
        history="",
        registry=ToolRegistry(),
        model_fn=model_fn,
    )
    assert result.final_text == "pong"
    assert result.steps == 1
    assert result.tool_trace == []
    assert calls["n"] == 1


def test_run_agent_loop_with_one_fake_tool():
    reg = ToolRegistry()

    def echo_handler(uid: str, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, output=f"echo:{arguments.get('msg', '')}")

    reg.register(
        ToolSpec(name="echo", description="eco de prueba"),
        echo_handler,
    )

    turns = [
        _FakeAI(content='{"tool_calls":[{"name":"echo","arguments":{"msg":"hola"}}]}'),
        _FakeAI(content="Listo: echo:hola"),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        assert "echo" in system_prompt  # hint de tools
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="haz eco de hola",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=5,
    )
    assert result.final_text == "Listo: echo:hola"
    assert result.steps == 2
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["tool"] == "echo"
    assert result.tool_trace[0]["ok"] is True


def test_run_agent_unknown_tool_returns_error_observation_then_final():
    reg = ToolRegistry()
    # registry vacío de handlers útiles — modelo pide tool inexistente
    turns = [
        _FakeAI(content='{"tool_calls":[{"name":"shell_root","arguments":{}}]}'),
        _FakeAI(content="No puedo usar esa herramienta."),
    ]
    idx = {"i": 0}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        # Tras error, el working_text debe incluir observación de error
        if idx["i"] == 1:
            assert "no disponible" in user_text.lower() or "shell_root" in user_text
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    # Registrar una tool distinta para activar el loop (si registry vacío = noop)
    reg.register(
        ToolSpec(name="noop_ok", description="dummy"),
        lambda uid, args: ToolResult(ok=True, output="ok"),
    )

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="whatsapp",
        text="root pls",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=4,
    )
    assert "No puedo" in result.final_text
    assert result.tool_trace[0]["tool"] == "shell_root"
    assert result.tool_trace[0]["ok"] is False


def test_run_agent_max_steps_hard_cap():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="spin", description="siempre pide otra vez"),
        lambda uid, args: ToolResult(ok=True, output="spun"),
    )

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        return _FakeAI(content='{"tool_calls":[{"name":"spin","arguments":{}}]}')

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="gira",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=3,
    )
    assert result.steps == 3
    assert "límite de pasos" in result.final_text.lower()
    assert len(result.tool_trace) == 3


def test_run_agent_nudges_incomplete_then_finishes():
    """Si el modelo corta con 'voy a…', el runtime empuja otro turno hasta el entregable."""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="echo", description="eco"),
        lambda uid, args: ToolResult(ok=True, output=f"echo:{args.get('msg', '')}"),
    )

    turns = [
        _FakeAI(content='{"tool_calls":[{"name":"echo","arguments":{"msg":"x"}}]}'),
        _FakeAI(content="Voy a analizar los resultados y luego te escribo el informe."),
        _FakeAI(
            content=(
                "Informe técnico completo: la carpeta tiene estructura modular, "
                "hallazgos A/B/C y mejoras sugeridas 1/2/3. Documento listo."
            )
        ),
    ]
    idx = {"i": 0}
    seen_nudge = {"ok": False}

    def model_fn(user_text: str, system_prompt: str) -> _FakeAI:
        if "incompleta" in user_text.lower() or "NO digas qué vas a hacer" in user_text:
            seen_nudge["ok"] = True
        out = turns[idx["i"]]
        idx["i"] += 1
        return out

    result = run_agent(
        uid="11111111-1111-1111-1111-111111111111",
        channel="pc",
        text="analiza el proyecto y dame informe profundo",
        system_prompt="Eres DOT.",
        registry=reg,
        model_fn=model_fn,
        max_steps=6,
    )
    assert seen_nudge["ok"] is True
    assert "Informe técnico completo" in result.final_text
    assert "Voy a analizar" not in result.final_text
    assert result.steps == 3
