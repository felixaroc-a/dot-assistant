"""Composite automation orchestrator skeleton (FREE-AU01 + FREE-AU02).

Feature-flagged via AUTOMATIONS_COMPOSITE_ENABLED. Chains up to five registered
tools sequentially via ToolRegistry. Halts on first tool error. Off by default.

AU03 — Calendar event triggers with time windows: ejecuta automations cuando un
       evento de calendario matchea una consulta o está a X minutos de empezar.
       Gate: AUTOMATIONS_CALENDAR_TRIGGERS.

AU04 — WhatsApp keyword + regex triggers: ejecuta automations cuando un mensaje
       entrante contiene palabras clave o matchea un patrón regex con toggle
       case-sensitive. Gate: AUTOMATIONS_WA_TRIGGERS.

AU05 — Enhanced execution history: registro in-memory + Firestore con estadísticas
       agregadas (success rate, top errors, trigger distribution), exportación
       JSON y TTL de 90 días para entradas viejas.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.application.agent.registry import ToolRegistry
from app.settings import settings

log = logging.getLogger("dot.automations.composite")

MAX_COMPOSITE_STEPS = 5
MAX_HISTORY_PER_UID = 100


# ═══════════════════════════════════════════════════════════════════
# AU01–AU02 — Composite automation core
# ═══════════════════════════════════════════════════════════════════


@dataclass
class AutomationStep:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationSpec:
    name: str
    steps: list[AutomationStep] = field(default_factory=list)


@dataclass
class AutomationRunResult:
    name: str
    ok: bool
    step_outputs: list[str] = field(default_factory=list)
    error: str | None = None


def composite_automation_enabled(uid: str | None = None) -> bool:
    if uid:
        from app.services.proactive_triggers_service import user_composite_enabled

        return user_composite_enabled(uid)
    return bool(settings.automations_composite_enabled)


# ═══════════════════════════════════════════════════════════════════
# Gate helpers for AU03 / AU04
# ═══════════════════════════════════════════════════════════════════


def calendar_triggers_enabled(uid: str | None = None) -> bool:
    if uid:
        from app.services.proactive_triggers_service import user_calendar_triggers_enabled

        if user_calendar_triggers_enabled(uid):
            return True
    if uid and composite_automation_enabled(uid):
        return bool(settings.automations_calendar_triggers)
    return composite_automation_enabled() and bool(settings.automations_calendar_triggers)


def wa_triggers_enabled(uid: str | None = None) -> bool:
    if uid:
        from app.services.proactive_triggers_service import user_wa_triggers_enabled

        if user_wa_triggers_enabled(uid):
            return True
    if uid and composite_automation_enabled(uid):
        return bool(settings.automations_wa_triggers)
    return composite_automation_enabled() and bool(settings.automations_wa_triggers)


# ═══════════════════════════════════════════════════════════════════
# AU03 — Calendar event triggers (with time windows)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class CalendarTrigger:
    """Dispara una automation cuando un evento de calendario matchea una consulta.

    Attributes:
        calendar_query: substring o palabra clave a buscar en el título (summary) del evento.
        automation_name: nombre de la automation a ejecutar.
    """
    calendar_query: str
    automation_name: str


@dataclass
class CalendarTriggerWindow:
    """Dispara una automation X minutos antes de un evento de calendario.

    A diferencia de CalendarTrigger (que matchea por summary), este trigger
    evalúa la hora de inicio del evento y dispara la automation cuando el
    tiempo restante hasta el evento es <= minutes_before.

    Attributes:
        minutes_before: minutos antes del evento para disparar (ej. 15).
        calendar_query: query opcional para filtrar eventos específicos.
            Si es "*" o vacío, aplica a cualquier evento.
        automation_name: nombre de la automation a ejecutar.
    """
    minutes_before: int
    calendar_query: str  # "*" para cualquier evento, o substring para filtrar
    automation_name: str


def _event_matches_query(event: dict[str, Any], query: str) -> bool:
    """Verifica si un evento de calendario matchea un query (case-insensitive)."""
    if not query or query == "*":
        return True
    summary = str(event.get("summary") or "").strip().lower()
    return query.strip().lower() in summary


def _minutes_until_event(event: dict[str, Any]) -> int | None:
    """Calcula cuántos minutos faltan para que empiece un evento.

    Retorna None si el evento no tiene hora de inicio o ya pasó.
    """
    start_raw = event.get("start", {})
    start_str = ""
    if isinstance(start_raw, dict):
        start_str = start_raw.get("dateTime") or start_raw.get("date") or ""
    elif isinstance(start_raw, str):
        start_str = start_raw

    if not start_str:
        return None

    try:
        # Intentar parsear ISO 8601
        from datetime import datetime as dt
        start_dt = dt.fromisoformat(start_str.replace("Z", "+00:00"))
        now = dt.now(timezone.utc)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        delta = start_dt - now
        return int(delta.total_seconds() / 60)
    except (ValueError, TypeError):
        return None


def match_and_run_calendar_triggers(
    uid: str,
    events_list: list[dict[str, Any]],
    triggers: list[CalendarTrigger],
    automations_by_name: dict[str, AutomationSpec],
    registry: ToolRegistry,
    *,
    window_triggers: list[CalendarTriggerWindow] | None = None,
) -> list[AutomationRunResult]:
    """Evalúa eventos de calendario contra triggers y ejecuta automations matching.

    Soporta dos tipos de triggers:
    1. CalendarTrigger: dispara cuando el summary contiene calendar_query (substring).
    2. CalendarTriggerWindow (AU03): dispara X minutos antes del evento si
       el query matchea (o "*" para cualquier evento).

    Args:
        uid: ID del usuario dueño de los eventos.
        events_list: lista de eventos de calendario con al menos {"summary": str}.
        triggers: lista de CalendarTrigger configurados (query-based).
        automations_by_name: diccionario name -> AutomationSpec para ejecutar.
        registry: ToolRegistry para ejecutar los pasos.
        window_triggers: lista de CalendarTriggerWindow (time-window-based).

    Returns:
        Lista de AutomationRunResult (uno por cada trigger disparado + ejecutado).
        Retorna lista vacía si la feature está deshabilitada.
    """
    if not calendar_triggers_enabled(uid):
        return []

    if not events_list or (not triggers and not window_triggers) or not automations_by_name:
        return []

    results: list[AutomationRunResult] = []
    fired: set[str] = set()  # (automation_name, event_summary) para evitar duplicados

    for event in events_list:
        summary = str(event.get("summary") or "").strip().lower()
        if not summary:
            continue

        # ─── CalendarTrigger (query-based, original) ───
        for trigger in triggers:
            query = (trigger.calendar_query or "").strip().lower()
            if not query:
                continue
            if query not in summary:
                continue

            dedup_key = f"{trigger.automation_name}|{summary}"
            if dedup_key in fired:
                continue

            spec = automations_by_name.get(trigger.automation_name)
            if spec is None:
                log.warning(
                    "Calendar trigger '%s' apunta a automation '%s' no encontrada para uid=%s",
                    query,
                    trigger.automation_name,
                    uid[:8],
                )
                continue

            log.info(
                "Calendar trigger disparado: evento='%s' query='%s' automation='%s' uid=%s",
                event.get("summary", "?")[:60],
                query,
                trigger.automation_name,
                uid[:8],
            )
            fired.add(dedup_key)
            result = run_composite_automation(uid, spec, registry, trigger_source="calendar")
            results.append(result)

        # ─── AU03: CalendarTriggerWindow (time-window-based) ───
        if window_triggers:
            minutes_left = _minutes_until_event(event)
            if minutes_left is None or minutes_left < 0:
                continue  # evento ya pasó o no tiene hora

            for wtrigger in window_triggers:
                if not _event_matches_query(event, wtrigger.calendar_query):
                    continue

                # Disparar si estamos dentro de la ventana de minutos
                if minutes_left > wtrigger.minutes_before:
                    continue

                dedup_key = f"{wtrigger.automation_name}|{summary}|window"
                if dedup_key in fired:
                    continue

                spec = automations_by_name.get(wtrigger.automation_name)
                if spec is None:
                    log.warning(
                        "Calendar window trigger '%s' (antes=%dmin) automation '%s' no encontrada uid=%s",
                        wtrigger.calendar_query,
                        wtrigger.minutes_before,
                        wtrigger.automation_name,
                        uid[:8],
                    )
                    continue

                log.info(
                    "Calendar window trigger: evento='%s' faltan=%dmin ventana=%dmin automation='%s' uid=%s",
                    event.get("summary", "?")[:60],
                    minutes_left,
                    wtrigger.minutes_before,
                    wtrigger.automation_name,
                    uid[:8],
                )
                fired.add(dedup_key)
                result = run_composite_automation(uid, spec, registry, trigger_source="calendar_window")
                results.append(result)

    return results


# ═══════════════════════════════════════════════════════════════════
# AU04 — WhatsApp keyword + regex triggers
# ═══════════════════════════════════════════════════════════════════


@dataclass
class KeywordTrigger:
    """Dispara una automation cuando un mensaje de WhatsApp contiene keywords.

    Attributes:
        keywords: lista de palabras clave a buscar (match case-insensitive).
        automation_name: nombre de la automation a ejecutar.
    """
    keywords: list[str]
    automation_name: str


@dataclass
class RegexTrigger:
    """Dispara una automation cuando un mensaje de WhatsApp coincide con un patrón regex.

    Attributes:
        pattern: patrón regex (compatible con re.search).
        automation_name: nombre de la automation a ejecutar.
        case_sensitive: si es False (default), se aplica re.IGNORECASE.
        description: descripción opcional para logging/debug.
    """
    pattern: str
    automation_name: str
    case_sensitive: bool = False  # False = case-insensitive por defecto
    description: str = ""


def _trigger_matches_keyword(keywords: list[str], normalized_text: str) -> bool:
    """Verifica si alguna keyword aparece en el texto normalizado."""
    for kw in keywords:
        needle = (kw or "").strip().lower()
        if needle and needle in normalized_text:
            return True
    return False


def _trigger_matches_regex(pattern: str, text: str, case_sensitive: bool) -> bool:
    """Verifica si un patrón regex matchea el texto."""
    import re
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.search(pattern, text, flags))
    except re.error as e:
        log.warning("Regex inválido '%s': %s", pattern[:80], e)
        return False


def match_and_run_wa_triggers(
    uid: str,
    msg_text: str,
    from_number: str,
    triggers: list[KeywordTrigger],
    automations_by_name: dict[str, AutomationSpec],
    registry: ToolRegistry,
    *,
    regex_triggers: list[RegexTrigger] | None = None,
) -> list[AutomationRunResult]:
    """Evalúa texto de mensaje WhatsApp entrante contra triggers de keywords y regex.

    Soporta dos tipos de triggers:
    1. KeywordTrigger: match case-insensitive por substring.
    2. RegexTrigger (AU04): match por patrón regex, con toggle case-sensitive.

    Un mensaje puede disparar múltiples automations.

    Args:
        uid: ID del usuario dueño del número vinculado.
        msg_text: texto del mensaje WhatsApp entrante.
        from_number: número de teléfono del remitente (para logging).
        triggers: lista de KeywordTrigger configurados.
        automations_by_name: diccionario name -> AutomationSpec para ejecutar.
        registry: ToolRegistry para ejecutar los pasos.
        regex_triggers: lista de RegexTrigger configurados (AU04).

    Returns:
        Lista de AutomationRunResult (uno por cada trigger disparado + ejecutado).
        Retorna lista vacía si la feature está deshabilitada.
    """
    if not wa_triggers_enabled(uid):
        return []

    normalized = (msg_text or "").strip().lower()
    raw_text = (msg_text or "").strip()
    if not normalized or (not triggers and not regex_triggers) or not automations_by_name:
        return []

    results: list[AutomationRunResult] = []
    fired: set[str] = set()  # automation_name → evita duplicados

    # ─── KeywordTrigger (original) ───
    for trigger in triggers:
        if not trigger.keywords:
            continue

        if not _trigger_matches_keyword(trigger.keywords, normalized):
            continue

        if trigger.automation_name in fired:
            continue

        spec = automations_by_name.get(trigger.automation_name)
        if spec is None:
            log.warning(
                "WA trigger '%s' apunta a automation '%s' no encontrada para uid=%s",
                trigger.keywords,
                trigger.automation_name,
                uid[:8],
            )
            continue

        log.info(
            "WA keyword trigger: keywords=%s automation='%s' from=%s uid=%s",
            trigger.keywords,
            trigger.automation_name,
            from_number,
            uid[:8],
        )
        fired.add(trigger.automation_name)
        result = run_composite_automation(uid, spec, registry, trigger_source="whatsapp")
        if result.step_outputs:
            result.step_outputs[0] = f"[WA de {from_number}]: {result.step_outputs[0]}"
        results.append(result)

    # ─── AU04: RegexTrigger ───
    if regex_triggers:
        for rt in regex_triggers:
            if not rt.pattern:
                continue
            if rt.automation_name in fired:
                continue

            # Usar raw_text o normalized según case_sensitivity
            target_text = raw_text if rt.case_sensitive else normalized
            if not _trigger_matches_regex(rt.pattern, target_text, rt.case_sensitive):
                continue

            spec = automations_by_name.get(rt.automation_name)
            if spec is None:
                log.warning(
                    "WA regex trigger pattern='%s' automation '%s' no encontrada uid=%s",
                    rt.pattern[:60],
                    rt.automation_name,
                    uid[:8],
                )
                continue

            log.info(
                "WA regex trigger: pattern='%s' automation='%s' from=%s uid=%s case_sensitive=%s",
                rt.pattern[:60],
                rt.automation_name,
                from_number,
                uid[:8],
                rt.case_sensitive,
            )
            fired.add(rt.automation_name)
            result = run_composite_automation(uid, spec, registry, trigger_source="whatsapp_regex")
            if result.step_outputs:
                result.step_outputs[0] = f"[WA de {from_number} regex:{rt.description or rt.pattern[:30]}]: {result.step_outputs[0]}"
            results.append(result)

    return results


# ═══════════════════════════════════════════════════════════════════
# AU05 — Enhanced execution history
# ═══════════════════════════════════════════════════════════════════

_history_lock = threading.Lock()
_automation_history: dict[str, list[dict[str, Any]]] = {}

# TTL para entradas viejas del historial en Firestore (90 días)
_HISTORY_TTL_DAYS = 90
# Máximo de entradas por usuario en memoria
MAX_HISTORY_PER_UID = 100


def _entry_age_days(entry: dict[str, Any]) -> float | None:
    """Calcula la antigüedad en días de una entrada del historial."""
    ts = entry.get("timestamp", "")
    if not ts:
        return None
    try:
        from datetime import datetime as dt
        entry_dt = dt.fromisoformat(ts)
        now = dt.now(timezone.utc)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        return (now - entry_dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def _trim_expired_entries(uid: str) -> int:
    """Elimina entradas del historial in-memory que excedan el TTL."""
    with _history_lock:
        hist = _automation_history.get(uid)
        if not hist:
            return 0
        before = len(hist)
        hist[:] = [
            entry for entry in hist
            if (_entry_age_days(entry) or 0) <= _HISTORY_TTL_DAYS
        ]
        trimmed = before - len(hist)
        if not hist:
            del _automation_history[uid]
        return trimmed


def _trim_expired_firestore_history(uid: str) -> int:
    """Elimina entradas del historial en Firestore con más de 90 días.

    Corre cada vez que se invocan stats o export, como mantenimiento pasivo.
    """
    from datetime import timedelta
    try:
        from app.firebase_db import get_db as get_firestore_client
        db = get_firestore_client()
        cutoff = datetime.now(timezone.utc) - timedelta(days=_HISTORY_TTL_DAYS)
        cutoff_str = cutoff.isoformat()

        docs = (
            db.collection("users")
            .document(uid)
            .collection("automation_executions")
            .where("executed_at", "<", cutoff_str)
            .limit(200)
            .stream()
        )
        deleted = 0
        batch = db.batch()
        batch_count = 0
        for doc in docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted += 1
            if batch_count >= 100:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        if batch_count > 0:
            batch.commit()

        if deleted:
            log.info("Firestore TTL: %d entradas expiradas para uid=%s", deleted, uid[:8])
        return deleted
    except Exception:
        log.debug("Error trimming Firestore history for uid=%s", uid[:8], exc_info=True)
        return 0


def _record_execution(
    uid: str,
    result: AutomationRunResult,
    trigger_source: str = "manual",
) -> None:
    """Registra una ejecución en el historial in-memory + Firestore opcional."""
    now = datetime.now(timezone.utc)
    entry = {
        "timestamp": now.isoformat(),
        "automation_name": result.name,
        "ok": result.ok,
        "steps_count": len(result.step_outputs),
        "step_outputs": result.step_outputs[:3],
        "error": result.error,
        "trigger_source": trigger_source,
    }

    with _history_lock:
        hist = _automation_history.get(uid)
        if hist is None:
            hist = []
            _automation_history[uid] = hist
        hist.insert(0, entry)
        if len(hist) > MAX_HISTORY_PER_UID:
            _automation_history[uid] = hist[:MAX_HISTORY_PER_UID]

    # Firestore: guardar últimas ejecuciones en perfil
    try:
        from app.firebase_db import FIRESTORE_AVAILABLE, merge_user_profile
        if FIRESTORE_AVAILABLE:
            recent = _automation_history.get(uid, [])[:20]
            merge_user_profile(uid, {
                "automation_composite_history": recent,
                "automation_composite_history_updated_at": now.isoformat(),
            })
    except Exception:
        log.debug("No se pudo persistir historial composite en Firestore uid=%s", uid[:8], exc_info=True)


def get_automation_history(
    uid: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Devuelve las últimas ejecuciones de automations compuestas para un uid.

    Args:
        uid: ID del usuario.
        limit: máximo de entradas a devolver (default 20, máximo 100).

    Returns:
        Lista de dicts con {timestamp, automation_name, ok, steps_count,
        step_outputs, error, trigger_source}, ordenadas de más reciente a más antigua.
    """
    clamped = max(1, min(limit, MAX_HISTORY_PER_UID))
    # Trim pasivo: limpia entradas expiradas antes de devolver
    _trim_expired_entries(uid)
    with _history_lock:
        hist = _automation_history.get(uid) or []
        return list(hist[:clamped])


# ─── AU05: Estadísticas agregadas ───


def get_automation_stats(uid: str) -> dict[str, Any]:
    """Devuelve estadísticas agregadas del historial de automatizaciones.

    Calcula: total runs, success rate, avg duration, most common errors, last run time.
    También ejecuta trim pasivo de entradas expiradas en Firestore.

    Args:
        uid: ID del usuario.

    Returns:
        Dict con:
        - total_runs: número total de ejecuciones registradas
        - success_count: ejecuciones exitosas
        - failure_count: ejecuciones fallidas
        - success_rate: porcentaje de éxito (0.0–100.0)
        - last_run_time: ISO timestamp de la última ejecución (o None)
        - top_errors: lista de los 5 errores más comunes [{error, count}]
        - trigger_sources: distribución por fuente de trigger {source: count}
        - history_size: número total de entradas en memoria
    """
    _trim_expired_entries(uid)

    with _history_lock:
        hist = list(_automation_history.get(uid) or [])

    if not hist:
        # Intentar cargar desde Firestore si no hay datos en memoria
        try:
            from app.firebase_db import get_user_profile
            profile = get_user_profile(uid) or {}
            firestore_hist = profile.get("automation_composite_history", [])
            if isinstance(firestore_hist, list) and firestore_hist:
                hist = firestore_hist
        except Exception:
            pass

    if not hist:
        return {
            "total_runs": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "last_run_time": None,
            "top_errors": [],
            "trigger_sources": {},
            "history_size": 0,
        }

    total = len(hist)
    success_count = sum(1 for e in hist if e.get("ok"))
    failure_count = total - success_count
    success_rate = round((success_count / total) * 100.0, 1) if total > 0 else 0.0

    # Última ejecución
    last_run_time = hist[0].get("timestamp") if hist else None

    # Errores más comunes
    error_counts: dict[str, int] = {}
    for e in hist:
        err = e.get("error")
        if err:
            err_key = str(err)[:200]
            error_counts[err_key] = error_counts.get(err_key, 0) + 1
    top_errors = sorted(
        [{"error": k, "count": v} for k, v in error_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:5]

    # Distribución por trigger source
    trigger_sources: dict[str, int] = {}
    for e in hist:
        src = e.get("trigger_source", "unknown")
        trigger_sources[src] = trigger_sources.get(src, 0) + 1

    # Limpieza pasiva Firestore TTL
    try:
        _trim_expired_firestore_history(uid)
    except Exception:
        pass

    return {
        "total_runs": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": success_rate,
        "last_run_time": last_run_time,
        "top_errors": top_errors,
        "trigger_sources": trigger_sources,
        "history_size": total,
    }


def export_automation_history(uid: str) -> dict[str, Any]:
    """Exporta el historial completo de automatizaciones en formato JSON-serializable.

    Ideal para dashboards y exportación de datos del usuario.

    Args:
        uid: ID del usuario.

    Returns:
        Dict con:
        - uid: ID del usuario
        - exported_at: ISO timestamp del momento de exportación
        - stats: estadísticas agregadas (mismo formato que get_automation_stats)
        - history: lista completa de entradas [{timestamp, automation_name, ok, ...}]
        - ttl_days: días de retención configurados
    """
    _trim_expired_entries(uid)

    stats = get_automation_stats(uid)

    with _history_lock:
        hist = list(_automation_history.get(uid) or [])

    # Serializar entradas asegurando que todo sea JSON-safe
    safe_history: list[dict[str, Any]] = []
    for entry in hist:
        safe_entry: dict[str, Any] = {}
        for k, v in entry.items():
            if isinstance(v, (str, int, float, bool, type(None))):
                safe_entry[k] = v
            elif isinstance(v, (list, dict)):
                safe_entry[k] = v
            else:
                safe_entry[k] = str(v)
        safe_history.append(safe_entry)

    return {
        "uid": uid,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "history": safe_history,
        "ttl_days": _HISTORY_TTL_DAYS,
    }


# ═══════════════════════════════════════════════════════════════════
# Core execution (AU01–02, updated with AU05 history recording)
# ═══════════════════════════════════════════════════════════════════


def run_composite_automation(
    uid: str,
    spec: AutomationSpec,
    registry: ToolRegistry,
    *,
    trigger_source: str = "manual",
) -> AutomationRunResult:
    """Execute tool steps in order; each step may use prior step output."""
    name = (spec.name or "").strip() or "(sin nombre)"
    if not spec.steps:
        result = AutomationRunResult(name=name, ok=False, error="La automatización no tiene pasos.")
        _record_execution(uid, result, trigger_source)
        return result

    if len(spec.steps) > MAX_COMPOSITE_STEPS:
        result = AutomationRunResult(
            name=name,
            ok=False,
            error=f"Máximo {MAX_COMPOSITE_STEPS} pasos en automatización compuesta.",
        )
        _record_execution(uid, result, trigger_source)
        return result

    outputs: list[str] = []
    prior_output = ""

    for index, step in enumerate(spec.steps, start=1):
        tool_name = (step.tool_name or "").strip()
        if not tool_name:
            result = AutomationRunResult(
                name=name,
                ok=False,
                step_outputs=outputs,
                error=f"Paso {index}: tool_name vacío.",
            )
            _record_execution(uid, result, trigger_source)
            return result
        if not registry.has(tool_name):
            result = AutomationRunResult(
                name=name,
                ok=False,
                step_outputs=outputs,
                error=f"Paso {index}: herramienta no disponible: {tool_name}",
            )
            _record_execution(uid, result, trigger_source)
            return result

        args = dict(step.arguments)
        if prior_output and "input" not in args:
            args["input"] = prior_output
        if "confirm" not in args:
            args["confirm"] = True  # mandato explícito al crear la automatización

        tool_result = registry.execute(uid, tool_name, args)
        if not tool_result.ok:
            result = AutomationRunResult(
                name=name,
                ok=False,
                step_outputs=outputs,
                error=tool_result.error or f"Paso {index} ({tool_name}) falló.",
            )
            _record_execution(uid, result, trigger_source)
            return result

        chunk = (tool_result.output or "").strip()
        outputs.append(chunk)
        prior_output = chunk

    result = AutomationRunResult(name=name, ok=True, step_outputs=outputs)
    _record_execution(uid, result, trigger_source)
    return result


def execute_composite_if_enabled(
    uid: str,
    spec: AutomationSpec,
    registry: ToolRegistry,
    *,
    trigger_source: str = "manual",
) -> AutomationRunResult | None:
    """Optional hook: returns None when the feature flag is off."""
    if not composite_automation_enabled(uid):
        return None
    return run_composite_automation(uid, spec, registry, trigger_source=trigger_source)
