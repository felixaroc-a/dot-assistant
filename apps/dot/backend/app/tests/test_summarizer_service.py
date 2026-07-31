"""Tests del SummarizerService."""
from __future__ import annotations

from app.services.summarizer_service import SummarizerService


def test_summarizer_service_texto_simple() -> None:
    service = SummarizerService(max_chunk_chars=200, overlap_chars=50)
    calls: list[str] = []

    def _summarize(prompt: str) -> str:
        calls.append(prompt)
        return "Resumen simple"

    result = service.summarize("Este es un texto corto para pruebas.", _summarize)
    assert result["summary"] == "Resumen simple"
    assert result["source_type"] == "text"
    assert result["chunks"] == 1
    assert len(calls) == 1


def test_summarizer_service_chunking_con_merge() -> None:
    service = SummarizerService(max_chunk_chars=1_000, overlap_chars=200)
    source = ("Bloque de prueba " * 250).strip()
    calls: list[str] = []

    def _summarize(prompt: str) -> str:
        calls.append(prompt)
        return f"Resumen {len(calls)}"

    result = service.summarize(source, _summarize)
    assert result["source_type"] == "text"
    assert int(result["chunks"]) > 1
    # chunks parciales + 1 llamada para unificar
    assert len(calls) == int(result["chunks"]) + 1
    assert str(result["summary"]).startswith("Resumen")


def test_summarizer_service_resuelve_url_html(monkeypatch) -> None:
    service = SummarizerService()

    class _FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        text = "<html><body><h1>Titulo</h1><p>Contenido</p></body></html>"
        content = b""

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url: str):
            return _FakeResponse()

    monkeypatch.setattr("app.services.summarizer_service.httpx.Client", lambda **_kwargs: _FakeClient())
    monkeypatch.setattr(service, "_extract_html_text", lambda _html: "texto html extraído")

    source_type, extracted = service._resolve_source("https://example.com/post")
    assert source_type == "url"
    assert extracted == "texto html extraído"


def test_summarizer_service_resuelve_url_pdf(monkeypatch) -> None:
    service = SummarizerService()

    class _FakeResponse:
        headers = {"content-type": "application/pdf"}
        text = ""
        content = b"%PDF-1.7 dummy"

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url: str):
            return _FakeResponse()

    monkeypatch.setattr("app.services.summarizer_service.httpx.Client", lambda **_kwargs: _FakeClient())
    monkeypatch.setattr(service, "_extract_pdf_text", lambda _bytes: "texto pdf extraído")

    source_type, extracted = service._resolve_source("https://example.com/reporte.pdf")
    assert source_type == "pdf_url"
    assert extracted == "texto pdf extraído"
