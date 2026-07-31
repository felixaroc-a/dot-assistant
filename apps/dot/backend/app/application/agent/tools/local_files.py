"""Ejecución de local-tools vía bridge Electron (nube no toca disco)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.local")

_VALID_OPS = frozenset(
    {
        "readFile", "readFileBytes", "writeFile", "writeFileBytes", "listFiles", "deleteFile",
        "downloadUrl", "searchFiles", "parseDocument",
    }
)


def execute_local_tool_via_bridge(
    operation: str,
    *,
    path: str = "",
    content: str | None = None,
    url: str | None = None,
    query: str | None = None,
    content_pattern: str | None = None,
    search_root: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """POST /v1/tools/execute en el bridge local. Fail-closed sin secret."""
    op = (operation or "").strip()
    if op not in _VALID_OPS:
        return {"ok": False, "error": f"Operación no permitida: {op}"}

    secret = settings.whatsapp_bridge_secret.strip()
    if not secret and settings.testing.strip() != "1":
        return {"ok": False, "error": "bridge_secret_not_configured"}

    url_bridge = f"{(settings.whatsapp_bridge_url or 'http://127.0.0.1:18790').rstrip('/')}/v1/tools/execute"
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Bridge-Secret"] = secret
    payload: dict[str, Any] = {"operation": op, "path": path or ""}
    if content is not None:
        payload["content"] = content
    if url is not None:
        payload["url"] = url
    if query is not None:
        payload["query"] = query
    if content_pattern is not None:
        payload["contentPattern"] = content_pattern
    if search_root is not None:
        payload["searchRoot"] = search_root
    if scope is not None:
        payload["scope"] = scope
    elif op == "searchFiles" and settings.full_disk_access_enabled:
        payload["scope"] = "full"

    # En tests el bridge no corre: timeout corto evita colgar CI (90s × N tests).
    bridge_timeout = 2.0 if settings.testing.strip() == "1" else 90.0
    try:
        with httpx.Client(timeout=bridge_timeout) as client:
            resp = client.post(url_bridge, json=payload, headers=headers)
            if resp.status_code == 401:
                return {"ok": False, "error": "bridge_unauthorized"}
            data = resp.json() if resp.content else {}
            if isinstance(data, dict):
                return data
            return {"ok": False, "error": "invalid_bridge_response"}
    except (httpx.ConnectError, httpx.TimeoutException):
        return {"ok": False, "error": "bridge_unreachable"}
    except Exception as e:
        log.warning("bridge local_tool falló: %s", e)
        return {"ok": False, "error": str(e)}


def _format_local_output(operation: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return str(result.get("error") or "error")
    if operation in {"writeFile", "writeFileBytes"}:
        return f"Archivo guardado en: {result.get('path') or 'ruta local'}"
    if operation == "downloadUrl":
        return (
            f"Descarga lista en: {result.get('path') or 'Escritorio'} "
            f"({result.get('bytes') or '?'} bytes)"
        )
    if operation == "readFile":
        content = str(result.get("content") or "")
        preview = content if len(content) <= 4000 else content[:4000] + "…"
        return f"path={result.get('path') or ''}\n{preview}"
    if operation == "listFiles":
        files = result.get("files") or []
        root = str(result.get("path") or "")
        if not isinstance(files, list) or not files:
            return f"path={root}\n(vacío)"
        dirs: list[str] = []
        plain: list[str] = []
        for f in files[:120]:
            if isinstance(f, dict):
                name = str(f.get("name") or "")
                if not name:
                    continue
                if f.get("isDirectory"):
                    dirs.append(name)
                else:
                    plain.append(name)
            else:
                plain.append(str(f))
        lines = [f"path={root}", f"total={len(files)} (dirs={len(dirs)} files={len(plain)})"]
        if dirs:
            lines.append("directorios:")
            lines.extend(f"  [dir] {d}" for d in dirs[:80])
        if plain:
            lines.append("archivos:")
            lines.extend(f"  [file] {n}" for n in plain[:80])
        lines.append(
            "Nota: listado NO recursivo. Para subcarpetas, llama listFiles otra vez con path hijo."
        )
        return "\n".join(lines)
    if operation == "deleteFile":
        return f"Eliminado: {result.get('path') or 'ok'}"
    if operation == "searchFiles":
        results = result.get("results") or []
        count = result.get("count", len(results) if isinstance(results, list) else 0)
        if not isinstance(results, list) or not results:
            return "No se encontraron archivos."
        lines = [f"Se encontraron {count} archivo(s):"]
        for r in results[:30]:
            if isinstance(r, dict):
                name = str(r.get("name") or "")
                fpath = str(r.get("path") or "")
                size_kb = (int(r.get("size") or 0)) / 1024
                lines.append(f"  {name} ({size_kb:.1f} KB) — {fpath}")
        return "\n".join(lines)
    if operation == "parseDocument":
        text = str(result.get("text", result.get("content", "")))
        preview = text if len(text) <= 8000 else text[:8000] + "…"
        return f"path={result.get('path', '')}\n{preview}"
    return "ok"


def make_local_file_handler(operation: str):
    """Handler ToolRegistry para una operación de archivo."""

    _BINARY_EXTS = (
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".zip",
        ".exe",
        ".docx",
        ".xlsx",
        ".pptx",
    )

    def handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
        path = str(arguments.get("path") or "").strip()
        content = arguments.get("content")
        url = str(arguments.get("url") or "").strip()
        search_query = str(arguments.get("query") or "").strip()
        search_content = str(arguments.get("contentPattern") or "").strip() or None
        search_root = str(arguments.get("searchRoot") or "all").strip()
        if operation == "searchFiles":
            if not search_query:
                return ToolResult(ok=False, output="", error="searchFiles requiere query")
            raw = execute_local_tool_via_bridge(
                "searchFiles",
                query=search_query,
                content_pattern=search_content,
                search_root=search_root,
                scope="full" if settings.full_disk_access_enabled else None,
            )
        elif operation == "writeFile":
            if not isinstance(content, str):
                return ToolResult(ok=False, output="", error="writeFile requiere content (texto)")
            lower = path.lower()
            if not settings.full_disk_access_enabled and any(
                lower.endswith(ext) for ext in _BINARY_EXTS
            ):
                return ToolResult(
                    ok=False,
                    output="",
                    error=(
                        "No uses writeFile para PDF/imágenes/binarios. "
                        "Usa download_url_to_desktop con la URL http/https."
                    ),
                )
            if not path:
                return ToolResult(ok=False, output="", error="writeFile requiere path")
            raw = execute_local_tool_via_bridge(
                "writeFile",
                path=path,
                content=content,
            )
        elif operation == "writeFileBytes":
            if not isinstance(content, str) or not content.strip():
                return ToolResult(
                    ok=False,
                    output="",
                    error="writeFileBytes requiere content (base64)",
                )
            if not path:
                return ToolResult(ok=False, output="", error="writeFileBytes requiere path")
            raw = execute_local_tool_via_bridge(
                "writeFileBytes",
                path=path,
                content=str(content),
            )
        elif operation == "downloadUrl":
            if not url:
                return ToolResult(ok=False, output="", error="download_url_to_desktop requiere url")
            raw = execute_local_tool_via_bridge("downloadUrl", path=path, url=url)
        else:
            if operation != "listFiles" and not path:
                return ToolResult(ok=False, output="", error=f"{operation} requiere path")
            raw = execute_local_tool_via_bridge(
                operation,
                path=path,
                content=content if isinstance(content, str) else None,
            )
        ok = bool(raw.get("ok"))
        if ok:
            return ToolResult(ok=True, output=_format_local_output(operation, raw))
        err = str(raw.get("error") or "falló la herramienta local")
        human = {
            "bridge_secret_not_configured": "El puente local no está configurado. Abre la app DOT en el PC.",
            "bridge_unreachable": "No pude llegar al PC (bridge). ¿Está abierta la app DOT?",
            "bridge_unauthorized": "El puente local rechazó la autenticación.",
        }.get(err, err)
        return ToolResult(ok=False, output="", error=human)

    return handler


def download_url_to_desktop_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Alias canónico PROMPTSOTE T-download."""
    return make_local_file_handler("downloadUrl")(uid, arguments)
