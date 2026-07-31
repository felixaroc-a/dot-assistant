"""Tests para document_output_service."""
from __future__ import annotations

from pathlib import Path

from app.services.document_output_service import (
    build_document_confirmation,
    build_output_filename,
    format_path_for_user,
    resolve_output_path,
    sanitize_document_title,
)


def test_sanitize_document_title_strips_unsafe_chars() -> None:
    assert sanitize_document_title('Informe "Ventas" 2026!') == "Informe Ventas 2026"


def test_build_output_filename_includes_date_and_extension() -> None:
    name = build_output_filename("Informe Ventas", "docx")
    assert name.endswith(".docx")
    assert "Informe Ventas" in name
    assert " - " in name


def test_resolve_output_path_avoids_collision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.document_output_service.get_desktop_work_dir",
        lambda: tmp_path,
    )
    first = resolve_output_path(kind="docx", title="Informe", extension="docx")
    first.write_bytes(b"x")
    second = resolve_output_path(kind="docx", title="Informe", extension="docx")
    assert first != second
    assert "(2)" in second.name


def test_build_document_confirmation_spanish() -> None:
    msg = build_document_confirmation(
        kind="docx",
        filename="Informe - 24-07-2026.docx",
        path=r"C:\Users\test\Desktop\DOT Trabajos\Documentos\Informe - 24-07-2026.docx",
    )
    assert "Listo." in msg
    assert "documento Word" in msg
    assert "Escritorio" in msg
    assert "Informe - 24-07-2026.docx" in msg
    assert "Ruta:" in msg


def test_format_path_for_user_desktop_prefix(tmp_path: Path, monkeypatch) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = desktop / "DOT Trabajos" / "Documentos" / "a.docx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    display = format_path_for_user(target)
    assert display.startswith("Escritorio/")
