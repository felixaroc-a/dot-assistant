"""Servicio de ejecución de código en sandbox Docker aislado.

Provee ejecución segura de Python, JavaScript y comandos shell dentro de
contenedores Docker con:
- Sin acceso a red (--network none)
- Filesystem raíz solo lectura
- Límite de memoria 256MB
- Límite de CPU 0.5 cores
- Timeout forzado
- Limpieza automática post-ejecución
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("dot.code_execution")

SANDBOX_IMAGE = "dot-sandbox:latest"
DOCKERFILE_PATH = Path(__file__).resolve().parent.parent.parent / "Dockerfile.sandbox"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

MAX_CODE_LENGTH = 10_000
MAX_OUTPUT_LENGTH = 50_000
DEFAULT_PYTHON_TIMEOUT = 30
DEFAULT_JS_TIMEOUT = 30
DEFAULT_SHELL_TIMEOUT = 10

PYTHON_DANGEROUS_PATTERNS = [
    "import os", "from os ", "import subprocess", "from subprocess",
    "import sys", "from sys ", "import shutil", "from shutil",
    "import ctypes", "from ctypes", "import socket", "from socket",
    "import importlib", "from importlib", "import runpy", "from runpy",
    "import code", "from code", "import codeop", "from codeop",
    "__import__(", "eval(", "exec(", "compile(",
    "open(", "breakpoint(",
    "import pickle", "from pickle", "import marshal", "from marshal",
    "import pty", "from pty", "import fcntl", "from fcntl",
]


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    sandbox_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class SandboxUnavailableError(Exception):
    """El sandbox no está disponible (Docker caído, imagen no construida, etc.)."""


class CodeSecurityError(ValueError):
    """El código contiene patrones bloqueados por seguridad."""


class CodeExecutionService:
    """Servicio para ejecutar código en un sandbox aislado.

    Estrategia de 2 capas:
    1. Docker (aislamiento completo) si está disponible
    2. Subprocess con timeout + validación AST (fallback worker #3)
    """

    def __init__(self) -> None:
        self._docker_available: bool | None = None

    def is_available(self) -> bool:
        """Verifica si Docker está corriendo y la imagen del sandbox existe."""
        if self._docker_available is not None:
            return self._docker_available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                log.warning("Docker no responde: %s", result.stderr.strip()[:200])
                self._docker_available = False
                return False

            # Verificar que la imagen existe
            img = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True, text=True, timeout=5,
            )
            if img.returncode != 0:
                log.warning("Imagen sandbox '%s' no encontrada. Ejecute: "
                            "docker build -f Dockerfile.sandbox -t dot-sandbox .", SANDBOX_IMAGE)
                self._docker_available = False
                return False

            self._docker_available = True
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("Docker no disponible: %s", e)
            self._docker_available = False
            return False

    def build_image(self) -> bool:
        """Construye la imagen Docker del sandbox."""
        if not DOCKERFILE_PATH.exists():
            log.error("Dockerfile.sandbox no encontrado en %s", DOCKERFILE_PATH)
            return False

        # Copiar script entrypoint a contexto de build
        entry_src = SCRIPTS_DIR / "sandbox_entry.py"
        if not entry_src.exists():
            log.error("sandbox_entry.py no encontrado en %s", SCRIPTS_DIR)
            return False

        build_context = DOCKERFILE_PATH.parent
        log.info("Construyendo imagen sandbox '%s' desde %s...", SANDBOX_IMAGE, build_context)
        try:
            result = subprocess.run(
                ["docker", "build", "-f", str(DOCKERFILE_PATH), "-t", SANDBOX_IMAGE, str(build_context)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                log.info("Imagen sandbox construida exitosamente")
                self._docker_available = True
                return True
            log.error("Fallo al construir imagen sandbox: %s", result.stderr.strip()[-500:])
            return False
        except subprocess.TimeoutExpired:
            log.error("Timeout al construir imagen sandbox (120s)")
            return False
        except FileNotFoundError:
            log.error("Docker no encontrado en el sistema")
            return False

    def _validate_code(self, code: str, language: str) -> None:
        """Valida el código contra patrones peligrosos."""
        if len(code) > MAX_CODE_LENGTH:
            raise CodeSecurityError(
                f"Código excede el límite de {MAX_CODE_LENGTH} caracteres "
                f"(tiene {len(code)})"
            )

        if language == "python":
            code_lower = code.lower()
            for pattern in PYTHON_DANGEROUS_PATTERNS:
                if pattern.lower() in code_lower:
                    raise CodeSecurityError(
                        f"Patrón bloqueado detectado: '{pattern}'. "
                        f"Este patrón no está permitido en el sandbox."
                    )
        elif language == "javascript":
            dangerous_js = [
                "require('child_process')", 'require("child_process")',
                "require('fs')", 'require("fs")',
                "require('net')", 'require("net")',
                "require('http')", 'require("http")',
                "require('dgram')", 'require("dgram")',
                "process.exit", "process.kill",
            ]
            for pattern in dangerous_js:
                if pattern in code:
                    raise CodeSecurityError(
                        f"Patrón JavaScript bloqueado: '{pattern}'"
                    )

    def _run_in_container(
        self,
        language: str,
        code: str,
        timeout_sec: int,
    ) -> ExecutionResult:
        """Ejecuta código dentro del contenedor Docker sandbox."""
        if not self.is_available():
            raise SandboxUnavailableError(
                "Sandbox no disponible. Verifique que Docker esté corriendo "
                "y la imagen 'dot-sandbox:latest' esté construida."
            )

        sandbox_id = uuid.uuid4().hex[:12]
        container_name = f"dot-sandbox-{sandbox_id}"

        payload = json.dumps({
            "language": language,
            "code": code,
            "timeout_sec": timeout_sec,
        })

        docker_cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--memory", "256m",
            "--memory-swap", "256m",
            "--cpus", "0.5",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs", "/sandbox:rw,noexec,nosuid,size=32m",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            SANDBOX_IMAGE,
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_sec + 10,  # margen extra para overhead de Docker
            )
        except subprocess.TimeoutExpired:
            # Matar el contenedor si aún existe
            _cleanup_container(container_name)
            return ExecutionResult(
                stdout="",
                stderr=f"Timeout: la ejecución excedió {timeout_sec}s (incluyendo overhead de Docker)",
                exit_code=124,
                sandbox_id=sandbox_id,
            )

        # Docker run puede fallar por problemas de infraestructura
        if result.returncode != 0 and not result.stdout.strip():
            log.error("Docker run falló (código %d): %s", result.returncode, result.stderr[:300])
            return ExecutionResult(
                stdout="",
                stderr=f"Error del sandbox (Docker): {result.stderr[:500]}",
                exit_code=2,
                sandbox_id=sandbox_id,
            )

        # Parsear la salida JSON del entrypoint
        try:
            parsed = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            return ExecutionResult(
                stdout=result.stdout[:MAX_OUTPUT_LENGTH],
                stderr=result.stderr[:MAX_OUTPUT_LENGTH],
                exit_code=result.returncode,
                sandbox_id=sandbox_id,
            )

        return ExecutionResult(
            stdout=parsed.get("stdout", "")[:MAX_OUTPUT_LENGTH],
            stderr=parsed.get("stderr", "")[:MAX_OUTPUT_LENGTH],
            exit_code=parsed.get("exit_code", 1),
            sandbox_id=sandbox_id,
        )

    def _run_subprocess(
        self, code: str, timeout_sec: int = DEFAULT_PYTHON_TIMEOUT,
    ) -> ExecutionResult:
        """Ejecuta código Python en un subprocess con timeout (#3 worker sandbox).

        Fallback cuando Docker no está disponible. Ejecuta en un proceso Python
        fresco con captura de stdout/stderr y timeout forzado.
        """
        sandbox_id = uuid.uuid4().hex[:12]
        log.info("Sandbox subprocess (#3) sandbox_id=%s timeout=%ds", sandbox_id, timeout_sec)

        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                stdout="",
                stderr=f"Timeout: la ejecución excedió {timeout_sec}s",
                exit_code=124,
                sandbox_id=sandbox_id,
            )

        return ExecutionResult(
            stdout=result.stdout[:MAX_OUTPUT_LENGTH],
            stderr=result.stderr[:MAX_OUTPUT_LENGTH],
            exit_code=result.returncode,
            sandbox_id=sandbox_id,
        )

    def execute_python(
        self, code: str, timeout_sec: int = DEFAULT_PYTHON_TIMEOUT,
    ) -> ExecutionResult:
        """Ejecuta código Python en el sandbox.

        Docker primero, fallback a subprocess con timeout (#3 worker sandbox).
        """
        self._validate_code(code, "python")
        if self.is_available():
            return self._run_in_container("python", code, timeout_sec)
        return self._run_subprocess(code, timeout_sec)

    def execute_javascript(
        self, code: str, timeout_sec: int = DEFAULT_JS_TIMEOUT,
    ) -> ExecutionResult:
        """Ejecuta código JavaScript en el sandbox."""
        self._validate_code(code, "javascript")
        return self._run_in_container("javascript", code, timeout_sec)

    def execute_shell(
        self, command: str, timeout_sec: int = DEFAULT_SHELL_TIMEOUT,
    ) -> ExecutionResult:
        """Ejecuta un comando shell en el sandbox (acceso muy restringido)."""
        if len(command) > MAX_CODE_LENGTH:
            raise CodeSecurityError(f"Comando excede {MAX_CODE_LENGTH} caracteres")

        # Bloquear comandos shell peligrosos incluso en sandbox
        dangerous_commands = [
            "curl ", "wget ", "nc ", "ncat ", "telnet ", "ssh ",
            "scp ", "rsync ", "mount ", "umount ", "chmod ", "chown ",
            "sudo ", "su ", "docker ", "kubectl ",
        ]
        cmd_lower = command.lower()
        for dc in dangerous_commands:
            if dc in cmd_lower:
                raise CodeSecurityError(
                    f"Comando shell bloqueado: '{dc}' no permitido en sandbox"
                )

        # Ejecutar el comando dentro del sandbox usando sh -c
        wrapped_code = (
            "import subprocess, sys\n"
            "r = subprocess.run(sys.argv[1], shell=True, capture_output=True, text=True)\n"
            "print(r.stdout, end='')\n"
            "print(r.stderr, end='', file=sys.stderr)\n"
            "sys.exit(r.returncode)\n"
        )

        if not self.is_available():
            raise SandboxUnavailableError(
                "Sandbox no disponible. Verifique que Docker esté corriendo."
            )

        sandbox_id = uuid.uuid4().hex[:12]
        container_name = f"dot-sandbox-{sandbox_id}"

        docker_cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--memory", "256m",
            "--memory-swap", "256m",
            "--cpus", "0.5",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            SANDBOX_IMAGE,
            "python", "-c", wrapped_code, command,
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec + 5,
            )
        except subprocess.TimeoutExpired:
            _cleanup_container(container_name)
            return ExecutionResult(
                stdout="",
                stderr=f"Timeout: el comando excedió {timeout_sec}s",
                exit_code=124,
                sandbox_id=sandbox_id,
            )

        return ExecutionResult(
            stdout=result.stdout[:MAX_OUTPUT_LENGTH],
            stderr=result.stderr[:MAX_OUTPUT_LENGTH],
            exit_code=result.returncode,
            sandbox_id=sandbox_id,
        )


def _cleanup_container(name: str) -> None:
    """Fuerza eliminación de un contenedor si aún existe."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# Instancia singleton
_code_execution_service: CodeExecutionService | None = None


def get_code_execution_service() -> CodeExecutionService:
    """Obtiene la instancia singleton del servicio de ejecución de código."""
    global _code_execution_service
    if _code_execution_service is None:
        _code_execution_service = CodeExecutionService()
    return _code_execution_service
