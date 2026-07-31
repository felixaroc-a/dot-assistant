"""Tests de analyze_cv (tool agente + pipeline CV)."""
from __future__ import annotations

from app.application.agent.tools.cv_tools import analyze_cv_handler


SAMPLE_CV = (
    "Nombre: Ana Pérez\n"
    "Email: ana@ejemplo.com\n"
    "Tel: +58 412 555 1234\n"
    "Resumen: Desarrolladora con 5 años en Python y FastAPI.\n"
    "Habilidades: Python, FastAPI, SQL, Docker\n"
)


def test_analyze_cv_requires_path():
    result = analyze_cv_handler("uid-test", {})
    assert not result.ok
    assert "ruta" in (result.error or "").lower()


def test_analyze_cv_rejects_unsupported_extension():
    result = analyze_cv_handler("uid-test", {"path": "~/Desktop/foto.png"})
    assert not result.ok
    assert "formato" in (result.error or "").lower() or "soportado" in (result.error or "").lower()


def test_analyze_cv_extracts_fields(monkeypatch):
    def fake_read(path_raw: str):
        assert "cv.pdf" in path_raw
        return SAMPLE_CV, None

    monkeypatch.setattr(
        "app.application.agent.tools.cv_tools._read_document_text",
        fake_read,
    )

    result = analyze_cv_handler("uid-test", {"path": "~/Desktop/cv.pdf"})
    assert result.ok
    assert "Ana Pérez" in result.output
    assert "ana@ejemplo.com" in result.output
    assert result.artifacts
    assert result.artifacts[0]["type"] == "cv_analysis"
    fields = result.artifacts[0]["fields"]
    assert fields["name"] == "Ana Pérez"
    assert fields["email"] == "ana@ejemplo.com"


def test_analyze_cv_bridge_error(monkeypatch):
    monkeypatch.setattr(
        "app.application.agent.tools.cv_tools._read_document_text",
        lambda _p: (None, "No se pudo conectar con el PC (bridge). ¿Está abierta la app DOT?"),
    )
    result = analyze_cv_handler("uid-test", {"path": "~/Desktop/cv.pdf"})
    assert not result.ok
    assert "DOT" in (result.error or "")


def test_analyze_cv_includes_question_hint(monkeypatch):
    monkeypatch.setattr(
        "app.application.agent.tools.cv_tools._read_document_text",
        lambda _p: (SAMPLE_CV, None),
    )
    result = analyze_cv_handler(
        "uid-test",
        {"path": "~/Desktop/cv.pdf", "question": "¿Cuántos años de experiencia tiene?"},
    )
    assert result.ok
    assert "Pregunta del usuario" in result.output


def test_analyze_cv_registered_in_registry():
    from app.application.agent.tools import build_default_registry

    reg = build_default_registry(include_web_search=False)
    assert reg.has("analyze_cv")
