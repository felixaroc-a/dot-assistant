"""Modos de razonamiento DOT: off / low / medium / high / auto."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.ai_provider import AIConfig, AIProvider, MODEL_CHAT, MODEL_REASONER
from app.settings import settings

log = logging.getLogger("dot.agent.reasoning")

ReasoningLevel = Literal["off", "low", "medium", "high", "auto"]
EffectiveLevel = Literal["off", "low", "medium", "high"]
ReasoningChannel = Literal["pc", "whatsapp", "automation", "pipeline"]

_VALID_LEVELS = frozenset({"off", "low", "medium", "high", "auto"})

_TRIVIAL_RE = re.compile(
    r"^\s*(hola|hello|hi|hey|buenos?\s+d[ií]as?|buenas?\s+(tardes|noches)|"
    r"gracias|ok|vale|si|s[ií]|no|thanks|thank\s+you)\s*[!.?]*\s*$",
    re.IGNORECASE,
)

_HIGH_SIGNALS = re.compile(
    r"\b(pipeline|automatizaci[oó]n|multi.?paso|planifica|dise[nñ]a|orquest|"
    r"workflow|encadena|secuencia\s+de\s+pasos)\b",
    re.IGNORECASE,
)

_MEDIUM_SIGNALS = re.compile(
    r"\b(whatsapp|wa\b|env[ií]a|mand[aá]|mensaje|archivo|escritorio|desktop|"
    r"descarga|busca\s+en\s+(internet|la\s+web)|gmail|calendar|correo|0412|\+58)\b",
    re.IGNORECASE,
)

_ACTION_VERBS = re.compile(
    r"\b(env[ií]a|mand[aá]|crea|guarda|escribe|descarga|busca|programa|automatiza|"
    r"vincula|configura|genera|analiza)\b",
    re.IGNORECASE,
)

_PLAN_SYSTEM = """Eres el planificador interno de DOT. Analiza la petición del usuario y produce
un plan JSON estructurado para que el agente ejecutor use tools reales.

Responde SOLO con JSON válido (sin markdown), con este esquema:
{
  "intent": "qué quiere lograr el usuario en una frase",
  "steps": ["paso 1", "paso 2"],
  "tools_needed": ["send_whatsapp_message", "writeFile"],
  "success_criteria": "cómo saber que la tarea se completó de verdad",
  "risks": ["qué puede fallar"],
  "user_visible_summary": "resumen corto en español para mostrar al usuario (2-4 oraciones)"
}

Reglas:
- DOT SÍ puede acceder al disco local del usuario con tools (listFiles, readFile, writeFile,
  file_search, generate_document, etc.). NUNCA digas que hay que "subir archivos" ni que
  no hay acceso a rutas locales C:\\... — planifica usar esas tools directamente.
- Si faltan datos (número, archivo, destinatario), indícalo en risks y steps.
- No afirmes éxito anticipado; el ejecutor debe usar tools y verificar.
- user_visible_summary debe ser claro y sin jerga técnica.
- Para informes profundos, los steps deben cubrir leer archivos reales y generar el entregable completo.
- FASE 2.2: si hay >=2 pasos, el plan se pasa automáticamente al planificador multi-paso
  para ejecución secuencial. No necesitas prefijo 'plan:'."""

_LOW_HINT = (
    "\n\n[MODO RAZONAMIENTO — LOW]\n"
    "Antes de responder o usar tools:\n"
    "1. Identifica la intención exacta del usuario.\n"
    "2. Si vas a afirmar que completaste una acción (WhatsApp, archivo, etc.), "
    "DEBES haber ejecutado la tool correspondiente con éxito.\n"
    "3. Si falta un dato crítico, pregunta antes de actuar.\n"
    "4. No dejes la tarea a medias: actúa hasta el entregable final completo.\n"
)

LOW_REASONING_SUFFIX = _LOW_HINT


@dataclass
class PlanArtifact:
    intent: str = ""
    steps: list[str] = field(default_factory=list)
    tools_needed: list[str] = field(default_factory=list)
    success_criteria: str = ""
    risks: list[str] = field(default_factory=list)
    user_visible_summary: str = ""
    level: EffectiveLevel = "medium"
    model: str | None = None
    usage: dict[str, Any] | None = None

    def to_sse_payload(self) -> dict[str, Any]:
        return {
            "type": "reasoning_plan",
            "summary": self.user_visible_summary or self.intent,
            "steps": self.steps[:8],
            "level": self.level,
            "tools_needed": self.tools_needed[:6],
        }


@dataclass
class ReasoningResult:
    effective_level: EffectiveLevel
    system_prompt: str
    plan: PlanArtifact | None = None
    reasoning_usage: dict[str, Any] | None = None
    reasoning_model: str | None = None
    sse_events: list[dict[str, Any]] = field(default_factory=list)
    # FASE 2.2: plan listo para ejecución por planner.py (si tiene >=2 steps)
    plan_for_execution: PlanArtifact | None = None


def normalize_level(raw: str | None) -> ReasoningLevel:
    level = (raw or "auto").strip().lower()
    if level not in _VALID_LEVELS:
        return "auto"
    return level  # type: ignore[return-value]


def load_reasoning_prefs(
    uid: str,
    *,
    request_enabled: bool | None = None,
    request_level: str | None = None,
) -> tuple[bool, ReasoningLevel]:
    enabled = False
    level: ReasoningLevel = "auto"
    try:
        from app.firebase_db import get_user_profile

        profile = get_user_profile(uid) or {}
        # FASE 2.2: razonamiento activado por defecto; usuario puede desactivar en perfil
        enabled = bool(profile.get("reasoning_enabled", True))
        level = normalize_level(str(profile.get("reasoning_level") or "auto"))
    except Exception:
        log.debug("Sin perfil Firestore para reasoning uid=%s", uid[:8] if uid else "?", exc_info=True)

    if request_enabled is not None:
        enabled = bool(request_enabled)
    if request_level is not None:
        level = normalize_level(request_level)
    return enabled, level


def is_trivial_message(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < 12 and _TRIVIAL_RE.match(t):
        return True
    if t.endswith("?") and len(t.split()) <= 6 and not _ACTION_VERBS.search(t):
        return True
    return False


def has_action_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _ACTION_VERBS.search(t):
        return True
    if _MEDIUM_SIGNALS.search(t):
        return True
    if _HIGH_SIGNALS.search(t):
        return True
    if len(t.split()) >= 25:
        return True
    return False


def classify_auto(text: str, channel: ReasoningChannel) -> EffectiveLevel:
    t = (text or "").strip()
    if is_trivial_message(t):
        return "off"
    if channel == "pipeline" or _HIGH_SIGNALS.search(t):
        return "high"
    if channel == "automation":
        return "medium" if has_action_intent(t) else "low"
    if _MEDIUM_SIGNALS.search(t) or len(_ACTION_VERBS.findall(t)) >= 2:
        return "medium"
    if has_action_intent(t):
        return "low"
    return "low"


def resolve_effective_level(
    enabled: bool,
    level: ReasoningLevel,
    text: str,
    channel: ReasoningChannel,
) -> EffectiveLevel:
    if not enabled or level == "off":
        return "off"
    if is_trivial_message(text):
        return "off"
    if level == "auto":
        return classify_auto(text, channel)
    if level in ("low", "medium", "high"):
        eff: EffectiveLevel = level
        if eff in ("medium", "high") and not has_action_intent(text) and len(text.split()) < 12:
            return "low"
        return eff
    return "off"


def _parse_plan_json(raw: str) -> PlanArtifact:
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
        raise ValueError("plan_not_object")
    steps = data.get("steps") or []
    tools = data.get("tools_needed") or []
    risks = data.get("risks") or []
    return PlanArtifact(
        intent=str(data.get("intent") or "").strip(),
        steps=[str(s).strip() for s in steps if str(s).strip()],
        tools_needed=[str(t).strip() for t in tools if str(t).strip()],
        success_criteria=str(data.get("success_criteria") or "").strip(),
        risks=[str(r).strip() for r in risks if str(r).strip()],
        user_visible_summary=str(data.get("user_visible_summary") or data.get("intent") or "").strip(),
    )


def run_planning_phase(
    level: EffectiveLevel,
    *,
    user_text: str,
    channel: ReasoningChannel,
    history: str = "",
    tools_available: list[str] | None = None,
) -> PlanArtifact | None:
    if level not in ("medium", "high"):
        return None
    if not has_action_intent(user_text) and len(user_text.split()) < 20:
        return None

    tools_line = ", ".join(tools_available or []) or "(agent runtime tools)"
    user_block = user_text.strip()
    if history.strip():
        user_block = f"{history.strip()}\n\nNuevo mensaje:\n{user_block}"

    prompt = (
        f"Canal: {channel}\n"
        f"Tools disponibles: {tools_line}\n\n"
        f"Petición del usuario:\n{user_block}"
    )

    model = MODEL_REASONER if level == "high" else MODEL_CHAT
    temperature = 0.2 if level == "high" else 0.3
    provider = AIProvider(
        AIConfig(
            api_key=settings.deepseek_api_key,
            model=model,
            temperature=temperature,
            timeout_seconds=90 if level == "high" else 45,
        )
    )
    try:
        response = provider.chat([{"role": "user", "content": prompt}], _PLAN_SYSTEM)
        plan = _parse_plan_json(response.content or "")
        plan.level = level
        plan.model = response.model or model
        plan.usage = response.usage
        return plan
    except Exception:
        log.warning("Planning phase failed level=%s channel=%s", level, channel, exc_info=True)
        return None


def inject_plan_into_system_prompt(base_prompt: str, plan: PlanArtifact) -> str:
    lines = [
        (base_prompt or "").rstrip(),
        "\n\n[PLAN DE EJECUCIÓN — generado por modo razonamiento]",
        f"Intención: {plan.intent}",
    ]
    if plan.steps:
        lines.append("Pasos:")
        lines.extend(f"  {i + 1}. {s}" for i, s in enumerate(plan.steps[:8]))
    if plan.tools_needed:
        lines.append(f"Tools sugeridas: {', '.join(plan.tools_needed[:8])}")
    if plan.success_criteria:
        lines.append(f"Criterio de éxito: {plan.success_criteria}")
    if plan.risks:
        lines.append(f"Riesgos: {'; '.join(plan.risks[:4])}")
    lines.append(
        "Ejecuta el plan usando tools reales. No afirmes éxito sin evidencia de tool OK. "
        "NO te detengas a mitad: completa TODOS los pasos y entrega en la respuesta "
        "final el resultado completo (informe, rutas, hallazgos), no un borrador corto."
    )
    return "\n".join(lines)


def apply_low_reasoning_suffix(base_system_prompt: str) -> str:
    return (base_system_prompt or "").rstrip() + LOW_REASONING_SUFFIX


def resolve_reasoning_for_request(
    *,
    uid: str,
    channel: ReasoningChannel,
    user_text: str,
    request_enabled: bool | None = None,
    request_level: str | None = None,
) -> tuple[bool, ReasoningLevel, EffectiveLevel]:
    enabled, pref_level = load_reasoning_prefs(
        uid,
        request_enabled=request_enabled,
        request_level=request_level,
    )
    effective = resolve_effective_level(enabled, pref_level, user_text, channel)
    return enabled, pref_level, effective


def apply_reasoning(
    *,
    uid: str,
    channel: ReasoningChannel,
    user_text: str,
    base_system_prompt: str,
    history: str = "",
    tools_available: list[str] | None = None,
    request_enabled: bool | None = None,
    request_level: str | None = None,
) -> ReasoningResult:
    enabled, pref_level = load_reasoning_prefs(
        uid,
        request_enabled=request_enabled,
        request_level=request_level,
    )
    effective = resolve_effective_level(enabled, pref_level, user_text, channel)
    events: list[dict[str, Any]] = []

    if effective == "off":
        return ReasoningResult(
            effective_level="off",
            system_prompt=base_system_prompt,
        )

    events.append({"type": "reasoning_progress", "phase": "analyzing", "level": effective})
    system = base_system_prompt

    if effective == "low":
        system = (base_system_prompt or "").rstrip() + _LOW_HINT
        return ReasoningResult(
            effective_level="low",
            system_prompt=system,
            sse_events=events,
        )

    events.append({"type": "reasoning_progress", "phase": "planning", "level": effective})
    plan = run_planning_phase(
        effective,
        user_text=user_text,
        channel=channel,
        history=history,
        tools_available=tools_available,
    )
    plan_for_execution: PlanArtifact | None = None
    if plan and len(plan.steps) >= 2:
        # FASE 2.2: plan listo para ejecución por planner.py
        from app.settings import settings as _dot_settings

        if _dot_settings.planner_enabled:
            plan_for_execution = plan
        system = inject_plan_into_system_prompt(base_system_prompt, plan)
        events.append(plan.to_sse_payload())
    elif plan:
        system = inject_plan_into_system_prompt(base_system_prompt, plan)
        events.append(plan.to_sse_payload())
    else:
        system = (base_system_prompt or "").rstrip() + _LOW_HINT

    events.append({"type": "reasoning_progress", "phase": "executing", "level": effective})

    return ReasoningResult(
        effective_level=effective,
        system_prompt=system,
        plan=plan,
        plan_for_execution=plan_for_execution,
        reasoning_usage=plan.usage if plan else None,
        reasoning_model=plan.model if plan else None,
        sse_events=events,
    )


def convert_plan_artifact_to_planner_plan(artifact: PlanArtifact) -> Any:
    """Convierte un PlanArtifact (reasoning) a Plan + list[PlanStep] (planner).

    Returns:
        Una tupla (goal_str, list_of_PlanStep) para inyectar en planner.run_planner().
        Retorna (artifact.intent, steps_vacíos) si no hay steps.
    """
    from app.application.agent.planner import PlanStep, StepStatus

    steps: list[Any] = []
    for i, step_desc in enumerate(artifact.steps[:8], start=1):
        step_id = str(i)
        # Si tools_needed tiene nombres de tools, asociarlos a los steps
        tool_name = None
        if artifact.tools_needed and i <= len(artifact.tools_needed):
            candidate = artifact.tools_needed[i - 1]
            if candidate and candidate.lower() not in ("null", "none", ""):
                tool_name = candidate
        steps.append(
            PlanStep(id=step_id, description=step_desc, tool_name=tool_name)
        )

    goal = artifact.intent or " ".join(artifact.steps)[:200] or "(plan sin intención)"
    return goal, steps


def record_reasoning_usage(
    db,
    *,
    cliente_id,
    plan: PlanArtifact | None,
) -> None:
    if not plan or not plan.usage:
        return
    from app.services.usage_service import (
        OPERATION_REASONING,
        calc_deepseek_reasoner_cost_usd,
        cost_from_deepseek_usage,
        record_usage,
    )

    prompt_t, completion_t, cached_t, cost_usd = cost_from_deepseek_usage(plan.usage)
    if cost_usd <= 0 and not (prompt_t or completion_t):
        return
    model = plan.model or MODEL_REASONER
    if model == MODEL_REASONER:
        cost = calc_deepseek_reasoner_cost_usd(prompt_t, completion_t, cached_t)
    else:
        cost = cost_usd
    record_usage(
        db,
        cliente_id=cliente_id,
        modelo=model,
        cost_usd=cost,
        operation=OPERATION_REASONING,
        tokens_prompt=prompt_t,
        tokens_completion=completion_t,
        tokens_cached=cached_t,
    )
