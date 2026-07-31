"""Tools avanzadas de archivos — F6c."""
from __future__ import annotations

import csv
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.file_advanced")


def file_read_csv_json_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee y parsea CSV, JSON o XML."""
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"No se pudo leer: {raw.get('error')}")

        content = str(raw.get("content") or "")
        ext = Path(path).suffix.lower()

        if ext == ".csv":
            reader = csv.DictReader(content.splitlines())
            rows = list(reader)
            preview = str(rows[:20])[:3000] if rows else "(vacio)"
            return ToolResult(ok=True, output=f"CSV ({len(rows)} filas, {len(rows[0]) if rows else 0} cols):\n{preview}")
        elif ext in (".json",):
            data = json.loads(content)
            if isinstance(data, list):
                preview = str(data[:10])[:3000]
                return ToolResult(ok=True, output=f"JSON ({len(data)} items):\n{preview}")
            return ToolResult(ok=True, output=str(data)[:3000])
        else:
            return ToolResult(ok=True, output=content[:5000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_convert_format_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte entre formatos (CSV->XLSX, JSON->CSV, etc.)."""
    try:
        path = str(arguments.get("path") or "").strip()
        to_format = str(arguments.get("to") or arguments.get("format") or "").strip().lower()
        if not path or not to_format:
            return ToolResult(ok=False, output="", error="Falta path y to/formato.")

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error=f"No se pudo leer: {raw.get('error')}")

        content = str(raw.get("content") or "")
        src_ext = Path(path).suffix.lower()
        dest = str(Path(path).with_suffix(f".{to_format}"))

        if src_ext == ".csv" and to_format == "json":
            reader = csv.DictReader(content.splitlines())
            data = list(reader)
            out = json.dumps(data, indent=2, ensure_ascii=False)
        elif src_ext == ".json" and to_format == "csv":
            data = json.loads(content)
            if isinstance(data, list) and data:
                writer_io = __import__("io").StringIO()
                writer = csv.DictWriter(writer_io, fieldnames=list(data[0].keys()) if isinstance(data[0], dict) else ["value"])
                writer.writeheader()
                if isinstance(data[0], dict):
                    writer.writerows(data)
                else:
                    for v in data:
                        writer.writerow({"value": str(v)})
                out = writer_io.getvalue()
            else:
                out = content
        else:
            out = content

        res = execute_local_tool_via_bridge("writeFile", path=dest, content=out)
        if res.get("ok"):
            return ToolResult(ok=True, output=f"Convertido: {dest}")
        return ToolResult(ok=False, output="", error=f"Error guardando: {res.get('error')}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_compress_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Comprime archivo/carpeta a ZIP."""
    try:
        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        p = Path(path)
        zip_path = str(p.with_suffix(".zip") if p.is_file() else str(p) + ".zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if p.is_dir():
                for root, _, files in os.walk(p):
                    for f in files:
                        fp = os.path.join(root, f)
                        zf.write(fp, os.path.relpath(fp, str(p)))
            else:
                zf.write(p, p.name)
        return ToolResult(ok=True, output=f"Comprimido: {zip_path}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_decompress_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Descomprime ZIP."""
    try:
        path = str(arguments.get("path") or "").strip()
        dest = str(arguments.get("dest") or Path(path).with_suffix(""))
        if not path or not path.endswith(".zip"):
            return ToolResult(ok=False, output="", error="Falta path de archivo .zip.")

        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(dest)
        return ToolResult(ok=True, output=f"Descomprimido en: {dest}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_find_duplicates_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Encuentra archivos duplicados en una carpeta."""
    try:
        folder = str(arguments.get("folder") or arguments.get("path") or "~/Desktop").strip()
        from collections import defaultdict
        from pathlib import Path

        hashes: dict[str, list[str]] = defaultdict(list)
        import hashlib

        for root, _, files in os.walk(Path(folder).expanduser()):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    h = hashlib.md5(open(fp, "rb").read(8192)).hexdigest()  # noqa: S324
                    hashes[h].append(fp)
                except Exception:
                    continue
                if len(hashes) > 200:
                    break

        dups = {h: paths for h, paths in hashes.items() if len(paths) > 1}
        if not dups:
            return ToolResult(ok=True, output="No se encontraron duplicados.")

        lines = [f"Duplicados encontrados ({len(dups)} grupos):"]
        for paths in list(dups.values())[:10]:
            size = os.path.getsize(paths[0]) if os.path.exists(paths[0]) else 0
            lines.append(f"- {size:,} bytes: {len(paths)} copias -> {paths[0][:80]}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_rename_bulk_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Renombra archivos en lote con patron."""
    try:
        folder = str(arguments.get("folder") or "~/Desktop").strip()
        pattern = str(arguments.get("pattern") or "").strip()
        if not pattern:
            return ToolResult(ok=False, output="", error="Falta pattern.")

        import re as _re
        import shutil

        folder_path = Path(folder).expanduser()
        matches = [f for f in folder_path.iterdir() if f.is_file() and _re.search(pattern, f.name)]

        renamed = 0
        replacement = str(arguments.get("replacement") or "").strip()
        prefix = str(arguments.get("prefix") or "").strip()

        for f in matches[:50]:
            new_name = _re.sub(pattern, replacement, f.name) if replacement else f.name
            if prefix:
                new_name = f"{prefix}_{new_name}"
            new_path = folder_path / new_name
            shutil.move(str(f), str(new_path))
            renamed += 1

        return ToolResult(ok=True, output=f"Renombrados: {renamed} archivos en {folder_path}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def file_get_metadata_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene metadatos de un archivo."""
    try:
        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")

        p = Path(path)
        stat = p.stat()
        info = {
            "nombre": p.name,
            "ruta": str(p),
            "tamano_bytes": stat.st_size,
            "tamano": f"{stat.st_size:,} bytes",
            "modificado": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "creado": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "extension": p.suffix,
            "es_directorio": p.is_dir(),
        }
        return ToolResult(ok=True, output=json.dumps(info, indent=2, ensure_ascii=False))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))

TOOLS = [("file_read_csv_json", file_read_csv_json_handler), ("file_convert_format", file_convert_format_handler), ("file_compress", file_compress_handler), ("file_decompress", file_decompress_handler), ("file_find_duplicates", file_find_duplicates_handler), ("file_rename_bulk", file_rename_bulk_handler), ("file_get_metadata", file_get_metadata_handler)]
