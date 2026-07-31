"""Script de entrada del sandbox — ejecuta Python o JavaScript recibido por stdin.

Formato de entrada (JSON en stdin):
{
    "language": "python" | "javascript",
    "code": "print('hola')",
    "timeout_sec": 30
}

Salida (JSON en stdout):
{
    "stdout": "...",
    "stderr": "...",
    "exit_code": 0
}

Seguridad:
- Python: bloquea import peligrosos (os, subprocess, sys, shutil, etc.)
- JavaScript: ejecución en sandbox básico (sin require de módulos nativos peligrosos)
- Timeout forzado por el entrypoint padre
"""
from __future__ import annotations

import json
import signal
import sys
import traceback

MAX_OUTPUT_CHARS = 50_000

PYTHON_DANGEROUS_IMPORTS = frozenset({
    "os", "subprocess", "sys", "shutil", "ctypes", "socket",
    "http", "urllib", "requests", "ftplib", "telnetlib", "smtplib",
    "poplib", "imaplib", "pickle", "shelve", "marshal", "code",
    "codeop", "pty", "fcntl", "posix", "grp", "pwd", "spwd",
    "crypt", "signal", "multiprocessing", "threading",
    "concurrent.futures", "asyncio", "pathlib",
})

PYTHON_DANGEROUS_CALLS = frozenset({
    "eval", "exec", "compile", "__import__",
    "open", "breakpoint",
    "getattr", "setattr", "delattr",
})


def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n... [TRUNCADO: {len(text) - max_chars} caracteres omitidos]"
    return text


def _validate_python_code(code: str) -> str:
    """Pre-procesa y valida código Python. Lanza ValueError si es peligroso."""
    import ast

    lines = code.split("\n")
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

    tree = ast.parse(code)

    for node in ast.walk(tree):
        # Bloquear imports peligrosos
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in PYTHON_DANGEROUS_IMPORTS:
                        raise ValueError(
                            f"Import bloqueado por seguridad: '{alias.name}' "
                            f"(módulo '{base}' no permitido en sandbox)"
                        )
            else:
                if node.module:
                    base = node.module.split(".")[0]
                    if base in PYTHON_DANGEROUS_IMPORTS:
                        raise ValueError(
                            f"Import bloqueado por seguridad: 'from {node.module} import ...' "
                            f"(módulo '{base}' no permitido en sandbox)"
                        )

        # Bloquear llamadas a funciones peligrosas
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in PYTHON_DANGEROUS_CALLS:
                raise ValueError(
                    f"Función bloqueada por seguridad: '{node.func.id}()' "
                    f"no permitida en sandbox"
                )

    return code


def _execute_python(code: str) -> dict:
    _validate_python_code(code)

    safe_builtins = {
        "True": True, "False": False, "None": None,
        "abs": abs, "all": all, "any": any, "ascii": ascii,
        "bin": bin, "bool": bool, "bytes": bytes, "chr": chr,
        "complex": complex, "dict": dict, "divmod": divmod,
        "enumerate": enumerate, "filter": filter, "float": float,
        "format": format, "frozenset": frozenset, "hash": hash,
        "hex": hex, "int": int, "isinstance": isinstance,
        "issubclass": issubclass, "iter": iter, "len": len,
        "list": list, "map": map, "max": max, "min": min,
        "oct": oct, "ord": ord, "pow": pow, "print": print,
        "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "slice": slice, "sorted": sorted,
        "str": str, "sum": sum, "tuple": tuple, "type": type,
        "zip": zip, "object": object, "Exception": Exception,
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "StopIteration": StopIterError, "RuntimeError": RuntimeError,
    }

    safe_globals: dict = {"__builtins__": safe_builtins}

    from io import StringIO
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    import contextlib
    with (contextlib.redirect_stdout(stdout_capture),
          contextlib.redirect_stderr(stderr_capture)):
        try:
            exec(compile(code, "<sandbox>", "exec"), safe_globals)
            exit_code = 0
        except Exception:
            traceback.print_exc(file=stderr_capture)
            exit_code = 1

    return {
        "stdout": _truncate(stdout_capture.getvalue()),
        "stderr": _truncate(stderr_capture.getvalue()),
        "exit_code": exit_code,
    }


def _execute_javascript(code: str) -> dict:
    """Ejecuta JavaScript usando Node.js en modo restringido."""
    import subprocess
    import tempfile
    import os

    # Escribir código a archivo temporal
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["node", "--no-warnings", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Timeout: la ejecución JavaScript excedió el tiempo límite",
            "exit_code": 124,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _alarm_handler(signum, frame):
    raise TimeoutError("Ejecución excedió el tiempo límite")


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"stdout": "", "stderr": "Sin entrada", "exit_code": 1}))
        sys.exit(0)

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"stdout": "", "stderr": f"JSON inválido: {e}", "exit_code": 1}))
        sys.exit(0)

    language = request.get("language", "python")
    code = request.get("code", "")
    timeout_sec = min(int(request.get("timeout_sec", 30)), 300)

    if not code.strip():
        print(json.dumps({"stdout": "", "stderr": "Código vacío", "exit_code": 1}))
        sys.exit(0)

    if language not in ("python", "javascript"):
        print(json.dumps({
            "stdout": "",
            "stderr": f"Lenguaje no soportado: {language}. Use 'python' o 'javascript'.",
            "exit_code": 1,
        }))
        sys.exit(0)

    # Configurar timeout vía SIGALRM
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_sec)

    try:
        if language == "python":
            result = _execute_python(code)
        else:
            result = _execute_javascript(code)
    except TimeoutError:
        result = {
            "stdout": "",
            "stderr": f"Timeout: la ejecución excedió {timeout_sec}s",
            "exit_code": 124,
        }
    except ValueError as e:
        result = {"stdout": "", "stderr": str(e), "exit_code": 1}
    finally:
        signal.alarm(0)

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
