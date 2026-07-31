"""Tests para el sandbox de ejecucion de automatizaciones."""
from __future__ import annotations

import platform

import pytest

from worker.sandbox import (
    ExecutionSandbox,
    SandboxError,
    SandboxTimeoutError,
    validate_automation_payload,
)


class TestExecutionSandbox:
    def test_run_exitoso(self):
        sandbox = ExecutionSandbox(timeout_seconds=5)
        result = sandbox.run(lambda: "resultado ok", context="test")
        assert result == "resultado ok"

    def test_run_con_error(self):
        sandbox = ExecutionSandbox(timeout_seconds=5)

        def failing_fn():
            raise RuntimeError("error interno")

        with pytest.raises(SandboxError, match="error interno"):
            sandbox.run(failing_fn, context="test")

    @pytest.mark.skipif(platform.system() == "Windows", reason="Threading-based timeout no capturable via pytest.raises en Windows")
    def test_timeout(self):
        sandbox = ExecutionSandbox(timeout_seconds=1)

        def slow_fn():
            import time
            time.sleep(5)
            return "ok"

        with pytest.raises(SandboxTimeoutError):
            sandbox.run(slow_fn, context="test")


class TestValidateAutomationPayload:
    def test_payload_valido(self):
        # No debe lanzar excepcion
        validate_automation_payload({
            "id": "auto-1",
            "name": "Test",
            "instruction": "revisar correo",
        })

    def test_instruccion_vacia(self):
        with pytest.raises(SandboxError, match="Instruccion vacia"):
            validate_automation_payload({
                "id": "auto-1",
                "instruction": "",
            })

    def test_instruccion_demasiado_larga(self):
        with pytest.raises(SandboxError, match="Instruccion demasiado larga"):
            validate_automation_payload({
                "id": "auto-1",
                "instruction": "x" * 10001,
            })

    def test_bloquea_keywords_peligrosas(self):
        dangerous = ["import os", "__import__", "eval(", "exec(", "system("]
        for kw in dangerous:
            with pytest.raises(SandboxError, match="Instruccion rechazada"):
                validate_automation_payload({
                    "id": "auto-1",
                    "instruction": f"haz {kw} algo",
                })
