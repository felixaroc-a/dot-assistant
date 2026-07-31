"""Tests de read_spreadsheet (agent core)."""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl

from app.application.agent.tools.read_spreadsheet import read_spreadsheet_handler


def _make_xlsx_bytes(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ventas"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_spreadsheet_requires_path() -> None:
    result = read_spreadsheet_handler("uid-test", {})
    assert result.ok is False
    assert "read_spreadsheet necesita" in (result.error or "")


def test_read_spreadsheet_rejects_unsupported_ext() -> None:
    result = read_spreadsheet_handler("uid-test", {"path": "~/Desktop/notas.txt"})
    assert result.ok is False
    assert "Formato no soportado" in (result.error or "")


def test_read_spreadsheet_analyzes_xlsx(monkeypatch, tmp_path: Path) -> None:
    xlsx_path = tmp_path / "ventas.xlsx"
    data = _make_xlsx_bytes([
        ["Producto", "Cantidad", "Precio"],
        ["Camisa", 10, 25.5],
        ["Pantalón", 5, 40],
        ["Camisa", 3, 25.5],
    ])
    xlsx_path.write_bytes(data)

    monkeypatch.setattr(
        "app.application.agent.tools.read_spreadsheet._read_file_bytes",
        lambda path: (data, None),
    )

    result = read_spreadsheet_handler("uid-test", {"path": str(xlsx_path), "sample_rows": 2})

    assert result.ok is True
    assert "Ventas" in result.output
    assert "Producto" in result.output
    assert "Camisa" in result.output
    assert "Estadísticas básicas" in result.output
    assert result.artifacts[0]["type"] == "spreadsheet_analysis"


def test_read_spreadsheet_unknown_sheet(monkeypatch, tmp_path: Path) -> None:
    data = _make_xlsx_bytes([["A"], [1]])
    monkeypatch.setattr(
        "app.application.agent.tools.read_spreadsheet._read_file_bytes",
        lambda path: (data, None),
    )

    result = read_spreadsheet_handler(
        "uid-test",
        {"path": str(tmp_path / "datos.xlsx"), "sheet": "Inexistente"},
    )

    assert result.ok is False
    assert "No encontré la hoja" in (result.error or "")


def test_read_spreadsheet_export_csv(monkeypatch, tmp_path: Path) -> None:
    data = _make_xlsx_bytes([["Col"], [1], [2]])
    written: dict = {}

    monkeypatch.setattr(
        "app.application.agent.tools.read_spreadsheet._read_file_bytes",
        lambda path: (data, None),
    )

    def fake_bridge(op, **kwargs):
        if op == "writeFile":
            written["path"] = kwargs.get("path")
            written["content"] = kwargs.get("content")
            return {"ok": True, "path": kwargs.get("path")}
        return {"ok": False}

    monkeypatch.setattr(
        "app.application.agent.tools.local_files.execute_local_tool_via_bridge",
        fake_bridge,
    )

    result = read_spreadsheet_handler(
        "uid-test",
        {"path": str(tmp_path / "datos.xlsx"), "export_csv": True},
    )

    assert result.ok is True
    assert "CSV exportado" in result.output
    assert written.get("content", "").startswith("Col")


def test_tool_registered() -> None:
    from app.application.agent.tools import build_default_registry

    specs = {s.name for s in build_default_registry().list_specs()}
    assert "read_spreadsheet" in specs
