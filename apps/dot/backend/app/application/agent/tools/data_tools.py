"""Tools de datos y analytics — F6e."""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.data")


def data_summary_stats_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Estadisticas descriptivas de un CSV/JSON."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path del archivo.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error lectura: {raw.get('error')}")

        content = str(raw.get("content") or "")
        ext = Path(path).suffix.lower()

        if ext == ".csv":
            reader = csv.DictReader(content.splitlines())
            rows = list(reader)
        elif ext == ".json":
            rows = json.loads(content)
            if not isinstance(rows, list):
                rows = [rows]
        else:
            return ToolResult(ok=False, output="", error="Formato no soportado. Usa .csv o .json.")

        if not rows:
            return ToolResult(ok=True, output="Archivo vacio.")

        numeric_cols = {}
        for row in rows:
            for k, v in row.items() if isinstance(row, dict) else []:
                if k not in numeric_cols:
                    numeric_cols[k] = []
                try:
                    numeric_cols[k].append(float(str(v).replace(",", ".")))
                except (ValueError, TypeError):
                    pass

        import statistics

        lines = [f"Estadisticas ({len(rows)} filas):"]
        for col, vals in numeric_cols.items():
            if len(vals) < 2:
                continue
            try:
                lines.append(
                    f"  {col}: med={statistics.median(vals):.2f} "
                    f"prom={statistics.mean(vals):.2f} "
                    f"min={min(vals):.2f} max={max(vals):.2f} "
                    f"stdev={statistics.stdev(vals):.2f}"
                )
            except Exception:
                pass

        cat_cols = [k for k in rows[0].keys() if k not in numeric_cols] if isinstance(rows[0], dict) else []
        for col in cat_cols[:3]:
            c = Counter(str(r.get(col, ""))[:30] for r in rows)
            lines.append(f"  {col}: top={c.most_common(5)}")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def data_filter_sort_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Filtra y ordena datos de CSV/JSON."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        column = str(arguments.get("column") or "").strip()
        sort_desc = bool(arguments.get("descending") or False)
        filter_val = str(arguments.get("filter") or "").strip()
        limit = int(arguments.get("limit") or 50)

        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error lectura: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines())) if path.endswith(".csv") else json.loads(content)
        if not isinstance(rows, list) or not rows:
            return ToolResult(ok=True, output="Sin datos.")

        if filter_val and column:
            rows = [r for r in rows if filter_val.lower() in str(r.get(column, "")).lower()]

        if column:
            try:
                rows.sort(key=lambda r: float(str(r.get(column, "0")).replace(",", ".")), reverse=sort_desc)
            except (ValueError, TypeError):
                rows.sort(key=lambda r: str(r.get(column, "")), reverse=sort_desc)

        result_rows = rows[:limit]
        out_path = str(Path(path).with_name(f"{Path(path).stem}_filtered.csv"))
        if result_rows:
            writer_io = ""
            import io
            writer_io_buf = io.StringIO()
            w = csv.DictWriter(writer_io_buf, fieldnames=list(result_rows[0].keys()))
            w.writeheader()
            w.writerows(result_rows)
            writer_io = writer_io_buf.getvalue()

            res = execute_local_tool_via_bridge("writeFile", path=out_path, content=writer_io)
            if res.get("ok"):
                return ToolResult(ok=True, output=f"Filtrado: {len(result_rows)} filas en {out_path}")
            return ToolResult(ok=False, output="", error=f"Error guardando: {res.get('error')}")

        return ToolResult(ok=True, output="Sin resultados tras filtrar.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def data_generate_chart_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera datos para un grafico desde CSV."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        x_col = str(arguments.get("x_column") or "").strip()
        y_col = str(arguments.get("y_column") or "").strip()

        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error lectura: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines()))

        if not rows or (x_col and not x_col):
            return ToolResult(ok=True, output="Sin datos para graficar.")

        # Usar primeras columnas si no se especifican
        cols = list(rows[0].keys())
        if not x_col:
            x_col = cols[0]
        if not y_col and len(cols) > 1:
            y_col = cols[1]

        points = []
        for r in rows[:50]:
            try:
                x = r.get(x_col, "")
                y = float(str(r.get(y_col, "0")).replace(",", "."))
                points.append({"x": str(x)[:20], "y": y})
            except (ValueError, TypeError):
                continue

        result = {"title": f"{y_col} vs {x_col}", "data": points, "count": len(points)}
        return ToolResult(ok=True, output=json.dumps(result, indent=2, ensure_ascii=False)[:3000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def data_categorize_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Categoriza filas de un CSV por una columna."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        column = str(arguments.get("column") or "").strip()

        if not path or not column:
            return ToolResult(ok=False, output="", error="Falta path y column.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error lectura: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines()))
        cats: dict[str, int] = {}
        for r in rows:
            val = str(r.get(column, "(vacio)"))[:50]
            cats[val] = cats.get(val, 0) + 1

        lines = [f"Categorias de '{column}' ({len(cats)}):"]
        for cat, cnt in sorted(cats.items(), key=lambda x: x[1], reverse=True)[:20]:
            lines.append(f"  {cat}: {cnt} ({cnt*100/max(1,len(rows)):.1f}%)")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def data_deduplicate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Elimina filas duplicadas de CSV."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"Error lectura: {raw.get('error')}")

        content = str(raw.get("content") or "")
        rows = list(csv.DictReader(content.splitlines()))
        seen = set()
        unique = []
        dups = 0

        for r in rows:
            key = json.dumps(dict(r), sort_keys=True, default=str)
            if key in seen:
                dups += 1
            else:
                seen.add(key)
                unique.append(r)

        out_path = str(Path(path).with_name(f"{Path(path).stem}_dedup.csv"))
        if unique:
            import io
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(unique[0].keys()))
            w.writeheader()
            w.writerows(unique)
            res = execute_local_tool_via_bridge("writeFile", path=out_path, content=buf.getvalue())
            if res.get("ok"):
                return ToolResult(ok=True, output=f"Duplicados eliminados: {dups} -> {len(unique)} filas. Guardado en {out_path}.")
            return ToolResult(ok=False, output="", error=f"Error guardando: {res.get('error')}")
        return ToolResult(ok=True, output="Sin datos.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))

TOOLS = [("data_summary_stats", data_summary_stats_handler), ("data_filter_sort", data_filter_sort_handler), ("data_generate_chart", data_generate_chart_handler), ("data_categorize", data_categorize_handler), ("data_deduplicate", data_deduplicate_handler)]
