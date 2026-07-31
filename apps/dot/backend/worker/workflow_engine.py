"""Motor de workflows multi-paso para automatizaciones.

Permite definir DAGs de pasos que se ejecutan secuencialmente:
1. trigger: schedule, webhook, evento
2. action: leer email, buscar web, procesar con IA, enviar WhatsApp
3. condition: bifurcacion basada en resultados
4. output: notificar, guardar archivo, enviar email

Ejemplo de workflow:
```python
workflow = WorkflowBuilder("Factura mensual") \\
    .trigger("schedule", {"cron": "0 9 1 * *"}) \\
    .action("gmail", "Buscar factura de este mes") \\
    .condition("if_result_contains", {"keyword": "monto total"}) \\
    .action("chat", "Extraer el monto de la factura") \\
    .action("web_search", "Buscar tipo de cambio del dia") \\
    .action("whatsapp", "Enviar resumen al usuario") \\
    .output("notify", {}) \\
    .build()
```
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

log = logging.getLogger("dot.workflow_engine")


class StepType(Enum):
    TRIGGER = "trigger"
    ACTION = "action"
    CONDITION = "condition"
    OUTPUT = "output"


class ConditionOperator(Enum):
    ALWAYS = "always"
    IF_RESULT_CONTAINS = "if_result_contains"
    IF_RESULT_MATCHES = "if_result_matches"
    IF_ERROR = "if_error"
    IF_NO_ERROR = "if_no_error"


@dataclass
class StepResult:
    """Resultado de un paso individual del workflow."""
    step_id: str
    step_type: StepType
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0


@dataclass
class WorkflowExecutionResult:
    """Resultado completo de la ejecucion de un workflow."""
    workflow_id: str
    workflow_name: str
    success: bool
    steps: list[StepResult]
    final_output: str
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None

    @property
    def total_duration_ms(self) -> float:
        if self.completed_at and self.steps:
            try:
                start = datetime.fromisoformat(self.started_at)
                end = datetime.fromisoformat(self.completed_at)
                return (end - start).total_seconds() * 1000
            except (ValueError, TypeError):
                pass
        return sum(s.duration_ms for s in self.steps)


@dataclass
class WorkflowStepDef:
    """Definicion de un paso en el workflow."""
    id: str
    type: StepType
    integration: str  # gmail, google-calendar, chat, web_search, whatsapp
    instruction: str
    condition_operator: ConditionOperator = ConditionOperator.ALWAYS
    condition_value: str = ""
    depends_on: list[str] = field(default_factory=list)
    timeout_seconds: int = 30


@dataclass
class WorkflowDef:
    """Definicion completa de un workflow."""
    id: str
    name: str
    steps: list[WorkflowStepDef]
    description: str = ""


class WorkflowBuilder:
    """Builder para construir workflows programaticamente."""

    def __init__(self, name: str, description: str = ""):
        self._id = f"wf_{uuid.uuid4().hex[:12]}"
        self._name = name
        self._description = description
        self._steps: list[WorkflowStepDef] = []

    def trigger(self, integration: str, instruction: str) -> "WorkflowBuilder":
        return self._add_step(StepType.TRIGGER, integration, instruction)

    def action(self, integration: str, instruction: str) -> "WorkflowBuilder":
        return self._add_step(StepType.ACTION, integration, instruction)

    def condition(
        self,
        operator: ConditionOperator | str,
        value: str = "",
        instruction: str = "",
    ) -> "WorkflowBuilder":
        if isinstance(operator, str):
            operator = ConditionOperator(operator)
        step_id = f"step_{len(self._steps) + 1}"
        step = WorkflowStepDef(
            id=step_id,
            type=StepType.CONDITION,
            integration="condition",
            instruction=instruction or f"Condicion: {operator.value} '{value}'",
            condition_operator=operator,
            condition_value=value,
            depends_on=[self._steps[-1].id] if self._steps else [],
        )
        self._steps.append(step)
        return self

    def output(self, integration: str, instruction: str = "notify") -> "WorkflowBuilder":
        return self._add_step(StepType.OUTPUT, integration, instruction)

    def _add_step(self, step_type: StepType, integration: str, instruction: str) -> "WorkflowBuilder":
        step_id = f"step_{len(self._steps) + 1}"
        step = WorkflowStepDef(
            id=step_id,
            type=step_type,
            integration=integration,
            instruction=instruction,
            depends_on=[self._steps[-1].id] if self._steps else [],
        )
        self._steps.append(step)
        return self

    def build(self) -> WorkflowDef:
        return WorkflowDef(
            id=self._id,
            name=self._name,
            description=self._description,
            steps=self._steps,
        )


# ─── Acciones registradas ──────────────────────────────

ActionHandler = Callable[[str, str], str]

_registered_actions: dict[str, ActionHandler] = {}


def register_action(name: str, handler: ActionHandler) -> None:
    """Registra un handler para un tipo de accion."""
    _registered_actions[name] = handler
    log.debug("Accion registrada: %s", name)


def get_action(name: str) -> ActionHandler | None:
    return _registered_actions.get(name)


# ─── Ejecutor de Workflows ─────────────────────────────

class WorkflowExecutor:
    """Ejecuta WorkflowDefs paso a paso.

    Cada paso se ejecuta secuencialmente (soporte futuro para paralelismo).
    Las condiciones pueden bifurcar o detener el flujo.
    """

    def __init__(self):
        self._uid: str = ""
        self._context: dict[str, Any] = {}

    def execute(self, uid: str, workflow: WorkflowDef) -> WorkflowExecutionResult:
        """Ejecuta un workflow completo. Retorna el resultado."""
        self._uid = uid
        self._context = {"workflow_id": workflow.id, "workflow_name": workflow.name}

        log.info("Ejecutando workflow: %s (%d pasos)", workflow.name, len(workflow.steps))

        results: list[StepResult] = []
        skip_remaining = False

        for step in workflow.steps:
            if skip_remaining:
                break

            step_result = self._execute_step(step)
            results.append(step_result)

            # Evaluar condicion
            if not self._evaluate_condition(step, step_result):
                log.info("Condicion no cumplida en paso %s, deteniendo workflow", step.id)
                skip_remaining = True

        final_output = self._build_final_output(results)
        success = all(r.error is None for r in results) and not skip_remaining

        result = WorkflowExecutionResult(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            success=success,
            steps=results,
            final_output=final_output,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        log.info(
            "Workflow %s completado: %s (%d pasos, %d errores)",
            workflow.name,
            "OK" if success else "FALLO",
            len(results),
            sum(1 for r in results if r.error),
        )
        return result

    def _execute_step(self, step: WorkflowStepDef) -> StepResult:
        """Ejecuta un paso individual."""
        log.debug("Ejecutando paso %s: %s/%s", step.id, step.type.value, step.integration)

        import time
        start = time.monotonic()

        try:
            output = self._dispatch_action(step)
            duration = (time.monotonic() - start) * 1000

            self._context[f"step_{step.id}_output"] = output
            return StepResult(
                step_id=step.id,
                step_type=step.type,
                output=output,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            error_msg = str(e)
            log.error("Paso %s fallo: %s", step.id, error_msg)

            self._context[f"step_{step.id}_error"] = error_msg
            return StepResult(
                step_id=step.id,
                step_type=step.type,
                output="",
                error=error_msg,
                duration_ms=duration,
            )

    def _dispatch_action(self, step: WorkflowStepDef) -> str:
        """Despacha un paso al handler registrado segun su integracion."""
        from worker.executor import AutomationExecutor

        executor = AutomationExecutor()

        # Contexto de pasos previos (para notificaciones WA con el resumen real)
        from app.services.pipeline_message_format import humanize_step_output

        prior_parts: list[str] = []
        for key, value in self._context.items():
            if key.endswith("_output") and isinstance(value, str) and value.strip():
                prior_parts.append(humanize_step_output(value.strip()) or value.strip())
        prior_output = "\n\n".join(prior_parts[-3:]) if prior_parts else ""

        integration = (step.integration or "chat").strip().lower()
        output_type = "chat"
        if integration in {"whatsapp", "wa"}:
            output_type = "whatsapp"

        auto_dict = {
            "id": f"wf_{step.id}",
            "name": f"{step.type.value}:{step.integration}",
            "integration_id": step.integration,
            "instruction": step.instruction,
            "output_type": output_type,
            "prior_output": prior_output,
            "step_type": step.type.value,
        }

        return executor.execute(self._uid, auto_dict)

    def _evaluate_condition(self, step: WorkflowStepDef, result: StepResult) -> bool:
        """Evalua si la condicion del paso se cumple."""
        if step.type != StepType.CONDITION:
            return True

        if step.condition_operator == ConditionOperator.ALWAYS:
            return True

        if step.condition_operator == ConditionOperator.IF_RESULT_CONTAINS:
            return step.condition_value.lower() in result.output.lower()

        if step.condition_operator == ConditionOperator.IF_RESULT_MATCHES:
            import re
            return bool(re.search(step.condition_value, result.output, re.IGNORECASE))

        if step.condition_operator == ConditionOperator.IF_ERROR:
            return result.error is not None

        if step.condition_operator == ConditionOperator.IF_NO_ERROR:
            return result.error is None

        return True

    def _build_final_output(self, results: list[StepResult]) -> str:
        """Construye el output final del workflow en texto legible (sin JSON crudo)."""
        from app.services.pipeline_message_format import humanize_step_output

        lines = []
        for i, r in enumerate(results, 1):
            if r.error:
                lines.append(f"Paso {i}: Error — {r.error}")
                continue
            human = humanize_step_output(r.output) or (r.output or "").strip()
            # Evitar volcar confirmaciones técnicas largas
            if human.lower().startswith("mensaje whatsapp enviado"):
                lines.append(f"Paso {i}: {human}")
            else:
                preview = human.replace("\n", " ").strip()
                if len(preview) > 220:
                    preview = preview[:220].rsplit(" ", 1)[0] + "…"
                lines.append(f"Paso {i}: {preview}")
        return "\n".join(lines)


# ─── Parseo de workflow desde Firestore ────────────────

def parse_workflow_from_profile(raw: dict[str, Any]) -> WorkflowDef | None:
    """Parsea un workflow desde el perfil de Firestore.

    Formato esperado:
    ```json
    {
        "id": "wf_...",
        "name": "Mi workflow",
        "steps": [
            {"type": "action", "integration": "gmail", "instruction": "..."},
            {"type": "condition", "operator": "if_result_contains", "value": "factura"}
        ]
    }
    ```
    """
    try:
        wf_id = raw.get("id", f"wf_{uuid.uuid4().hex[:12]}")
        name = raw.get("name", "Workflow sin nombre")
        steps_raw = raw.get("steps", [])

        steps: list[WorkflowStepDef] = []
        for i, s in enumerate(steps_raw):
            step_type = StepType(s.get("type", "action"))
            integration = s.get("integration", "chat")
            instruction = s.get("instruction", "")
            condition_op = ConditionOperator(s.get("condition_operator", "always"))
            condition_val = s.get("condition_value", "")

            step = WorkflowStepDef(
                id=f"step_{i + 1}",
                type=step_type,
                integration=integration,
                instruction=instruction,
                condition_operator=condition_op,
                condition_value=condition_val,
                depends_on=[f"step_{i}"] if i > 0 else [],
            )
            steps.append(step)

        return WorkflowDef(id=wf_id, name=name, steps=steps)
    except Exception as e:
        log.warning("Error parseando workflow desde perfil: %s", e)
        return None
