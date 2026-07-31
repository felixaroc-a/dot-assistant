"""Multi-step planner (PL01–PL06 + feedback loop).

Feature-flagged via PLANNER_ENABLED. Messages with prefix ``plan:`` draft a
short ordered plan. FASE 2.2: el prefijo ya no es obligatorio; el planificador
puede ser invocado directamente desde runtime.py con un plan pre-generado por
reasoning.py.

PL01 – Plan parser: LLM genera plan JSON estructurado.
PL02 – Ejecutor: orquestación secuencial vía run_planner.
PL03 – Verificación: plan activo en memoria por uid.
PL04 – Reintentos: mark_step_status / clear_plan.
PL05 – Reflexión post-paso: replan_after_failure ajusta pasos restantes.
       + plan_history: almacena hasta 10 planes completados por uid.
       + reflect_and_improve: analiza últimos 3 planes y sugiere mejoras.
PL06 – Tool failure recovery: fallback mapping en registry + continue_on_error.
       + continue_plan: negociación multi-turno, añade pasos a plan activo.
       + plan_cancel_reason: registra el motivo de cancelación/aborto.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.application.agent.registry import ToolRegistry
from app.settings import settings

log = logging.getLogger("dot.agent.planner")

PLANNER_PREFIX = "plan:"

# PL03: último plan activo por uid (in-process, opcional)
_active_plans: dict[str, "Plan"] = {}

# PL05: historial de planes completados por uid (máx. 10)
_plan_history: dict[str, list["PlanHistoryEntry"]] = {}

MAX_PLAN_HISTORY = 10

_PLANNER_LLM_SYSTEM = """Eres el planificador interno de DOT. Devuelve SOLO JSON válido (sin markdown):
{
  "steps": [
    {"id": "1", "description": "paso concreto en español", "tool_name": null},
    {"id": "2", "description": "...", "tool_name": "web_search"}
  ]
}
Reglas:
- Entre 2 y 4 pasos concretos en español.
- tool_name solo si corresponde a una tool real de la lista disponible; si no, null.
- No inventes tools fuera de la lista.
- FASE 2.2: ahora eres el ejecutor por defecto — cualquier mensaje complejo
  puede activar planificación automática sin prefijo 'plan:'."""


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


@dataclass
class PlanStep:
    id: str
    description: str
    tool_name: str | None = None
    status: StepStatus = StepStatus.pending
    result_summary: str | None = None
    fallback_used: str | None = None  # PL06: tool alternativa que se usó (si hubo)


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    cancel_reason: str | None = None  # PL06: motivo de cancelación/aborto


@dataclass
class PlanHistoryEntry:
    """PL05: entrada individual en el historial de planes de un uid."""
    goal: str
    steps: list[PlanStep]
    timestamp: datetime
    success: bool  # True si todos los steps tool finalizaron sin fallo
    summary: str | None = None
    cancel_reason: str | None = None


def is_planner_message(text: str) -> bool:
    return text.strip().lower().startswith(PLANNER_PREFIX)


def extract_planner_goal(text: str) -> str:
    stripped = text.strip()
    if not stripped.lower().startswith(PLANNER_PREFIX):
        return stripped
    return stripped[len(PLANNER_PREFIX):].strip()


def get_active_plan(uid: str) -> Plan | None:
    """PL03: devuelve el último plan en memoria para el uid, si existe."""
    return _active_plans.get(uid)


def clear_plan(uid: str, *, cancel_reason: str | None = None) -> None:
    """PL03/PL04/PL06: elimina el plan activo del uid (abort/cancel).

    Si se especifica cancel_reason, se registra en el plan antes de archivarlo
    en el historial (PL05). El plan se mueve a _plan_history con max_entries=10.
    """
    plan = _active_plans.pop(uid, None)
    if plan is None:
        return

    if cancel_reason is not None:
        plan.cancel_reason = cancel_reason

    _archive_plan(uid, plan)


def set_plan_cancel_reason(uid: str, reason: str) -> Plan | None:
    """PL06: registra el motivo de cancelación en el plan activo sin eliminarlo.

    Retorna el plan si existe, None en caso contrario.
    """
    plan = _active_plans.get(uid)
    if plan is None:
        log.warning("set_plan_cancel_reason: no hay plan activo para uid=%s", uid)
        return None

    plan.cancel_reason = reason.strip() or "(sin motivo)"
    log.info("plan_cancel_reason uid=%s: %s", uid, plan.cancel_reason)
    return plan


# ── PL05 — Historial de planes ──

def _archive_plan(uid: str, plan: Plan) -> None:
    """Mueve un plan completado/cancelado al historial del uid (máx. 10)."""
    entries = _plan_history.setdefault(uid, [])

    # Determinar éxito: ningún step con tool en estado failed
    tool_steps = [s for s in plan.steps if s.tool_name]
    success = all(s.status != StepStatus.failed for s in tool_steps) if tool_steps else True

    done_count = sum(1 for s in plan.steps if s.status == StepStatus.done)
    failed_count = sum(1 for s in plan.steps if s.status == StepStatus.failed)
    skipped_count = sum(1 for s in plan.steps if s.status == StepStatus.skipped)

    summary_parts = []
    if done_count:
        summary_parts.append(f"{done_count} completados")
    if failed_count:
        summary_parts.append(f"{failed_count} fallidos")
    if skipped_count:
        summary_parts.append(f"{skipped_count} saltados")
    if plan.cancel_reason:
        summary_parts.append(f"cancelado: {plan.cancel_reason}")

    entry = PlanHistoryEntry(
        goal=plan.goal,
        steps=[PlanStep(
            id=s.id,
            description=s.description,
            tool_name=s.tool_name,
            status=s.status,
            result_summary=s.result_summary,
            fallback_used=s.fallback_used,
        ) for s in plan.steps],
        timestamp=datetime.now(timezone.utc),
        success=success,
        summary="; ".join(summary_parts) or "(sin pasos ejecutados)",
        cancel_reason=plan.cancel_reason,
    )

    entries.append(entry)
    # Limitar a MAX_PLAN_HISTORY (conservar los más recientes)
    if len(entries) > MAX_PLAN_HISTORY:
        _plan_history[uid] = entries[-MAX_PLAN_HISTORY:]

    log.info(
        "_archive_plan uid=%s: éxito=%s, %d pasos → historial (%d total)",
        uid, success, len(plan.steps), len(_plan_history[uid]),
    )


def get_plan_history(uid: str) -> list[PlanHistoryEntry]:
    """PL05: devuelve el historial de planes completados/cancelados del uid."""
    return list(_plan_history.get(uid, []))


def mark_step_status(
    uid: str,
    step_id: str,
    status: StepStatus,
    *,
    result_summary: str | None = None,
) -> PlanStep | None:
    """PL04: actualiza el estado de un paso del plan activo; None si no existe."""
    plan = _active_plans.get(uid)
    if plan is None:
        return None

    target_id = (step_id or "").strip()
    if not target_id:
        return None

    for step in plan.steps:
        if step.id == target_id:
            step.status = status
            if result_summary is not None:
                step.result_summary = result_summary
            return step
    return None


# ────────────────────────────────────────────────────────
# PL05 — Reflexión post-paso (continuación)
# ────────────────────────────────────────────────────────

def reflect_and_improve(uid: str) -> str:
    """PL05 — Analiza los últimos 3 planes en historial y sugiere mejoras.

    Busca patrones:
    - Herramientas que siempre fallan → sugerir alternativas o skill gap.
    - Herramientas que siempre funcionan → recomendar como first-choice.
    - Planes siempre cancelados → recomendar dividir el objetivo en pasos más
      pequeños.

    Retorna un texto legible con sugerencias concretas, o cadena vacía si no
    hay suficiente historial para analizar.
    """
    history = _plan_history.get(uid, [])
    if len(history) < 3:
        return ""

    recent = history[-3:]

    # Patrón 1: herramientas que siempre fallan (aparecen en ≥2 planes como failed)
    tool_failures: dict[str, int] = {}
    tool_successes: dict[str, int] = {}
    cancel_count = 0

    for entry in recent:
        if entry.cancel_reason:
            cancel_count += 1

        for step in entry.steps:
            if not step.tool_name:
                continue
            if step.status == StepStatus.failed:
                tool_failures[step.tool_name] = tool_failures.get(step.tool_name, 0) + 1
            elif step.status == StepStatus.done:
                tool_successes[step.tool_name] = tool_successes.get(step.tool_name, 0) + 1

    suggestions: list[str] = []

    # Herramientas recurrentemente fallidas
    chronic_failures = {t: c for t, c in tool_failures.items() if c >= 2}
    if chronic_failures:
        failed_names = ", ".join(chronic_failures)
        suggestions.append(
            f"Las siguientes herramientas fallaron en {len(chronic_failures)} de los "
            f"últimos {len(recent)} planes: {failed_names}. "
            "Considerá verificar su configuración o usar alternativas."
        )

    # Herramientas siempre exitosas (en todos los planes recientes)
    reliable_tools = {
        t: c for t, c in tool_successes.items()
        if c == len(recent) and t not in chronic_failures
    }
    if reliable_tools:
        reliable_names = ", ".join(reliable_tools)
        suggestions.append(
            f"Herramientas confiables en los últimos {len(recent)} planes: "
            f"{reliable_names}. Seguí usándolas como primera opción."
        )

    # Cancelaciones frecuentes
    if cancel_count >= 2:
        suggestions.append(
            f"{cancel_count} de los últimos {len(recent)} planes fueron cancelados. "
            "Probá dividir el objetivo en pasos más pequeños o revisar los permisos "
            "necesarios antes de planificar."
        )

    # Sin patrones detectados
    if not suggestions:
        suggestions.append(
            f"No se detectaron patrones claros en los últimos {len(recent)} planes. "
            "El planificador está funcionando dentro de lo esperado."
        )

    return "\n".join(f"- {s}" for s in suggestions)


# ────────────────────────────────────────────────────────
# PL05 — Reflexión post-paso (existente)
# ────────────────────────────────────────────────────────

def replan_after_failure(
    uid: str,
    failed_step_id: str,
    registry: ToolRegistry,
) -> Plan | None:
    """PL05 — Re-evalúa y ajusta pasos restantes tras un fallo parcial.

    Estrategia heurística:
    1. Si el paso fallido usaba una tool, intenta buscar fallback en el registry
       para los pasos siguientes que usen tools similares.
    2. Si PLANNER_CONTINUE_ON_ERROR está en false, marca los pasos tool restantes
       como skipped para no desperdiciar recursos.
    3. Reordena pasos no-tool al final para que siempre se responda al usuario.

    Retorna el plan ajustado, o None si no hay plan activo.
    """
    plan = _active_plans.get(uid)
    if plan is None:
        log.warning("replan_after_failure: no hay plan activo para uid=%s", uid)
        return None

    # Encontrar el índice del paso fallido
    failed_idx: int | None = None
    for i, step in enumerate(plan.steps):
        if step.id == failed_step_id:
            failed_idx = i
            break

    if failed_idx is None:
        log.warning("replan_after_failure: paso %s no encontrado en plan uid=%s", failed_step_id, uid)
        return plan

    remaining = plan.steps[failed_idx + 1:]
    if not remaining:
        log.info("replan_after_failure: sin pasos restantes para uid=%s", uid)
        return plan

    failed_step = plan.steps[failed_idx]

    # Heurística: si el paso fallido tenía tool, aplicar fallback a steps tool restantes
    if failed_step.tool_name:
        for step in remaining:
            if step.tool_name and step.status == StepStatus.pending:
                fallback = registry.get_fallback(step.tool_name)
                if fallback and registry.has(fallback):
                    log.info(
                        "PL05 replan: step %s (%s) → fallback %s para uid=%s",
                        step.id, step.tool_name, fallback, uid,
                    )
                    step.tool_name = fallback
                    step.fallback_used = fallback
                    step.result_summary = f"Replanificando con alternativa: {fallback}"
                elif not settings.planner_continue_on_error:
                    step.status = StepStatus.skipped
                    step.result_summary = (
                        f"Saltado — fallo previo en step {failed_step_id} "
                        f"(PLANNER_CONTINUE_ON_ERROR=false)"
                    )

    # Reordenar: pasos no-tool (respuesta al usuario) siempre al final
    tool_steps = [s for s in remaining if s.tool_name]
    no_tool_steps = [s for s in remaining if not s.tool_name]
    if tool_steps or no_tool_steps:
        # Reconstruir: mantiene orden de steps antes del fallido + reordenados
        plan.steps = plan.steps[: failed_idx + 1] + tool_steps + no_tool_steps

    log.info("replan_after_failure: plan ajustado para uid=%s, %d pasos restantes", uid, len(remaining))
    return plan


# ════════════════════════════════════════════════════════
# PL06 — continue_plan: negociación multi-turno
# ════════════════════════════════════════════════════════

def continue_plan(
    uid: str,
    new_steps: list[PlanStep],
    *,
    goal_override: str | None = None,
) -> Plan | None:
    """PL06 — Añade nuevos pasos al plan activo sin reemplazarlo.

    Útil para negociación multi-turno donde el usuario pide añadir pasos
    adicionales (ej: "Plan: Buscar vuelos" → luego "Plan: agregá reservar hotel").

    Args:
        uid: identificador del usuario.
        new_steps: lista de PlanStep a añadir (con IDs únicos).
        goal_override: si se provee, actualiza el goal del plan activo.

    Returns:
        El plan actualizado, o None si no hay plan activo para el uid.
    """
    plan = _active_plans.get(uid)
    if plan is None:
        log.warning("continue_plan: no hay plan activo para uid=%s", uid)
        return None

    if not new_steps:
        log.info("continue_plan uid=%s: sin pasos nuevos que añadir", uid)
        return plan

    # Evitar duplicados por ID: solo añadir pasos con IDs no existentes
    existing_ids = {s.id for s in plan.steps}
    truly_new = [s for s in new_steps if s.id not in existing_ids]
    skipped = len(new_steps) - len(truly_new)

    if skipped:
        log.info(
            "continue_plan uid=%s: %d pasos ignorados (IDs duplicados)",
            uid, skipped,
        )

    if not truly_new:
        return plan

    plan.steps.extend(truly_new)

    if goal_override is not None and goal_override.strip():
        plan.goal = goal_override.strip()

    log.info(
        "continue_plan uid=%s: %d nuevos pasos añadidos, total=%d",
        uid, len(truly_new), len(plan.steps),
    )
    return plan


# ────────────────────────────────────────────────────────
# PL06 — Tool failure recovery (fallback en execute_plan_step — existente)
# ────────────────────────────────────────────────────────

def _try_fallback_tool(
    uid: str,
    registry: ToolRegistry,
    step: PlanStep,
    arguments: dict[str, Any] | None,
) -> bool:
    """PL06: intenta ejecutar la tool alternativa definida en registry.get_fallback."""
    fallback_name = registry.get_fallback(step.tool_name or "")
    if not fallback_name or not registry.has(fallback_name):
        return False

    log.info(
        "PL06 fallback: %s → %s para uid=%s step=%s",
        step.tool_name, fallback_name, uid, step.id,
    )
    fb_result = registry.execute(uid, fallback_name, arguments or {})
    if fb_result.ok:
        step.status = StepStatus.done
        step.fallback_used = fallback_name
        output = (fb_result.output or "").strip()
        step.result_summary = f"[vía {fallback_name}] {output[:460]}" if output else f"[vía {fallback_name}] (sin salida)"
        return True

    log.warning(
        "PL06 fallback también falló: %s → %s para uid=%s — %s",
        step.tool_name, fallback_name, uid, fb_result.error,
    )
    return False


# ════════════════════════════════════════════════════════
# Funciones core (PL01–PL02 existentes, PL06 en execute)
# ════════════════════════════════════════════════════════

def _llm_client_available() -> bool:
    return bool(settings.planner_llm and settings.deepseek_api_key)


def _draft_plan_heuristic(goal: str, registry: ToolRegistry | None = None) -> Plan:
    """Heuristic stub: 2-3 steps for demo (no LLM call)."""
    steps: list[PlanStep] = [
        PlanStep(id="1", description=f"Analizar objetivo: {goal}"),
    ]

    if registry is not None and registry.has("web_search"):
        steps.append(
            PlanStep(
                id="2",
                description=f"Buscar información sobre: {goal}",
                tool_name="web_search",
            )
        )
        steps.append(
            PlanStep(
                id="3",
                description="Sintetizar resultados y responder al usuario",
            )
        )
    else:
        steps.append(
            PlanStep(
                id="2",
                description="Preparar respuesta con el contexto disponible",
            )
        )

    return Plan(goal=goal, steps=steps)


def _parse_llm_plan_steps(raw: str, registry: ToolRegistry | None) -> list[PlanStep] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        return None

    raw_steps = data.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        return None

    steps: list[PlanStep] = []
    for idx, item in enumerate(raw_steps[:4], start=1):
        if isinstance(item, str):
            steps.append(PlanStep(id=str(idx), description=item.strip()))
            continue
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or item.get("step") or "").strip()
        if not desc:
            continue
        step_id = str(item.get("id") or idx).strip() or str(idx)
        tool_name = item.get("tool_name")
        tool: str | None = None
        if tool_name is not None:
            candidate = str(tool_name).strip()
            if candidate and candidate.lower() not in ("null", "none", ""):
                if registry is None or registry.has(candidate):
                    tool = candidate
        steps.append(PlanStep(id=step_id, description=desc, tool_name=tool))

    return steps or None


def _draft_plan_via_llm(goal: str, registry: ToolRegistry | None = None) -> Plan | None:
    """PL02: borrador vía DeepSeek barato; None si falla."""
    try:
        from app.services.provider_router import route_chat

        tools_line = "(sin registry)"
        if registry is not None:
            names = sorted(s.name for s in registry.list_specs())
            tools_line = ", ".join(names[:40])
            if len(names) > 40:
                tools_line += ", …"

        prompt = (
            f"Objetivo del usuario:\n{goal}\n\n"
            f"Tools disponibles: {tools_line}\n\n"
            "Genera un plan breve de 2-4 pasos."
        )
        raw = route_chat(
            prompt,
            provider_id="deepseek",
            system_prompt=_PLANNER_LLM_SYSTEM,
            include_document_action_prompt=False,
        )
        steps = _parse_llm_plan_steps(raw, registry)
        if not steps:
            return None
        return Plan(goal=goal, steps=steps)
    except Exception:
        log.warning("draft_plan LLM failed; falling back to heuristic", exc_info=True)
        return None


def draft_plan(goal: str, registry: ToolRegistry | None = None) -> Plan:
    """Draft plan: LLM opcional (PLANNER_LLM) o heurística por defecto."""
    goal = goal.strip()
    if not goal:
        goal = "(objetivo vacío)"

    if _llm_client_available():
        llm_plan = _draft_plan_via_llm(goal, registry)
        if llm_plan is not None:
            return llm_plan

    return _draft_plan_heuristic(goal, registry)


def execute_plan_step(
    uid: str,
    registry: ToolRegistry,
    step: PlanStep,
    arguments: dict[str, Any] | None = None,
) -> PlanStep:
    """Execute a single plan step; calls ToolRegistry once (+ fallback PL06 si falla)."""
    if step.status in (StepStatus.done, StepStatus.skipped):
        return step

    if not step.tool_name:
        step.status = StepStatus.done
        step.result_summary = step.description
        return step

    if not registry.has(step.tool_name):
        step.status = StepStatus.failed
        step.result_summary = f"Herramienta no disponible: {step.tool_name}"
        return step

    step.status = StepStatus.running
    result = registry.execute(uid, step.tool_name, arguments or {})
    if result.ok:
        step.status = StepStatus.done
        step.result_summary = (result.output or "").strip()[:500] or "(sin salida)"
        return step

    # PL06: si la tool primaria falló, intentar fallback
    if _try_fallback_tool(uid, registry, step, arguments):
        return step

    step.status = StepStatus.failed
    step.result_summary = result.error or "Error desconocido"
    return step


def format_plan_summary(plan: Plan) -> str:
    lines = [f"**Plan para:** {plan.goal}", ""]
    for step in plan.steps:
        marker = f"[{step.status.value}]"
        lines.append(f"- {marker} {step.id}. {step.description}")
        if step.result_summary and step.tool_name:
            preview = step.result_summary[:200]
            if len(step.result_summary) > 200:
                preview += "…"
            lines.append(f"  → {preview}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────
# PL restante — Feedback loop final
# ────────────────────────────────────────────────────────

def generate_final_feedback(plan: Plan) -> str:
    """PL restante — Resumen de lo logrado vs goal original.

    Incluye conteo de pasos completados, fallos, pendientes y sugerencia
    interactiva si quedan pasos por ejecutar.
    """
    done = [s for s in plan.steps if s.status == StepStatus.done]
    failed = [s for s in plan.steps if s.status == StepStatus.failed]
    pending = [s for s in plan.steps if s.status == StepStatus.pending]
    skipped = [s for s in plan.steps if s.status == StepStatus.skipped]

    lines = [format_plan_summary(plan), ""]
    lines.append(f"**Resumen:** {len(done)}/{len(plan.steps)} pasos completados.")

    if done:
        lines.append("\n✓ Completado:")
        for s in done:
            prefix = f"  (vía {s.fallback_used})" if s.fallback_used else ""
            lines.append(f"  - {s.id}. {s.description}{prefix}")

    if failed:
        lines.append(f"\n✗ {len(failed)} paso(s) fallaron:")
        for s in failed:
            lines.append(f"  - {s.id}. {s.description}")

    if skipped:
        lines.append(f"\n⊘ {len(skipped)} paso(s) saltados:")
        for s in skipped:
            lines.append(f"  - {s.id}. {s.description}")

    if pending:
        pending_names = ", ".join(f"{s.id}. {s.description}" for s in pending)
        lines.append(f"\n📋 Quedan {len(pending)} paso(s) pendientes: {pending_names}")
        lines.append("💡 ¿Querés que lo intente de nuevo?")

    return "\n".join(lines)


def run_planner(
    uid: str,
    goal: str,
    registry: ToolRegistry,
    prebuilt_plan: Plan | None = None,
) -> tuple[Plan, str]:
    """Draft plan (o usar prebuilt_plan), execute tool steps (con PL05/PL06), return plan + feedback final.

    FASE 2.2: acepta ``prebuilt_plan`` opcional para ser llamado desde runtime.py
    con un plan ya generado por reasoning.py (sin prefijo ``plan:``).

    Flujo:
    1. Si prebuilt_plan → usarlo directamente; si no → draft_plan (PL01/PL02)
    2. Ejecutar steps con tool (PL06 fallback si falla)
    3. PL05: replan_after_failure si PLANNER_REFLECT=true tras fallo
    4. PL06: PLANNER_CONTINUE_ON_ERROR=true → seguir; false → skip restantes
    5. Ejecutar steps sin tool (respuesta al usuario)
    6. PL05: archivar plan en historial (_archive_plan)
    7. PL restante: generate_final_feedback
    8. Workboard: crear cards si WORKBOARD_ENABLED=true
    """
    if prebuilt_plan is not None:
        plan = prebuilt_plan
        if not plan.goal.strip():
            plan.goal = goal.strip() or "(plan sin intención)"
    else:
        plan = draft_plan(goal, registry)
    _active_plans[uid] = plan

    # Workboard: crear card raíz para el plan si está habilitado
    _create_workboard_plan_cards(uid, plan)

    # GOAL 5: si hay múltiples steps tool, ejecutar en paralelo via sub-agentes
    tool_steps = [s for s in plan.steps if s.tool_name and s.status == StepStatus.pending]
    if len(tool_steps) >= 3:
        try:
            plan = _run_with_sub_agents(uid, plan, registry)
            _sync_workboard_from_plan(uid, plan)
            _archive_plan(uid, plan)
            summary = generate_final_feedback(plan)
            return plan, summary
        except Exception:
            log.debug("Ejecución paralela con sub-agentes falló, usando secuencial", exc_info=True)

    # Fase 1: ejecutar steps con tool (secuencial)
    for step in plan.steps:
        if step.tool_name and step.status == StepStatus.pending:
            args: dict[str, Any] | None = None
            if step.tool_name == "web_search":
                args = {"query": plan.goal}
            execute_plan_step(uid, registry, step, args)

            # PL05: reflexión post-paso si falló y el flag está activo
            if settings.planner_reflect and step.status == StepStatus.failed:
                log.info("PL05 activado: replan_after_failure uid=%s step=%s", uid, step.id)
                replan_after_failure(uid, step.id, registry)

            # PL06: si no continuar en error, saltar steps tool restantes
            if step.status == StepStatus.failed and not settings.planner_continue_on_error:
                for remaining in plan.steps:
                    if remaining.status == StepStatus.pending and remaining.tool_name:
                        remaining.status = StepStatus.skipped
                        remaining.result_summary = (
                            f"Saltado — fallo previo en step {step.id} "
                            f"(PLANNER_CONTINUE_ON_ERROR=false)"
                        )
                break

    # Fase 2: ejecutar steps sin tool (pasos de respuesta al usuario)
    for step in plan.steps:
        if not step.tool_name and step.status == StepStatus.pending:
            execute_plan_step(uid, registry, step)

    # Sincronizar workboard con estado final del plan
    _sync_workboard_from_plan(uid, plan)

    # PL05: archivar plan en historial (se conserva copia; _active_plans se limpia después)
    _archive_plan(uid, plan)

    # PL restante: feedback loop final
    summary = generate_final_feedback(plan)
    return plan, summary


# ═══════════════════════════════════════════════════════════
# Workboard integration — crear/mover cards desde el planner
# ═══════════════════════════════════════════════════════════

# Mapa plan_step_id → card_id para sincronización
_plan_card_map: dict[str, dict[str, str]] = {}  # uid -> {step_id: card_id}


def _create_workboard_plan_cards(uid: str, plan: Plan) -> None:
    """Crea cards de workboard para cada paso del plan si WORKBOARD_ENABLED=true."""
    if not settings.workboard_enabled:
        return

    try:
        from app.services.workboard_service import (
            CardPriority,
            CardStatus,
            get_workboard_service,
        )

        svc = get_workboard_service()
        if not svc.enabled:
            return

        step_map: dict[str, str] = {}

        # Crear card raíz para el plan
        root_card = svc.create_card(
            uid=uid,
            title=f"Plan: {plan.goal[:100]}",
            description=f"Plan generado con {len(plan.steps)} pasos",
            priority=CardPriority.medium,
            labels=["plan"],
            metadata={"plan_goal": plan.goal, "step_count": len(plan.steps)},
        )

        if root_card:
            step_map["_root"] = root_card.id

            # Crear card por cada paso del plan
            for step in plan.steps:
                priority = CardPriority.medium
                if step.tool_name:
                    priority = CardPriority.high

                step_card = svc.create_card(
                    uid=uid,
                    title=step.description[:200],
                    description=f"Paso {step.id} — Tool: {step.tool_name or 'sin tool'}",
                    parent_id=root_card.id,
                    priority=priority,
                    labels=[step.tool_name] if step.tool_name else ["manual"],
                    metadata={
                        "step_id": step.id,
                        "tool_name": step.tool_name,
                        "plan_goal": plan.goal,
                    },
                )

                if step_card:
                    step_map[step.id] = step_card.id
                    # Mover a in_progress si es un paso con tool
                    if step.tool_name:
                        svc.move_card(uid, step_card.id, CardStatus.in_progress)

        _plan_card_map[uid] = step_map
        log.info("Workboard: %d cards creadas para plan uid=%s", len(step_map), uid[:8])

    except Exception:
        log.debug("Workboard integration: error creando cards para plan", exc_info=True)


def _sync_workboard_from_plan(uid: str, plan: Plan) -> None:
    """Sincroniza el estado del workboard con el plan completado."""
    if not settings.workboard_enabled:
        return

    step_map = _plan_card_map.get(uid, {})
    if not step_map:
        return

    try:
        from app.services.workboard_service import CardStatus, get_workboard_service

        svc = get_workboard_service()
        if not svc.enabled:
            return

        for step in plan.steps:
            card_id = step_map.get(step.id)
            if not card_id:
                continue

            if step.status == StepStatus.done:
                svc.move_card(uid, card_id, CardStatus.done)
            elif step.status == StepStatus.failed:
                svc.move_card(uid, card_id, CardStatus.blocked)
            elif step.status == StepStatus.skipped:
                svc.move_card(uid, card_id, CardStatus.done)
            elif step.status == StepStatus.running:
                svc.move_card(uid, card_id, CardStatus.in_progress)
            else:
                svc.move_card(uid, card_id, CardStatus.todo)

        # Marcar card raíz como done
        root_id = step_map.get("_root")
        if root_id:
            svc.move_card(uid, root_id, CardStatus.done)

        log.info("Workboard: sincronizado plan uid=%s, %d steps", uid[:8], len(plan.steps))

    except Exception:
        log.debug("Workboard integration: error sincronizando plan", exc_info=True)
    finally:
        # Limpiar el mapa
        _plan_card_map.pop(uid, None)


# ════════════════════════════════════════════════════════
# GOAL 5: Ejecución paralela con sub-agentes
# ════════════════════════════════════════════════════════

def _run_with_sub_agents(
    uid: str,
    plan: Plan,
    registry: ToolRegistry,
) -> Plan:
    """Ejecuta steps con tool en paralelo usando sub-agentes.

    Cada step con tool_name se delega a un sub-agente independiente.
    Los resultados se recolectan y se integran al plan.
    """
    from app.services.sub_agent_service import get_sub_agent_manager

    manager = get_sub_agent_manager()

    tool_steps = [s for s in plan.steps if s.tool_name and s.status == StepStatus.pending]
    if not tool_steps:
        return plan

    # Lanzar sub-agentes en paralelo
    spawned: dict[str, tuple[str, PlanStep]] = {}
    for step in tool_steps:
        try:
            agent_id = manager.spawn_sub_agent(
                uid=uid,
                name=f"Planner-{step.id}",
                goal=step.description,
                allowed_tools=[step.tool_name] if step.tool_name else [],
                context={"plan_goal": plan.goal, "step_id": step.id},
                registry=registry,
            )
            spawned[agent_id] = (step.id, step)
            step.status = StepStatus.running
            step.result_summary = f"Delegado a sub-agente {agent_id[:8]}"
            log.info(
                "PL05+GOAL5: step %s delegado a sub-agente %s",
                step.id, agent_id[:8],
            )
        except RuntimeError:
            # Límite de sub-agentes alcanzado — ejecutar secuencial
            log.warning(
                "No se pudo crear sub-agente para step %s — ejecutando secuencial",
                step.id,
            )
            execute_plan_step(uid, registry, step)

    # Esperar resultados
    for agent_id, (step_id, step) in spawned.items():
        result = manager.wait_for_sub_agent(uid, agent_id, timeout=300.0)
        if result is None:
            step.status = StepStatus.failed
            step.result_summary = f"Sub-agente {agent_id[:8]} no respondió a tiempo"
            continue

        if result["status"] == "completed":
            step.status = StepStatus.done
            step.result_summary = result.get("result_summary", "")[:500] or "(completado)"
        elif result["status"] == "failed":
            step.status = StepStatus.failed
            step.result_summary = result.get("error_message", "Error")[:500]
        elif result["status"] in ("cancelled", "idle_timeout"):
            step.status = StepStatus.skipped
            step.result_summary = f"Sub-agente {agent_id[:8]}: {result['status']}"
        else:
            step.status = StepStatus.failed
            step.result_summary = f"Estado inesperado: {result['status']}"

    # Ejecutar steps sin tool (respuesta al usuario)
    for step in plan.steps:
        if not step.tool_name and step.status == StepStatus.pending:
            execute_plan_step(uid, registry, step)

    return plan
