"""Tests parseo local_tool para path WA (C2)."""
from __future__ import annotations

from app.application.whatsapp.local_tool_parse import (
    format_tool_result_for_wa,
    parse_local_tool_action,
    strip_local_tool_json,
)


def test_parse_write_file_action():
    text = (
        'Creo el archivo.\n'
        '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/prueba-dot.txt","content":"hola"}'
    )
    action = parse_local_tool_action(text)
    assert action is not None
    assert action["operation"] == "writeFile"
    assert action["path"] == "~/Desktop/prueba-dot.txt"
    assert action["content"] == "hola"


def test_parse_truncated_write_file_missing_brace():
    """Stream a veces corta el cierre } — debe repararse."""
    text = (
        '{"action":"local_tool","operation":"writeFile",'
        '"path":"~/Desktop/prueba-dot.txt","content":"hola"'
    )
    action = parse_local_tool_action(text)
    assert action is not None
    assert action["operation"] == "writeFile"
    assert action["content"] == "hola"


def test_parse_rejects_unknown_operation():
    text = '{"action":"local_tool","operation":"shell","path":"x"}'
    assert parse_local_tool_action(text) is None


def test_format_and_strip():
    raw = 'Hecho.\n{"action":"local_tool","operation":"writeFile","path":"a.txt","content":"x"}'
    assert "local_tool" not in strip_local_tool_json(raw) or strip_local_tool_json(raw) == "Hecho."
    msg = format_tool_result_for_wa("writeFile", {"ok": True, "path": "C:/Users/x/Escritorio/a.txt"})
    assert "guardado" in msg.lower() or "Archivo" in msg


def test_finalize_assistant_tools_executes_write(monkeypatch):
    from app.application.agent import legacy_shim

    def fake_bridge(operation, *, path="", content=None, url=None):
        assert operation == "writeFile"
        assert "prueba-dot" in path
        assert content == "hola"
        return {"ok": True, "path": r"C:\Users\X\Escritorio\prueba-dot.txt"}

    monkeypatch.setattr(
        "app.application.agent.legacy_shim.execute_local_tool_via_bridge",
        fake_bridge,
    )
    out = legacy_shim.finalize_assistant_tools(
        "11111111-1111-1111-1111-111111111111",
        '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/prueba-dot.txt","content":"hola"',
    )
    assert "local_tool" not in out
    assert "prueba-dot" in out or "guardado" in out.lower() or "Archivo" in out


def test_parse_tool_calls_accepts_legacy_local_tool():
    from app.application.agent.tool_protocol import parse_tool_calls

    calls = parse_tool_calls(
        '{"action":"local_tool","operation":"writeFile","path":"~/Desktop/a.txt","content":"x"}'
    )
    assert calls is not None
    assert calls[0].name == "writeFile"
    assert calls[0].arguments["path"] == "~/Desktop/a.txt"


def test_parse_tool_calls_accepts_create_document_as_writefile():
    from app.application.agent.tool_protocol import parse_tool_calls

    raw = (
        '{"action":"create_document","type":"txt","title":"resumen-ia",'
        '"content":"Linea 1\\nReferencias:\\n- https://example.com/a"}'
    )
    calls = parse_tool_calls(raw)
    assert calls is not None
    assert calls[0].name == "writeFile"
    assert "Desktop" in calls[0].arguments["path"]
    assert "https://example.com" in calls[0].arguments["content"]


def test_finalize_create_document_writes(monkeypatch):
    from app.application.agent import legacy_shim

    def fake_bridge(operation, *, path="", content=None, url=None):
        assert operation == "writeFile"
        assert "Desktop" in path
        assert "Resumen" in (content or "")
        return {"ok": True, "path": r"C:\Users\X\Escritorio\resumen-ia.txt"}

    monkeypatch.setattr(
        "app.application.agent.legacy_shim.execute_local_tool_via_bridge",
        fake_bridge,
    )
    out = legacy_shim.finalize_assistant_tools(
        "11111111-1111-1111-1111-111111111111",
        '{"action":"create_document","type":"txt","title":"resumen-ia","content":"Resumen\\n- https://x.com"}',
    )
    assert "create_document" not in out
    assert "Resumen" in out
    assert "Escritorio" in out or "guardado" in out.lower()
    assert "{" not in out or "https://" in out  # contenido ok, no action JSON
