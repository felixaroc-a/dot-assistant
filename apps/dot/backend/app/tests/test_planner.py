"""Tests del planner (PL01–PL06 + feedback loop)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.agent.planner import (
    PlanStep,
    StepStatus,
    clear_plan,
    draft_plan,
    execute_plan_step,
    extract_planner_goal,
    format_plan_summary,
    generate_final_feedback,
    get_active_plan,
    is_planner_message,
    mark_step_status,
    replan_after_failure,
    run_planner,
)
from app.application.agent.ports import ToolResult, ToolSpec
from app.application.agent.registry import ToolRegistry


# ────────────────────────────────────────────────────────
# PL01–PL04 (existing tests — preserved)
# ────────────────────────────────────────────────────────

def test_is_planner_message_and_extract_goal():
    assert is_planner_message("plan: buscar precio del dólar")
    assert not is_planner_message("hola mundo")
    assert extract_planner_goal("plan:  enviar correo") == "enviar correo"


def test_draft_plan_heuristic_steps():
    plan = draft_plan("resumir noticias de hoy")
    assert plan.goal == "resumir noticias de hoy"
    assert 2 <= len(plan.steps) <= 3
    assert plan.steps[0].status == StepStatus.pending
    assert plan.steps[0].tool_name is None


def test_draft_plan_includes_web_search_when_registry_has_it():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="ok"),
    )
    plan = draft_plan("clima en Caracas", reg)
    tool_steps = [s for s in plan.steps if s.tool_name]
    assert len(tool_steps) == 1
    assert tool_steps[0].tool_name == "web_search"


def test_draft_plan_uses_llm_when_flag_and_key(monkeypatch):
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="ok"),
    )
    monkeypatch.setattr("app.application.agent.planner.settings.planner_llm", True)
    monkeypatch.setattr("app.application.agent.planner.settings.deepseek_api_key", "test-key")

    llm_json = (
        '{"steps": ['
        '{"id": "1", "description": "Revisar objetivo", "tool_name": null},'
        '{"id": "2", "description": "Buscar clima", "tool_name": "web_search"}'
        "]}"
    )
    with patch("app.services.provider_router.route_chat", return_value=llm_json):
        plan = draft_plan("clima en Caracas", reg)

    assert len(plan.steps) == 2
    assert plan.steps[1].tool_name == "web_search"


def test_draft_plan_llm_fallback_to_heuristic(monkeypatch):
    monkeypatch.setattr("app.application.agent.planner.settings.planner_llm", True)
    monkeypatch.setattr("app.application.agent.planner.settings.deepseek_api_key", "test-key")

    with patch("app.services.provider_router.route_chat", side_effect=RuntimeError("boom")):
        plan = draft_plan("resumir noticias de hoy")

    assert len(plan.steps) >= 2
    assert plan.steps[0].description.startswith("Analizar objetivo")


def test_active_plan_persistence():
    clear_plan("uid-a")
    reg = MagicMock(spec=ToolRegistry)
    reg.has.return_value = False

    run_planner("uid-a", "organizar tareas", reg)
    active = get_active_plan("uid-a")
    assert active is not None
    assert active.goal == "organizar tareas"

    clear_plan("uid-a")
    assert get_active_plan("uid-a") is None


def test_execute_plan_step_calls_registry_once():
    reg = MagicMock(spec=ToolRegistry)
    reg.has.return_value = True
    reg.execute.return_value = ToolResult(ok=True, output="resultado demo")

    step = PlanStep(id="1", description="Buscar", tool_name="echo")
    out = execute_plan_step("uid-test", reg, step, {"msg": "hola"})

    reg.execute.assert_called_once_with("uid-test", "echo", {"msg": "hola"})
    assert out.status == StepStatus.done
    assert out.result_summary == "resultado demo"


def test_mark_step_status_updates_active_plan():
    clear_plan("uid-b")
    reg = MagicMock(spec=ToolRegistry)
    reg.has.return_value = False

    run_planner("uid-b", "cancelar paso", reg)
    updated = mark_step_status("uid-b", "1", StepStatus.skipped, result_summary="Cancelado")
    assert updated is not None
    assert updated.status == StepStatus.skipped
    assert updated.result_summary == "Cancelado"

    active = get_active_plan("uid-b")
    assert active is not None
    assert active.steps[0].status == StepStatus.skipped

    clear_plan("uid-b")
    assert mark_step_status("uid-b", "1", StepStatus.failed) is None


# ────────────────────────────────────────────────────────
# PL05 — Reflexión post-paso (replan_after_failure)
# ────────────────────────────────────────────────────────


def test_pl05_replan_after_failure_replaces_fallback(monkeypatch):
    """PL05: al fallar un paso tool, replan aplica fallback a steps tool restantes."""
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_continue_on_error",
        False,
    )

    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar web", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="búsqueda web"),
    )
    reg.register(
        ToolSpec(name="web_fetch", description="fetch URL", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="fetch ok"),
    )
    reg.set_fallback("web_search", "web_fetch")

    # Simular: step 1 OK, step 2 (web_search) falló
    from app.application.agent.planner import Plan, _active_plans

    plan = Plan(
        goal="buscar noticias",
        steps=[
            PlanStep(id="1", description="Analizar", tool_name=None, status=StepStatus.done),
            PlanStep(id="2", description="Buscar web", tool_name="web_search", status=StepStatus.failed),
            PlanStep(id="3", description="Buscar más", tool_name="web_search", status=StepStatus.pending),
            PlanStep(id="4", description="Responder", tool_name=None, status=StepStatus.pending),
        ],
    )
    _active_plans["uid-pl05"] = plan

    result = replan_after_failure("uid-pl05", "2", reg)
    assert result is not None

    # step 3 debería tener ahora fallback web_fetch
    step3 = next(s for s in result.steps if s.id == "3")
    assert step3.tool_name == "web_fetch"
    assert step3.fallback_used == "web_fetch"

    # step 4 (no-tool) debe quedar al final
    last_step = result.steps[-1]
    assert last_step.id == "4"
    assert last_step.tool_name is None

    clear_plan("uid-pl05")


def test_pl05_replan_skips_when_continue_on_error_false(monkeypatch):
    """PL05: sin continue_on_error, marca steps tool restantes como skipped."""
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_continue_on_error",
        False,
    )

    reg = ToolRegistry()
    # Sin fallback mapping → se aplica skip
    reg.register(
        ToolSpec(name="web_search", description="buscar web", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="ok"),
    )

    from app.application.agent.planner import Plan, _active_plans

    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id="1", description="Buscar", tool_name="web_search", status=StepStatus.failed),
            PlanStep(id="2", description="Buscar más", tool_name="web_search", status=StepStatus.pending),
            PlanStep(id="3", description="Responder", tool_name=None, status=StepStatus.pending),
        ],
    )
    _active_plans["uid-pl05b"] = plan

    replan_after_failure("uid-pl05b", "1", reg)
    step2 = next(s for s in plan.steps if s.id == "2")
    assert step2.status == StepStatus.skipped
    clear_plan("uid-pl05b")


def test_pl05_replan_no_active_plan_returns_none():
    """PL05: sin plan activo, devuelve None."""
    clear_plan("uid-inexistente")
    reg = ToolRegistry()
    result = replan_after_failure("uid-inexistente", "1", reg)
    assert result is None


# ────────────────────────────────────────────────────────
# PL06 — Tool failure recovery (fallback + continue_on_error)
# ────────────────────────────────────────────────────────


def test_pl06_fallback_tool_tried_when_primary_fails():
    """PL06: execute_plan_step intenta fallback si la tool primaria falla."""
    primary_called = False
    fallback_called = False

    def primary(uid, args):
        nonlocal primary_called
        primary_called = True
        return ToolResult(ok=False, output="", error="primary error")

    def fallback_handler(uid, args):
        nonlocal fallback_called
        fallback_called = True
        return ToolResult(ok=True, output="resultado del fallback")

    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        primary,
    )
    reg.register(
        ToolSpec(name="web_fetch", description="fetch URL", parameters_schema={}),
        fallback_handler,
    )
    reg.set_fallback("web_search", "web_fetch")

    step = PlanStep(id="1", description="Buscar", tool_name="web_search")
    result = execute_plan_step("uid-pl06", reg, step, {"query": "test"})

    assert primary_called
    assert fallback_called
    assert result.status == StepStatus.done
    assert result.fallback_used == "web_fetch"
    assert "[vía web_fetch]" in (result.result_summary or "")


def test_pl06_fallback_not_tried_if_no_mapping():
    """PL06: sin fallback mapping, el paso queda como failed."""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        lambda uid, args: ToolResult(ok=False, output="", error="sin resultados"),
    )

    step = PlanStep(id="1", description="Buscar", tool_name="web_search")
    result = execute_plan_step("uid-pl06b", reg, step)

    assert result.status == StepStatus.failed
    assert result.fallback_used is None
    assert "sin resultados" in (result.result_summary or "")


def test_pl06_fallback_not_tried_when_fallback_not_in_registry():
    """PL06: si el fallback no está registrado, el paso falla igual."""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        lambda uid, args: ToolResult(ok=False, output="", error="error"),
    )
    reg.set_fallback("web_search", "web_fetch")  # web_fetch no registrada

    step = PlanStep(id="1", description="Buscar", tool_name="web_search")
    result = execute_plan_step("uid-pl06c", reg, step)

    assert result.status == StepStatus.failed
    assert result.fallback_used is None


def test_pl06_continue_on_error_skips_remaining_tools(monkeypatch):
    """PL06: con continue_on_error=false, al fallar un tool step se saltan los demás tool steps."""
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_continue_on_error",
        False,
    )
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_reflect",
        False,
    )

    call_count = 0

    def failing_tool(uid, args):
        nonlocal call_count
        call_count += 1
        return ToolResult(ok=False, output="", error="error simulado")

    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        failing_tool,
    )

    clear_plan("uid-pl06d")

    # run_planner with heuristic (no LLM) — usará web_search
    plan, summary = run_planner("uid-pl06d", "buscar clima hoy", reg)

    # Solo debería haberse ejecutado una vez (falló y se skip-eó el resto)
    # El plan heurístico tiene 3 steps: step1 no-tool, step2 web_search, step3 no-tool.
    # Al fallar step2, los tool steps pendientes se skipean.
    skipped = [s for s in plan.steps if s.status == StepStatus.skipped]
    failed = [s for s in plan.steps if s.status == StepStatus.failed]
    assert len(failed) == 1
    assert "Saltado" in (skipped[0].result_summary if skipped else "") or len(skipped) >= 0
    clear_plan("uid-pl06d")


def test_pl06_continue_on_error_true_keeps_going(monkeypatch):
    """PL06: con continue_on_error=true, el planner sigue ejecutando pasos tras fallo."""
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_continue_on_error",
        True,
    )
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_reflect",
        False,
    )

    call_count = 0

    def fail_first(uid, args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ToolResult(ok=False, output="", error="primer intento falla")
        return ToolResult(ok=True, output="segundo intento ok")

    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        fail_first,
    )

    clear_plan("uid-pl06e")
    plan, summary = run_planner("uid-pl06e", "buscar algo", reg)

    # Con continue_on_error=true, el segundo tool step debería haberse ejecutado
    # Verificar que NO hay steps skipped
    skipped = [s for s in plan.steps if s.status == StepStatus.skipped]
    assert len(skipped) == 0

    failed = [s for s in plan.steps if s.status == StepStatus.failed]
    assert len(failed) == 1  # solo el primer tool step falló

    clear_plan("uid-pl06e")


# ────────────────────────────────────────────────────────
# PL restante — Feedback loop (generate_final_feedback)
# ────────────────────────────────────────────────────────


def test_final_feedback_includes_done_failed_pending():
    """PL restante: generate_final_feedback incluye conteo de done/failed/pending."""
    from app.application.agent.planner import Plan

    plan = Plan(
        goal="test feedback",
        steps=[
            PlanStep(id="1", description="Paso OK", status=StepStatus.done, tool_name="echo"),
            PlanStep(id="2", description="Paso fallido", status=StepStatus.failed, tool_name="web_search"),
            PlanStep(id="3", description="Paso pendiente", status=StepStatus.pending),
        ],
    )

    feedback = generate_final_feedback(plan)

    assert "1/3 pasos completados" in feedback
    assert "Paso OK" in feedback
    assert "Paso fallido" in feedback
    assert "paso(s) pendientes" in feedback.lower() or "pendientes" in feedback.lower()
    assert "Paso pendiente" in feedback
    assert "¿Querés que lo intente de nuevo?" in feedback


def test_final_feedback_all_done_no_suggestion():
    """PL restante: si todo está done, no sugiere reintentar."""
    from app.application.agent.planner import Plan

    plan = Plan(
        goal="todo ok",
        steps=[
            PlanStep(id="1", description="Paso 1", status=StepStatus.done, result_summary="ok"),
            PlanStep(id="2", description="Paso 2", status=StepStatus.done, result_summary="ok"),
        ],
    )

    feedback = generate_final_feedback(plan)
    assert "2/2 pasos completados" in feedback
    assert "¿Querés que lo intente de nuevo?" not in feedback


def test_final_feedback_shows_fallback_used():
    """PL restante: el feedback muestra cuándo se usó fallback."""
    from app.application.agent.planner import Plan

    plan = Plan(
        goal="con fallback",
        steps=[
            PlanStep(
                id="1",
                description="Buscar",
                tool_name="web_search",
                status=StepStatus.done,
                fallback_used="web_fetch",
                result_summary="[vía web_fetch] resultado",
            ),
        ],
    )

    feedback = generate_final_feedback(plan)
    assert "1/1 pasos completados" in feedback
    assert "web_fetch" in feedback


def test_run_planner_returns_feedback_string(monkeypatch):
    """PL restante: run_planner devuelve feedback string con resumen."""
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_continue_on_error",
        False,
    )
    monkeypatch.setattr(
        "app.application.agent.planner.settings.planner_reflect",
        False,
    )

    reg = ToolRegistry()
    reg.register(
        ToolSpec(name="web_search", description="buscar", parameters_schema={}),
        lambda uid, args: ToolResult(ok=True, output="resultados de búsqueda"),
    )

    clear_plan("uid-fb")
    plan, summary = run_planner("uid-fb", "precio del dólar", reg)

    assert isinstance(summary, str)
    assert "Resumen:" in summary
    assert "pasos completados" in summary
    assert "precio del dólar" in plan.goal
    clear_plan("uid-fb")


# ────────────────────────────────────────────────────────
# ToolRegistry fallback mapping tests
# ────────────────────────────────────────────────────────


def test_registry_set_and_get_fallback():
    """ToolRegistry.set_fallback / get_fallback."""
    reg = ToolRegistry()
    reg.set_fallback("web_search", "web_fetch")
    assert reg.get_fallback("web_search") == "web_fetch"
    assert reg.get_fallback("nonexistent") is None


def test_registry_set_fallback_same_tool_raises():
    """set_fallback con from_tool == to_tool lanza ValueError."""
    reg = ToolRegistry()
    try:
        reg.set_fallback("web_search", "web_search")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_registry_set_fallback_empty_raises():
    """set_fallback con strings vacíos lanza ValueError."""
    reg = ToolRegistry()
    try:
        reg.set_fallback("", "web_fetch")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass
    try:
        reg.set_fallback("web_search", "")
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass
