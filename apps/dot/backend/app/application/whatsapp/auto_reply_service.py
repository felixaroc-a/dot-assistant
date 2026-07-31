"""Auto-reply WhatsApp usando el mismo cerebro que el chat PC (B1/B2).

Flujo: inbound allow_auto_reply → DeepSeek (build_system_prompt) → bridge outbound.
Fail-closed en límite IA (D13) y si el bridge no está disponible.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from uuid import UUID

from app.application.whatsapp.inbound_service import WHATSAPP_STT_FAILURE_MESSAGE
from app.domain.whatsapp.message import InboundWhatsAppMessage, StoredWhatsAppMessage
from app.settings import settings

log = logging.getLogger("dot.whatsapp.auto_reply")

# Paridad con desktop (~100 en Electron); cap duro en runtime.WHATSAPP_HARD_MAX_STEPS (60).
WHATSAPP_AGENT_MAX_STEPS = 50

_replied_ids: set[str] = set()
_replied_lock = threading.Lock()
_MAX_REPLIED = 4000

_WA_SURFACE_HINT = (
    "\n\n[Estás respondiendo por WhatsApp] Responde en texto corto y claro para móvil "
    "(ideal ≤500 caracteres). Sin JSON, sin markdown de código, sin nombres de tools. "
    "Eres la misma DOT que en el PC: si completaste algo en el PC, confírmalo en una o dos frases. "
    "Si el usuario pregunta qué pidió en el PC, usa el bloque de continuidad del system prompt. "
    "Si pide guardar una foto/PDF recién recibida en el Escritorio, "
    "usa save_whatsapp_media_to_desktop (adjunto cacheado del último mensaje)."
)


def format_whatsapp_outbound(text: str, *, max_chars: int = 900) -> str:
    """Quita JSON residual y acorta para WhatsApp (FASE 4)."""
    import re

    cleaned = (text or "").strip()
    # Quitar bloques JSON residuales (tool_calls / local_tool / gmail)
    cleaned = re.sub(
        r"\{[\s\S]*?(?:\"tool_calls\"|\"action\"\s*:\s*\"(?:local_tool|gmail_send)\")[\s\S]*\}",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned).strip()
    if not cleaned:
        cleaned = "Listo. Ya lo procesé en tu PC."
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def resolve_reply_to(message: InboundWhatsAppMessage) -> str:
    """Destino outbound: JID de grupo si aplica; si no, teléfono del remitente."""
    chat_jid = (message.chat_jid or "").strip()
    if chat_jid and "@" in chat_jid:
        return chat_jid
    group = (message.group_name or message.group_subject or "").strip()
    # Baileys legacy: group_name a veces trae el remoteJid @g.us
    if message.is_group and "@g.us" in group:
        return group
    return (message.from_phone or "").strip()


def _mark_replied(message_id: str) -> bool:
    """True si es la primera vez (debe responder); False si ya se respondió."""
    mid = (message_id or "").strip()
    if not mid:
        return True
    with _replied_lock:
        if mid in _replied_ids:
            return False
        _replied_ids.add(mid)
        if len(_replied_ids) > _MAX_REPLIED:
            for _ in range(500):
                try:
                    _replied_ids.pop()
                except KeyError:
                    break
        return True


def clear_replied_ids_for_tests() -> None:
    with _replied_lock:
        _replied_ids.clear()


def _persist_assistant_to_chat_history(uid: str, text: str) -> None:
    try:
        from app.billing_db import get_session_factory
        from app.services.chat_persistence import append_whatsapp_chat_message

        factory = get_session_factory()
        session = factory()
        try:
            append_whatsapp_chat_message(session, uid, "assistant", text)
        finally:
            session.close()
    except Exception:
        log.warning(
            "No se pudo persistir reply WA en chat_history uid=%s",
            uid[:8] if uid else "?",
            exc_info=True,
        )


def _check_usage_or_block_message(uid: str) -> str | None:
    """None si OK; mensaje humano si bloqueado / fail-closed."""
    from fastapi import HTTPException

    from app.billing_db import get_session_factory
    from app.services.usage_service import (
        USAGE_LIMIT_EXCEEDED_CODE,
        USAGE_LIMIT_EXCEEDED_MESSAGE,
        assert_ai_usage_allowed,
    )

    try:
        cliente_id = UUID(uid)
    except ValueError:
        log.warning("Fail-closed auto-reply: uid no UUID uid=%s", uid[:16])
        return "No pude validar tu cuenta para responder por WhatsApp."

    try:
        factory = get_session_factory()
        db = factory()
        try:
            assert_ai_usage_allowed(db, cliente_id)
            return None
        finally:
            db.close()
    except HTTPException as e:
        detail = e.detail
        if isinstance(detail, dict) and detail.get("code") == USAGE_LIMIT_EXCEEDED_CODE:
            return USAGE_LIMIT_EXCEEDED_MESSAGE
        if e.status_code == 402:
            return USAGE_LIMIT_EXCEEDED_MESSAGE
        log.warning("Fail-closed auto-reply usage HTTP %s uid=%s", e.status_code, uid[:8])
        return (
            "No pude verificar tu límite de uso de IA ahora. "
            "Intenta de nuevo en unos minutos desde el chat de DOT."
        )
    except Exception as e:
        log.warning(
            "Fail-closed auto-reply: no se pudo validar uso IA uid=%s err=%s",
            uid[:8],
            e,
        )
        return (
            "No pude verificar tu límite de uso de IA ahora. "
            "Intenta de nuevo en unos minutos desde el chat de DOT."
        )


def _send_wa_sync(to: str, text: str) -> tuple[bool, str | None]:
    from app.services.whatsapp_client import send_whatsapp_message

    return asyncio.run(send_whatsapp_message(to, text))


def _record_chat_usage(uid: str, ai_result, enriched_text: str, respuesta: str) -> None:
    try:
        from app.billing_db import get_session_factory
        from app.services.usage_service import (
            OPERATION_CHAT,
            calc_deepseek_cost_usd,
            cost_from_deepseek_usage,
            estimate_chat_tokens_from_text,
            record_usage,
        )

        cliente_id = UUID(uid)
        factory = get_session_factory()
        db = factory()
        try:
            prompt_t, completion_t, cached_t, cost_usd = cost_from_deepseek_usage(
                ai_result.usage
            )
            if cost_usd <= 0 and (prompt_t or completion_t):
                cost_usd = calc_deepseek_cost_usd(prompt_t, completion_t, cached_t)
            elif cost_usd <= 0:
                est_p, est_c = estimate_chat_tokens_from_text(enriched_text, respuesta)
                prompt_t, completion_t = est_p, est_c
                cost_usd = calc_deepseek_cost_usd(prompt_t, completion_t)

            record_usage(
                db,
                cliente_id=cliente_id,
                modelo=ai_result.model or settings.default_chat_model,
                cost_usd=cost_usd,
                operation=OPERATION_CHAT,
                tokens_prompt=prompt_t,
                tokens_completion=completion_t,
                tokens_cached=cached_t,
            )
        finally:
            db.close()
    except Exception:
        log.warning("No se pudo registrar usage de auto-reply WA uid=%s", uid[:8], exc_info=True)


def _execute_local_tool_via_bridge(action: dict) -> dict:
    """Shim: delega al módulo canónico del Agent Runtime."""
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    return execute_local_tool_via_bridge(
        action["operation"],
        path=action.get("path") or "",
        content=action.get("content"),
    )


def run_whatsapp_stt_failure_reply(
    *,
    uid: str,
    message: InboundWhatsAppMessage,
    message_id: str,
) -> dict:
    """Responde con mensaje humano cuando STT de nota de voz falla."""
    if not uid:
        return {"ok": False, "error": "missing_uid"}

    if not _mark_replied(message_id):
        log.info("STT failure reply omitido (dedupe) message_id=%s", message_id)
        return {"ok": False, "error": "already_replied"}

    reply_to = resolve_reply_to(message)
    if not reply_to:
        return {"ok": False, "error": "no_reply_to"}

    ok, err = _send_wa_sync(reply_to, WHATSAPP_STT_FAILURE_MESSAGE)
    if ok:
        log.info("STT failure reply enviado uid=%s message_id=%s", uid[:8], message_id)
    return {"ok": ok, "error": None if ok else err}


def run_whatsapp_media_save_reply(
    *,
    uid: str,
    message: InboundWhatsAppMessage,
    message_id: str,
    reply_text: str,
) -> dict:
    """Confirma guardado de adjunto WA en Escritorio (sin pasar por el agente)."""
    if not uid:
        return {"ok": False, "error": "missing_uid"}

    text = format_whatsapp_outbound((reply_text or "").strip())
    if not text:
        return {"ok": False, "error": "empty_reply"}

    if not _mark_replied(message_id):
        log.info("Media save reply omitido (dedupe) message_id=%s", message_id)
        return {"ok": False, "error": "already_replied"}

    reply_to = resolve_reply_to(message)
    if not reply_to:
        return {"ok": False, "error": "no_reply_to"}

    ok, err = _send_wa_sync(reply_to, text)
    if ok:
        _persist_assistant_to_chat_history(uid, text)
        log.info("Media save reply enviado uid=%s message_id=%s", uid[:8], message_id)
    return {"ok": ok, "error": None if ok else err}


def run_whatsapp_auto_reply(
    *,
    uid: str,
    message: InboundWhatsAppMessage,
    message_id: str,
    user_text: str | None = None,
) -> dict:
    """Genera respuesta con el mismo pipeline de chat y la envía por bridge."""
    effective_user_text = (user_text if user_text is not None else message.text).strip()
    if not uid or not effective_user_text:
        return {"ok": False, "error": "missing_uid_or_text"}

    if not _mark_replied(message_id):
        log.info("Auto-reply omitido (dedupe) message_id=%s", message_id)
        return {"ok": False, "error": "already_replied"}

    reply_to = resolve_reply_to(message)
    if not reply_to:
        log.warning("Auto-reply sin destino uid=%s message_id=%s", uid[:8], message_id)
        return {"ok": False, "error": "no_reply_to"}

    blocked_msg = _check_usage_or_block_message(uid)
    if blocked_msg:
        ok, err = _send_wa_sync(reply_to, blocked_msg)
        return {"ok": ok, "blocked": True, "error": None if ok else err}

    try:
        from app.application.whatsapp.inbound_service import get_message_store
        from app.billing_db import get_session_factory
        from app.chat_models import ConversationORM
        from app.services.chat_context import build_conversation_history, build_system_prompt
        from app.services.provider_router import route_chat_detailed

        dynamic_system = ""
        history_block = ""
        try:
            factory = get_session_factory()
            db = factory()
            try:
                dynamic_system = (
                    build_system_prompt(uid, effective_user_text, surface="whatsapp", db=db)
                    + _WA_SURFACE_HINT
                )
                conv = (
                    db.query(ConversationORM)
                    .filter(
                        ConversationORM.cliente_id == UUID(uid),
                        ConversationORM.channel == "whatsapp",
                        ConversationORM.archived_at.is_(None),
                    )
                    .first()
                )
                if conv is not None:
                    history_block = build_conversation_history(db, uid, str(conv.id))
            finally:
                db.close()
        except Exception:
            log.debug("Sin historial WA para uid=%s", uid[:8], exc_info=True)
            if not dynamic_system:
                dynamic_system = (
                    build_system_prompt(uid, effective_user_text, surface="whatsapp")
                    + _WA_SURFACE_HINT
                )

        user_text = effective_user_text

        # FASE 2: mismo Agent Runtime + tools que chat PC (serializado por sesión WA)
        from app.application.agent import run_agent
        from app.application.agent.reasoning import apply_reasoning, record_reasoning_usage
        from app.application.agent.run_queue import enqueue_agent_run
        from app.application.agent.session_key import build_session_key
        from app.application.agent.tools import build_default_registry

        registry = build_default_registry(
            include_web_search=bool(settings.enable_web_search)
        )
        tools_available = [s.name for s in registry.list_specs()]
        reasoning = apply_reasoning(
            uid=uid,
            channel="whatsapp",
            user_text=user_text,
            base_system_prompt=dynamic_system,
            history=history_block or "",
            tools_available=tools_available,
        )
        agent_system = reasoning.system_prompt

        def _model_fn(user_text_in: str, system_prompt: str):
            return route_chat_detailed(
                user_text_in,
                "deepseek",
                system_prompt,
                include_document_action_prompt=False,
            )

        session_key = build_session_key(
            uid,
            "whatsapp",
            chat_jid=reply_to or message.chat_jid or "",
        )

        def _run_wa_agent(cancel_event=None):
            return run_agent(
                uid=uid,
                channel="whatsapp",
                text=user_text,
                system_prompt=agent_system,
                history=history_block or "",
                registry=registry,
                model_fn=_model_fn,
                max_steps=WHATSAPP_AGENT_MAX_STEPS,
                cancel_event=cancel_event,
                # FASE 2.2: pasar plan generado por reasoning para ejecución con planner
                prebuilt_plan=reasoning.plan_for_execution,
            )

        from app.application.agent.run_queue import AgentRunSuperseded

        try:
            agent_result = enqueue_agent_run(
                session_key, _run_wa_agent, mode="interrupt"
            )
        except AgentRunSuperseded:
            return {"ok": False, "error": "superseded_by_newer_message"}
        respuesta = (agent_result.final_text or "").strip()
        if not respuesta:
            return {"ok": False, "error": "empty_ai_response"}
        if respuesta.startswith("(Tarea cancelada") or respuesta.startswith("Detuve esa tarea"):
            return {"ok": False, "error": "cancelled_by_newer_message"}
        ai_result = type(
            "_AICompat",
            (),
            {
                "content": respuesta,
                "usage": agent_result.model_usage,
                "model": agent_result.model_name,
            },
        )()

        # Shim legacy: trailing JSON local_tool / gmail si el modelo no usó tool_calls
        from app.application.agent.legacy_shim import finalize_assistant_tools

        respuesta = finalize_assistant_tools(uid, respuesta)
        from app.application.agent.truth_check import truth_check_file_mission

        respuesta = truth_check_file_mission(
            user_text=user_text,
            final_text=respuesta,
            tool_trace=agent_result.tool_trace,
        )
        if agent_result.tool_trace:
            log.info(
                "agent_wa_trace uid=%s steps=%s tools=%s",
                uid[:8],
                agent_result.steps,
                [
                    {"tool": t.get("tool"), "ok": t.get("ok"), "ms": t.get("ms")}
                    for t in agent_result.tool_trace
                ],
            )
        respuesta = format_whatsapp_outbound(respuesta)

        ok, bridge_result = _send_wa_sync(reply_to, respuesta)
        if not ok:
            log.error(
                "Auto-reply outbound falló uid=%s to=%s err=%s message_id=%s",
                uid[:8],
                reply_to[:24],
                bridge_result,
                message_id,
            )
            return {"ok": False, "error": bridge_result or "bridge_send_failed"}

        out_id = bridge_result or f"wa_out_{message_id}"
        get_message_store().save(
            StoredWhatsAppMessage(
                id=out_id,
                uid=uid,
                from_phone=message.to_phone or "",
                to_phone=reply_to,
                text=respuesta,
                timestamp=datetime.now(timezone.utc).isoformat(),
                direction="outbound",
                status="sent",
            )
        )
        _persist_assistant_to_chat_history(uid, respuesta)
        _record_chat_usage(uid, ai_result, user_text, respuesta)
        if reasoning.plan:
            try:
                from app.billing_db import get_session_factory

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
                log.debug("Usage reasoning WA omitido uid=%s", uid[:8], exc_info=True)

        # Misma memoria que el chat PC (FREE-M07): extracción best-effort en background.
        try:
            from app.services.memory_service import schedule_memory_update

            schedule_memory_update(
                uid,
                user_text,
                respuesta,
                had_tool_use=bool(agent_result.tool_trace),
                force=True,
            )
        except Exception:
            log.debug("Memoria WA omitida uid=%s", uid[:8], exc_info=True)

        log.info(
            "Auto-reply WA ok uid=%s message_id=%s out_id=%s chars=%d",
            uid[:8],
            message_id,
            out_id,
            len(respuesta),
        )
        return {"ok": True, "message_id": out_id, "chars": len(respuesta)}
    except Exception as e:
        log.exception("Auto-reply WA error uid=%s message_id=%s", uid[:8], message_id)
        return {"ok": False, "error": str(e)}
