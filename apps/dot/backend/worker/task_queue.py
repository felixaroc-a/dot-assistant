"""Cola de tareas persistente para automatizaciones.

Usa SQLite como backend de cola (no requiere Redis).
Las tareas se persisten inmediatamente, lo que permite:
- Recuperacion ante caidas del worker
- Varios workers compitiendo por tareas
- Visibilidad del estado de cada tarea
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("dot.task_queue")

TaskStatus = Literal["pending", "running", "completed", "failed"]

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "tasks.db"


class TaskQueue:
    """Cola de tareas FIFO con persistencia SQLite.

    Cada tarea tiene:
    - id: UUID unico
    - uid: usuario propietario
    - payload: JSON con datos de la automatizacion
    - status: pending / running / completed / failed
    - created_at / started_at / completed_at: timestamps
    - result: texto del resultado
    - error: mensaje de error si fallo
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    uid TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, task_id: str, uid: str, payload: dict[str, Any]) -> None:
        """Agrega una tarea a la cola (persistente)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tasks (id, uid, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (task_id, uid, json.dumps(payload), now),
            )
            conn.commit()
        log.debug("Tarea encolada: %s (uid=%s)", task_id[:8], uid[:8])

    def has_active_task_for_automation(self, uid: str, auto_id: str) -> bool:
        """True si ya hay tarea pending/running para la misma automatización (T01b)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM tasks WHERE uid = ? AND status IN ('pending', 'running')",
                (uid,),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (json.JSONDecodeError, TypeError):
                continue
            if str(payload.get("id", "")) == auto_id:
                return True
        return False

    def dequeue(self, timeout: float = 5.0) -> dict[str, Any] | None:
        """Obtiene la siguiente tarea pending como FIFO (con timeout)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT id, uid, payload FROM tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
                ).fetchone()
                if row is not None:
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
                        (now, row["id"]),
                    )
                    conn.commit()
                    return {
                        "id": row["id"],
                        "uid": row["uid"],
                        "payload": json.loads(row["payload"]),
                    }
            time.sleep(0.2)
        return None

    def complete(self, task_id: str, result: str) -> None:
        """Marca una tarea como completada."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
                (now, result[:10000], task_id),
            )
            conn.commit()

    def fail(self, task_id: str, error: str) -> None:
        """Marca una tarea como fallida."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'failed', completed_at = ?, error = ? WHERE id = ?",
                (now, error[:2000], task_id),
            )
            conn.commit()

    def reset_stale(self, max_seconds: int = 300) -> int:
        """Reabre tareas 'running' que llevan mas de max_seconds."""
        count = 0
        with self._lock, self._connect() as conn:
            # Buscar tareas running cuyo started_at es anterior a ahora - max_seconds
            rows = conn.execute(
                "SELECT id, started_at FROM tasks WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                started = row["started_at"]
                if started and _is_stale(started, max_seconds):
                    conn.execute(
                        "UPDATE tasks SET status = 'pending', started_at = NULL WHERE id = ?",
                        (row["id"],),
                    )
                    count += 1
            conn.commit()
        if count:
            log.warning("Tareas stale recuperadas: %d", count)
        return count

    def clear_old(self, max_age_days: int = 7) -> int:
        """Elimina tareas completadas/fallidas con mas de max_age_days."""
        from datetime import timedelta

        threshold = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "DELETE FROM tasks WHERE status IN ('completed', 'failed') AND created_at < ?",
                (threshold,),
            )
            conn.commit()
            return result.rowcount

    def pending_count(self, uid: str | None = None) -> int:
        """Cantidad de tareas pendientes (opcionalmente por usuario)."""
        with self._connect() as conn:
            if uid:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending' AND uid = ?",
                    (uid,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'"
                ).fetchone()
            return row["cnt"] if row else 0

    def count_by_status(self) -> dict[str, int]:
        """Cantidad de tareas por status (para health check)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
            ).fetchall()
            return {row["status"]: row["cnt"] for row in rows}

    def stats(self) -> dict:
        """Estadisticas completas de la cola para monitoreo."""
        with self._connect() as conn:
            counts = dict(
                conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
                ).fetchall()
            )
            total = sum(counts.values())
            # Ultima tarea procesada (completada o fallida)
            last = conn.execute(
                "SELECT id, status, completed_at, error FROM tasks "
                "WHERE status IN ('completed', 'failed') "
                "ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            # Tarea mas antigua pendiente
            oldest = conn.execute(
                "SELECT id, created_at FROM tasks WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

        now = datetime.now(timezone.utc)
        oldest_age_seconds = None
        if oldest:
            try:
                dt = datetime.fromisoformat(oldest["created_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                oldest_age_seconds = (now - dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return {
            "db_path": str(self._db_path),
            "total_tasks": total,
            "by_status": {
                k: counts.get(k, 0)
                for k in ("pending", "running", "completed", "failed")
            },
            "last_processed": {
                "id": last["id"][:8] if last else None,
                "status": last["status"] if last else None,
                "completed_at": last["completed_at"] if last else None,
                "error": (last["error"][:200] if last and last["error"] else None),
            },
            "oldest_pending_age_secs": round(oldest_age_seconds, 1) if oldest_age_seconds else None,
        }

    def get_recent_failures(self, limit: int = 10) -> list[dict]:
        """Ultimas tareas fallidas para diagnostico."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, uid, error, completed_at FROM tasks "
                "WHERE status = 'failed' "
                "ORDER BY completed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": r["id"][:8],
                    "uid": r["uid"][:8] if r["uid"] else "?",
                    "error": (r["error"] or "")[:300],
                    "failed_at": r["completed_at"],
                }
                for r in rows
            ]


def _is_stale(iso_timestamp: str, max_seconds: int) -> bool:
    """Determina si un timestamp ISO esta mas alla de max_seconds en el pasado."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        return elapsed > max_seconds
    except (ValueError, TypeError):
        return True
