"""Servicio de automatizaciones programadas.

Ahora usa TaskQueue (SQLite persistente) en lugar de ejecutar directamente.
El scheduler usa APScheduler (AsyncIOScheduler) para los triggers, pero al
dispararse encola la tarea en lugar de ejecutarla. Un worker independiente
consume la cola.

Robustez ante reinicios (sin Celery):
- Al arrancar, rehidrata jobs desde Firestore (automation_bootstrap.py).
- APScheduler es in-memory puro, pero con misfire_grace_time=300 los jobs
  programados hasta 5 min después del tiempo nominal se ejecutan igual.
- max_instances=1 + coalesce=True evitan que se apilen ejecuciones atrasadas.
- Los jobs fallidos no matan el scheduler (captura de excepciones granular).
- AsyncIOScheduler: jobs sync se ejecutan en default executor, no bloquean event loop.

T01: Migrado 100% a AsyncIOScheduler (Jul 2026). Ya no hay código legacy sync.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.firebase_db import get_db as get_firestore_client
from app.services.automation_jobs import (
    remove_user_jobs,
    remove_automation_job,
    schedule_automation,
)
log = logging.getLogger("dot.automation_scheduler")

# Cuánto tiempo después del horario programado se tolera que un job se ejecute
# (útil cuando el API se reinició justo después de la hora programada).
MISFIRE_GRACE_SECONDS = 300  # 5 minutos


class AutomationScheduler:
    """Programa y encola automatizaciones.

    Responsabilidades:
    - Cargar automatizaciones desde Firestore
    - Programar triggers via APScheduler
    - Encolar tareas en TaskQueue (SQLite persistente) al dispararse
    - Ejecucion inmediata (manual) tambien via TaskQueue
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._started = False
        self._ready = False  # True tras hidratación de Firestore
        # Tracking de errores para health check y diagnóstico
        self._error_log: list[dict] = []
        self._last_run_times: dict[str, str] = {}  # job_id → ISO timestamp
        self._restart_count = 0  # T01: contador de reinicios automáticos
        log.info("AutomationScheduler creado (AsyncIOScheduler, triggers UTC, cola SQLite)")

    def start(self) -> None:
        """Inicia el scheduler APScheduler."""
        if self._started:
            return
        try:
            self._scheduler.start()
            self._started = True
            # F4: Worker de recordatorios cada 60 segundos
            self._scheduler.add_job(
                _fire_reminders_job,
                trigger="interval",
                seconds=60,
                id="reminder_worker",
                name="Fire due reminders",
                replace_existing=True,
            )
            # F4 Gateway: agent heartbeat cada 5 min (auditoría mandatos; execute opcional)
            self._scheduler.add_job(
                _agent_heartbeat_job,
                trigger="interval",
                minutes=5,
                id="agent_heartbeat",
                name="DOT Gateway agent heartbeat",
                replace_existing=True,
            )
            # P1 Loop-9: revisión proactiva de mandatos vs calendario cada 10 min
            self._scheduler.add_job(
                _proactive_calendar_job,
                trigger="interval",
                minutes=10,
                id="proactive_calendar",
                name="Proactive calendar mandate check",
                replace_existing=True,
            )
            log.info(
                "AutomationScheduler iniciado (APScheduler + reminder + agent heartbeat + calendar)"
            )
        except Exception as e:
            log.critical("AutomationScheduler no pudo iniciar: %s", e)
            raise

    def mark_ready(self) -> None:
        """Marca el scheduler como listo tras hidratacion de Firestore."""
        self._ready = True
        running = self._scheduler.running if hasattr(self._scheduler, 'running') else self._started
        job_count = len(self._scheduler.get_jobs())
        log.info("AutomationScheduler listo (running=%s, jobs=%d)", running, job_count)

    @property
    def is_alive(self) -> bool:
        """T01: verifica si el scheduler está vivo y corriendo."""
        try:
            return self._scheduler.running if hasattr(self._scheduler, 'running') else self._started
        except Exception:
            return False

    def health_check(self) -> dict:
        """Devuelve estado del scheduler para monitoreo.

        Incluye jobs activos, ultimos runs, log de errores recientes y cola SQLite.
        """
        try:
            running = self.is_alive
            jobs = self._scheduler.get_jobs()
            queue_info: dict | None = None
            try:
                from worker.task_queue import TaskQueue

                queue_info = TaskQueue().stats()
            except Exception as queue_err:
                queue_info = {"error": str(queue_err)}

            return {
                "ok": running,
                "ready": self._ready,
                "started": self._started,
                "scheduler_type": "AsyncIOScheduler",
                "misfire_grace_seconds": MISFIRE_GRACE_SECONDS,
                "job_count": len(jobs),
                "jobs": [
                    {
                        "id": j.id,
                        "name": j.name,
                        "next_run": str(j.next_run_time) if j.next_run_time else None,
                        "trigger": str(j.trigger) if j.trigger else "unknown",
                        "last_run": self._last_run_times.get(j.id),
                    }
                    for j in jobs
                ],
                "recent_errors": self._error_log[-10:],  # últimos 10 errores
                "error_count": len(self._error_log),
                "restart_count": self._restart_count,
                "queue": queue_info,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "ready": self._ready, "restart_count": self._restart_count}

    def reload_user_automations(self, uid: str, plan: str = "mensual") -> None:
        """Limpia jobs previos y recarga desde Firestore."""
        log.info("Recargando automatizaciones para uid=%s", uid[:8])
        remove_user_jobs(self._scheduler, uid)
        self.load_user_automations(uid, plan)

    def load_user_automations(self, uid: str, plan: str = "mensual") -> None:
        """Carga automatizaciones de un usuario desde Firestore."""
        try:
            db = get_firestore_client()
            doc = db.collection("users").document(uid).get()
            if not doc.exists:
                return
            profile = doc.to_dict()
            automations = profile.get("saved_automations", [])

            scheduled_count = 0
            for auto in automations:
                if auto.get("active") and auto.get("schedule") and auto.get("schedule") != "manual":
                    ok = schedule_automation(
                        self._scheduler, uid, auto, plan,
                        job_fn=self._on_trigger,
                    )
                    if ok:
                        scheduled_count += 1

            if scheduled_count:
                log.info("Cargadas %d automatizaciones para uid=%s", scheduled_count, uid[:8])
        except Exception as e:
            log.warning("Error loading automations for %s: %s", uid[:8], e)

    def execute_now(self, uid: str, auto: dict) -> str:
        """Ejecuta una automatizacion inmediatamente (trigger manual).

        En lugar de ejecutar directamente, encola la tarea y espera el resultado.
        Para requests sincronas, ejecutamos directo (sync path).
        """
        from worker.executor import AutomationExecutor
        from worker.sandbox import ExecutionSandbox, resolve_sandbox_timeout, validate_automation_payload

        instruction = str(auto.get("instruction", "")).strip()
        if not instruction:
            raise RuntimeError("La automatizacion no tiene instruccion.")

        validate_automation_payload(auto)

        sandbox = ExecutionSandbox(timeout_seconds=resolve_sandbox_timeout(auto))
        executor = AutomationExecutor()

        try:
            result = sandbox.run(
                lambda: executor.execute(uid, auto),
                context=f"{auto.get('name', 'manual')[:20]} ({uid[:8]})",
            )
        except Exception as exec_err:
            log.exception("Automation execution failed (manual): %s", auto.get("id"))
            self._track_error(f"auto_{uid}_{auto.get('id', '?')}", auto.get("name", "?"), uid, str(exec_err))
            self._record_failure_firestore(uid, auto.get("id", "?"), auto.get("name", "?"), str(exec_err))
            raise

        output_type = auto.get("output_type", "chat")
        executor.save_result(uid, auto["id"], result, output_type)
        executor.mark_pending(uid, auto["id"], auto.get("name", "Sin nombre"), result)

        log.info("Automation %s ejecutada (manual) para usuario %s", auto.get("name"), uid[:8])
        return result

    def enqueue_async(self, uid: str, auto: dict) -> str:
        """Encola una automatizacion para ejecucion asincrona por el worker."""
        from worker.task_queue import TaskQueue

        auto_id = str(auto.get("id", "") or "?")
        queue = TaskQueue()

        # Idempotencia T01b: evitar duplicados pending/running para la misma auto
        if auto_id != "?" and queue.has_active_task_for_automation(uid, auto_id):
            deduped_id = f"auto_{uid[:8]}_{auto_id}_deduped"
            log.info(
                "Idempotencia: skip enqueue duplicado auto=%s uid=%s",
                auto_id,
                uid[:8],
            )
            return deduped_id

        task_id = f"auto_{uid[:8]}_{uuid.uuid4().hex[:12]}"
        queue.enqueue(task_id, uid, auto)
        log.info("Tarea encolada: %s (%s)", task_id, auto.get("name", "?"))
        return task_id

    def remove_automation(self, uid: str, auto_id: str) -> None:
        """Elimina una automatizacion programada."""
        log.info("Eliminando automatizacion %s para uid=%s", auto_id, uid[:8])
        remove_automation_job(self._scheduler, uid, auto_id)

    def shutdown(self) -> None:
        """Apaga el scheduler de forma segura."""
        job_count = len(self._scheduler.get_jobs())
        log.info("Apagando AutomationScheduler (%d jobs activos)", job_count)
        if self._scheduler.running if hasattr(self._scheduler, 'running') else self._started:
            self._scheduler.shutdown(wait=False)
        self._started = False
        self._ready = False
        log.info("AutomationScheduler detenido")

    # ─── Handler de triggers programados ─────────────────

    def _on_trigger(self, uid: str, auto: dict) -> None:
        """Callback cuando un trigger programado se dispara.

        Encola la tarea para que el worker la procese.
        Captura todas las excepciones para que un job fallido no mate el scheduler.
        """
        auto_name = auto.get("name", "?")
        auto_id = auto.get("id", "?")
        job_id = f"auto_{uid}_{auto_id}"
        log.info("Trigger programado disparado: %s (uid=%s, job=%s)", auto_name, uid[:8], job_id)

        try:
            # Registrar timestamp para health check
            self._last_run_times[job_id] = datetime.now(timezone.utc).isoformat()

            # Ejecutar automatización cuenta como uso (BIBLIA §11).
            try:
                from app.services.activity_service import touch_last_active_best_effort
                touch_last_active_best_effort(uid)
            except Exception as e:
                log.warning(
                    "Error actualizando last_active para %s (no crítico): %s",
                    uid[:8], e,
                )

            task_id = self.enqueue_async(uid, auto)
            log.info(
                "Job programado completado: %s encolada como %s",
                auto_name, task_id,
            )

            # Log periódico de salud del scheduler
            job_count = len(self._scheduler.get_jobs())
            log.debug("Scheduler health: jobs=%d ready=%s", job_count, self._ready)
        except Exception as e:
            log.exception("Error encolando automation %s para uid=%s", auto_name, uid[:8])
            self._track_error(job_id, auto_name, uid, str(e))
            self._record_failure_firestore(uid, auto_id, auto_name, str(e))

    # ─── Tracking de errores ─────────────────────────────

    def _track_error(self, job_id: str, auto_name: str, uid: str, error: str) -> None:
        """Registra un error para health check y diagnostico."""
        entry = {
            "job_id": job_id,
            "auto_name": auto_name,
            "uid": uid[:8],
            "error": error[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._error_log.append(entry)
        # Mantener solo los ultimos 100 errores para no crecer sin limite
        if len(self._error_log) > 100:
            self._error_log = self._error_log[-100:]

    @staticmethod
    def _record_failure_firestore(uid: str, auto_id: str, auto_name: str, error: str) -> None:
        """Guarda un fallo de automatización en Firestore para notificar al usuario."""
        try:
            db = get_firestore_client()
            db.collection("users").document(uid).collection("automation_failures").add({
                "auto_id": auto_id,
                "auto_name": auto_name,
                "error": error[:500],
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "acknowledged": False,
            })
        except Exception:
            log.warning("No se pudo guardar fallo en Firestore para %s", uid[:8])

    # ─── Metodos de consulta (delegados) ─────────────────

    def get_execution_history(self, uid: str, auto_id: str) -> list[dict]:
        """Devuelve historial de ejecuciones desde Firestore."""
        try:
            db = get_firestore_client()
            docs = (
                db.collection("users")
                .document(uid)
                .collection("automation_executions")
                .where("automation_id", "==", auto_id)
                .order_by("executed_at", direction="DESCENDING")
                .limit(50)
                .stream()
            )
            return [
                {
                    "executed_at": d.to_dict().get("executed_at", ""),
                    "result": d.to_dict().get("result", ""),
                    "output_type": d.to_dict().get("output_type", "chat"),
                }
                for d in docs
            ]
        except Exception as e:
            log.warning("Error obteniendo execution history: %s", e)
            return []

    def clear_pending_results(self, uid: str) -> None:
        """Limpia resultados pendientes."""
        try:
            db = get_firestore_client()
            db.collection("users").document(uid).set(
                {
                    "pending_automation_results": {
                        "has_new": False,
                        "last_auto_id": "",
                        "last_auto_name": "",
                        "last_executed_at": "",
                        "last_result_preview": "",
                    }
                },
                merge=True,
            )
        except Exception as e:
            log.warning("Error limpiando pending results: %s", e)


# ─── F4: Recordatorio worker (module-level para APScheduler) ──

def _fire_reminders_job() -> None:
    """Job APScheduler: dispara recordatorios vencidos cada 60s."""
    from app.services.reminder_worker import fire_due_reminders

    fire_due_reminders()


def _agent_heartbeat_job() -> None:
    """Job APScheduler: heartbeat agéntico del Gateway (BIBLIA §20)."""
    import os

    from app.services.agent_heartbeat import run_agent_heartbeat

    # En demo, ejecutar checklist ligero de mandatos (costo IA acotado)
    if os.environ.get("DOT_DEMO_MODE", "").strip() == "1":
        os.environ.setdefault("DOT_AGENT_HEARTBEAT_EXECUTE", "1")
    run_agent_heartbeat(max_users=10, max_mandates_per_user=2)


def _proactive_calendar_job() -> None:
    """Job APScheduler: mandatos manuales vs eventos de calendario."""
    from app.services.proactive_calendar_worker import run_proactive_calendar_check

    run_proactive_calendar_check(max_users=10, max_mandates_per_user=2)


# Instancia global para tools/handlers sin Request (p.ej. auto_create).
_ACTIVE_SCHEDULER: AutomationScheduler | None = None


def set_active_scheduler(scheduler: AutomationScheduler | None) -> None:
    global _ACTIVE_SCHEDULER
    _ACTIVE_SCHEDULER = scheduler


def get_scheduler() -> AutomationScheduler | None:
    return _ACTIVE_SCHEDULER
