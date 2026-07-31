"""Modelos Pydantic para pipelines compuestos multi-paso (C2).

Un pipeline es una secuencia de pasos con lógica condicional que encadena
herramientas (Gmail → guardar archivo → WhatsApp notify, etc.).

PipelineStep: un paso individual del pipeline.
PipelineDef: definición completa de un pipeline (equivalente API a WorkflowDef).
PipelineExecutionResult: resultado de una ejecución de pipeline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepType(str, Enum):
    TRIGGER = "trigger"
    ACTION = "action"
    CONDITION = "condition"
    OUTPUT = "output"


class ConditionOperator(str, Enum):
    ALWAYS = "always"
    IF_RESULT_CONTAINS = "if_result_contains"
    IF_RESULT_MATCHES = "if_result_matches"
    IF_ERROR = "if_error"
    IF_NO_ERROR = "if_no_error"


class OnFailure(str, Enum):
    """Qué hacer cuando un paso falla."""
    SKIP = "skip"       # Continuar con el siguiente paso
    LOG = "log"         # Registrar error y continuar
    ABORT = "abort"     # Detener el pipeline completo


class PipelineStepDef(BaseModel):
    """Definición de un paso individual del pipeline."""
    id: str = Field(default_factory=lambda: f"step_{id(PipelineStepDef) % 10000}")
    type: StepType = StepType.ACTION
    integration: str = "chat"  # gmail, google-calendar, chat, whatsapp, web_search, file
    instruction: str = ""
    condition_operator: ConditionOperator = ConditionOperator.ALWAYS
    condition_value: str = ""
    depends_on: list[str] = Field(default_factory=list)
    on_failure: OnFailure = OnFailure.LOG
    timeout_seconds: int = 30


class PipelineDef(BaseModel):
    """Definición completa de un pipeline."""
    id: str = ""
    name: str = "Pipeline sin nombre"
    description: str = ""
    steps: list[PipelineStepDef] = Field(default_factory=list)
    schedule: str = "manual"  # manual, daily:09:00, weekly:mon:09:00
    active: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_run: str | None = None
    source_nl: str = ""  # descripción en lenguaje natural original

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=False)


class StepResult(BaseModel):
    """Resultado de un paso individual."""
    step_id: str
    step_type: str
    output: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0


class PipelineExecutionResult(BaseModel):
    """Resultado completo de la ejecución de un pipeline."""
    pipeline_id: str
    pipeline_name: str
    success: bool
    steps: list[StepResult] = Field(default_factory=list)
    final_output: str = ""
    error: str | None = None
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


class PipelineIntentResponse(BaseModel):
    """Respuesta del LLM al detectar intención de pipeline."""
    is_pipeline: bool
    pipeline: PipelineDef | None = None
    explanation: str = ""


class PipelineListResponse(BaseModel):
    """Lista de pipelines del usuario."""
    pipelines: list[PipelineDef]


class PipelineCreateRequest(BaseModel):
    """Request para crear un pipeline desde NL o estructura manual."""
    name: str = ""
    description: str = ""
    natural_language: str = ""  # "cada lunes revisa Gmail, guarda PDFs, avisa por WA"
    schedule: str = "manual"
    steps: list[PipelineStepDef] = Field(default_factory=list)  # Si ya viene estructurado


class PipelineUpdateRequest(BaseModel):
    """Request para actualizar un pipeline."""
    name: str | None = None
    description: str | None = None
    steps: list[PipelineStepDef] | None = None
    schedule: str | None = None
    active: bool | None = None


class PipelineExecuteResponse(BaseModel):
    """Respuesta de ejecución de pipeline."""
    execution_id: str
    success: bool
    final_output: str
    steps_count: int
    executed_at: str
    error: str | None = None
    steps: list[StepResult] = Field(default_factory=list)
