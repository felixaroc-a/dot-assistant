"""Tests del orquestador de automatizaciones compuestas (FREE-AU01 + FREE-AU02)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.agent.ports import ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry
from app.application.automations.composite import (
    AutomationSpec,
    AutomationStep,
    execute_composite_if_enabled,
    run_composite_automation,
)


def test_run_composite_chains_two_tools(monkeypatch):
    monkeypatch.setattr(
        "app.application.automations.composite.settings.automations_composite_enabled",
        True,
    )

    reg = ToolRegistry()

    def step_one(_uid: str, args: dict) -> ToolResult:
        return ToolResult(ok=True, output=f"uno:{args.get('q', '')}")

    def step_two(_uid: str, args: dict) -> ToolResult:
        return ToolResult(ok=True, output=f"dos:{args.get('input', '')}")

    reg.register(ToolSpec(name="tool_a", description="a", parameters_schema={}), step_one)
    reg.register(ToolSpec(name="tool_b", description="b", parameters_schema={}), step_two)

    spec = AutomationSpec(
        name="demo",
        steps=[
            AutomationStep(tool_name="tool_a", arguments={"q": "hola"}),
            AutomationStep(tool_name="tool_b"),
        ],
    )

    result = run_composite_automation("uid-1", spec, reg)
    assert result.ok
    assert result.step_outputs == ["uno:hola", "dos:uno:hola"]


def test_execute_composite_if_enabled_returns_none_when_flag_off(monkeypatch):
    monkeypatch.setattr(
        "app.application.automations.composite.settings.automations_composite_enabled",
        False,
    )
    monkeypatch.setattr(
        "app.services.proactive_triggers_service.user_composite_enabled",
        lambda _uid: False,
    )
    reg = MagicMock(spec=ToolRegistry)
    spec = AutomationSpec(name="x", steps=[AutomationStep(tool_name="echo")])
    assert execute_composite_if_enabled("uid", spec, reg) is None
    reg.execute.assert_not_called()


def test_execute_composite_if_enabled_runs_when_user_pref_on(monkeypatch):
    monkeypatch.setattr(
        "app.application.automations.composite.settings.automations_composite_enabled",
        False,
    )
    monkeypatch.setattr(
        "app.services.proactive_triggers_service.user_composite_enabled",
        lambda _uid: True,
    )
    reg = ToolRegistry()

    def echo_tool(_uid: str, args: dict) -> ToolResult:
        return ToolResult(ok=True, output=str(args.get("input", "ok")))

    reg.register(ToolSpec(name="echo", description="echo", parameters_schema={}), echo_tool)
    spec = AutomationSpec(name="x", steps=[AutomationStep(tool_name="echo")])
    result = execute_composite_if_enabled("uid", spec, reg)
    assert result is not None
    assert result.ok


def test_run_composite_rejects_more_than_five_steps():
    reg = ToolRegistry()
    spec = AutomationSpec(
        name="demasiados",
        steps=[AutomationStep(tool_name=f"tool_{idx}") for idx in range(6)],
    )
    result = run_composite_automation("uid", spec, reg)
    assert not result.ok
    assert "Máximo 5 pasos" in (result.error or "")


def test_run_composite_halts_on_first_tool_error():
    reg = ToolRegistry()
    calls: list[str] = []

    def ok_tool(_uid: str, _args: dict) -> ToolResult:
        calls.append("ok")
        return ToolResult(ok=True, output="uno")

    def fail_tool(_uid: str, _args: dict) -> ToolResult:
        calls.append("fail")
        return ToolResult(ok=False, output="", error="boom")

    def never_tool(_uid: str, _args: dict) -> ToolResult:
        calls.append("never")
        return ToolResult(ok=True, output="tres")

    reg.register(ToolSpec(name="tool_ok", description="ok", parameters_schema={}), ok_tool)
    reg.register(ToolSpec(name="tool_fail", description="fail", parameters_schema={}), fail_tool)
    reg.register(ToolSpec(name="tool_never", description="never", parameters_schema={}), never_tool)

    spec = AutomationSpec(
        name="fail-fast",
        steps=[
            AutomationStep(tool_name="tool_ok"),
            AutomationStep(tool_name="tool_fail"),
            AutomationStep(tool_name="tool_never"),
        ],
    )

    result = run_composite_automation("uid", spec, reg)
    assert not result.ok
    assert result.step_outputs == ["uno"]
    assert calls == ["ok", "fail"]
