"""Protocolo estricto de tool_calls parseable dentro del runtime (multi-turn).

DeepSeek v1 no usa function-calling nativo estable aquí: el modelo puede
devolver JSON de tool_calls entre turnos del runtime. Path feliz futuro;
NO es trailing-JSON del frontend.

También acepta un formato XML erróneo que a veces inventa el modelo:
  <listFiles><path>C:\\Users\\...\\carpeta</path></listFiles>
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.application.agent.ports import ToolCall

log = logging.getLogger("dot.agent.tool_protocol")

# Bloque completo o trailing con tool_calls
_TOOL_CALLS_BLOCK = re.compile(
    r"\{[\s\S]*\"tool_calls\"\s*:\s*\[[\s\S]*\][\s\S]*\}\s*$",
    re.IGNORECASE,
)

# Tools que el modelo a veces envuelve en XML en vez de JSON
_XML_TOOL_NAMES = (
    "listFiles",
    "readFile",
    "writeFile",
    "deleteFile",
    "file_search",
    "web_search",
    "download_url_to_desktop",
    "gmail_send",
    "generate_document",
    "generate_spreadsheet",
    "send_whatsapp_message",
    "read_document",
    "read_spreadsheet",
    "analyze_cv",
    "parseDocument",
    "translate",
    "summarize",
)
_XML_TOOL_RE = re.compile(
    r"<(" + "|".join(_XML_TOOL_NAMES) + r")\s*>(.*?)</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_XML_ARG_RE = re.compile(r"<(\w+)\s*>(.*?)</\1\s*>", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Intento directo
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Trailing object
    match = _TOOL_CALLS_BLOCK.search(raw)
    if not match:
        # Buscar primer { ... } que contenga tool_calls
        start = raw.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(raw)):
            ch = raw[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = raw[start : i + 1]
                    try:
                        data = json.loads(chunk)
                        if isinstance(data, dict) and "tool_calls" in data:
                            return data
                    except json.JSONDecodeError:
                        return None
                    break
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_xml_tool_calls(model_text: str) -> list[ToolCall] | None:
    """Convierte <toolName><arg>...</arg></toolName> a ToolCall."""
    raw = model_text or ""
    calls: list[ToolCall] = []
    for match in _XML_TOOL_RE.finditer(raw):
        found = match.group(1)
        name = next((n for n in _XML_TOOL_NAMES if n.lower() == found.lower()), found)
        inner = match.group(2) or ""
        args: dict[str, Any] = {}
        for am in _XML_ARG_RE.finditer(inner):
            key = am.group(1).strip()
            val = (am.group(2) or "").strip()
            if key.lower() == name.lower():
                continue
            args[key] = val
        if not args and inner.strip():
            if name in {"listFiles", "readFile", "deleteFile", "read_document", "read_spreadsheet", "analyze_cv"}:
                args["path"] = inner.strip()
            elif name in {"translate", "summarize"}:
                args["text"] = inner.strip()
            elif name in {"file_search", "web_search"}:
                args["query"] = inner.strip()
            else:
                args["content"] = inner.strip()
        calls.append(ToolCall(name=name, arguments=args))
    return calls or None


def parse_tool_calls(model_text: str) -> list[ToolCall] | None:
    """Si el turno pide tools, devuelve la lista; si es respuesta final, None.

    También acepta legacy {"action":"local_tool"|\"gmail_send\",...} y XML
    <listFiles><path>...</path></listFiles>.
    """
    data = _extract_json_object(model_text)
    if not data:
        xml_calls = _parse_xml_tool_calls(model_text)
        if xml_calls:
            return xml_calls
        from app.application.whatsapp.local_tool_parse import parse_local_tool_action

        legacy = parse_local_tool_action(model_text)
        if legacy:
            args: dict[str, Any] = {"path": legacy.get("path") or ""}
            if legacy.get("content") is not None:
                args["content"] = legacy["content"]
            return [ToolCall(name=str(legacy["operation"]), arguments=args)]
        return None

    action = str(data.get("action") or "").lower()
    if action == "local_tool":
        from app.application.whatsapp.local_tool_parse import parse_local_tool_action

        legacy = parse_local_tool_action(model_text)
        if not legacy:
            return None
        args = {"path": legacy.get("path") or ""}
        if legacy.get("content") is not None:
            args["content"] = legacy["content"]
        return [ToolCall(name=str(legacy["operation"]), arguments=args)]
    if action == "gmail_send":
        args: dict[str, Any] = {
            "to": str(data.get("to") or ""),
            "subject": str(data.get("subject") or ""),
            "body": str(data.get("body") or ""),
        }
        body_html = data.get("body_html")
        if isinstance(body_html, str) and body_html.strip():
            args["body_html"] = body_html
        attachments = data.get("attachments")
        if isinstance(attachments, list) and attachments:
            args["attachments"] = attachments
        return [
            ToolCall(
                name="gmail_send",
                arguments=args,
            )
        ]
    if action == "create_document":
        title = str(data.get("title") or "documento-dot").strip() or "documento-dot"
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title)[:80]
        ext = str(data.get("type") or "txt").strip().lower().replace(".", "")
        if ext not in {"txt", "md", "csv"}:
            ext = "txt"
        return [
            ToolCall(
                name="writeFile",
                arguments={
                    "path": f"~/Desktop/{safe}.{ext}",
                    "content": content,
                },
            )
        ]

    raw_calls = data.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        return _parse_xml_tool_calls(model_text)
    calls: list[ToolCall] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("tool") or "").strip()
        if not name:
            continue
        args = item.get("arguments") or item.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        if not isinstance(args, dict):
            args = {"value": args}
        calls.append(ToolCall(name=name, arguments=args))
    return calls or None


def strip_tool_calls_json(model_text: str) -> str:
    """Quita JSON de tool_calls y bloques XML de tools del texto hablado."""
    raw = (model_text or "").strip()
    data = _extract_json_object(raw)
    if data and "tool_calls" in data:
        try:
            if json.loads(raw).get("tool_calls") is not None:
                return ""
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        match = _TOOL_CALLS_BLOCK.search(raw)
        if match:
            raw = raw[: match.start()].strip()

    cleaned = _XML_TOOL_RE.sub("", raw).strip()
    return cleaned


def format_observation(tool_name: str, result_ok: bool, output: str, error: str | None) -> str:
    status = "ok" if result_ok else "error"
    body = output if result_ok else (error or "falló")
    if len(body) > 4000:
        head = body[:2000]
        tail = body[-1000:]
        omitted = len(body) - len(head) - len(tail)
        body = f"{head}\n\n…[{omitted:_} caracteres omitidos]…\n\n{tail}"
    return f"[tool_result name={tool_name} status={status}]\n{body}"


def tools_system_hint(registry) -> str:
    """Genera el hint de herramientas con schemas COMPLETOS para el modelo.
    
    El modelo necesita saber EXACTAMENTE qué herramientas existen,
    qué parámetros aceptan y cuáles son requeridos. Sin esto, adivina.
    """
    if registry is None:
        return ""

    # Aceptar tanto registry como lista de nombres (legacy)
    if isinstance(registry, list):
        names = registry
        if not names:
            return ""
        details_block = "  • " + "\n  • ".join(names)
        return (
            f"\n\n[Agent Runtime] Tools disponibles: {', '.join(names)}.\n"
            f"{details_block}\n"
            'Formato: {{"tool_calls":[{{"name":"<tool>","arguments":{{...}}}}]}}\n'
            "PROHIBIDO XML. Solo JSON o texto.\n"
        )

    try:
        specs = registry.list_specs()
    except AttributeError:
        return ""

    if not specs:
        return "\n\n[Agent Runtime] No hay herramientas disponibles. Responde solo con texto."

    names = ", ".join(s.name for s in specs)
    details = []

    for s in specs:
        params = {}
        required = []
        if s.parameters_schema and isinstance(s.parameters_schema, dict):
            params = s.parameters_schema.get("properties", {})
            required = s.parameters_schema.get("required", [])

        if params:
            param_parts = []
            for k, v in params.items():
                ptype = v.get("type", "string") if isinstance(v, dict) else "string"
                req_mark = " (REQUERIDO)" if k in required else ""
                param_parts.append(f"{k}: {ptype}{req_mark}")
            param_str = ", ".join(param_parts)
        else:
            param_str = "sin parámetros"

        desc = (s.description or s.name.replace("_", " ").title())[:120]
        details.append(f"  • {s.name}({param_str}): {desc}")

    return (
        f"\n\n[Agent Runtime] TIENES {len(specs)} HERRAMIENTAS REALES. DEBES usarlas para obtener datos.\n\n"
        + "\n".join(details)
        + "\n\nFormato JSON EXACTO para usar herramientas:\n"
        + '{{"tool_calls":[{{"name":"<nombre_tool>","arguments":{{"param1":"valor1","param2":"valor2"}}}}]}}\n\n'
        + "PUEDES ejecutar VARIAS herramientas en una misma respuesta.\n"
        + "PROHIBIDO XML, <tags>, o cualquier formato que no sea JSON o texto.\n"
        + "RECUERDA: si no ejecutaste la herramienta, NO puedes reportar sus resultados.\n"
        + "Cuando hayas terminado TODAS las acciones necesarias, responde en texto claro y COMPLETO en español."
        + "\n\n╔══ PLANIFICADOR MULTI-PASO ACTIVO ═══╗\n"
        + "║ El planificador interno de DOT puede  ║\n"
        + "║ ejecutar planes multi-paso por ti.   ║\n"
        + "║ Concéntrate en la tarea actual y usa  ║\n"
        + "║ las tools cuando sea necesario.       ║\n"
        + "╚═══════════════════════════════════════╝"
    )
