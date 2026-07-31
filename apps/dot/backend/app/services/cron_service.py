"""Servicio de tareas programadas recurrentes (cron).

Permite a los usuarios programar tareas con triggers tipo cron:
- Cada N minutos/horas/días
- A una hora específica cada día
- Día de la semana específico
- Expresiones cron personalizadas

Persiste los jobs en Firestore `users/{uid}/cron_jobs/{job_id}` para
sobrevivir reinicios del servidor. Al arrancar, rehidrata todos los jobs.

Usa AsyncIOScheduler de APScheduler. Cada job ejecuta el tool especificado
por el usuario (p.ej. enviar WhatsApp, consultar clima, fetch dólar).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

from app.firebase_db import get_db as get_firestore_client

log = logging.getLogger("dot.cron_service")

_ACTIVE_CRON_SERVICE: "CronService | None" = None


def set_active_cron_service(service: "CronService | None") -> None:
    global _ACTIVE_CRON_SERVICE
    _ACTIVE_CRON_SERVICE = service


def get_cron_service() -> "CronService | None":
    return _ACTIVE_CRON_SERVICE


# ─── Modelos de datos ───────────────────────────────────────────


class CronScheduleType(str, Enum):
    INTERVAL = "interval"        # cada N minutos/horas/días
    DAILY_AT = "daily_at"        # todos los días a HH:MM
    WEEKLY_ON = "weekly_on"      # día de semana específico a HH:MM
    CRON = "cron"                # expresión cron raw
    EVERY_N_MINUTES = "every_n_minutes"
    EVERY_N_HOURS = "every_n_hours"


class CronJobStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class CronJobDef:
    """Definición de un job cron para un usuario."""

    def __init__(
        self,
        uid: str,
        name: str,
        schedule_type: CronScheduleType,
        schedule_value: str,  # HH:MM, "mon@HH:MM", "*/5 * * * *", etc.
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        job_id: str | None = None,
        status: CronJobStatus = CronJobStatus.ACTIVE,
        last_run: str | None = None,
        last_status: str | None = None,
        last_error: str | None = None,
        run_count: int = 0,
        next_run: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ):
        self.job_id = job_id or str(uuid.uuid4())
        self.uid = uid
        self.name = name
        self.schedule_type = schedule_type
        self.schedule_value = schedule_value
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.status = status
        self.last_run = last_run
        self.last_status = last_status
        self.last_error = last_error
        self.run_count = run_count
        self.next_run = next_run
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "uid": self.uid,
            "name": self.name,
            "schedule_type": self.schedule_type.value if isinstance(self.schedule_type, CronScheduleType) else self.schedule_type,
            "schedule_value": self.schedule_value,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "status": self.status.value if isinstance(self.status, CronJobStatus) else self.status,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "run_count": self.run_count,
            "next_run": self.next_run,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJobDef:
        return cls(
            uid=str(data.get("uid", "")),
            name=str(data.get("name", "")),
            schedule_type=CronScheduleType(data.get("schedule_type", "daily_at")),
            schedule_value=str(data.get("schedule_value", "")),
            tool_name=str(data.get("tool_name", "")),
            tool_args=data.get("tool_args") or {},
            job_id=str(data.get("job_id", "")),
            status=CronJobStatus(data.get("status", "active")),
            last_run=data.get("last_run"),
            last_status=data.get("last_status"),
            last_error=data.get("last_error"),
            run_count=int(data.get("run_count", 0)),
            next_run=data.get("next_run"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ─── Plantillas preconfiguradas ──────────────────────────────────

CRON_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Briefing matutino",
        "description": "Resumen diario de correos y citas (sin IA)",
        "schedule_type": CronScheduleType.DAILY_AT.value,
        "schedule_value": "08:00",
        "tool_name": "send_morning_briefing",
        "tool_args": {},
    },
    {
        "name": "Buenos días (clima)",
        "description": "Envía clima y noticias a WhatsApp cada mañana",
        "schedule_type": CronScheduleType.DAILY_AT.value,
        "schedule_value": "08:00",
        "tool_name": "send_whatsapp_daily_briefing",
        "tool_args": {"include_weather": True, "include_news": True},
    },
    {
        "name": "Recordatorio reuniones",
        "description": "Revisa el calendario y recuerda reuniones del día",
        "schedule_type": CronScheduleType.DAILY_AT.value,
        "schedule_value": "09:00",
        "tool_name": "check_calendar_reminders",
        "tool_args": {"lookahead_hours": 12},
    },
    {
        "name": "Dólar diario",
        "description": "Consulta la tasa del dólar y la guarda",
        "schedule_type": CronScheduleType.DAILY_AT.value,
        "schedule_value": "10:00",
        "tool_name": "fetch_dollar_rate",
        "tool_args": {"save_to_memory": True},
    },
    {
        "name": "Resumen semanal",
        "description": "Resumen de actividad semanal cada lunes",
        "schedule_type": CronScheduleType.WEEKLY_ON.value,
        "schedule_value": "mon@18:00",
        "tool_name": "weekly_summary",
        "tool_args": {"send_to_whatsapp": True},
    },
]


# ─── Utilidades de scheduling ────────────────────────────────────


def build_apscheduler_trigger(job: CronJobDef) -> CronTrigger | IntervalTrigger:
    """Construye un trigger de APScheduler a partir de la definición del job."""
    st = job.schedule_type

    if st == CronScheduleType.INTERVAL or st == CronScheduleType.EVERY_N_MINUTES:
        minutes = int(job.schedule_value)
        if minutes < 1:
            raise ValueError("El intervalo mínimo es 1 minuto")
        return IntervalTrigger(minutes=minutes, timezone=timezone.utc)

    if st == CronScheduleType.EVERY_N_HOURS:
        hours = int(job.schedule_value)
        if hours < 1:
            raise ValueError("El intervalo mínimo es 1 hora")
        return IntervalTrigger(hours=hours, timezone=timezone.utc)

    if st == CronScheduleType.DAILY_AT:
        parts = job.schedule_value.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return CronTrigger(hour=hour, minute=minute, timezone=timezone.utc)

    if st == CronScheduleType.WEEKLY_ON:
        # formato: "mon@18:00" o "monday@18:00"
        day_map = {
            "mon": "mon", "monday": "mon",
            "tue": "tue", "tuesday": "tue",
            "wed": "wed", "wednesday": "wed",
            "thu": "thu", "thursday": "thu",
            "fri": "fri", "friday": "fri",
            "sat": "sat", "saturday": "sat",
            "sun": "sun", "sunday": "sun",
        }
        day_part, time_part = job.schedule_value.strip().lower().split("@", 1)
        day = day_map.get(day_part.strip(), "mon")
        hour_str, minute_str = time_part.strip().split(":", 1)
        return CronTrigger(
            day_of_week=day,
            hour=int(hour_str),
            minute=int(minute_str),
            timezone=timezone.utc,
        )

    if st == CronScheduleType.CRON:
        # raw cron expression: "minute hour day month day_of_week"
        parts = job.schedule_value.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Expresión cron inválida: {job.schedule_value}")
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone=timezone.utc,
        )

    raise ValueError(f"Tipo de schedule no soportado: {st}")


# ─── CronService ─────────────────────────────────────────────────


class CronService:
    """Gestiona jobs cron de usuarios con persistencia en Firestore.

    Responsabilidades:
    - CRUD de jobs cron por usuario
    - Programar triggers via APScheduler (AsyncIOScheduler)
    - Ejecutar el tool especificado al dispararse
    - Persistir en Firestore para sobrevivir reinicios
    - Historial de ejecución por job
    - Pausar/reanudar jobs individuales
    """

    def __init__(self, enabled: bool = True):
        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._started = False
        self._enabled = enabled
        # job_id (firestore) -> CronJobDef
        self._jobs: dict[str, CronJobDef] = {}
        # job_id -> apscheduler_job_id
        self._aps_ids: dict[str, str] = {}
        log.info("CronService creado (AsyncIOScheduler, persistencia Firestore)")

    # ─── Lifecycle ─────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return
        if not self._enabled:
            log.info("CronService deshabilitado — no se inicia el scheduler")
            return
        try:
            self._scheduler.start()
            self._started = True
            log.info("CronService iniciado")
        except Exception as e:
            log.critical("CronService no pudo iniciar: %s", e)
            raise

    def shutdown(self) -> None:
        if not self._started:
            return
        job_count = len(self._scheduler.get_jobs())
        log.info("Apagando CronService (%d jobs activos)", job_count)
        if hasattr(self._scheduler, 'running') and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False
        self._jobs.clear()
        self._aps_ids.clear()
        log.info("CronService detenido")

    @property
    def is_alive(self) -> bool:
        try:
            return self._scheduler.running if hasattr(self._scheduler, 'running') else self._started
        except Exception:
            return False

    # ─── CRUD de jobs ──────────────────────────────────────

    def add_cron_job(
        self,
        uid: str,
        name: str,
        schedule_type: CronScheduleType,
        schedule_value: str,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> CronJobDef:
        """Crea y programa un nuevo job cron para un usuario."""
        job = CronJobDef(
            uid=uid,
            name=name,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            tool_name=tool_name,
            tool_args=tool_args,
            job_id=job_id or str(uuid.uuid4()),
        )

        try:
            trigger = build_apscheduler_trigger(job)
        except ValueError as e:
            raise ValueError(f"No se pudo construir el trigger: {e}") from e

        aps_job_id = f"cron_{uid[:12]}_{job.job_id[:8]}"
        try:
            aps_job = self._scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                id=aps_job_id,
                name=job.name,
                args=[job.job_id, uid, job.tool_name, job.tool_args],
                replace_existing=True,
                misfire_grace_time=300,
                max_instances=1,
                coalesce=True,
            )
            job.next_run = aps_job.next_run_time.isoformat() if aps_job.next_run_time else None
        except Exception as e:
            log.exception("Error al programar job cron %s: %s", job.job_id[:8], e)
            raise RuntimeError(f"Error al programar job cron: {e}") from e

        self._jobs[job.job_id] = job
        self._aps_ids[job.job_id] = aps_job_id
        self._persist_job(job)
        log.info(
            "Job cron creado: %s (uid=%s, type=%s, next=%s)",
            job.name, uid[:8], schedule_type.value, job.next_run,
        )
        return job

    def get_user_jobs(self, uid: str) -> list[dict[str, Any]]:
        """Lista todos los jobs cron de un usuario."""
        user_jobs = [j for j in self._jobs.values() if j.uid == uid]

        # Sincronizar next_run desde APScheduler
        for job in user_jobs:
            aps_id = self._aps_ids.get(job.job_id)
            if aps_id:
                try:
                    aps_job = self._scheduler.get_job(aps_id)
                    if aps_job and aps_job.next_run_time:
                        job.next_run = aps_job.next_run_time.isoformat()
                except JobLookupError:
                    pass

        return [j.to_dict() for j in user_jobs]

    def remove_cron_job(self, uid: str, job_id: str) -> bool:
        """Elimina un job cron y lo desprograma."""
        job = self._jobs.get(job_id)
        if job is None or job.uid != uid:
            return False

        aps_id = self._aps_ids.pop(job_id, None)
        if aps_id:
            try:
                self._scheduler.remove_job(aps_id)
            except JobLookupError:
                log.debug("Job APScheduler ya no existía: %s", aps_id)

        del self._jobs[job_id]
        self._delete_persisted_job(uid, job_id)
        log.info("Job cron eliminado: %s (uid=%s)", job.name, uid[:8])
        return True

    def pause_cron_job(self, uid: str, job_id: str) -> bool:
        """Pausa un job cron (no se ejecutará hasta reanudar)."""
        job = self._jobs.get(job_id)
        if job is None or job.uid != uid:
            return False

        aps_id = self._aps_ids.get(job_id)
        if aps_id:
            try:
                self._scheduler.pause_job(aps_id)
            except JobLookupError:
                pass

        job.status = CronJobStatus.PAUSED
        job.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        log.info("Job cron pausado: %s (uid=%s)", job.name, uid[:8])
        return True

    def resume_cron_job(self, uid: str, job_id: str) -> bool:
        """Reanuda un job cron pausado."""
        job = self._jobs.get(job_id)
        if job is None or job.uid != uid:
            return False

        aps_id = self._aps_ids.get(job_id)
        if aps_id:
            try:
                self._scheduler.resume_job(aps_id)
                aps_job = self._scheduler.get_job(aps_id)
                if aps_job and aps_job.next_run_time:
                    job.next_run = aps_job.next_run_time.isoformat()
            except JobLookupError:
                pass

        job.status = CronJobStatus.ACTIVE
        job.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        log.info("Job cron reanudado: %s (uid=%s)", job.name, uid[:8])
        return True

    def get_job_history(self, uid: str, job_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Devuelve el historial de ejecuciones de un job."""
        job = self._jobs.get(job_id)
        if job is None or job.uid != uid:
            return []

        db = get_firestore_client()
        if db is None:
            return []

        try:
            docs = (
                db.collection("users")
                .document(uid)
                .collection("cron_jobs")
                .document(job_id)
                .collection("history")
                .order_by("executed_at", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]
        except Exception as e:
            log.warning("Error leyendo historial de job %s: %s", job_id[:8], e)
            return []

    # ─── Rehidratación al arranque ─────────────────────────

    def load_all_persisted_jobs(self) -> int:
        """Carga todos los jobs persistidos en Firestore y los programa.

        Recorre todos los usuarios en Firestore, busca su subcolección
        cron_jobs y programa cada job activo.
        """
        db = get_firestore_client()
        if db is None:
            log.warning("Firestore no disponible — no se pueden cargar jobs cron persistidos")
            return 0

        count = 0
        try:
            users_ref = db.collection("users").stream()
            user_ids = [doc.id for doc in users_ref]
        except Exception as e:
            log.warning("Error listando usuarios para rehidratar cron: %s", e)
            return 0

        for uid in user_ids:
            try:
                jobs_ref = (
                    db.collection("users")
                    .document(uid)
                    .collection("cron_jobs")
                    .stream()
                )
                for doc in jobs_ref:
                    data = doc.to_dict()
                    if not data:
                        continue
                    try:
                        job = CronJobDef.from_dict(data)
                        # Solo programar jobs activos
                        if job.status != CronJobStatus.ACTIVE:
                            self._jobs[job.job_id] = job
                            continue

                        trigger = build_apscheduler_trigger(job)
                        aps_job_id = f"cron_{uid[:12]}_{job.job_id[:8]}"
                        aps_job = self._scheduler.add_job(
                            self._execute_job,
                            trigger=trigger,
                            id=aps_job_id,
                            name=job.name,
                            args=[job.job_id, uid, job.tool_name, job.tool_args],
                            replace_existing=True,
                            misfire_grace_time=300,
                            max_instances=1,
                            coalesce=True,
                        )
                        job.next_run = aps_job.next_run_time.isoformat() if aps_job.next_run_time else None
                        self._jobs[job.job_id] = job
                        self._aps_ids[job.job_id] = aps_job_id
                        count += 1
                    except Exception as e:
                        log.warning(
                            "Error rehidratando job cron %s para uid=%s: %s",
                            doc.id, uid[:8], e,
                        )
            except Exception as e:
                log.warning("Error accediendo cron_jobs para uid=%s: %s", uid[:8], e)
                continue

        log.info("Rehidratados %d jobs cron desde Firestore", count)
        return count

    # ─── Ejecución ──────────────────────────────────────────

    def _execute_job(self, job_id: str, uid: str, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Callback cuando un trigger cron se dispara.

        Ejecuta el tool especificado y registra el resultado en Firestore.
        Captura todas las excepciones para que un job fallido no mate el scheduler.
        """
        job = self._jobs.get(job_id)
        job_name = job.name if job else tool_name
        log.info("Trigger cron disparado: %s (uid=%s, tool=%s)", job_name, uid[:8], tool_name)

        now = datetime.now(timezone.utc).isoformat()
        status = "success"
        error_msg: str | None = None

        try:
            # Actualizar last_active del usuario (BIBLIA §11)
            try:
                from app.services.activity_service import touch_last_active_best_effort
                touch_last_active_best_effort(uid)
            except Exception:
                pass

            # Ejecutar el tool
            self._run_tool(uid, tool_name, tool_args)

        except Exception as e:
            log.exception("Error ejecutando job cron %s: %s", job_id[:8], e)
            status = "error"
            error_msg = str(e)[:500]
            if job:
                job.status = CronJobStatus.ERROR
                job.last_error = error_msg

        # Actualizar métricas
        if job:
            job.last_run = now
            job.last_status = status
            job.run_count += 1
            job.updated_at = now

        # Sincronizar next_run
        aps_id = self._aps_ids.get(job_id)
        if aps_id and job:
            try:
                aps_job = self._scheduler.get_job(aps_id)
                if aps_job and aps_job.next_run_time:
                    job.next_run = aps_job.next_run_time.isoformat()
            except JobLookupError:
                pass

        self._record_history(uid, job_id, now, status, error_msg)
        if job:
            self._persist_job(job)

        log.info(
            "Job cron completado: %s (status=%s, runs=%d)",
            job_name, status, job.run_count if job else 0,
        )

    def _run_tool(self, uid: str, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Ejecuta el tool especificado. Punto de extensión para nuevos tools."""
        log.info("Ejecutando tool '%s' para uid=%s con args=%s", tool_name, uid[:8], tool_args)

        # Mapeo de tools conocidos
        if tool_name == "send_whatsapp_daily_briefing":
            self._tool_daily_briefing(uid, tool_args)
        elif tool_name == "send_morning_briefing":
            self._tool_morning_briefing(uid, tool_args)
        elif tool_name == "check_calendar_reminders":
            self._tool_calendar_reminders(uid, tool_args)
        elif tool_name == "fetch_dollar_rate":
            self._tool_dollar_rate(uid, tool_args)
        elif tool_name == "weekly_summary":
            self._tool_weekly_summary(uid, tool_args)
        elif tool_name == "send_user_reminder":
            self._tool_send_user_reminder(uid, tool_args)
        else:
            log.warning("Tool desconocido: %s — ejecución omitida", tool_name)

    def _tool_send_user_reminder(self, uid: str, args: dict[str, Any]) -> None:
        """Envía recordatorio recurrente al usuario (app o WhatsApp)."""
        message = str(args.get("message") or "").strip()
        channel = str(args.get("channel") or "notify").strip().lower()
        if not message:
            return

        if channel == "whatsapp":
            if self._send_whatsapp_if_linked(uid, f"Recordatorio DOT: {message}"):
                return

        try:
            from firebase_admin import firestore

            db = get_firestore_client()
            if db is None:
                return
            preview = message.replace("\r", " ").replace("\n", " ").strip()[:280]
            db.collection("users").document(uid).set(
                {
                    "pending_automation_results": {
                        "has_new": True,
                        "last_auto_id": "cron_reminder",
                        "last_auto_name": "Recordatorio",
                        "last_executed_at": datetime.now(timezone.utc).isoformat(),
                        "last_result_preview": preview,
                    }
                },
                merge=True,
            )
        except Exception as e:
            log.warning("No se pudo encolar recordatorio cron uid=%s: %s", uid[:8], e)

    # ─── Implementaciones de tools ──────────────────────────

    def _tool_morning_briefing(self, uid: str, args: dict[str, Any]) -> None:
        """Briefing matutino con correos y citas (sin consumo de IA)."""
        from app.services.morning_briefing_service import run_morning_briefing

        run_morning_briefing(uid, args)

    def _tool_daily_briefing(self, uid: str, args: dict[str, Any]) -> None:
        """Envía briefing diario (clima + noticias) por WhatsApp."""
        include_weather = args.get("include_weather", True)
        include_news = args.get("include_news", True)

        parts: list[str] = ["☀️ Buenos días! Aquí está tu resumen diario:\n"]

        if include_weather:
            try:
                from app.services.skills.weather import get_weather_for_user_city
                weather = get_weather_for_user_city(uid)
                parts.append(f"🌤 Clima: {weather}")
            except Exception as e:
                log.warning("No se pudo obtener clima para uid=%s: %s", uid[:8], e)
                parts.append("🌤 Clima: no disponible en este momento")

        if include_news:
            try:
                from app.services.skills.news import get_news_summary
                news = get_news_summary(uid)
                parts.append(f"📰 Noticias: {news}")
            except Exception as e:
                log.warning("No se pudo obtener noticias para uid=%s: %s", uid[:8], e)
                parts.append("📰 Noticias: no disponible en este momento")

        message = "\n\n".join(parts)
        self._send_whatsapp_if_linked(uid, message)

    def _tool_calendar_reminders(self, uid: str, args: dict[str, Any]) -> None:
        """Revisa eventos del calendario y envía recordatorios."""
        lookahead = int(args.get("lookahead_hours", 12))

        try:
            from app.services.calendar_service import get_upcoming_events
            events = get_upcoming_events(uid, lookahead_hours=lookahead)
        except Exception as e:
            log.warning("No se pudo leer calendario para uid=%s: %s", uid[:8], e)
            return

        if not events:
            log.info("Sin eventos próximos para uid=%s", uid[:8])
            return

        lines = ["📅 Recordatorio de reuniones de hoy:"]
        for ev in events[:5]:
            lines.append(f"• {ev.get('summary', 'Sin título')} — {ev.get('start', '?')}")
        message = "\n".join(lines)
        self._send_whatsapp_if_linked(uid, message)

    def _tool_dollar_rate(self, uid: str, args: dict[str, Any]) -> None:
        """Consulta la tasa del dólar y la persiste en memoria."""
        try:
            from app.services.skills.currency import fetch_dollar_rate as fetch_rate
            rate_info = fetch_rate()
        except Exception as e:
            log.warning("No se pudo obtener tasa del dólar para uid=%s: %s", uid[:8], e)
            return

        save_to_memory = args.get("save_to_memory", True)
        if save_to_memory:
            try:
                from app.firebase_db import merge_user_profile
                merge_user_profile(uid, {
                    "dollar_rate_cache": {
                        "rate": str(rate_info),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                })
            except Exception as e:
                log.warning("No se pudo guardar tasa en perfil para uid=%s: %s", uid[:8], e)

        summary = rate_info.get("summary") if isinstance(rate_info, dict) else str(rate_info)
        message = f"💵 Tasa del dólar: {summary}"
        self._send_whatsapp_if_linked(uid, message)

    def _tool_weekly_summary(self, uid: str, args: dict[str, Any]) -> None:
        """Genera resumen semanal de actividad."""
        try:
            from app.services.activity_service import get_weekly_activity_summary
            summary = get_weekly_activity_summary(uid)
        except Exception as e:
            log.warning("No se pudo generar resumen semanal para uid=%s: %s", uid[:8], e)
            summary = "No se pudo generar el resumen semanal en este momento."

        send_whatsapp = args.get("send_to_whatsapp", True)
        message = f"📊 Resumen semanal:\n\n{summary}"

        if send_whatsapp:
            self._send_whatsapp_if_linked(uid, message)
        log.info("Resumen semanal generado para uid=%s", uid[:8])

    # ─── Helpers ────────────────────────────────────────────

    def _send_whatsapp_if_linked(self, uid: str, message: str) -> bool:
        """Envía un mensaje por WhatsApp si el usuario tiene el número vinculado."""
        try:
            from app.firebase_db import get_user_profile
            from app.services.whatsapp_client import send_whatsapp_message

            profile = get_user_profile(uid)
            if not profile:
                return False

            phone = profile.get("phone_number")
            if not phone:
                log.info("Usuario %s no tiene WhatsApp vinculado — mensaje no enviado", uid[:8])
                return False

            send_whatsapp_message(phone, message)
            log.info("WhatsApp enviado a uid=%s", uid[:8])
            return True
        except Exception as e:
            log.warning("No se pudo enviar WhatsApp para uid=%s: %s", uid[:8], e)
            return False

    # ─── Persistencia Firestore ─────────────────────────────

    def _persist_job(self, job: CronJobDef) -> None:
        """Guarda la definición del job en Firestore."""
        db = get_firestore_client()
        if db is None:
            return
        try:
            db.collection("users").document(job.uid).collection("cron_jobs").document(job.job_id).set(
                job.to_dict(), merge=True,
            )
        except Exception as e:
            log.warning("Error persistiendo job cron %s: %s", job.job_id[:8], e)

    def _delete_persisted_job(self, uid: str, job_id: str) -> None:
        """Elimina un job de Firestore."""
        db = get_firestore_client()
        if db is None:
            return
        try:
            db.collection("users").document(uid).collection("cron_jobs").document(job_id).delete()
        except Exception as e:
            log.warning("Error eliminando job cron %s de Firestore: %s", job_id[:8], e)

    def _record_history(
        self,
        uid: str,
        job_id: str,
        executed_at: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Registra una ejecución en el historial del job."""
        db = get_firestore_client()
        if db is None:
            return
        try:
            entry: dict[str, Any] = {
                "executed_at": executed_at,
                "status": status,
            }
            if error:
                entry["error"] = error[:500]
            db.collection("users").document(uid).collection("cron_jobs").document(job_id).collection("history").add(entry)
        except Exception as e:
            log.warning("Error guardando historial de job %s: %s", job_id[:8], e)

    def health_check(self) -> dict[str, Any]:
        """Devuelve estado del servicio para monitoreo."""
        try:
            running = self.is_alive
            aps_jobs = self._scheduler.get_jobs() if running else []
            return {
                "ok": running,
                "enabled": self._enabled,
                "started": self._started,
                "scheduler_type": "AsyncIOScheduler",
                "job_count": len(self._jobs),
                "aps_job_count": len(aps_jobs),
                "jobs": [
                    {
                        "job_id": j.job_id,
                        "name": j.name,
                        "uid": j.uid[:8],
                        "schedule_type": j.schedule_type.value if isinstance(j.schedule_type, CronScheduleType) else j.schedule_type,
                        "status": j.status.value if isinstance(j.status, CronJobStatus) else j.status,
                        "next_run": j.next_run,
                        "run_count": j.run_count,
                        "last_run": j.last_run,
                        "last_status": j.last_status,
                    }
                    for j in self._jobs.values()
                ],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
