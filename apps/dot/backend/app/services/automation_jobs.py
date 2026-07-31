"""Gestion de jobs de automatizaciones programadas.

Cada job programado incluye:
- misfire_grace_time=300s: tolera hasta 5 min de retraso tras reinicio del API.
- max_instances=1: evita que se apilen ejecuciones si un job esta stuck.
- coalesce=True: si hay multiples ejecuciones pendientes, ejecuta solo la ultima.

T01: Migrado a AsyncIOScheduler (Jul 2026).
AU02: Cron expression support added (Jul 2026).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("dot.automation_jobs")

# Tolerancia para jobs atrasados tras un reinicio del scheduler
MISFIRE_GRACE_SECONDS = 300

# ─── AU02: Cron expression parsing & validation ───

# Nombres de día de semana aceptados (3 letras minúsculas)
_CRON_DOW_NAMES = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
# Nombres de mes aceptados
_CRON_MONTH_NAMES = {"jan", "feb", "mar", "apr", "may", "jun",
                     "jul", "aug", "sep", "oct", "nov", "dec"}

_CRON_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 7),  # 0 y 7 = domingo
}


def validate_cron_expression(expr: str) -> bool:
    """Valida que una expresión cron de 5 campos sea sintácticamente correcta.

    Campos: minute hour day month weekday

    Soporta:
    - Valores fijos: 30 9 * * 1-5
    - Rangos: 0-30
    - Pasos: */15, 0-30/10
    - Listas: 1,15,30
    - Nombres: mon,tue,wed,thu,fri (weekday); jan,feb,... (month)
    - Comodín: *

    Args:
        expr: expresión cron de 5 campos separados por espacios.

    Returns:
        True si la expresión es válida.
    """
    if not expr or not isinstance(expr, str):
        return False

    parts = expr.strip().split()
    if len(parts) != 5:
        return False

    field_names = ["minute", "hour", "day", "month", "weekday"]
    for idx, (field, name) in enumerate(zip(parts, field_names)):
        lo, hi = _CRON_RANGES[name]

        # Dividir por coma para listas
        subfields = field.split(",")
        for sub in subfields:
            sub = sub.strip()
            if sub == "*":
                continue

            # Paso: */N o rango/n
            step_match = re.match(r"^(.+)/(\d+)$", sub)
            step_val = None
            if step_match:
                sub = step_match.group(1)
                step_val = int(step_match.group(2))
                if step_val < 1:
                    return False

            if sub == "*":
                continue

            # Rango: X-Y
            range_match = re.match(r"^(\w+)-(\w+)$", sub)
            if range_match:
                left_val = _parse_cron_atom(range_match.group(1), name)
                right_val = _parse_cron_atom(range_match.group(2), name)
                if left_val is None or right_val is None:
                    return False
                if left_val < lo or left_val > hi or right_val < lo or right_val > hi:
                    return False
                if left_val > right_val:
                    return False
                continue

            # Valor simple
            atom_val = _parse_cron_atom(sub, name)
            if atom_val is None:
                return False
            if atom_val < lo or atom_val > hi:
                return False

    return True


def _parse_cron_atom(atom: str, field_name: str) -> int | None:
    """Convierte un átomo cron a entero. Soporta nombres para weekday y month."""
    atom_lower = atom.strip().lower()
    if field_name == "weekday":
        if atom_lower in _CRON_DOW_NAMES:
            return list(_CRON_DOW_NAMES).index(atom_lower)
        # También aceptamos números (0-7)
        try:
            return int(atom)
        except ValueError:
            return None
    elif field_name == "month":
        if atom_lower in _CRON_MONTH_NAMES:
            return list(_CRON_MONTH_NAMES).index(atom_lower) + 1
        try:
            return int(atom)
        except ValueError:
            return None
    else:
        try:
            return int(atom)
        except ValueError:
            return None


def parse_cron_to_trigger(expr: str) -> CronTrigger | None:
    """Convierte una expresión cron de 5 campos a un CronTrigger de APScheduler.

    Args:
        expr: expresión cron de 5 campos (minute hour day month weekday).

    Returns:
        CronTrigger configurado, o None si la expresión es inválida.
    """
    if not validate_cron_expression(expr):
        return None

    parts = expr.strip().split()
    minute, hour, day, month, weekday = parts

    kwargs: dict[str, Any] = {}
    kwargs["minute"] = minute
    kwargs["hour"] = hour
    kwargs["day"] = day

    # Convertir nombres de mes a números si es necesario
    kwargs["month"] = _resolve_cron_field_names(month, _CRON_MONTH_NAMES)

    # Convertir nombres de día de semana a números si es necesario
    kwargs["day_of_week"] = _resolve_cron_field_names(weekday, _CRON_DOW_NAMES)

    # Si day y day_of_week son ambos específicos (no '*'), APScheduler
    # dispara cuando cualquiera de los dos cumple. Limpiamos day si
    # weekday está especificado (caso común).
    if weekday != "*" and day == "*":
        pass  # weekday-specific triggers, OK
    elif day != "*" and weekday == "*":
        # Solo day específico: no pasamos day_of_week para evitar ambigüedad
        kwargs.pop("day_of_week", None)

    try:
        return CronTrigger(**kwargs)
    except Exception:
        log.warning("Error creando CronTrigger desde expresión: %s", expr, exc_info=True)
        return None


def _resolve_cron_field_names(field: str, name_map: set[str]) -> str:
    """Reemplaza nombres (mon, jan) por sus equivalentes numéricos en el campo cron."""
    result: list[str] = []
    for sub in field.split(","):
        sub = sub.strip()
        # Manejar pasos y rangos con nombres
        if "/" in sub:
            base, step = sub.split("/", 1)
            base = _replace_name_in_cron_fragment(base, name_map)
            result.append(f"{base}/{step}")
        elif "-" in sub:
            left, right = sub.split("-", 1)
            left = _replace_name_in_cron_fragment(left, name_map)
            right = _replace_name_in_cron_fragment(right, name_map)
            result.append(f"{left}-{right}")
        else:
            result.append(_replace_name_in_cron_fragment(sub, name_map))
    return ",".join(result)


def _replace_name_in_cron_fragment(fragment: str, name_map: set[str]) -> str:
    """Reemplaza un fragmento atómico: nombre → número."""
    frag = fragment.strip().lower()
    if frag in name_map:
        return str(list(name_map).index(frag) + (1 if name_map == _CRON_MONTH_NAMES else 0))
    return frag


def remove_user_jobs(scheduler: AsyncIOScheduler, uid: str) -> None:
    """Elimina todos los jobs programados para un usuario."""
    prefix = f"auto_{uid}_"
    removed = 0
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(prefix):
            try:
                scheduler.remove_job(job.id)
                removed += 1
            except Exception:
                pass
    if removed:
        log.debug("Eliminados %d jobs para uid=%s", removed, uid[:8])


def remove_automation_job(scheduler: AsyncIOScheduler, uid: str, auto_id: str) -> None:
    """Elimina una automatizacion programada."""
    job_id = f"auto_{uid}_{auto_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        log.debug("Job eliminado: %s", job_id)


def parse_schedule(schedule: str) -> CronTrigger | None:
    """Parsea string de schedule a CronTrigger.

    Soporta:
      - "daily:09:00" -> CronTrigger a las 09:00
      - "daily:18:00" -> CronTrigger a las 18:00
      - "weekly:mon:09:00" -> CronTrigger lunes 09:00
      - "monthly:15:09:00" -> CronTrigger dia 15 del mes a las 09:00
      - "daily_09", "daily_18", "weekly_mon_09", "monthly_1_09" (legacy)
      - "cron:30 9 * * 1-5" -> CronTrigger a las 09:30 L-V (AU02)
      - "cron:0 */6 * * *" -> CronTrigger cada 6 horas (AU02)
      - Cron expression directa: "30 9 * * 1-5" (AU02, con spaces)
    """
    # ─── Cron expression directa (AU02) ───
    if schedule.startswith("cron:"):
        expr = schedule[5:].strip()
        return parse_cron_to_trigger(expr)

    # Detectar expresiones cron puras (5 campos, no empiezan con keyword)
    parts_space = schedule.strip().split()
    if len(parts_space) == 5 and not schedule.startswith(("daily", "weekly", "monthly")):
        possible_cron = all(
            c in "0123456789*,-/ abcdefghijklmnopqrstuvwxyz"
            for c in schedule.lower()
        )
        if possible_cron and validate_cron_expression(schedule):
            return parse_cron_to_trigger(schedule)

    # ─── Formatos simples legacy ───
    schedule_map: dict[str, CronTrigger] = {
        "daily_09": CronTrigger(hour=9, minute=0),
        "daily_18": CronTrigger(hour=18, minute=0),
        "weekly_mon_09": CronTrigger(day_of_week="mon", hour=9, minute=0),
        "monthly_1_09": CronTrigger(day=1, hour=9, minute=0),
    }

    if schedule in schedule_map:
        return schedule_map[schedule]

    if schedule.startswith("daily:"):
        parts = schedule.split(":")
        if len(parts) == 3:
            try:
                return CronTrigger(hour=int(parts[1]), minute=int(parts[2]))
            except ValueError:
                return None

    if schedule.startswith("weekly:"):
        parts = schedule.split(":")
        if len(parts) == 4:
            day_map = {
                "mon": "mon", "tue": "tue", "wed": "wed",
                "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
            }
            dow = day_map.get(parts[1])
            if dow:
                try:
                    return CronTrigger(day_of_week=dow, hour=int(parts[2]), minute=int(parts[3]))
                except ValueError:
                    return None

    # ─── AU02: "monthly:day:HH:MM" ───
    if schedule.startswith("monthly:"):
        parts = schedule.split(":")
        if len(parts) == 4:
            try:
                return CronTrigger(day=int(parts[1]), hour=int(parts[2]), minute=int(parts[3]))
            except ValueError:
                return None

    return None


def schedule_automation(
    scheduler: AsyncIOScheduler,
    uid: str,
    auto: dict,
    plan: str = "mensual",
    job_fn: Any = None,
) -> bool:
    """Programa una automatizacion individual verificando limites.

    Soporta tanto automatizaciones simples (instruccion unica) como
    pipelines multi-paso (con pipeline_steps). Si detecta is_pipeline=True
    o pipeline_steps no vacio, delega a schedule_pipeline.

    Parametros de robustez:
    - misfire_grace_time: tolera jobs atrasados hasta 5 min (reinicio del API).
    - max_instances: 1 sola ejecucion a la vez (previene apilamiento).
    - coalesce: si hay varias pendientes, ejecuta solo la ultima.
    """
    job_id = f"auto_{uid}_{auto['id']}"

    # C02: detectar pipeline multi-paso
    if auto.get("is_pipeline") and auto.get("pipeline_steps"):
        return schedule_pipeline(scheduler, uid, auto, job_fn)

    schedule_str = auto.get("schedule", "")
    instruction = auto.get("instruction", "")

    if not instruction:
        log.debug("Automation %s sin instruccion, ignorada", job_id)
        return False

    trigger = parse_schedule(schedule_str)
    if not trigger:
        log.debug("Schedule %s no parseable para %s", schedule_str, job_id)
        return False

    _ = plan  # sin gating por tier (BIBLIA D1)

    scheduler.add_job(
        job_fn,
        trigger=trigger,
        args=[uid, auto],
        id=job_id,
        replace_existing=True,
        name=auto.get("name", "Sin nombre"),
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        max_instances=1,
        coalesce=True,
    )
    log.info("Programada: %s con schedule=%s (misfire_grace=%ds)", job_id, schedule_str, MISFIRE_GRACE_SECONDS)
    return True


def schedule_pipeline(
    scheduler: AsyncIOScheduler,
    uid: str,
    auto: dict[str, Any],
    job_fn: Any = None,
) -> bool:
    """Programa un pipeline multi-paso como automatizacion compuesta (C02).

    Un pipeline tiene: trigger (cron/manual), steps [accion1, accion2, ...],
    output (chat/WA/archivo). Cada step puede ser: gmail_search, gmail_download,
    summarize, send_whatsapp, read_file, generate_document.

    Los pasos se ejecutan secuencialmente con dependencias entre ellos.
    Si un paso falla, se evalúa on_failure (skip/log/abort).
    """
    job_id = f"auto_{uid}_{auto['id']}"
    schedule_str = auto.get("schedule", "")

    pipeline_steps = auto.get("pipeline_steps", [])
    if not pipeline_steps:
        log.debug("Pipeline %s sin pasos, ignorado", job_id)
        return False

    trigger = parse_schedule(schedule_str) if schedule_str != "manual" else None
    if not trigger and schedule_str != "manual":
        log.debug("Schedule %s no parseable para pipeline %s", schedule_str, job_id)
        return False

    if not trigger:
        # Pipeline solo-manual — no programar, pero reportar OK
        log.info("Pipeline %s configurado como manual, sin programación.", job_id)
        return True

    scheduler.add_job(
        job_fn,
        trigger=trigger,
        args=[uid, auto],
        id=job_id,
        replace_existing=True,
        name=auto.get("name", "Pipeline sin nombre"),
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        max_instances=1,
        coalesce=True,
    )
    log.info(
        "Pipeline programado: %s con %d pasos, schedule=%s (misfire_grace=%ds)",
        job_id, len(pipeline_steps), schedule_str, MISFIRE_GRACE_SECONDS,
    )
    return True
