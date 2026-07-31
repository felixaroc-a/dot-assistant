"""Parseo mínimo de acciones local_tool en respuestas del asistente (C2 WA)."""
from __future__ import annotations

import json
import re
from typing import Any

_VALID_OPS = frozenset({"readFile", "writeFile", "listFiles", "deleteFile"})


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    raw = text or ""
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = raw[start : i + 1]
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    # JSON truncado (p.ej. stream cortó el `}` final): intentar cerrar llaves
    return _repair_truncated_json_object(raw[start:])


def _repair_truncated_json_object(chunk: str) -> dict[str, Any] | None:
    """Cierra comillas/llaves abiertas lo mínimo para parsear local_tool truncado."""
    if '"action"' not in chunk and "'action'" not in chunk:
        return None
    candidate = chunk.rstrip()
    # Cerrar string abierto si terminó a mitad de valor
    in_str = False
    escape = False
    depth = 0
    for ch in candidate:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if in_str:
        candidate += '"'
    if depth > 0:
        candidate += "}" * depth
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_local_tool_action(text: str) -> dict[str, Any] | None:
    data = extract_first_json_object(text)
    if not data:
        return None
    if str(data.get("action") or "").lower() != "local_tool":
        return None
    operation = str(data.get("operation") or "").strip()
    if operation not in _VALID_OPS:
        return None
    path = str(data.get("path") or "").strip()
    content = data.get("content")
    if operation == "writeFile" and not isinstance(content, str):
        return None
    if operation != "listFiles" and not path:
        return None
    return {
        "operation": operation,
        "path": path,
        "content": content if isinstance(content, str) else None,
    }


def format_tool_result_for_wa(operation: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"No pude completar la acción de archivo ({operation}): {result.get('error') or 'error'}."
    if operation == "writeFile":
        return f"Listo. Archivo guardado en: {result.get('path') or 'ruta local'}."
    if operation == "readFile":
        content = str(result.get("content") or "")
        preview = content if len(content) <= 1500 else content[:1500] + "…"
        return f"Contenido de {result.get('path') or 'archivo'}:\n{preview}"
    if operation == "listFiles":
        files = result.get("files") or []
        if not isinstance(files, list) or not files:
            return "La carpeta está vacía (o no hay archivos visibles)."
        names = []
        for f in files[:40]:
            if isinstance(f, dict):
                names.append(str(f.get("name") or ""))
            else:
                names.append(str(f))
        return "Archivos:\n- " + "\n- ".join(n for n in names if n)
    if operation == "deleteFile":
        return f"Archivo eliminado: {result.get('path') or 'ok'}."
    return "Acción local completada."


_TRAILING_JSON = re.compile(r"\{[\s\S]*\"action\"\s*:\s*\"local_tool\"[\s\S]*\}\s*$", re.IGNORECASE)


def strip_local_tool_json(text: str) -> str:
    """Quita el bloque JSON de local_tool del mensaje hablado al usuario."""
    cleaned = _TRAILING_JSON.sub("", text or "").strip()
    return cleaned or text.strip()
