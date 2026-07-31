"""Chat: enviar mensaje, streaming SSE, helpers de streaming.

FREE-T04b: Auditoría de threads completada (Jul 2026).
  - threading.Thread legacy: ELIMINADO (reemplazado por asyncio.to_thread).
  - asyncio.to_thread restantes JUSTIFICADOS:
    * Line ~477: run_planner() — sync LLM call (route_chat_detailed), no async SDK.
    * Line ~541: run_planning_phase() — sync LLM call (route_chat_detailed).
    * Line ~622: enqueue_agent_run() — run queue es sync por diseño (ver run_queue.py).
  - memory_service usa ThreadPoolExecutor propio (2 workers) — sin impacto en event loop.
  - /completion y /send/stream usan httpx.AsyncClient → sin bloquear event loop.

M2S4-A: Migración del agent loop a Electron.
  - Endpoints legacy (/send, /send/stream) soportan header X-Use-Local-Agent.
  - Nuevo endpoint /completion (proxy DeepSeek simple, sin agent loop).
  - Plan: deprecar chat.py completo cuando la migración a agent-loop.cjs esté completa.
"""
import asyncio
from datetime import datetime
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_deps import claims_cliente_id, claims_uid, check_usage_limit, require_product_jwt
from app.billing_db import get_billing_db
from app.dependencies.limiter import limiter
from app.deps.ai_provider import get_ai_provider
from app.settings import settings
from app.services.ai_provider import AIProvider
from app.services.chat_context import (
    BASE_SYSTEM_PROMPT as SYSTEM_PROMPT,
    build_system_prompt,
    build_conversation_history,
    prepare_user_text,
)
from app.services.chat_persistence import save_exchange as persist_chat_exchange
from app.services.usage_service import (
    OPERATION_CHAT,
    BillingPeriod,
    cost_from_deepseek_usage,
    estimate_chat_tokens_from_text,
    calc_deepseek_cost_usd,
    record_usage,
)
from app.routers.chat_utils import (
    SendMessageRequest,
    SendMessageResponse,
    ChatMessageResponse,
)
from app.application.agent.run_queue import AgentRunSuperseded, enqueue_agent_run
from app.application.agent.session_key import build_session_key
from app.application.agent.runtime import run_agent
from app.application.agent.tools import build_default_registry
from app.application.agent.reasoning import apply_reasoning
from app.services.provider_router import route_chat_detailed
from app.services.usage_service import build_usage_summary

log = logging.getLogger("dot.chat")

router = APIRouter(prefix="/v1/chat", tags=["chat"])

_STREAM_SENTINEL = object()


# ── B2: Endpoint de consumo IA ────────────────────────────────────

@router.get("/usage/summary")
def usage_summary(
    request: Request,
    claims: dict = Depends(require_product_jwt),
    db: Session = Depends(get_billing_db),
):
    """Devuelve el consumo IA del mes actual con porcentaje y estado."""
    uid = claims_uid(claims)
    cliente_id = claims_cliente_id(claims)
    summary = build_usage_summary(db, uuid.UUID(cliente_id))
    return {
        "limit_usd": float(summary.limit_usd),
        "consumed_usd": float(summary.consumed_usd),
        "remaining_usd": float(summary.remaining_usd),
        "percent": summary.consumed_percent,
        "blocked": summary.blocked,
        "warning": summary.consumed_percent >= 80,
        "limit_enabled": summary.limit_enabled,
        "breakdown": {
            "chat": float(summary.breakdown.chat_usd) if summary.breakdown else 0,
            "vision": float(summary.breakdown.vision_usd) if summary.breakdown else 0,
            "image_gen": float(summary.breakdown.image_gen_usd) if summary.breakdown else 0,
        },
        "provider_breakdown": summary.breakdown.provider_breakdown if summary.breakdown else None,
    }


# ── M2S4-A: Modelos para /v1/chat/completion (proxy DeepSeek) ─────────────


class CompletionMessage(BaseModel):
    """Mensaje individual en el array de messages (formato OpenAI-compatible)."""
    role: str
    content: str


class CompletionRequest(BaseModel):
    """Request para el endpoint proxy DeepSeek simple.

    Lo usa agent-loop.cjs en Electron para comunicarse con DeepSeek
    sin pasar por el agent loop del backend.
    """
    model: str = "deepseek-chat"
    preferred_model: str | None = None  # Override del modelo preferido
    messages: list[CompletionMessage]
    stream: bool = False
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)


# ---------------------------------------------------------------------------
# Helpers de streaming
# ---------------------------------------------------------------------------


async def _stream_provider_events(
    user_text: str,
    provider_id: str,
    system_prompt: str | None = None,
    ai_provider: AIProvider | None = None,
):
    """Streaming async nativo — no bloquea el event loop.
    Usa httpx.AsyncClient internamente en vez de asyncio.to_thread.
    """
    from app.services.provider_router import async_stream_deepseek

    async for token_text, finish_reason in async_stream_deepseek(
        user_text,
        system_prompt or SYSTEM_PROMPT,
        ai_provider=ai_provider,
    ):
        if token_text:
            yield {"token": token_text}
        if finish_reason:
            yield {"done": True}
            return
    yield {"done": True}


def _extract_memory_background(
    uid: str,
    user_msg: str,
    assistant_resp: str,
    had_tool_use: bool = False,
    conversation_id: str | None = None,
    db_factory=None,
) -> None:
    """Programa extracción de memoria sin bloquear la respuesta (delega a memory_service).

    FREE-T04b: llamar directamente desde sync y async chat; no usar run_in_executor/to_thread
    encima — schedule_memory_update ya despacha a _memory_executor.

    El snapshot markdown se guarda al finalizar update_memory (evita carrera con extracción).
    """
    from app.services.memory_service import schedule_memory_update

    schedule_memory_update(
        uid,
        user_msg,
        assistant_resp,
        had_tool_use=had_tool_use,
        conversation_id=conversation_id,
        db_factory=db_factory,
    )


# ---------------------------------------------------------------------------
# Endpoint sin streaming (legacy)
# ---------------------------------------------------------------------------
# M2S4-A: Si el header X-Use-Local-Agent está presente, el backend delega
# al agent loop local de Electron y responde 202 Accepted.


@router.post("/send", response_model=SendMessageResponse)
@limiter.limit("30/minute")
def chat_send(
    request: Request,
    body: SendMessageRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio.")

    conversation_id = body.conversation_id or str(uuid.uuid4())

    # M2S4-A: Si el cliente Electron envía X-Use-Local-Agent, delegar al agent loop local
    if request.headers.get("X-Use-Local-Agent", "").lower() == "true":
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": (
                    "Este mensaje debe procesarse con el agent loop local de Electron. "
                    "El backend ahora es solo proxy de DeepSeek + auth + billing."
                ),
                "conversation_id": conversation_id,
            },
        )

    # v1: solo DeepSeek — se ignora body.provider si el cliente lo envía
    provider_id = "deepseek"
    uid = claims_uid(claims)

    dynamic_system = build_system_prompt(uid, body.text, surface="pc", db=db)
    from app.services.memory_service import build_memory_recall_hint

    memory_recall = build_memory_recall_hint(uid, body.text)
    history_block = build_conversation_history(db, uid, conversation_id)
    enriched_text = prepare_user_text(body)
    if history_block:
        enriched_text = (
            f"{history_block}\n\nNuevo mensaje del usuario:\n{enriched_text}"
        )

    try:
        from app.application.agent import run_agent
        from app.application.agent.reasoning import apply_reasoning, record_reasoning_usage
        from app.application.agent.tools import build_default_registry
        from app.services.provider_router import ProviderNotAvailableError, route_chat_detailed

        registry = build_default_registry(
            include_web_search=bool(settings.enable_web_search)
        )

        # FREE-PL01: planner skeleton (PLANNER_ENABLED + prefix plan:)
        if settings.planner_enabled:
            from app.application.agent.planner import (
                extract_planner_goal,
                is_planner_message,
                run_planner,
            )

            if is_planner_message(body.text):
                goal = extract_planner_goal(body.text)
                _, respuesta = run_planner(uid, goal, registry)

                # Registrar uso de IA del planner (estimado basado en texto de entrada/salida)
                est_prompt, est_completion = estimate_chat_tokens_from_text(
                    goal, respuesta
                )
                cost_usd = calc_deepseek_cost_usd(est_prompt, est_completion)
                record_usage(
                    db,
                    cliente_id=claims_cliente_id(claims),
                    modelo=settings.default_chat_model,
                    cost_usd=cost_usd,
                    operation=OPERATION_CHAT,
                    tokens_prompt=est_prompt,
                    tokens_completion=est_completion,
                )

                history_saved = persist_chat_exchange(
                    db,
                    uid,
                    conversation_id,
                    body.text,
                    respuesta,
                    provider_id,
                )
                return SendMessageResponse(
                    message=ChatMessageResponse(
                        id=str(uuid.uuid4()),
                        role="assistant",
                        text=respuesta,
                        createdAt=datetime.utcnow().isoformat() + "Z",
                    ),
                    conversation_id=conversation_id,
                    history_saved=history_saved,
                    artifacts=[],
                )

        # GOAL 5: Sub-agent delegation — detectar mensajes de delegación
        if _is_delegation_message(body.text):
            agent_id, respuesta = _handle_delegation(
                uid, body.text, registry, conversation_id
            )
            if agent_id:
                est_prompt, est_completion = estimate_chat_tokens_from_text(
                    body.text, respuesta
                )
                cost_usd = calc_deepseek_cost_usd(est_prompt, est_completion)
                record_usage(
                    db,
                    cliente_id=claims_cliente_id(claims),
                    modelo=settings.default_chat_model,
                    cost_usd=cost_usd,
                    operation=OPERATION_CHAT,
                    tokens_prompt=est_prompt,
                    tokens_completion=est_completion,
                )
                history_saved = persist_chat_exchange(
                    db, uid, conversation_id, body.text, respuesta, provider_id,
                )
                return SendMessageResponse(
                    message=ChatMessageResponse(
                        id=str(uuid.uuid4()),
                        role="assistant",
                        text=respuesta,
                        createdAt=datetime.utcnow().isoformat() + "Z",
                    ),
                    conversation_id=conversation_id,
                    history_saved=history_saved,
                    artifacts=[],
                )

        tools_available = [s.name for s in registry.list_specs()]
        reasoning = apply_reasoning(
            uid=uid,
            channel="pc",
            user_text=body.text,
            base_system_prompt=dynamic_system,
            history=history_block or "",
            tools_available=tools_available,
            request_enabled=body.reasoning_enabled,
            request_level=body.reasoning_level,
        )
        agent_system = reasoning.system_prompt

        # FASE 2: runtime con tools (gmail, files, web). Path canónico backend.
        def _model_fn(user_text: str, system_prompt: str):
            return route_chat_detailed(
                user_text,
                provider_id,
                system_prompt,
                include_document_action_prompt=False,
                ai_provider=ai_provider,
            )

        session_key = build_session_key(uid, "pc", conversation_id=conversation_id)

        def _run_pc_agent(cancel_event=None):
            return run_agent(
                uid=uid,
                channel="pc",
                text=prepare_user_text(body),
                system_prompt=agent_system,
                history=history_block or "",
                registry=registry,
                model_fn=_model_fn,
                max_steps=20,
                local_tools=False,
                cancel_event=cancel_event,
                # FASE 2.2: pasar plan generado por reasoning para ejecución con planner
                prebuilt_plan=reasoning.plan_for_execution,
            )

        try:
            agent_result = enqueue_agent_run(
                session_key, _run_pc_agent, mode="interrupt"
            )
        except AgentRunSuperseded:
            raise HTTPException(
                status_code=409,
                detail="Mensaje reemplazado por uno más reciente en esta conversación.",
            )
        respuesta = agent_result.final_text
        ai_result = type(
            "_AICompat",
            (),
            {
                "content": respuesta,
                "usage": agent_result.model_usage,
                "model": agent_result.model_name,
            },
        )()

        # Shim legacy (stream usa esto; sync también vía finalize)
        from app.application.agent.legacy_shim import finalize_assistant_tools

        respuesta = finalize_assistant_tools(uid, respuesta)
        from app.application.agent.truth_check import truth_check_file_mission

        respuesta = truth_check_file_mission(
            user_text=body.text,
            final_text=respuesta,
            tool_trace=agent_result.tool_trace,
        )

        history_saved = persist_chat_exchange(
            db,
            uid,
            conversation_id,
            body.text,
            respuesta,
            provider_id,
        )

        # Extracción de memoria en background (FREE-T04b: schedule_memory_update ya usa executor propio).
        _extract_memory_background(
            uid,
            body.text,
            respuesta,
            bool(agent_result.tool_trace),
            conversation_id,
            lambda: next(get_billing_db()),
        )

        prompt_t, completion_t, cached_t, cost_usd = cost_from_deepseek_usage(ai_result.usage)
        if cost_usd <= 0 and (prompt_t or completion_t):
            cost_usd = calc_deepseek_cost_usd(prompt_t, completion_t, cached_t)
        elif cost_usd <= 0:
            est_prompt, est_completion = estimate_chat_tokens_from_text(enriched_text, respuesta)
            prompt_t, completion_t = est_prompt, est_completion
            cost_usd = calc_deepseek_cost_usd(prompt_t, completion_t)

        record_usage(
            db,
            cliente_id=claims_cliente_id(claims),
            modelo=ai_result.model or settings.default_chat_model,
            cost_usd=cost_usd,
            operation=OPERATION_CHAT,
            tokens_prompt=prompt_t,
            tokens_completion=completion_t,
            tokens_cached=cached_t,
        )
        record_reasoning_usage(
            db,
            cliente_id=claims_cliente_id(claims),
            plan=reasoning.plan,
        )

        return SendMessageResponse(
            message=ChatMessageResponse(
                id=str(uuid.uuid4()),
                role="assistant",
                text=respuesta,
                createdAt=datetime.utcnow().isoformat() + "Z",
            ),
            conversation_id=conversation_id,
            history_saved=history_saved,
            artifacts=agent_result.artifacts,
            memory_recall=memory_recall,
        )
    except ProviderNotAvailableError as e:
        log.warning("Provider not available: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        log.warning("AI provider error: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        log.exception("Error inesperado en chat")
        raise HTTPException(status_code=500, detail="Error al procesar el mensaje.")


# ---------------------------------------------------------------------------
# Endpoint con streaming SSE
# ---------------------------------------------------------------------------
# M2S4-A: Si el header X-Use-Local-Agent está presente, el backend delega
# al agent loop local de Electron y responde 202 Accepted.


@router.post("/send/stream")
@limiter.limit("10/minute")
async def chat_send_stream(
    request: Request,
    body: SendMessageRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    """Responde al chat con streaming SSE."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio.")

    conversation_id = body.conversation_id or str(uuid.uuid4())

    # M2S4-A: Si el cliente Electron envía X-Use-Local-Agent, delegar al agent loop local
    if request.headers.get("X-Use-Local-Agent", "").lower() == "true":
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "message": (
                    "Este mensaje debe procesarse con el agent loop local de Electron. "
                    "El backend ahora es solo proxy de DeepSeek + auth + billing."
                ),
                "conversation_id": conversation_id,
            },
        )

    # v1: solo DeepSeek — se ignora body.provider si el cliente lo envía
    provider_id = "deepseek"
    uid = claims_uid(claims)

    dynamic_system = build_system_prompt(uid, body.text, surface="pc", db=db)
    from app.services.memory_service import build_memory_recall_hint

    memory_recall = build_memory_recall_hint(uid, body.text)
    history_block = build_conversation_history(db, uid, conversation_id)
    enriched_text = prepare_user_text(body)
    if history_block:
        enriched_text = (
            f"{history_block}\n\nNuevo mensaje del usuario:\n{enriched_text}"
        )

    async def event_stream():
        full_response = ""
        total_tokens = 0
        done_emitted = False
        agent_artifacts: list[dict] = []

        def _sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n: flush\n\n"

        try:
            if memory_recall:
                yield _sse({"type": "memory_recall", "text": memory_recall})

            # FASE 3: stream usa el mismo Agent Runtime (loop multi-tool), no un solo turno.
            from app.application.agent import run_agent
            from app.application.agent.legacy_shim import finalize_assistant_tools
            from app.application.agent.reasoning import (
                apply_low_reasoning_suffix,
                inject_plan_into_system_prompt,
                load_reasoning_prefs,
                record_reasoning_usage,
                resolve_effective_level,
                run_planning_phase,
            )
            from app.application.agent.tools import build_default_registry
            from app.services.provider_router import ProviderNotAvailableError, route_chat_detailed

            registry = build_default_registry(
                include_web_search=bool(settings.enable_web_search)
            )

            # FREE-PL01: planner skeleton (PLANNER_ENABLED + prefix plan:)
            if settings.planner_enabled:
                from app.application.agent.planner import (
                    extract_planner_goal,
                    is_planner_message,
                    run_planner,
                )

                if is_planner_message(body.text):
                    goal = extract_planner_goal(body.text)
                    # FREE-T04b: to_thread justificado — run_planner llama a route_chat_detailed()
                    # que es sync (httpx sync client). Migrar a async requeriría refactor completo
                    # de provider_router + ai_provider. Bajo impacto: solo en path planner (raro).
                    _, full_response = await asyncio.to_thread(
                        run_planner, uid, goal, registry
                    )

                    # Registrar uso de IA del planner (estimado basado en texto de entrada/salida)
                    est_prompt, est_completion = estimate_chat_tokens_from_text(
                        goal, full_response
                    )
                    cost_usd = calc_deepseek_cost_usd(est_prompt, est_completion)
                    record_usage(
                        db,
                        cliente_id=claims_cliente_id(claims),
                        modelo=settings.default_chat_model,
                        cost_usd=cost_usd,
                        operation=OPERATION_CHAT,
                        tokens_prompt=est_prompt,
                        tokens_completion=est_completion,
                    )

                    for i in range(0, len(full_response), 64):
                        piece = full_response[i : i + 64]
                        total_tokens += 1
                        yield _sse({"token": piece, "conversation_id": conversation_id})
                    if not done_emitted:
                        done_emitted = True
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "done": True,
                                    "conversation_id": conversation_id,
                                    "final_text": full_response,
                                }
                            )
                            + "\n\n"
                        )
                    history_saved = persist_chat_exchange(
                        db,
                        uid,
                        conversation_id,
                        body.text,
                        full_response,
                        provider_id,
                        total_tokens,
                    )
                    if not history_saved:
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "warning": "No se pudo guardar el historial del chat.",
                                    "history_saved": False,
                                }
                            )
                            + "\n\n"
                        )
                    return

            # GOAL 5: Sub-agent delegation en streaming
            if _is_delegation_message(body.text):
                agent_id, respuesta = _handle_delegation(
                    uid, body.text, registry, conversation_id
                )
                if agent_id:
                    for i in range(0, len(respuesta), 64):
                        piece = respuesta[i : i + 64]
                        total_tokens += 1
                        yield _sse({"token": piece, "conversation_id": conversation_id})
                    if not done_emitted:
                        done_emitted = True
                        yield (
                            "data: "
                            + json.dumps({
                                "done": True,
                                "conversation_id": conversation_id,
                                "final_text": respuesta,
                                "sub_agent_id": agent_id,
                            })
                            + "\n\n"
                        )
                    est_prompt, est_completion = estimate_chat_tokens_from_text(
                        body.text, respuesta
                    )
                    cost_usd = calc_deepseek_cost_usd(est_prompt, est_completion)
                    record_usage(
                        db,
                        cliente_id=claims_cliente_id(claims),
                        modelo=settings.default_chat_model,
                        cost_usd=cost_usd,
                        operation=OPERATION_CHAT,
                        tokens_prompt=est_prompt,
                        tokens_completion=est_completion,
                    )
                    history_saved = persist_chat_exchange(
                        db, uid, conversation_id, body.text, respuesta, provider_id, total_tokens,
                    )
                    if not history_saved:
                        yield (
                            "data: "
                            + json.dumps({"warning": "No se pudo guardar el historial del chat.", "history_saved": False})
                            + "\n\n"
                        )
                    return

            tools_available = [s.name for s in registry.list_specs()]

            enabled, pref_level = load_reasoning_prefs(
                uid,
                request_enabled=body.reasoning_enabled,
                request_level=body.reasoning_level,
            )
            effective = resolve_effective_level(enabled, pref_level, body.text, "pc")
            agent_system = dynamic_system
            reasoning_plan = None

            if effective != "off":
                yield _sse({"type": "reasoning_progress", "phase": "analyzing", "level": effective})
                await asyncio.sleep(0.35)

                if effective == "low":
                    agent_system = apply_low_reasoning_suffix(dynamic_system)
                    yield _sse({"type": "reasoning_progress", "phase": "executing", "level": effective})
                    await asyncio.sleep(0.25)
                else:
                    yield _sse({"type": "reasoning_progress", "phase": "planning", "level": effective})
                    await asyncio.sleep(0.35)
                    # FREE-T04b: to_thread justificado — run_planning_phase() usa sync LLM
                    # (provider_router) para generar plan. Migrar a async SDK no es viable
                    # sin reescribir todo el pipeline de AIProvider.
                    reasoning_plan = await asyncio.to_thread(
                        run_planning_phase,
                        effective,
                        user_text=body.text,
                        channel="pc",
                        history=history_block or "",
                        tools_available=tools_available,
                    )
                    if reasoning_plan:
                        yield _sse(reasoning_plan.to_sse_payload())
                        await asyncio.sleep(0.2)
                        agent_system = inject_plan_into_system_prompt(dynamic_system, reasoning_plan)
                    else:
                        agent_system = apply_low_reasoning_suffix(dynamic_system)

                    yield _sse({"type": "reasoning_progress", "phase": "executing", "level": effective})
                    await asyncio.sleep(0.25)
            elif enabled:
                # Razonamiento pedido pero guardrail lo omitió (mensaje trivial)
                yield _sse({"type": "reasoning_progress", "phase": "analyzing", "level": pref_level})
                await asyncio.sleep(0.3)
                yield _sse({"type": "reasoning_progress", "phase": "executing", "level": pref_level})
                await asyncio.sleep(0.2)

            def _model_fn(user_text: str, system_prompt: str):
                return route_chat_detailed(
                    user_text,
                    provider_id,
                    system_prompt,
                    include_document_action_prompt=False,
                    ai_provider=ai_provider,
                )

            # Cola thread-safe para eventos de progreso desde el agent runtime
            progress_queue: asyncio.Queue[dict] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _on_step(step: int, tool_name: str, preview: str, ok: bool) -> None:
                try:
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        {"type": "tool_progress", "step": step, "tool": tool_name, "preview": preview, "ok": ok},
                    )
                except Exception:
                    # best-effort: no bloquear el agent runtime por error en cola de progreso
                    log.debug("Error encolando tool_progress en SSE", exc_info=True)

            def _on_complete(final_text: str, artifacts: list[dict]) -> None:
                nonlocal agent_artifacts
                agent_artifacts = list(artifacts) if artifacts else []
                try:
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        {"type": "agent_complete", "artifacts": agent_artifacts},
                    )
                except Exception:
                    # best-effort: no bloquear el agent runtime por error en cola de progreso
                    log.debug("Error encolando agent_complete en SSE", exc_info=True)

            def _run(cancel_event=None) -> Any:
                return run_agent(
                    uid=uid,
                    channel="pc",
                    text=prepare_user_text(body),
                    system_prompt=agent_system,
                    history=history_block or "",
                    registry=registry,
                    model_fn=_model_fn,
                    max_steps=20,
                    local_tools=False,
                    on_step_complete=_on_step,
                    on_complete=_on_complete,
                    cancel_event=cancel_event,
                    # FASE 2.2: pasar plan generado por reasoning_plan para ejecución con planner
                    prebuilt_plan=reasoning_plan,
                )

            session_key = build_session_key(uid, "pc", conversation_id=conversation_id)

            def _queued_run() -> Any:
                return enqueue_agent_run(session_key, _run, mode="interrupt")

            # FREE-T04b: to_thread justificado. AgentRunQueue (run_queue.py) es sync
            # por diseño — usa locks/queues thread-safe. Migrar a asyncio requeriría
            # reescribir runtime + cancel cooperativo. Documentado en run_queue.py §FREE-T04b.
            agent_task = asyncio.create_task(asyncio.to_thread(_queued_run))

            # Emitir eventos de progreso mientras el agente trabaja
            heartbeat_ticks = 0
            while not agent_task.done():
                try:
                    progress_event = await asyncio.wait_for(progress_queue.get(), timeout=0.4)
                    yield _sse(progress_event)
                except asyncio.TimeoutError:
                    # Keep-alive SIEMPRE (no solo con reasoning): evita timeout idle del cliente
                    # en misiones largas (análisis de carpetas, informes profundos).
                    heartbeat_ticks += 1
                    if heartbeat_ticks % 3 == 0:
                        if effective != "off" or enabled:
                            yield _sse({
                                "type": "reasoning_progress",
                                "phase": "executing",
                                "level": effective if effective != "off" else pref_level,
                            })
                        else:
                            yield _sse({"type": "heartbeat", "t": heartbeat_ticks})

            # Recoger resultado final
            try:
                agent_result = await agent_task
            except AgentRunSuperseded:
                yield _sse({
                    "type": "superseded",
                    "error": "Mensaje reemplazado por uno más reciente.",
                })
                return
            except ProviderNotAvailableError as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return
            except RuntimeError as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

            # Drenar eventos pendientes del progress_queue
            while not progress_queue.empty():
                try:
                    progress_event = progress_queue.get_nowait()
                    yield _sse(progress_event)
                except Exception:
                    # best-effort: drenar cola de progreso pendiente
                    log.debug("Error drenando progress_queue en SSE", exc_info=True)
                    break

            raw_final = (agent_result.final_text or "").strip()
            full_response = finalize_assistant_tools(uid, raw_final)
            from app.application.agent.truth_check import truth_check_file_mission

            full_response = truth_check_file_mission(
                user_text=body.text,
                final_text=full_response,
                tool_trace=agent_result.tool_trace,
            )
            if agent_result.tool_trace:
                log.info(
                    "agent_stream_trace uid=%s steps=%s tools=%s",
                    uid[:8],
                    agent_result.steps,
                    [
                        {"tool": t.get("tool"), "ok": t.get("ok"), "ms": t.get("ms")}
                        for t in agent_result.tool_trace
                    ],
                )

            # Emitir marcadores local_tool para que Electron los ejecute via bridge
            local_tool_markers = [
                a for a in agent_result.artifacts
                if isinstance(a, dict) and a.get("action") == "local_tool"
            ]
            for marker in local_tool_markers:
                yield _sse({"type": "local_tool", "tool": marker["tool"], "params": marker["params"]})

            # Emitir artifacts del agente si hay
            if agent_result.artifacts:
                yield f"data: {json.dumps({'type': 'artifacts', 'items': agent_result.artifacts})}\n\n"

            # Emitir el texto final en trozos (rápido: no quemar el idle/timeout del cliente)
            chunk_size = 64 if len(full_response) > 2000 else 16
            for i in range(0, len(full_response), chunk_size):
                piece = full_response[i : i + chunk_size]
                total_tokens += 1
                yield _sse({"token": piece, "conversation_id": conversation_id})
                if chunk_size <= 16:
                    await asyncio.sleep(0.012)
                elif i % (chunk_size * 8) == 0:
                    await asyncio.sleep(0)

            if not done_emitted:
                done_emitted = True
                done_payload: dict[str, Any] = {
                    "done": True,
                    "conversation_id": conversation_id,
                    "final_text": full_response,
                }
                if memory_recall:
                    done_payload["memory_recall"] = memory_recall
                yield (
                    "data: "
                    + json.dumps(done_payload)
                    + "\n\n"
                )

            history_saved = persist_chat_exchange(
                db,
                uid,
                conversation_id,
                body.text,
                full_response,
                provider_id,
                total_tokens,
            )
            usage = agent_result.model_usage
            prompt_t, completion_t, cached_t, cost_usd = cost_from_deepseek_usage(usage)
            if cost_usd <= 0:
                est_prompt, est_completion = estimate_chat_tokens_from_text(
                    enriched_text, full_response
                )
                prompt_t, completion_t = est_prompt, est_completion
                cost_usd = calc_deepseek_cost_usd(prompt_t, completion_t)
            record_usage(
                db,
                cliente_id=claims_cliente_id(claims),
                modelo=agent_result.model_name or settings.default_chat_model,
                cost_usd=cost_usd,
                operation=OPERATION_CHAT,
                tokens_prompt=prompt_t,
                tokens_completion=completion_t,
                tokens_cached=cached_t,
            )
            record_reasoning_usage(
                db,
                cliente_id=claims_cliente_id(claims),
                plan=reasoning_plan,
            )
            if not history_saved:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "warning": "No se pudo guardar el historial del chat.",
                            "history_saved": False,
                        }
                    )
                    + "\n\n"
                )

            # FREE-T04b: no envolver en to_thread — schedule_memory_update ya corre en background.
            _extract_memory_background(
                uid,
                body.text,
                full_response,
                bool(agent_result.tool_trace),
                conversation_id,
                lambda: next(get_billing_db()),
            )
        except Exception as e:
            log.exception("Error en streaming SSE")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# M2S4-A — NUEVO ENDPOINT: Proxy DeepSeek simple (sin agent loop)
# ═══════════════════════════════════════════════════════════════════════════
# Este endpoint reemplaza al agent loop del backend.
# Lo usa agent-loop.cjs en Electron para obtener respuestas de DeepSeek
# y ejecutar tools localmente en el cliente.
#
# Plan: cuando la migración esté completa, los endpoints legacy
# (/send, /send/stream) se eliminarán y solo quedará /completion.


@router.post("/completion")
@limiter.limit("30/minute")
async def chat_completion(
    request: Request,
    body: CompletionRequest,
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
    ai_provider: AIProvider = Depends(get_ai_provider),
):
    """Proxy DeepSeek simple — sin agent loop, sin tool calling.

    Recibe un array de messages (formato OpenAI-compatible) y reenvía
    a DeepSeek. Soporta streaming SSE (stream=True) y no-streaming.

    Este es el endpoint canónico para clientes Electron con agent loop local.
    """
    if not body.messages:
        raise HTTPException(status_code=400, detail="El array de messages no puede estar vacío.")

    uid = claims_uid(claims)

    # Extraer system prompt y user text de los messages
    system_prompt = ""
    user_texts: list[str] = []
    for msg in body.messages:
        if msg.role == "system":
            system_prompt = msg.content or ""
        elif msg.role in ("user", "assistant"):
            user_texts.append(f"[{msg.role}]: {msg.content or ''}")

    if not user_texts:
        raise HTTPException(status_code=400, detail="No se encontraron mensajes de usuario/asistente.")

    combined_user_text = "\n\n".join(user_texts)

    if not body.stream:
        # ── Modo no-streaming ──────────────────────────────────────
        try:
            from app.services.model_router import route_chat_completion, AllProvidersExhaustedError

            messages_for_llm = [
                {"role": msg.role, "content": msg.content}
                for msg in body.messages
            ]

            result = route_chat_completion(
                messages_for_llm,
                system_prompt=system_prompt or (
                    "Eres DOT, un asistente IA de escritorio para Windows. "
                    "Responde siempre en español claro y útil."
                ),
                preferred_model=body.preferred_model or body.model,
            )

            content = result.text
            usage = result.usage or {}
            model = result.model
            provider = result.provider

            prompt_t = int(usage.get("prompt_tokens", 0) or result.tokens_in or 0)
            completion_t = int(usage.get("completion_tokens", 0) or result.tokens_out or 0)
            cost_usd = result.usage.get("cost_usd")

            if not cost_usd:
                from app.services.cost_calculator import calculate_cost
                cost_usd = calculate_cost(provider, model, prompt_t, completion_t)

            record_usage(
                db,
                cliente_id=claims_cliente_id(claims),
                modelo=model or body.model,
                cost_usd=cost_usd,
                operation=OPERATION_CHAT,
                tokens_prompt=prompt_t,
                tokens_completion=completion_t,
                provider=provider,
            )

            return {
                "id": str(uuid.uuid4()),
                "object": "chat.completion",
                "created": int(datetime.utcnow().timestamp()),
                "model": model or body.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage or {},
            }

        except AllProvidersExhaustedError as e:
            log.warning("All providers exhausted: %s", e)
            raise HTTPException(status_code=503, detail=str(e))
        except RuntimeError as e:
            log.warning("AI provider error: %s", e)
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:
            log.exception("Error inesperado en chat/completion")
            raise HTTPException(status_code=500, detail="Error al procesar el mensaje.")

    else:
        # ── Modo streaming SSE (OpenAI-compatible) ─────────────────
        async def _completion_stream():
            full_content = ""
            done_emitted = False

            def _sse(payload: dict) -> str:
                return f"data: {json.dumps(payload)}\n\n"

            try:
                from app.services.model_router import route_chat_stream

                messages_for_llm = [
                    {"role": msg.role, "content": msg.content}
                    for msg in body.messages
                ]

                async for token_text, finish_reason in route_chat_stream(
                    messages_for_llm,
                    system_prompt=system_prompt or (
                        "Eres DOT, un asistente IA de escritorio para Windows. "
                        "Responde siempre en español claro y útil."
                    ),
                    preferred_model=body.preferred_model or body.model,
                    temperature=body.temperature,
                    max_tokens=body.max_tokens,
                ):
                    if token_text:
                        full_content += token_text
                        chunk = {
                            "id": str(uuid.uuid4()),
                            "object": "chat.completion.chunk",
                            "created": int(datetime.utcnow().timestamp()),
                            "model": body.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": token_text},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield _sse(chunk)

                    if finish_reason and not done_emitted:
                        final_chunk = {
                            "id": str(uuid.uuid4()),
                            "object": "chat.completion.chunk",
                            "created": int(datetime.utcnow().timestamp()),
                            "model": body.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": finish_reason,
                                }
                            ],
                        }
                        yield _sse(final_chunk)
                        yield "data: [DONE]\n\n"
                        done_emitted = True

                if not done_emitted:
                    yield "data: [DONE]\n\n"

                # Registrar uso de IA (estimado porque streaming no devuelve usage exacto)
                prompt_t, completion_t = estimate_chat_tokens_from_text(
                    combined_user_text, full_content
                )
                from app.services.cost_calculator import calculate_cost
                cost_usd = calculate_cost(
                    "deepseek", body.preferred_model or body.model,
                    prompt_t, completion_t
                )
                record_usage(
                    db,
                    cliente_id=claims_cliente_id(claims),
                    modelo=body.preferred_model or body.model,
                    cost_usd=cost_usd,
                    operation=OPERATION_CHAT,
                    tokens_prompt=prompt_t,
                    tokens_completion=completion_t,
                    provider="deepseek",
                )

            except Exception as e:
                log.exception("Error en streaming de /completion")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _completion_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",
            },
        )


# ═══════════════════════════════════════════════════════════════════════════
# Multi-model: endpoint de modelos disponibles
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/models")
def list_models(request: Request):
    """Devuelve los modelos IA disponibles según las API keys configuradas.

    Respuesta formato OpenAI-compatible (/v1/models).
    """
    from app.services.model_registry import get_available_models, get_default_model

    available = get_available_models()
    default = get_default_model()

    return {
        "object": "list",
        "data": [
            {
                "id": m.model_id,
                "object": "model",
                "created": 0,
                "owned_by": m.provider,
                "display_name": m.display_name,
                "context_window": m.context_window,
                "capabilities": m.capabilities,
                "tier": m.tier,
                "is_default": m.model_id == (default.model_id if default else ""),
                "cost": {
                    "input_1m": m.cost_input_1m,
                    "output_1m": m.cost_output_1m,
                },
            }
            for m in available
        ],
    }


# ═══════════════════════════════════════════════════════════
# GOAL 5: Delegación de sub-agentes desde el chat
# ═══════════════════════════════════════════════════════════

DELEGATION_KEYWORDS = [
    "delegate to",
    "delega a",
    "create agent",
    "crear agente",
    "crea un agente",
    "create sub-agent",
    "crear sub-agente",
    "delegar a",
    "encarga a",
    "asigna a",
    "assign to",
]


def _is_delegation_message(text: str) -> bool:
    """Detecta si el mensaje del usuario es una solicitud de delegación."""
    text_lower = text.strip().lower()
    return any(kw in text_lower for kw in DELEGATION_KEYWORDS)


def _extract_delegation_goal(text: str) -> tuple[str, str]:
    """Extrae el nombre y goal de un mensaje de delegación.

    Returns:
        (agent_name, goal) — tupla con nombre del agente y objetivo.
    """
    text_lower = text.lower()

    # Intentar extraer después de keywords conocidos
    for kw in DELEGATION_KEYWORDS:
        idx = text_lower.find(kw)
        if idx >= 0:
            remaining = text[idx + len(kw):].strip().lstrip(":").strip()
            if remaining:
                # Primeras 80 chars como goal, nombre derivado
                goal = remaining[:200]
                name = f"Agent-{remaining[:30].strip()}"
                return name, goal

    # Fallback: usar el texto completo
    name = f"Agent-{text[:30].strip()}"
    return name, text.strip()


def _handle_delegation(
    uid: str,
    text: str,
    registry: Any,
    conversation_id: str,
) -> tuple[str | None, str]:
    """Maneja una solicitud de delegación creando un sub-agente.

    Returns:
        (agent_id, response_text) — agent_id es None si falló.
    """
    try:
        from app.services.sub_agent_service import get_sub_agent_manager

        agent_name, goal = _extract_delegation_goal(text)
        manager = get_sub_agent_manager()

        agent_id = manager.spawn_sub_agent(
            uid=uid,
            name=agent_name,
            goal=goal,
            allowed_tools=[],
            context={"source": "chat", "conversation_id": conversation_id},
            parent_conversation_id=conversation_id,
            registry=registry,
        )

        response = (
            f"He creado un sub-agente **'{agent_name}'** para encargarse de tu tarea.\n\n"
            f"**Objetivo:** {goal}\n"
            f"**ID:** `{agent_id[:8]}`\n\n"
            f"El agente está trabajando en background. Puedes consultar su progreso "
            f"con `/v1/agents/{agent_id}/status` o preguntarme '¿cómo va {agent_name}?'.\n\n"
            f"Te avisaré cuando termine."
        )

        log.info(
            "Delegación desde chat: uid=%s agent=%s goal=%s",
            uid[:8], agent_name, goal[:80],
        )
        return agent_id, response

    except RuntimeError as e:
        log.warning("Delegación falló: %s", e)
        return None, f"No pude crear el sub-agente: {e}"
    except Exception:
        log.exception("Error inesperado en delegación")
        return None, "Ocurrió un error al crear el sub-agente. Intenta de nuevo."
