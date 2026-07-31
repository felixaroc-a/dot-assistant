"""El paso file del pipeline debe listar/leer vía bridge (no mentir con LLM)."""
from __future__ import annotations

import pytest

from worker.executor import AutomationExecutor


def test_file_lists_desktop_via_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_bridge(operation: str, **kwargs):
        calls.append((operation, kwargs))
        if operation == "listFiles":
            return {
                "ok": True,
                "path": r"C:\Users\Test\Desktop",
                "files": [
                    {"name": "a.txt", "isDirectory": False},
                    {"name": "fotos", "isDirectory": True},
                ],
            }
        return {"ok": False, "error": f"unexpected {operation}"}

    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        fake_bridge,
    )

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": "Leer archivo en Escritorio / listar resumen",
            "integration_id": "file",
        },
    )

    assert calls and calls[0][0] == "listFiles"
    assert calls[0][1].get("path") == "~/Desktop"
    assert "a.txt" in out
    assert "fotos" in out
    assert "no tengo acceso" not in out.lower()


def test_file_read_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_bridge(operation: str, **kwargs):
        assert operation == "readFile"
        assert kwargs.get("path") == r"C:\Users\Test\Desktop\notas.txt"
        return {
            "ok": True,
            "path": kwargs["path"],
            "content": "hola mundo desde el escritorio",
        }

    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        fake_bridge,
    )

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": r"Leer C:\Users\Test\Desktop\notas.txt",
            "integration_id": "file",
        },
    )
    assert "hola mundo" in out
    assert "Archivo leído" in out


def test_file_read_pdf_uses_parse_document(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_bridge(operation: str, **kwargs):
        calls.append((operation, kwargs))
        assert operation == "parseDocument"
        assert kwargs.get("path") == r"C:\Users\Test\Desktop\cv.pdf"
        assert kwargs.get("content") == "application/pdf"
        return {
            "ok": True,
            "path": kwargs["path"],
            "text": "Nombre: Luis Gómez\nEmail: luis@test.org",
        }

    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        fake_bridge,
    )

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": r"Leer C:\Users\Test\Desktop\cv.pdf",
            "integration_id": "file",
        },
    )
    assert calls and calls[0][0] == "parseDocument"
    assert "Luis Gómez" in out
    assert "Archivo leído" in out


def test_file_fails_loudly_on_bridge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        lambda *a, **k: {"ok": False, "error": "bridge_unreachable"},
    )

    with pytest.raises(RuntimeError, match="bridge|DOT|listar"):
        AutomationExecutor().execute(
            "uid-test",
            {
                "instruction": "Listar archivos en Escritorio",
                "integration_id": "file",
            },
        )


def test_document_chat_writes_real_file_from_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, str] = {}

    def fake_bridge(operation: str, **kwargs):
        assert operation == "writeFile"
        written["path"] = kwargs.get("path") or ""
        written["content"] = kwargs.get("content") or ""
        return {"ok": True, "path": r"C:\Users\Test\Desktop\Resumen_DOT.txt"}

    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        fake_bridge,
    )

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": "Generar documento carta (resumen de escritorio)",
            "integration_id": "chat",
            "prior_output": "Archivos en Escritorio — 2 elementos:\n- a.txt (archivo)\n- b.pdf (archivo)",
        },
    )

    assert "Documento guardado" in out
    assert "a.txt" in written["content"]
    assert written["path"].startswith("~/Desktop/")


def test_document_chat_fails_without_prior() -> None:
    with pytest.raises(RuntimeError, match="no hay datos reales"):
        AutomationExecutor().execute(
            "uid-test",
            {
                "instruction": "Generar documento resumen de escritorio",
                "integration_id": "chat",
                "prior_output": "",
            },
        )


def test_trigger_does_not_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("no debe llamar al LLM en trigger")

    monkeypatch.setattr("worker.executor.route_chat", boom)

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": "Ejecutar manualmente cuando el usuario lo pida",
            "integration_id": "chat",
            "step_type": "trigger",
        },
    )
    assert "Disparador listo" in out
