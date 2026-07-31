"""Tests de tools translate y summarize (agent core)."""

from __future__ import annotations

from app.application.agent.tools.text_tools import summarize_handler, translate_handler


def test_translate_text_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.provider_router.route_translate",
        lambda text, target_lang, **_: ("Hello world", "google_translate", "en"),
    )

    result = translate_handler(
        "uid-test",
        {"text": "Hola mundo", "target_lang": "inglés"},
    )

    assert result.ok is True
    assert result.output == "Hello world"
    assert result.artifacts[0]["target_lang"] == "en"


def test_translate_requires_target_lang() -> None:
    result = translate_handler("uid-test", {"text": "Hola"})
    assert result.ok is False
    assert "idioma destino" in (result.error or "").lower()


def test_translate_strips_read_document_prefix(monkeypatch) -> None:
    captured: dict = {}

    def fake_route(text, target_lang, **_):
        captured["text"] = text
        return "Translated", "deepseek", "en"

    monkeypatch.setattr("app.services.provider_router.route_translate", fake_route)

    translate_handler(
        "uid-test",
        {
            "text": "Contenido de informe.pdf:\n\nTexto del informe.",
            "target_lang": "en",
        },
    )

    assert captured["text"] == "Texto del informe."


def test_summarize_text_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.provider_router.route_summarize",
        lambda content, **_: ("Resumen corto.", "text", 1),
    )

    result = summarize_handler(
        "uid-test",
        {"text": "Texto largo " * 50, "style": "breve"},
    )

    assert result.ok is True
    assert "Resumen" in result.output
    assert result.artifacts[0]["source_type"] == "text"


def test_summarize_via_path_uses_read_document(monkeypatch) -> None:
    from app.application.agent.ports import ToolResult

    monkeypatch.setattr(
        "app.application.agent.tools.read_document.read_document_handler",
        lambda uid, args: ToolResult(
            ok=True,
            output="Contenido de doc.pdf:\n\nCapítulo uno del libro.",
        ),
    )
    monkeypatch.setattr(
        "app.services.provider_router.route_summarize",
        lambda content, **_: (f"Resumen: {content[:20]}", "text", 1),
    )

    result = summarize_handler("uid-test", {"path": "~/Desktop/doc.pdf"})

    assert result.ok is True
    assert "Capítulo uno" in result.output or "Resumen:" in result.output


def test_translate_summarize_registered_in_core_registry() -> None:
    from app.application.agent.tools import build_default_registry

    reg = build_default_registry(include_web_search=False)
    names = {s.name for s in reg.list_specs()}
    assert "translate" in names
    assert "summarize" in names
