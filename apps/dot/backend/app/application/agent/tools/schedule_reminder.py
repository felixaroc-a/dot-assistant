"""Tool schedule_reminder para programar recordatorios relativos.

Permite al agente programar un aviso para una fecha/hora futura,
enviado por WhatsApp o notificacion en app. Persiste en Firestore
(sobrevive reinicios) con fallback SQLite offline.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult
from app.services.time_parser import format_spanish_datetime, resolve_remind_at

log = logging.getLogger("dot.agent.tools.reminder")

_DB_PATH = Path(__file__).resolve().parents[5] / "data" / "reminders.db"

TOOL_SCHEMAS: dict[str, dict] = {
    "schedule_reminder": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Texto del recordatorio (REQUERIDO). Ej: 'llamar a mamá'.",
            },
            "when": {
                "type": "string",
                "description": (
                    "Cuándo avisar en español o ISO. Ej: 'mañana a las 9', 'el lunes a las 18:30', "
                    "'en 2 horas'. Preferir when sobre remind_at."
                ),
            },
            "remind_at": {
                "type": "string",
                "description": "Fecha/hora ISO 8601 alternativa (YYYY-MM-DDTHH:MM:SS).",
            },
            "channel": {
                "type": "string",
                "description": "notify (app, default) o whatsapp.",
            },
        },
        "required": ["message"],
    },
}


def _ensure_sqlite_db() -> None:
    import sqlite3

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                uid TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                message TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'notify',
                created_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _persist_sqlite(uid: str, remind_dt: datetime, message: str, channel: str) -> str:
    import sqlite3

    _ensure_sqlite_db()
    reminder_id = f"rem_{uid[:8]}_{uuid.uuid4().hex[:12]}"
    created = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute(
            "INSERT INTO reminders (id, uid, remind_at, message, channel, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (reminder_id, uid, remind_dt.isoformat(), message, channel, created),
        )
        conn.commit()
    finally:
        conn.close()
    return reminder_id


def schedule_reminder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Programa un recordatorio único: when/remind_at + message + channel."""
    try:
        message = str(arguments.get("message") or "").strip()
        channel = str(arguments.get("channel") or "notify").strip().lower()

        if not message:
            return ToolResult(ok=False, output="", error="Falta message (texto del recordatorio).")

        remind_dt = resolve_remind_at(arguments)
        if remind_dt is None:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    "Falta cuándo avisarte. Usa when='mañana a las 9' o remind_at en ISO 8601."
                ),
            )

        now = datetime.now(timezone.utc)
        if remind_dt <= now:
            return ToolResult(
                ok=False,
                output="",
                error="Esa fecha ya pasó. Indica un momento futuro.",
            )

        if channel not in ("notify", "whatsapp"):
            channel = "notify"

        reminder_id = ""
        used_firestore = False

        try:
            from app.services.reminder_service import get_reminder_service

            svc = get_reminder_service()
            if svc is not None and svc.is_enabled:
                created = svc.create_reminder(uid, message, remind_dt, channel=channel)
                reminder_id = str(created.get("id", ""))
                used_firestore = True
        except Exception as e:
            log.warning("Firestore reminder fallback uid=%s: %s", uid[:8], e)

        if not used_firestore:
            reminder_id = _persist_sqlite(uid, remind_dt, message, channel)

        when_human = format_spanish_datetime(remind_dt)
        channel_label = "WhatsApp" if channel == "whatsapp" else "la app"
        confirmation = f"Listo, te aviso el {when_human} por {channel_label}: {message}"

        log.info(
            "Reminder scheduled id=%s uid=%s at=%s channel=%s firestore=%s",
            reminder_id,
            uid[:8],
            remind_dt.isoformat(),
            channel,
            used_firestore,
        )

        return ToolResult(ok=True, output=confirmation)
    except Exception as e:
        log.warning("schedule_reminder error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def get_and_fire_due_reminders() -> list[dict[str, Any]]:
    """Obtiene recordatorios SQLite vencidos (legacy/offline) y los marca disparados."""
    import sqlite3

    _ensure_sqlite_db()
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(_DB_PATH))
    try:
        rows = conn.execute(
            "SELECT id, uid, remind_at, message, channel FROM reminders WHERE fired = 0 AND remind_at <= ?",
            (now,),
        ).fetchall()

        if not rows:
            return []

        ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE reminders SET fired = 1 WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "uid": row[1],
                "remind_at": row[2],
                "message": row[3],
                "channel": row[4] or "notify",
            })
        log.info("Fired %d due SQLite reminders", len(results))
        return results
    finally:
        conn.close()


TOOLS = [("schedule_reminder", schedule_reminder_handler)]
