"""Retención D01/D02/D05 — purge de datos de producto tras 3 meses sin pago o sin uso.

MASTER-EXECUTION-PLAN:
  D01 — purga por inactividad 3 meses (notificaciones 7d, 3d, 1d antes).
  D02 — purga por no pago 3 meses.
  D05 — 1 día de gracia post-vencimiento.

Fuente de verdad: docs/BIBLIA.md §11.
No borra clientes_suscripcion ni subscription_reminder_outbox.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from firebase_admin import firestore
from sqlalchemy.orm import Session

from app.chat_models import ConversationORM
from app.firebase_db import (
    delete_user_google_tokens,
    get_db as get_firestore_client,
    get_user_profile,
    merge_user_profile,
)
from app.services.activity_service import parse_last_active_at
from app.services.subscription_service import is_subscription_expired
from app.settings import settings

log = logging.getLogger("dot.data_retention")

# ── Constantes de notificaciones de retención ────────────────────────────
_RETENTION_WARNING_DAYS = [7, 3, 1]  # Días antes del purge para enviar aviso


@dataclass(frozen=True)
class RetentionDecision:
    should_purge: bool
    unpaid: bool
    inactive: bool
    reason: str

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        if self.unpaid:
            out.append("unpaid_3m")
        if self.inactive:
            out.append("inactive_3m")
        return out


def retention_days() -> int:
    return max(1, int(settings.retention_days))


def unpaid_beyond_retention(
    fecha_vencimiento: date,
    *,
    today: date | None = None,
    days: int | None = None,
) -> bool:
    """True si la suscripción venció hace al menos `days` días calendario."""
    today = today or datetime.now(timezone.utc).date()
    days = retention_days() if days is None else max(1, days)
    if not is_subscription_expired(fecha_vencimiento, today=today):
        return False
    return today > fecha_vencimiento + timedelta(days=days)


def inactive_beyond_retention(
    last_active_at: datetime | None,
    *,
    now: datetime | None = None,
    days: int | None = None,
) -> bool:
    """True si hay last_active_at y es más viejo que la ventana de retención.

    Sin last_active_at no se purgea por inactividad (evita borrar usuarios
    históricos antes de que el heartbeat esté desplegado).
    """
    if last_active_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    days = retention_days() if days is None else max(1, days)
    if last_active_at.tzinfo is None:
        last_active_at = last_active_at.replace(tzinfo=timezone.utc)
    return now >= last_active_at + timedelta(days=days)


def decide_retention(
    *,
    fecha_vencimiento: date | None,
    last_active_at: datetime | None,
    today: date | None = None,
    now: datetime | None = None,
    days: int | None = None,
    already_purged: bool = False,
) -> RetentionDecision:
    """Decide si el usuario debe perder datos de producto (D5)."""
    today = today or datetime.now(timezone.utc).date()
    now = now or datetime.now(timezone.utc)
    days = retention_days() if days is None else max(1, days)

    unpaid = (
        unpaid_beyond_retention(fecha_vencimiento, today=today, days=days)
        if fecha_vencimiento is not None
        else False
    )
    inactive = inactive_beyond_retention(last_active_at, now=now, days=days)

    if already_purged and (unpaid or inactive):
        return RetentionDecision(
            should_purge=False,
            unpaid=unpaid,
            inactive=inactive,
            reason="already_purged",
        )

    if unpaid or inactive:
        parts = []
        if unpaid:
            parts.append("unpaid")
        if inactive:
            parts.append("inactive")
        return RetentionDecision(
            should_purge=True,
            unpaid=unpaid,
            inactive=inactive,
            reason="+".join(parts),
        )

    return RetentionDecision(
        should_purge=False,
        unpaid=False,
        inactive=False,
        reason="within_policy",
    )


def delete_all_user_conversations(db: Session, uid: str) -> int:
    """Elimina todas las conversaciones (y mensajes en cascade) del cliente."""
    uid_uuid = UUID(uid)
    convs = (
        db.query(ConversationORM)
        .filter(ConversationORM.cliente_id == uid_uuid)
        .all()
    )
    count = len(convs)
    for conv in convs:
        db.delete(conv)
    if count:
        db.commit()
    return count


def _delete_subcollection(uid: str, name: str, *, batch_size: int = 100) -> int:
    db = get_firestore_client()
    col = db.collection("users").document(uid).collection(name)
    deleted = 0
    while True:
        docs = list(col.limit(batch_size).stream())
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
        if len(docs) < batch_size:
            break
    return deleted


def _delete_top_level_document(collection_name: str, doc_id: str) -> bool:
    """Borra un documento en una colección top-level por ID.

    Usado para limpiar automation_results/{uid} y colecciones similares
    donde el doc_id coincide con el uid del usuario.
    """
    try:
        db = get_firestore_client()
        ref = db.collection(collection_name).document(doc_id)
        snap = ref.get()
        if snap.exists:
            # Borrar subcolecciones primero (campaigns, etc.)
            for sub in ref.collections():
                _delete_all_in_collection(sub)
            ref.delete()
            return True
    except Exception:
        log.warning(
            "No se pudo borrar %s/%s",
            collection_name,
            doc_id[:8],
            exc_info=True,
        )
    return False


def _delete_all_in_collection(col_ref, *, batch_size: int = 100) -> int:
    """Borra todos los documentos en una referencia de colección arbitraria."""
    deleted = 0
    while True:
        docs = list(col_ref.limit(batch_size).stream())
        if not docs:
            break
        batch = col_ref._client.batch() if hasattr(col_ref, '_client') else get_firestore_client().batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
        if len(docs) < batch_size:
            break
    return deleted


def _delete_profile_memory(uid: str) -> bool:
    """Borra el documento users/{uid}/profile/memory (memoria resumida B02)."""
    try:
        db = get_firestore_client()
        ref = db.collection("users").document(uid).collection("profile").document("memory")
        if ref.get().exists:
            ref.delete()
            return True
    except Exception:
        log.warning(
            "No se pudo borrar profile/memory uid=%s",
            uid[:8],
            exc_info=True,
        )
    return False


def purge_user_product_data(db: Session, uid: str) -> dict[str, object]:
    """Borra memoria, chats, automatizaciones y tokens Google del usuario.

    D01/D02 — MASTER-EXECUTION-PLAN:
      a) Borrar memory_summary en Firestore users/{uid}/profile/memory
      b) Borrar chat_conversations + chat_messages en Postgres (hard-delete)
      c) Borrar automatizaciones + resultados en Firestore
      d) Revocar tokens OAuth en Firestore
      e) NO borrar: clientes_suscripcion, usage_tokens

    Idempotente: correrlo 2 veces no debe borrar 2 veces (best-effort).
    """
    clean = uid.strip()
    if not clean:
        raise ValueError("uid requerido")

    profile_before = get_user_profile(clean) or {}

    # (b) Chats Postgres
    chats_deleted = delete_all_user_conversations(db, clean)

    # (a) Memoria Firestore — documento de perfil + subcolección profile/memory
    memory_deleted = _delete_profile_memory(clean)

    # (c) Automatizaciones — ejecuciones + resultados
    executions_deleted = 0
    try:
        executions_deleted = _delete_subcollection(clean, "automation_executions")
    except Exception:
        log.warning(
            "No se pudieron borrar automation_executions uid=%s",
            clean[:8],
            exc_info=True,
        )

    results_deleted = 0
    try:
        if _delete_top_level_document("automation_results", clean):
            results_deleted = 1
    except Exception:
        log.warning(
            "No se pudieron borrar automation_results uid=%s",
            clean[:8],
            exc_info=True,
        )

    # (d) Revocar tokens OAuth
    google_tokens_deleted = False
    try:
        delete_user_google_tokens(clean)
        google_tokens_deleted = True
    except Exception:
        log.warning(
            "No se pudieron borrar tokens Google uid=%s",
            clean[:8],
            exc_info=True,
        )

    # (e) Marcamos el perfil como purgado sin borrar datos comerciales
    merge_user_profile(
        clean,
        {
            "memory_summary": None,
            "saved_automations": [],
            "pending_automation_results": None,
            "automation_summary": firestore.DELETE_FIELD,
            "retention_purged_at": datetime.now(timezone.utc).isoformat(),
            "retention_purge_reason": "d5_retention",
        },
    )

    result = {
        "uid": clean,
        "chats_deleted": chats_deleted,
        "memory_profile_doc_deleted": memory_deleted,
        "automation_executions_deleted": executions_deleted,
        "automation_results_deleted": results_deleted,
        "google_tokens_deleted": google_tokens_deleted,
        "had_memory": profile_before.get("memory_summary") is not None,
        "had_automations": bool(profile_before.get("saved_automations")),
    }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Notificaciones de retención (D01 — avisos previos al purge)
# ═══════════════════════════════════════════════════════════════════════════


def _get_warnings_sent(uid: str, profile: dict | None = None) -> list[str]:
    """Lee retention_warnings_sent del perfil Firestore.

    Devuelve lista de identificadores tipo 'd-7', 'd-3', 'd-1'.
    """
    if profile is None:
        profile = get_user_profile(uid) or {}
    raw = profile.get("retention_warnings_sent")
    if isinstance(raw, list):
        return [str(w) for w in raw]
    return []


def _should_send_warning(
    uid: str,
    days_before: int,
    profile: dict | None = None,
) -> bool:
    """True si el warning para `days_before` días no se ha enviado aún."""
    key = f"d-{days_before}"
    sent = _get_warnings_sent(uid, profile)
    return key not in sent


def _record_warning_sent(uid: str, days_before: int, *, now: datetime | None = None) -> None:
    """Registra que el warning de `days_before` fue enviado en retention_warnings_sent."""
    now = now or datetime.now(timezone.utc)
    key = f"d-{days_before}"
    existing = _get_warnings_sent(uid)
    if key in existing:
        return
    existing.append(key)
    try:
        merge_user_profile(
            uid,
            {
                "retention_warnings_sent": existing,
                "retention_last_warning_at": now.isoformat(),
            },
        )
    except Exception:
        log.warning("No se pudo registrar warning_sent uid=%s key=%s", uid[:8], key, exc_info=True)


def _send_retention_warning(
    uid: str,
    days_before: int,
    reason: str,
    *,
    now: datetime | None = None,
) -> None:
    """Envía/loggea un aviso de retención para el usuario.

    En producción futura: enviar email, push notification o alerta admin.
    Por ahora: log estructurado + alerta admin en Firestore.
    """
    now = now or datetime.now(timezone.utc)
    purge_date = now + timedelta(days=days_before)

    mensajes: dict[int, str] = {
        7: "Tu cuenta será eliminada en 7 días por inactividad o falta de pago. "
           "Usa DOT hoy para conservar tus datos.",
        3: "Quedan 3 días antes de que tus datos sean eliminados. "
           "Abre DOT para evitarlo.",
        1: "Último día: mañana tus datos de DOT serán eliminados. "
           "Usa la app hoy para conservarlos.",
    }

    mensaje = mensajes.get(days_before, f"Quedan {days_before} días antes del purge de datos.")

    log.warning(
        "RETENCIÓN: aviso d-%d enviado a uid=%s reason=%s purge_previsto=%s mensaje=%s",
        days_before,
        uid[:8],
        reason,
        purge_date.date().isoformat(),
        mensaje,
    )

    # Alerta admin en Firestore para trazabilidad
    try:
        from app.firebase_db import save_admin_alert

        save_admin_alert(
            alert_type="retention_warning",
            cliente_id=uid,
            reason=f"d-{days_before}: {reason} — purge previsto {purge_date.date().isoformat()}",
        )
    except Exception:
        log.debug("No se pudo guardar alerta admin de retención uid=%s", uid[:8], exc_info=True)

    _record_warning_sent(uid, days_before, now=now)


def _compute_days_until_purge(
    *,
    fecha_vencimiento: date | None,
    last_active_at: datetime | None,
    today: date | None = None,
    now: datetime | None = None,
    days: int | None = None,
) -> int | None:
    """Calcula cuántos días faltan para que el usuario sea elegible para purge.

    Retorna el número de días (7, 6, ..., 1, 0) o None si no está en
    trayectoria de purge.

    D01/D02: el purge requiere suscripción vencida Y (inactividad o no pago).
    Si la suscripción está activa, no hay trayectoria de purge aunque
    el usuario esté inactivo.
    """
    today = today or datetime.now(timezone.utc).date()
    now = now or datetime.now(timezone.utc)
    days = retention_days() if days is None else max(1, days)

    decision = decide_retention(
        fecha_vencimiento=fecha_vencimiento,
        last_active_at=last_active_at,
        today=today,
        now=now,
        days=days,
        already_purged=False,
    )
    if decision.should_purge:
        return 0  # Ya elegible para purge

    # Si la suscripción no está vencida, no hay trayectoria de purge.
    if fecha_vencimiento is None or not is_subscription_expired(fecha_vencimiento, today=today):
        return None

    # Suscripción vencida: calcular cuántos días faltan para completar
    # la ventana de retención desde el vencimiento O desde la última actividad.
    candidates: list[int] = []

    # Días desde el vencimiento
    venc_delta = (today - fecha_vencimiento).days
    venc_remaining = days - venc_delta
    if venc_remaining > 0:
        candidates.append(venc_remaining)

    # Días desde la última actividad
    if last_active_at is not None:
        if last_active_at.tzinfo is None:
            last_active_at = last_active_at.replace(tzinfo=timezone.utc)
        act_delta = (now - last_active_at).days
        act_remaining = days - act_delta
        if act_remaining > 0:
            candidates.append(act_remaining)

    return min(candidates) if candidates else None


def send_retention_warnings(db: Session) -> dict[str, object]:
    """Escanea usuarios próximos al purge y envía notificaciones a 7, 3, 1 día.

    Idempotente: no reenvía warnings ya registrados en retention_warnings_sent.
    Corre como paso previo a run_retention_scan en el cron diario.
    """
    from app.billing_models import ClienteORM

    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    warnings_sent = 0
    warnings_skipped = 0
    details: list[dict[str, object]] = []

    clientes = db.query(ClienteORM).all()
    for cliente in clientes:
        uid = str(cliente.id)
        try:
            profile = get_user_profile(uid) or {}
            last_active = parse_last_active_at(profile.get("last_active_at"))

            days_remaining = _compute_days_until_purge(
                fecha_vencimiento=cliente.fecha_vencimiento,
                last_active_at=last_active,
                today=today,
                now=now,
            )

            if days_remaining is None or days_remaining > 7:
                continue  # Muy lejos del purge o no en trayectoria

            # Enviar avisos para cada threshold alcanzado
            decision = decide_retention(
                fecha_vencimiento=cliente.fecha_vencimiento,
                last_active_at=last_active,
                today=today,
                now=now,
            )
            if decision.should_purge:
                continue  # Ya es elegible — el purge lo maneja run_retention_scan

            reason = decision.reason or "within_policy"

            for days_before in _RETENTION_WARNING_DAYS:
                if days_remaining <= days_before and _should_send_warning(uid, days_before, profile):
                    _send_retention_warning(uid, days_before, reason, now=now)
                    warnings_sent += 1
                    details.append(
                        {
                            "uid": uid,
                            "days_before": days_before,
                            "days_remaining": days_remaining,
                            "reason": reason,
                        }
                    )
                else:
                    warnings_skipped += 1

        except Exception:
            log.exception("Error enviando warnings de retención uid=%s", uid[:8])

    summary = {
        "warnings_sent": warnings_sent,
        "warnings_skipped": warnings_skipped,
        "details": details,
        "ran_at": now.isoformat(),
    }
    if warnings_sent:
        log.info("Retención: %d warnings enviados, %d omitidos (ya notificados)", warnings_sent, warnings_skipped)
    return summary


# ═══════════════════════════════════════════════════════════════════════════
# Evaluación y scan
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_cliente_for_purge(
    *,
    uid: str,
    fecha_vencimiento: date,
    profile: dict | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> RetentionDecision:
    """Evalúa un cliente concreto (Postgres + perfil Firestore)."""
    profile = profile if profile is not None else (get_user_profile(uid) or {})
    last_active = parse_last_active_at(profile.get("last_active_at"))
    already = bool(profile.get("retention_purged_at"))
    return decide_retention(
        fecha_vencimiento=fecha_vencimiento,
        last_active_at=last_active,
        today=today,
        now=now,
        already_purged=already,
    )


def run_retention_scan(db: Session) -> dict[str, object]:
    """Escanea clientes_suscripcion y purgea los elegibles.

    Diseñado para cron diario; idempotente.
    D01/D02 — Primero envía notificaciones, luego ejecuta purgas.
    """
    from app.billing_models import ClienteORM

    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    # Fase 1: Enviar notificaciones de retención (D01)
    try:
        warning_summary = send_retention_warnings(db)
    except Exception:
        log.exception("Error en fase de warnings de retención")
        warning_summary = {"warnings_sent": 0, "warnings_skipped": 0, "error": "exception"}

    # Fase 2: Ejecutar purgas
    scanned = 0
    purged = 0
    skipped = 0
    errors = 0
    details: list[dict[str, object]] = []

    clientes = db.query(ClienteORM).all()
    for cliente in clientes:
        scanned += 1
        uid = str(cliente.id)
        try:
            profile = get_user_profile(uid) or {}
            decision = evaluate_cliente_for_purge(
                uid=uid,
                fecha_vencimiento=cliente.fecha_vencimiento,
                profile=profile,
                today=today,
                now=now,
            )
            if not decision.should_purge:
                skipped += 1
                continue

            result = purge_user_product_data(db, uid)
            purged += 1
            details.append(
                {
                    "uid": uid,
                    "reason": decision.reason,
                    "reasons": decision.reasons,
                    **result,
                }
            )
            log.info(
                "Retención D5: purged uid=%s reason=%s chats=%s",
                uid[:8],
                decision.reason,
                result.get("chats_deleted"),
            )
        except Exception:
            errors += 1
            log.exception("Retención D5: error procesando uid=%s", uid[:8])

    summary = {
        "scanned": scanned,
        "purged": purged,
        "skipped": skipped,
        "errors": errors,
        "retention_days": retention_days(),
        "ran_at": now.isoformat(),
        "warnings": warning_summary,
        "details": details,
    }
    log.info(
        "Retención D5 completada scanned=%d purged=%d skipped=%d errors=%d warnings=%d",
        scanned,
        purged,
        skipped,
        errors,
        warning_summary.get("warnings_sent", 0),
    )
    return summary
