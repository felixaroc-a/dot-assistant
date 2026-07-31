from __future__ import annotations
import logging
import threading
from typing import Any

log = logging.getLogger("dot.whatsapp.mandates")


def _evaluate_mandates_sync(uid: str, message_text: str, from_phone: str) -> list[dict[str, Any]]:
    from app.services.proactive_triggers_service import user_wa_triggers_enabled

    if not user_wa_triggers_enabled(uid):
        log.debug("WA triggers desactivados para uid=%s — mandatos omitidos", uid[:8])
        return []

    try:
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            return []
        profile = doc.to_dict()
        automations = profile.get("saved_automations", [])
        if not automations:
            return []
        candidates = [a for a in automations if a.get("active") and a.get("schedule") == "manual"]
        if not candidates:
            return []
        log.info("Evaluating %d active manual mandates for uid=%s after WA inbound", len(candidates), uid[:8])
        from app.application.agent.runtime import run_agent
        from app.application.agent.tools import build_default_registry
        registry = build_default_registry(include_web_search=False)
        results: list[dict[str, Any]] = []
        for auto in candidates[:5]:
            auto_name = auto.get("name", "sin nombre")
            instruction = auto.get("instruction", "")
            prompt = (
                f"WA message from {from_phone}: {message_text}. "
                f"Active mandate: {instruction}. "
                f"Does this message trigger the mandate? If YES, execute tools NOW. If NO, say NO_MATCH."
            )
            result = run_agent(
                uid=uid, channel="automation_inbound", text=prompt,
                system_prompt="Evaluate if WA message triggers mandate. Execute tools if yes, say NO_MATCH if no.",
                registry=registry, max_steps=8,
            )
            final = result.final_text.strip()
            if final and "NO_MATCH" not in final:
                log.info("Mandate '%s' triggered by WA inbound uid=%s steps=%d", auto_name, uid[:8], result.steps)
                from worker.executor import AutomationExecutor
                auto_id = auto.get("id", "unknown")
                AutomationExecutor.mark_pending(uid, auto_id, auto_name, final)
                AutomationExecutor.save_result(uid, auto_id, final, auto.get("output_type", "notify"))
                results.append({"auto_id": auto_id, "auto_name": auto_name, "triggered": True, "result": final[:1000]})
            else:
                log.debug("Mandate '%s' NOT triggered by message", auto_name)
        return results
    except Exception as e:
        log.warning("Error evaluating mandates inbound uid=%s: %s", uid[:8], e, exc_info=True)
        return []


def evaluate_mandates_async(uid: str, message_text: str, from_phone: str) -> None:
    thread = threading.Thread(target=_evaluate_mandates_sync, args=(uid, message_text, from_phone), daemon=True)
    thread.start()
    log.debug("Mandate evaluator launched async uid=%s thread=%s", uid[:8], thread.name)
