"""Tool run_python para DOT Agent Runtime — FASE 3.1.

Llama al endpoint interno POST /v1/code/execute para ejecutar código
Python en el sandbox (Docker si disponible, subprocess con timeout si no).

Seguridad:
- Sin acceso a red ni disco (vía Docker o validación pre-ejecución)
- Timeout forzado (default 30s, máx 300s)
- Patrones peligrosos bloqueados (os, subprocess, eval, exec, importlib, etc.)
- Rate limit: 10/min por usuario (middleware global)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.code_execution")

# URL del endpoint interno
_EXECUTE_URL = "http://127.0.0.1:8000/v1/code/execute"

# Schema de la tool para el modelo
TOOL_SPECS: dict[str, dict[str, Any]] = {
    "run_python": {
        "description": (
            "Ejecuta código Python en un sandbox seguro sin red ni acceso a disco. "
            "Ideal para cálculos, transformación de datos, generación de gráficos, "
            "procesamiento de cadenas, análisis numérico o cualquier tarea de cómputo. "
            "El código se ejecuta en un entorno aislado con timeout forzado. "
            "Retorna stdout, stderr y código de salida. "
            "NO disponible para comandos shell, acceso a sistema de archivos, red, "
            "ni importación de módulos peligrosos (os, subprocess, shutil, etc.)."
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Código Python a ejecutar. Sin imports peligrosos "
                        "(os, subprocess, shutil, socket, importlib, etc.). "
                        "Máx 10.000 caracteres."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (1-300, default 30).",
                    "default": 30,
                },
            },
            "required": ["code"],
        },
    },
}


def run_python_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Ejecuta código Python en el sandbox vía endpoint interno.

    Args:
        uid: ID del usuario.
        arguments: ``code`` (str, req) y ``timeout`` (int, opc, default 30).

    Returns:
        ToolResult con stdout/stderr/exit_code.
    """
    code = str(arguments.get("code") or "").strip()
    if not code:
        return ToolResult(
            ok=False,
            output="",
            error="Falta 'code': no hay código Python para ejecutar.",
        )

    timeout = int(arguments.get("timeout") or 30)
    timeout = max(1, min(timeout, 300))

    payload = {
        "language": "python",
        "code": code,
        "timeout": timeout,
    }

    try:
        with httpx.Client(timeout=timeout + 10) as client:
            resp = client.post(_EXECUTE_URL, json=payload)

        if resp.status_code == 503:
            detail = resp.json().get("detail", {})
            msg = detail.get("message", "Sandbox no disponible.")
            return ToolResult(
                ok=False,
                output="",
                error=f"Sandbox no disponible: {msg}",
            )

        if resp.status_code == 400:
            detail = resp.json().get("detail", {})
            msg = detail.get("message", "Código rechazado por seguridad.")
            return ToolResult(
                ok=False,
                output="",
                error=f"Código rechazado: {msg}",
            )

        if resp.status_code != 200:
            return ToolResult(
                ok=False,
                output="",
                error=f"Error inesperado del sandbox (HTTP {resp.status_code}): "
                f"{resp.text[:300]}",
            )

        data = resp.json()
        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")
        exit_code = data.get("exit_code", 0)
        sandbox_id = data.get("sandbox_id", "?")

        # Armar salida amigable para el modelo
        output_parts: list[str] = []
        if stdout:
            output_parts.append(f"[stdout]\n{stdout}")
        if stderr:
            output_parts.append(f"[stderr]\n{stderr}")
        output_parts.append(f"[exit_code] {exit_code}")
        output_parts.append(f"[sandbox] {sandbox_id}")

        ok = exit_code == 0 and not stderr.strip()
        error = "" if ok else (
            f"El código terminó con código {exit_code}"
            f"{' y errores en stderr' if stderr.strip() else ''}"
        )

        return ToolResult(
            ok=ok,
            output="\n\n".join(output_parts),
            error=error,
        )

    except httpx.ConnectError:
        return ToolResult(
            ok=False,
            output="",
            error=(
                "No se pudo conectar al sandbox (backend no responde en "
                "127.0.0.1:8000). Verifica que el servidor esté corriendo."
            ),
        )
    except httpx.TimeoutException:
        return ToolResult(
            ok=False,
            output="",
            error=f"El sandbox no respondió dentro del tiempo límite ({timeout}s + margen).",
        )
    except Exception as e:
        log.warning(
            "run_python error uid=%s: %s",
            uid[:8] if uid else "?", e,
        )
        return ToolResult(
            ok=False,
            output="",
            error=f"Error ejecutando código en sandbox: {e}",
        )


# Export para el registro automático
TOOLS: list[tuple[str, Any]] = [
    ("run_python", run_python_handler),
]
