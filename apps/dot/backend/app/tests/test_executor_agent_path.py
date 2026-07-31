"""Fase 1: third-option / chat / vacío → Agent Runtime (no LLM pelado)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker.executor import AutomationExecutor


def test_third_option_calls_run_agent():
    fake = MagicMock()
    fake.final_text = "Tasa paralelo 870 Bs"
    fake.steps = 2
    fake.tool_trace = [{"name": "monitor_dollar_rate"}]

    with patch("app.application.agent.runtime.run_agent", return_value=fake) as ra:
        with patch("app.application.agent.tools.build_default_registry") as br:
            br.return_value = MagicMock()
            br.return_value.list_specs.return_value = [
                SimpleNamespace(name="monitor_dollar_rate")
            ]
            out = AutomationExecutor().execute(
                "uid-test",
                {
                    "integration_id": "third-option",
                    "instruction": "Consulta la tasa del dólar paralelo",
                    "output_type": "notify",
                },
            )

    assert ra.called
    assert "870" in out
    assert "Zapier" not in out


def test_empty_integration_calls_run_agent():
    fake = MagicMock()
    fake.final_text = "Noticias OK"
    fake.steps = 1
    fake.tool_trace = []

    with patch("app.application.agent.runtime.run_agent", return_value=fake) as ra:
        with patch("app.application.agent.tools.build_default_registry") as br:
            br.return_value = MagicMock()
            br.return_value.list_specs.return_value = []
            out = AutomationExecutor().execute(
                "uid-test",
                {"integration_id": "", "instruction": "Busca noticias Venezuela dólar"},
            )

    assert ra.called
    assert "Noticias" in out


def test_chat_integration_is_agentic():
    fake = MagicMock()
    fake.final_text = "Agenda vacía"
    fake.steps = 1
    fake.tool_trace = []

    with patch("app.application.agent.runtime.run_agent", return_value=fake) as ra:
        with patch("app.application.agent.tools.build_default_registry") as br:
            br.return_value = MagicMock()
            br.return_value.list_specs.return_value = []
            AutomationExecutor().execute(
                "uid-test",
                {"integration_id": "chat", "instruction": "Resume mi día"},
            )

    assert ra.called
