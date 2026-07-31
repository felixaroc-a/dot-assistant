"""Automatizaciones compuestas (FREE-AU01 skeleton)."""

from app.application.automations.composite import (
    AutomationRunResult,
    AutomationSpec,
    AutomationStep,
    execute_composite_if_enabled,
    run_composite_automation,
)

__all__ = [
    "AutomationRunResult",
    "AutomationSpec",
    "AutomationStep",
    "execute_composite_if_enabled",
    "run_composite_automation",
]
