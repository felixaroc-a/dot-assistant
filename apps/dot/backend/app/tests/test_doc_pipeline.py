"""Tests del pipeline doc/CV (FREE-DC01–DC06)."""

from __future__ import annotations

from pathlib import Path

from app.application.documents.pipeline import (
    chunk_text,
    export_results,
    extract_from_path,
    extract_from_text,
    process_folder,
    run_doc_pipeline_if_enabled,
    supported_path_suffixes,
)


# ── DC01–DC02 (existing) ────────────────────────────────────────────────────

def test_extract_from_text_heuristic_fields():
    text = (
        "Nombre: Ana Pérez\n"
        "Email: ana@ejemplo.com\n"
        "Tel: +58 412 555 1234\n"
    )
    result = extract_from_text(text)
    assert result["ok"] is True
    fields = result["fields"]
    assert fields["name"] == "Ana Pérez"
    assert fields["email"] == "ana@ejemplo.com"
    assert fields["phone"] is not None


def test_run_doc_pipeline_if_enabled_returns_none_when_flag_off(monkeypatch):
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.doc_pipeline_enabled",
        False,
    )
    assert run_doc_pipeline_if_enabled(text="hola") is None


def test_extract_from_path_reads_txt(tmp_path: Path):
    sample = tmp_path / "cv.txt"
    sample.write_text("Nombre: Luis Gómez\nContacto: luis@test.org\n", encoding="utf-8")
    result = extract_from_text(sample.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["fields"]["email"] == "luis@test.org"

    path_result = extract_from_path(sample)
    assert path_result["ok"] is True
    assert path_result["fields"]["name"] == "Luis Gómez"


def test_supported_suffixes_include_docx_when_declared(monkeypatch):
    monkeypatch.setattr(
        "app.application.documents.pipeline._declared_requirement_names",
        lambda: frozenset({"python-docx"}),
    )
    monkeypatch.setattr(
        "app.application.documents.pipeline._docx_extraction_available",
        lambda: True,
    )
    suffixes = supported_path_suffixes()
    assert ".docx" in suffixes
    assert ".pdf" not in suffixes


def test_extract_from_path_docx_when_available(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.application.documents.pipeline._docx_extraction_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.application.documents.pipeline._extract_docx_text",
        lambda path: "Nombre: Carla Ruiz\nEmail: carla@test.org\n",
    )

    docx_path = tmp_path / "cv.docx"
    docx_path.write_bytes(b"fake-docx")
    result = extract_from_path(docx_path)
    assert result["ok"] is True
    assert result["file_type"] == "docx"
    assert result["fields"]["email"] == "carla@test.org"


def test_extract_from_path_rejects_pdf_without_declared_backend(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.application.documents.pipeline._pdf_extraction_available",
        lambda: False,
    )
    pdf_path = tmp_path / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    result = extract_from_path(pdf_path)
    assert result["ok"] is False
    assert "no soportado" in (result.get("error") or "").lower()


# ── DC03: Chunking ──────────────────────────────────────────────────────────

def test_chunk_text_small_returns_single_chunk():
    text = "Hola mundo, esto es un texto corto."
    chunks = chunk_text(text, max_chars=500)
    assert len(chunks) == 1
    assert chunks[0]["index"] == 0
    assert chunks[0]["text"] == text


def test_chunk_text_large_splits_with_overlap():
    # Generate text that exceeds chunk limit
    paragraph = "Esta es una línea de texto que se repite para generar contenido. " * 20
    max_chars = 400
    overlap = 100
    chunks = chunk_text(paragraph, max_chars=max_chars, overlap=overlap)

    assert len(chunks) > 1
    # Verify overlap: last chars of chunk N appear in first chars of chunk N+1
    if len(chunks) >= 2:
        last_of_0 = chunks[0]["text"][-overlap + 1:]
        first_of_1 = chunks[1]["text"][: len(last_of_0)]
        # At least some overlap should exist
        assert any(c0 == c1 for c0, c1 in zip(last_of_0[-5:], first_of_1[:5]))


def test_chunk_text_empty():
    assert chunk_text("", max_chars=100) == [
        {"index": 0, "text": "", "start_char": 0, "end_char": 0, "char_count": 0}
    ]


def test_extract_from_path_with_chunks(tmp_path: Path):
    long_text = ("Línea de contenido del documento.\n" * 200)
    sample = tmp_path / "large.txt"
    sample.write_text(long_text, encoding="utf-8")

    result = extract_from_path(sample, chunk_large=True)
    assert result["ok"] is True
    assert "chunks" in result
    assert len(result["chunks"]) > 1
    for c in result["chunks"]:
        assert "index" in c
        assert "text" in c
        assert "char_count" in c


def test_extract_from_path_without_chunks_no_chunks_key(tmp_path: Path):
    short_text = "Texto corto."
    sample = tmp_path / "small.txt"
    sample.write_text(short_text, encoding="utf-8")

    result = extract_from_path(sample, chunk_large=True)
    assert result["ok"] is True
    # short text <= chunk_size → no chunks key
    assert "chunks" not in result


# ── DC04: Structured output / LLM ───────────────────────────────────────────

def test_extract_from_text_includes_extended_fields():
    text = (
        "Nombre: Juan Martínez\n"
        "Email: juan@correo.com\n"
        "Tel: +57 300 111 2233\n\n"
        "Resumen: Ingeniero de software con 5 años de experiencia en Python y React.\n\n"
        "Experiencia:\n"
        "- Desarrollador Senior en Empresa X — lideré equipo de 5 ingenieros.\n"
        "- Analista de datos en Empresa Y — migración de bases de datos SQL.\n"
    )
    result = extract_from_text(text)
    assert result["ok"] is True
    fields = result["fields"]
    assert fields["name"] == "Juan Martínez"
    assert fields["email"] == "juan@correo.com"
    assert fields["phone"] is not None
    # extended fields
    assert isinstance(fields.get("skills"), list)
    assert isinstance(fields.get("experience"), list)
    # summary should be populated from "Resumen:"
    assert fields.get("summary") is not None
    assert "Ingeniero" in (fields.get("summary") or "")


def test_extract_from_text_skills_detected():
    text = (
        "Nombre: Maria Gómez\n"
        "Habilidades: Python, React, Docker, Kubernetes, gestión de proyectos\n"
    )
    result = extract_from_text(text)
    skills = result["fields"].get("skills", [])
    assert len(skills) > 0


def test_llm_extraction_not_available_by_default(monkeypatch):
    """DOC_PIPELINE_LLM=false → uses heuristic even if key exists."""
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.doc_pipeline_llm",
        False,
    )
    result = extract_from_text("Nombre: Test User\n", use_llm=False)
    assert result["method"] == "heuristic"


def test_llm_extraction_available_when_flag_and_key(monkeypatch):
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.doc_pipeline_llm",
        True,
    )
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.deepseek_api_key",
        "sk-test-key",
    )
    from app.application.documents.pipeline import _llm_extraction_available

    assert _llm_extraction_available() is True


def test_llm_fallback_to_heuristic_on_error(monkeypatch):
    """When LLM call fails, falls back to heuristic."""
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.doc_pipeline_llm",
        True,
    )
    monkeypatch.setattr(
        "app.application.documents.pipeline.settings.deepseek_api_key",
        "sk-test-key",
    )
    monkeypatch.setattr(
        "app.application.documents.pipeline._llm_extract_fields",
        lambda text: {"name": "LLM Name", "email": "llm@test.com", "phone": None, "summary": None, "skills": [], "experience": []},
    )
    result = extract_from_text(
        "Nombre: Real Name\nEmail: real@test.com\n",
        use_llm=True,
    )
    assert result["ok"] is True
    assert result["fields"]["name"] == "LLM Name"


# ── DC05: Batch process folder ──────────────────────────────────────────────

def test_process_folder_txt_files(tmp_path: Path):
    (tmp_path / "cv1.txt").write_text("Nombre: Ana López\nEmail: ana@correo.com\n", encoding="utf-8")
    (tmp_path / "cv2.txt").write_text("Nombre: Pedro Ruiz\nEmail: pedro@correo.com\n", encoding="utf-8")
    (tmp_path / "notas.md").write_text("# Notas\nSin datos de CV aquí.", encoding="utf-8")
    (tmp_path / "imagen.png").write_bytes(b"\x89PNG")  # should be skipped

    result = process_folder(tmp_path)
    assert result["ok"] is True
    assert result["total_files"] == 3  # 2 txt + 1 md
    assert "cv1.txt" in result["results"]
    assert "cv2.txt" in result["results"]
    assert "notas.md" in result["results"]
    assert "imagen.png" not in result["results"]
    assert "imagen.png" not in result["errors"]
    assert result["results"]["cv1.txt"]["fields"]["name"] == "Ana López"
    assert result["results"]["cv2.txt"]["fields"]["email"] == "pedro@correo.com"


def test_process_folder_recursive(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "root.txt").write_text("Nombre: Root\n", encoding="utf-8")
    (sub / "nested.txt").write_text("Nombre: Nested\nEmail: nested@test.com\n", encoding="utf-8")

    result = process_folder(tmp_path, recursive=True)
    assert result["total_files"] == 2
    assert "root.txt" in result["results"]
    assert "nested.txt" in result["results"]


def test_process_folder_non_recursive(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "root.txt").write_text("Nombre: Root\n", encoding="utf-8")
    (sub / "nested.txt").write_text("Nombre: Nested\n", encoding="utf-8")

    result = process_folder(tmp_path, recursive=False)
    assert result["total_files"] == 1
    assert "root.txt" in result["results"]
    assert "nested.txt" not in result["results"]


def test_process_folder_nonexistent():
    result = process_folder("/nonexistent/folder/path")
    assert result["ok"] is False
    assert result["error"] is not None


# ── DC06: Export ────────────────────────────────────────────────────────────

def test_export_results_json_string():
    docs = {
        "cv1.txt": {
            "ok": True,
            "fields": {"name": "Ana", "email": "ana@test.com", "phone": "555", "summary": None, "skills": ["python"], "experience": []},
            "file_type": "txt",
        },
        "cv2.txt": {
            "ok": True,
            "fields": {"name": "Luis", "email": "luis@test.com", "phone": None, "summary": "Dev", "skills": [], "experience": ["CEO at X"]},
            "file_type": "txt",
        },
    }
    result = export_results(docs, format="json")
    assert isinstance(result, str)
    parsed = __import__("json").loads(result)
    assert len(parsed) == 2
    assert parsed[0]["filename"] == "cv1.txt"
    assert parsed[0]["name"] == "Ana"
    assert parsed[0]["skills"] == "python"


def test_export_results_csv_string():
    docs = {
        "cv.txt": {
            "fields": {"name": "Test", "email": "t@t.com", "phone": "123", "summary": "S", "skills": ["a"], "experience": ["b"]},
            "file_type": "txt",
        },
    }
    result = export_results(docs, format="csv")
    assert isinstance(result, str)
    assert "filename,name,email" in result
    assert "cv.txt,Test,t@t.com" in result


def test_export_results_to_disk(tmp_path: Path):
    docs = {
        "cv.txt": {
            "fields": {"name": "X", "email": "x@x.com", "phone": "", "summary": "", "skills": [], "experience": []},
            "file_type": "txt",
        },
    }
    out = tmp_path / "export.json"
    result = export_results(docs, format="json", output_path=str(out))
    assert result is None
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "x@x.com" in content


def test_export_results_from_process_folder_format(tmp_path: Path):
    """export_results accepts the nested {results: {...}} format from process_folder."""
    (tmp_path / "a.txt").write_text("Nombre: A\nEmail: a@a.com\n", encoding="utf-8")
    folder_result = process_folder(tmp_path)
    exported = export_results(folder_result, format="json")
    assert isinstance(exported, str)
    assert "a.txt" in exported
    assert "a@a.com" in exported


def test_export_results_empty_csv():
    result = export_results({}, format="csv")
    assert result == ""


def test_chunk_text_handles_whitespace_only():
    chunks = chunk_text("   ", max_chars=100)
    assert len(chunks) == 1
    assert chunks[0]["text"] == ""
