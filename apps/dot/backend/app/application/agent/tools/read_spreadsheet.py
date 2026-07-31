"""Tool: read_spreadsheet — lee y analiza hojas XLSX/XLS del PC del usuario."""

from __future__ import annotations

import base64
import csv
import io
import logging
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.read_spreadsheet")

SUPPORTED_EXTS = {".xlsx", ".xlsm", ".xls"}
MAX_OUTPUT_CHARS = 14_000
DEFAULT_SAMPLE_ROWS = 5
MAX_ROWS_SCAN = 5_000


def _bridge_human_error(err: str) -> str:
    return {
        "bridge_secret_not_configured": "El puente local no está configurado. Abre la app DOT en el PC.",
        "bridge_unreachable": "No se pudo conectar con el PC (bridge). ¿Está abierta la app DOT?",
        "bridge_unauthorized": "El puente local rechazó la autenticación.",
    }.get(err, err)


def _read_file_bytes(path: str) -> tuple[bytes | None, str | None]:
    """Lee bytes de una ruta local vía bridge o filesystem (tests)."""
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    result = execute_local_tool_via_bridge("readFileBytes", path=path)
    if isinstance(result, dict) and result.get("ok"):
        b64 = result.get("content_base64") or result.get("contentBase64")
        if b64:
            return base64.b64decode(str(b64)), None
        content = result.get("content")
        if isinstance(content, str):
            return content.encode("utf-8"), None

    expanded = os.path.expanduser(os.path.expandvars(path))
    if os.path.isfile(expanded):
        with open(expanded, "rb") as handle:
            return handle.read(), None

    err = str(result.get("error") if isinstance(result, dict) else "archivo no accesible")
    return None, _bridge_human_error(err)


def _normalize_header(value: Any, index: int) -> str:
    if value is None or str(value).strip() == "":
        return f"col_{index + 1}"
    return str(value).strip()


def _row_to_dict(headers: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for idx, header in enumerate(headers):
        data[header] = row[idx] if idx < len(row) else None
    return data


def _compute_stats_lines(rows: list[dict[str, Any]], headers: list[str]) -> list[str]:
    if not rows:
        return ["  (sin filas de datos)"]

    numeric_cols: dict[str, list[float]] = {}
    for row in rows:
        for header in headers:
            raw = row.get(header)
            if raw is None or str(raw).strip() == "":
                continue
            try:
                numeric_cols.setdefault(header, []).append(
                    float(str(raw).replace(",", ".").replace("$", "").strip())
                )
            except (ValueError, TypeError):
                pass

    lines: list[str] = []
    for header in headers:
        vals = numeric_cols.get(header, [])
        if len(vals) >= 2:
            try:
                lines.append(
                    f"  {header}: med={statistics.median(vals):.2f} "
                    f"prom={statistics.mean(vals):.2f} "
                    f"min={min(vals):.2f} max={max(vals):.2f} "
                    f"stdev={statistics.stdev(vals):.2f} (n={len(vals)})"
                )
            except statistics.StatisticsError:
                pass

    cat_headers = [h for h in headers if h not in numeric_cols or len(numeric_cols.get(h, [])) < 2]
    for header in cat_headers[:3]:
        counter = Counter(str(row.get(header, ""))[:40] for row in rows if row.get(header) not in (None, ""))
        if counter:
            top = ", ".join(f"{k} ({v})" for k, v in counter.most_common(5))
            lines.append(f"  {header}: top → {top}")

    return lines or ["  (sin estadísticas numéricas detectadas)"]


def _format_sample_rows(rows: list[dict[str, Any]], headers: list[str], sample_n: int) -> list[str]:
    if not rows:
        return ["  (vacío)"]
    lines: list[str] = []
    for row in rows[:sample_n]:
        cells = " | ".join(f"{h}={row.get(h)!r}" for h in headers[:8])
        if len(headers) > 8:
            cells += " | …"
        lines.append(f"  • {cells}")
    return lines


def _parse_openpyxl(data: bytes) -> dict[str, list[dict[str, Any]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets: dict[str, list[dict[str, Any]]] = {}
    try:
        for ws in wb.worksheets:
            rows_iter = ws.iter_rows(values_only=True)
            first = next(rows_iter, None)
            if first is None:
                sheets[ws.title] = []
                continue
            headers = [_normalize_header(v, i) for i, v in enumerate(first)]
            parsed: list[dict[str, Any]] = []
            for row in rows_iter:
                if row is None or all(c is None or str(c).strip() == "" for c in row):
                    continue
                parsed.append(_row_to_dict(headers, row))
                if len(parsed) >= MAX_ROWS_SCAN:
                    break
            sheets[ws.title] = parsed
    finally:
        wb.close()
    return sheets


def _parse_xlrd(data: bytes) -> dict[str, list[dict[str, Any]]]:
    try:
        import xlrd
    except ImportError as exc:
        raise ImportError(
            "Para archivos .xls antiguos falta xlrd. Guarda el archivo como .xlsx e inténtalo de nuevo."
        ) from exc

    book = xlrd.open_workbook(file_contents=data)
    sheets: dict[str, list[dict[str, Any]]] = {}
    for sheet in book.sheets():
        if sheet.nrows == 0:
            sheets[sheet.name] = []
            continue
        header_row = sheet.row_values(0)
        headers = [_normalize_header(v, i) for i, v in enumerate(header_row)]
        parsed: list[dict[str, Any]] = []
        for row_idx in range(1, min(sheet.nrows, MAX_ROWS_SCAN + 1)):
            row_vals = sheet.row_values(row_idx)
            if all(v in ("", None) for v in row_vals):
                continue
            parsed.append(_row_to_dict(headers, tuple(row_vals)))
        sheets[sheet.name] = parsed
    return sheets


def _parse_workbook(path: str, data: bytes) -> dict[str, list[dict[str, Any]]]:
    ext = Path(path).suffix.lower()
    if ext in {".xlsx", ".xlsm"}:
        return _parse_openpyxl(data)
    if ext == ".xls":
        return _parse_xlrd(data)
    raise ValueError(f"Extensión no soportada: {ext}")


def _export_sheet_csv(
    uid: str,
    source_path: str,
    sheet_name: str,
    headers: list[str],
    rows: list[dict[str, Any]],
) -> str | None:
    if not rows or not headers:
        return None
    out_path = str(
        Path(source_path).with_name(f"{Path(source_path).stem}_{sheet_name}_dot.csv".replace(" ", "_"))
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    result = execute_local_tool_via_bridge("writeFile", path=out_path, content=buf.getvalue())
    if result.get("ok"):
        return out_path
    log.warning("read_spreadsheet export_csv falló uid=%s path=%s err=%s", uid[:8], out_path, result.get("error"))
    return None


def read_spreadsheet_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee y analiza un Excel (.xlsx/.xls) del PC: hojas, columnas, muestra y stats.

    Args:
        arguments:
            path (str): ruta al archivo (~Desktop/ventas.xlsx o absoluta).
            sheet (str, opcional): nombre de hoja concreta; si omites, resume todas.
            sample_rows (int, opcional): filas de muestra por hoja (default 5).
            export_csv (bool, opcional): exporta la hoja analizada a CSV para data_* tools.
    """
    path_raw = str(arguments.get("path") or "").strip()
    if not path_raw:
        return ToolResult(
            ok=False,
            output="",
            error="read_spreadsheet necesita la ruta del archivo Excel (path).",
        )

    ext = Path(path_raw).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"Formato no soportado: {ext or 'sin extensión'}. "
                "Usa archivos .xlsx o .xls de Excel."
            ),
        )

    sheet_filter = str(arguments.get("sheet") or "").strip()
    try:
        sample_rows = max(1, min(int(arguments.get("sample_rows") or DEFAULT_SAMPLE_ROWS), 20))
    except (TypeError, ValueError):
        sample_rows = DEFAULT_SAMPLE_ROWS
    export_csv = bool(arguments.get("export_csv"))

    data, read_err = _read_file_bytes(path_raw)
    if read_err or data is None:
        return ToolResult(
            ok=False,
            output="",
            error=read_err or "No pude leer el archivo Excel. Revisa la ruta y que DOT esté abierto.",
        )

    try:
        sheets = _parse_workbook(path_raw, data)
    except ImportError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    except Exception as exc:
        log.exception("Error parseando Excel path=%s", path_raw[:120])
        return ToolResult(
            ok=False,
            output="",
            error=f"No pude abrir el Excel. ¿Está corrupto o protegido con contraseña? ({exc})",
        )

    if not sheets:
        return ToolResult(ok=False, output="", error="El archivo Excel no contiene hojas legibles.")

    if sheet_filter:
        if sheet_filter not in sheets:
            available = ", ".join(sheets.keys())
            return ToolResult(
                ok=False,
                output="",
                error=f"No encontré la hoja «{sheet_filter}». Hojas disponibles: {available}.",
            )
        sheets = {sheet_filter: sheets[sheet_filter]}

    filename = Path(path_raw).name
    lines = [f"Análisis de {filename} ({len(sheets)} hoja(s)):"]
    csv_export_path: str | None = None
    total_rows = 0

    for sheet_name, rows in sheets.items():
        headers: list[str] = []
        if rows:
            headers = list(rows[0].keys())
        elif sheet_filter:
            lines.append(f"\n## Hoja: {sheet_name}")
            lines.append("  (vacía)")
            continue

        total_rows += len(rows)
        lines.append(f"\n## Hoja: {sheet_name}")
        lines.append(f"Filas de datos: {len(rows)}")
        lines.append(f"Columnas ({len(headers)}): {', '.join(headers[:20])}" + (" …" if len(headers) > 20 else ""))
        lines.append("Muestra:")
        lines.extend(_format_sample_rows(rows, headers, sample_rows))
        lines.append("Estadísticas básicas:")
        lines.extend(_compute_stats_lines(rows, headers))

        if export_csv and csv_export_path is None and rows:
            csv_export_path = _export_sheet_csv(uid, path_raw, sheet_name, headers, rows)

    output = "\n".join(lines)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n\n[Análisis truncado — pide una hoja concreta con sheet=…]"

    if csv_export_path:
        output += (
            f"\n\nCSV exportado para análisis avanzado (data_summary_stats, data_filter_sort, etc.): "
            f"{csv_export_path}"
        )

    artifacts: list[dict[str, Any]] = [{
        "type": "spreadsheet_analysis",
        "path": path_raw,
        "sheets": list(sheets.keys()),
        "row_count": total_rows,
    }]
    if csv_export_path:
        artifacts.append({"type": "csv_export", "path": csv_export_path})

    return ToolResult(ok=True, output=output, artifacts=artifacts)
