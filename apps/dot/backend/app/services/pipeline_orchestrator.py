"""Orquestador de pipelines compuestos multi-paso (C2).

Convierte descripciones en lenguaje natural a pipelines estructurados usando LLM,
los almacena en Firestore y los ejecuta a través del WorkflowExecutor.

Flujo:
1. Usuario dice "cada lunes revisa Gmail, guarda PDFs, avisa por WA"
2. LLM parsea la intención → estructura de pasos (PipelineDef)
3. Se almacena en Firestore users/{uid}/pipelines/{id}
4. Se programa en el scheduler para ejecución recurrente
5. El worker ejecuta cada paso secuencialmente
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.firebase_db import get_db as get_firestore_client
from app.models.pipeline import (
    ConditionOperator,
    OnFailure,
    PipelineCreateRequest,
    PipelineDef,
    PipelineExecutionResult,
    PipelineStepDef,
    PipelineUpdateRequest,
    StepType,
)
from app.services.provider_router import route_chat

log = logging.getLogger("dot.pipeline_orchestrator")

PIPELINE_PARSE_SYSTEM_PROMPT = """Eres un motor de automatizaciones que convierte instrucciones en lenguaje natural
a pipelines estructurados multi-paso. Analiza la instrucción del usuario y genera un JSON
con los pasos necesarios.

REGLAS:
1. Identifica TODAS las herramientas mencionadas: Gmail, Google Calendar, WhatsApp, archivos locales, búsqueda web, IA/chat.
2. Determina la secuencia lógica de pasos.
3. Si hay condiciones ("si hay PDFs", "si encuentras X"), agrega pasos CONDITION.
4. Usa estos tipos de paso:
   - "action": ejecuta una herramienta (leer correos, buscar, procesar con IA)
   - "condition": bifurca el flujo (if_result_contains, if_no_error, etc.)
   - "output": notifica o guarda resultados (whatsapp, archivo, notify)
5. Cada paso debe tener:
   - "integration": nombre de la herramienta (gmail, google-calendar, chat, whatsapp, web_search, file)
   - "instruction": qué hacer en ese paso, en español claro
   - "condition_operator" (solo para condition): "if_result_contains", "if_result_matches", "if_error", "if_no_error", "always"
   - "condition_value" (solo para condition): palabra clave o regex
6. El último paso debe ser de tipo "output" para notificar al usuario.

INTEGRACIONES DISPONIBLES:
- gmail: leer correos, buscar correos, enviar correos
- google-calendar: consultar agenda, crear eventos
- whatsapp: enviar mensajes por WhatsApp
- chat: procesar texto con IA (extraer datos, resumir, analizar)
- web_search: buscar información en internet
- file: leer/escribir archivos locales (PDF, DOCX, TXT)

Responde SOLO con JSON válido, sin markdown, con este esquema exacto:
{
  "name": "nombre corto del pipeline",
  "description": "descripción breve",
  "steps": [
    {
      "type": "action",
      "integration": "gmail",
      "instruction": "Buscar correos con PDFs adjuntos",
      "on_failure": "log"
    },
    {
      "type": "condition",
      "integration": "condition",
      "instruction": "Verificar si se encontraron PDFs",
      "condition_operator": "if_result_contains",
      "condition_value": "PDF",
      "on_failure": "skip"
    },
    {
      "type": "action",
      "integration": "file",
      "instruction": "Guardar los PDFs encontrados en la carpeta DOT",
      "on_failure": "log"
    },
    {
      "type": "output",
      "integration": "whatsapp",
      "instruction": "Notificar al usuario con un resumen de lo encontrado y guardado",
      "on_failure": "log"
    }
  ]
}"""


class PipelineOrchestrator:
    """Orquesta la creación, almacenamiento y ejecución de pipelines multi-paso."""

    FIRESTORE_COLLECTION = "pipelines"  # subcolección de users/{uid}

    def parse_natural_language(self, uid: str, text: str) -> PipelineDef:
        """Convierte una descripción NL en un PipelineDef usando LLM."""
        from app.application.agent.reasoning import apply_reasoning, record_reasoning_usage
        from app.billing_db import get_session_factory
        from uuid import UUID

        reasoning = apply_reasoning(
            uid=uid,
            channel="pipeline",
            user_text=text,
            base_system_prompt=PIPELINE_PARSE_SYSTEM_PROMPT,
        )
        system_prompt = reasoning.system_prompt

        prompt = (
            f"Convierte esta instrucción en un pipeline de automatización:\n\n"
            f'"{text}"\n\n'
            "Genera SOLO el JSON del pipeline."
        )

        try:
            response = route_chat(
                prompt,
                system_prompt=system_prompt,
                include_document_action_prompt=False,
            )
            if reasoning.plan:
                try:
                    factory = get_session_factory()
                    db = factory()
                    try:
                        record_reasoning_usage(
                            db,
                            cliente_id=UUID(uid),
                            plan=reasoning.plan,
                        )
                    finally:
                        db.close()
                except Exception:
                    log.debug("Usage reasoning pipeline omitido uid=%s", uid[:8], exc_info=True)
            return self._parse_llm_response(response, text)
        except Exception as e:
            log.error("Error parseando pipeline NL: %s", e)
            raise RuntimeError(f"No se pudo interpretar la instrucción como pipeline: {e}")

    def create_pipeline(self, uid: str, request: PipelineCreateRequest) -> PipelineDef:
        """Crea un pipeline desde NL o estructura manual.

        Prioridad: steps estructurados (editor visual) > NL (LLM) > error.
        """
        if request.steps:
            pipeline = PipelineDef(
                name=request.name or "Pipeline personalizado",
                description=request.description or "",
                steps=list(request.steps),
                source_nl=request.natural_language or "",
            )
        elif request.natural_language:
            try:
                pipeline = self.parse_natural_language(uid, request.natural_language)
            except Exception as e:
                log.warning(
                    "LLM pipeline falló, usando fallback heurístico: %s", e,
                )
                pipeline = self._heuristic_pipeline_from_text(request.natural_language)
            pipeline.source_nl = request.natural_language
        else:
            raise ValueError("Debe proporcionar natural_language o steps.")

        pipeline.schedule = request.schedule
        pipeline.id = f"pl_{uuid.uuid4().hex[:12]}"

        if request.name:
            pipeline.name = request.name
        if request.description:
            pipeline.description = request.description

        self._save_to_firestore(uid, pipeline)
        log.info("Pipeline creado: %s (%s) para uid=%s", pipeline.name, pipeline.id, uid[:8])
        return pipeline

    @staticmethod
    def _heuristic_pipeline_from_text(text: str) -> PipelineDef:
        """Fallback sin LLM: arma pasos básicos a partir de palabras clave."""
        import re

        t = text.lower()
        steps: list[PipelineStepDef] = []
        n = 0

        def add(step_type: StepType, integration: str, instruction: str, **kw: Any) -> None:
            nonlocal n
            n += 1
            steps.append(
                PipelineStepDef(
                    id=f"step_{n}",
                    type=step_type,
                    integration=integration,
                    instruction=instruction,
                    depends_on=[f"step_{n - 1}"] if n > 1 else [],
                    **kw,
                )
            )

        if re.search(r"(diario|diaria|todos los d[ií]as|cada d[ií]a|semanal)", t):
            add(StepType.TRIGGER, "chat", f"Programar revisión periódica: {text[:120]}")
        else:
            add(StepType.TRIGGER, "chat", "Ejecutar manualmente cuando el usuario lo pida")

        if re.search(r"gmail|correo|email|bandeja", t):
            add(StepType.ACTION, "gmail", "Revisar correos relevantes en Gmail")
        if re.search(r"archivo|descarg|escritorio|carpeta|pdf|documento|pc", t):
            add(
                StepType.ACTION,
                "file",
                "Listar archivos reales en el Escritorio (~/Desktop) con nombres",
            )
        if re.search(r"whatsapp|notific|avis", t):
            add(StepType.OUTPUT, "whatsapp", "Notificar al usuario por WhatsApp con el resumen")
        else:
            add(StepType.OUTPUT, "chat", "Mostrar al usuario un resumen de lo encontrado")

        name = "Pipeline desde descripción"
        if "pc" in t or "archivo" in t:
            name = "Revisar PC y archivos"
        elif "gmail" in t or "correo" in t:
            name = "Revisar correo"

        return PipelineDef(name=name, description=text[:200], steps=steps, source_nl=text)

    def get_pipeline(self, uid: str, pipeline_id: str) -> PipelineDef | None:
        """Obtiene un pipeline por ID desde Firestore."""
        data = self._get_from_firestore(uid, pipeline_id)
        if not data:
            return None
        return PipelineDef(**data)

    def list_pipelines(self, uid: str) -> list[PipelineDef]:
        """Lista todos los pipelines del usuario."""
        try:
            db = get_firestore_client()
            docs = (
                db.collection("users")
                .document(uid)
                .collection(self.FIRESTORE_COLLECTION)
                .stream()
            )
            return [PipelineDef(**d.to_dict()) for d in docs if d.to_dict()]
        except Exception as e:
            log.warning("Error listando pipelines para uid=%s: %s", uid[:8], e)
            return []

    def update_pipeline(self, uid: str, pipeline_id: str, request: PipelineUpdateRequest) -> PipelineDef:
        """Actualiza un pipeline existente."""
        existing = self.get_pipeline(uid, pipeline_id)
        if not existing:
            raise ValueError(f"Pipeline {pipeline_id} no encontrado.")

        update_data: dict[str, Any] = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.steps is not None:
            update_data["steps"] = [s.model_dump() for s in request.steps]
        if request.schedule is not None:
            update_data["schedule"] = request.schedule
        if request.active is not None:
            update_data["active"] = request.active

        if not update_data:
            return existing

        try:
            db = get_firestore_client()
            db.collection("users").document(uid).collection(
                self.FIRESTORE_COLLECTION
            ).document(pipeline_id).set(update_data, merge=True)
            log.info("Pipeline actualizado: %s para uid=%s", pipeline_id, uid[:8])
        except Exception as e:
            log.error("Error actualizando pipeline %s: %s", pipeline_id, e)
            raise RuntimeError(f"Error al actualizar pipeline: {e}")

        return self.get_pipeline(uid, pipeline_id) or existing

    def delete_pipeline(self, uid: str, pipeline_id: str) -> bool:
        """Elimina un pipeline."""
        try:
            db = get_firestore_client()
            db.collection("users").document(uid).collection(
                self.FIRESTORE_COLLECTION
            ).document(pipeline_id).delete()
            log.info("Pipeline eliminado: %s para uid=%s", pipeline_id, uid[:8])
            return True
        except Exception as e:
            log.error("Error eliminando pipeline %s: %s", pipeline_id, e)
            return False

    def execute_pipeline(self, uid: str, pipeline_id: str) -> PipelineExecutionResult:
        """Ejecuta un pipeline inmediatamente."""
        pipeline = self.get_pipeline(uid, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} no encontrado.")

        return self._execute(uid, pipeline)

    def execute_pipeline_from_def(self, uid: str, pipeline: PipelineDef) -> PipelineExecutionResult:
        """Ejecuta un PipelineDef directamente (sin buscar en Firestore)."""
        return self._execute(uid, pipeline)

    def _execute(self, uid: str, pipeline: PipelineDef) -> PipelineExecutionResult:
        """Ejecuta un pipeline paso a paso usando WorkflowExecutor."""
        from worker.workflow_engine import (
            ConditionOperator as WfConditionOp,
            StepType as WfStepType,
            WorkflowDef,
            WorkflowExecutor,
            WorkflowStepDef,
        )

        # Convertir PipelineStepDef → WorkflowStepDef
        wf_steps: list[WorkflowStepDef] = []
        for i, step in enumerate(pipeline.steps):
            wf_step = WorkflowStepDef(
                id=step.id,
                type=WfStepType(step.type.value),
                integration=step.integration,
                instruction=step.instruction,
                condition_operator=WfConditionOp(step.condition_operator.value),
                condition_value=step.condition_value,
                depends_on=step.depends_on or ([f"step_{i}"] if i > 0 else []),
                timeout_seconds=step.timeout_seconds,
            )
            wf_steps.append(wf_step)

        wf = WorkflowDef(
            id=pipeline.id,
            name=pipeline.name,
            description=pipeline.description,
            steps=wf_steps,
        )

        executor = WorkflowExecutor()
        wf_result = executor.execute(uid, wf)

        # Convertir resultado a modelo API
        from app.models.pipeline import StepResult

        step_results = [
            StepResult(
                step_id=s.step_id,
                step_type=s.step_type.value,
                output=s.output,
                error=s.error,
                metadata=s.metadata,
                executed_at=s.executed_at,
                duration_ms=s.duration_ms,
            )
            for s in wf_result.steps
        ]

        result = PipelineExecutionResult(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            success=wf_result.success,
            steps=step_results,
            final_output=wf_result.final_output,
            error=wf_result.error,
            started_at=wf_result.started_at,
            completed_at=wf_result.completed_at,
        )

        # Actualizar last_run en Firestore
        try:
            db = get_firestore_client()
            db.collection("users").document(uid).collection(
                self.FIRESTORE_COLLECTION
            ).document(pipeline.id).set(
                {"last_run": datetime.now(timezone.utc).isoformat()},
                merge=True,
            )
        except Exception as e:
            log.warning("Error actualizando last_run: %s", e)

        return result

    def to_task_payload(self, pipeline: PipelineDef) -> dict[str, Any]:
        """Convierte un pipeline a payload compatible con TaskQueue."""
        return {
            "id": pipeline.id,
            "name": pipeline.name,
            "integration_id": "pipeline",
            "instruction": pipeline.description or pipeline.name,
            "output_type": "chat",
            "active": pipeline.active,
            "schedule": pipeline.schedule,
            "is_pipeline": True,
            "pipeline_steps": [s.model_dump() for s in pipeline.steps],
        }

    # ─── Firestore helpers ──────────────────────────────

    def _save_to_firestore(self, uid: str, pipeline: PipelineDef) -> None:
        db = get_firestore_client()
        doc_ref = db.collection("users").document(uid).collection(
            self.FIRESTORE_COLLECTION
        ).document(pipeline.id)
        doc_ref.set(pipeline.model_dump())
        log.debug("Pipeline guardado en Firestore: %s", pipeline.id)

    def _get_from_firestore(self, uid: str, pipeline_id: str) -> dict[str, Any] | None:
        try:
            db = get_firestore_client()
            doc = (
                db.collection("users")
                .document(uid)
                .collection(self.FIRESTORE_COLLECTION)
                .document(pipeline_id)
                .get()
            )
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            log.warning("Error leyendo pipeline %s: %s", pipeline_id, e)
        return None

    # ─── LLM response parser ────────────────────────────

    @staticmethod
    def _parse_llm_response(response: str, source_nl: str) -> PipelineDef:
        """Parsea la respuesta JSON del LLM a PipelineDef."""
        # Limpiar respuesta (posibles markdown code blocks)
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Intentar extraer el primer objeto JSON del texto
            import re
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    raise RuntimeError("El LLM no devolvió JSON válido para el pipeline.")
            else:
                raise RuntimeError("El LLM no devolvió JSON válido para el pipeline.")

        name = data.get("name", "Pipeline")
        description = data.get("description", "")
        steps_raw = data.get("steps", [])

        steps: list[PipelineStepDef] = []
        for i, s in enumerate(steps_raw):
            step = PipelineStepDef(
                id=f"step_{i + 1}",
                type=StepType(s.get("type", "action")),
                integration=s.get("integration", "chat"),
                instruction=s.get("instruction", ""),
                condition_operator=ConditionOperator(s.get("condition_operator", "always")),
                condition_value=s.get("condition_value", ""),
                depends_on=[f"step_{i}"] if i > 0 else [],
                on_failure=OnFailure(s.get("on_failure", "log")),
                timeout_seconds=s.get("timeout_seconds", 30),
            )
            steps.append(step)

        return PipelineDef(
            id=f"pl_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            steps=steps,
            source_nl=source_nl,
        )
