"""Parseo de fechas/horarios en español para recordatorios y rutinas.

Convierte expresiones naturales como "mañana a las 9", "el lunes a las 18:30"
o "cada lunes a las 9" a datetime UTC o definiciones de cron.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.cron_service import CronScheduleType

_DAY_ES_TO_EN: dict[str, str] = {
    "lunes": "mon",
    "martes": "tue",
    "miercoles": "wed",
    "miércoles": "wed",
    "jueves": "thu",
    "viernes": "fri",
    "sabado": "sat",
    "sábado": "sat",
    "domingo": "sun",
}

_DAY_EN_TO_ES: dict[str, str] = {
    "mon": "lunes",
    "tue": "martes",
    "wed": "miércoles",
    "thu": "jueves",
    "fri": "viernes",
    "sat": "sábado",
    "sun": "domingo",
}

_MONTH_ES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _normalize(text: str) -> str:
    return (
        text.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .strip()
    )


def _parse_time_part(text: str, default_hour: int = 9, default_minute: int = 0) -> tuple[int, int]:
    """Extrae hora:minuto de fragmentos como 'a las 9', '9:30 am', '15:00'."""
    hour, minute = default_hour, default_minute
    text = _normalize(text)

    en_match = re.search(r"en\s+(\d+)\s*(hora|minuto|min)", text)
    if en_match:
        qty = int(en_match.group(1))
        unit = en_match.group(2)
        now = datetime.now()
        target = now + (timedelta(hours=qty) if unit.startswith("h") else timedelta(minutes=qty))
        return target.hour, target.minute

    time_match = re.search(
        r"(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.?\s*m\.?|p\.?\s*m\.?)?",
        text,
    )
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "").lower().replace(".", "").replace(" ", "")
        if ampm.startswith("p") and hour < 12:
            hour += 12
        elif ampm.startswith("a") and hour == 12:
            hour = 0
        return hour, minute

    return hour, minute


def parse_spanish_datetime(text: str, *, now: datetime | None = None) -> datetime | None:
    """Convierte texto relativo/absoluto en español a datetime UTC."""
    if not text or not str(text).strip():
        return None

    raw = str(text).strip()
    # ISO directo
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    local = base  # sin TZ de usuario aún; UTC local del servidor

    norm = _normalize(raw)
    target_date = local.date()

    if "pasado manana" in norm:
        target_date = (local + timedelta(days=2)).date()
    elif "manana" in norm:
        target_date = (local + timedelta(days=1)).date()
    elif "hoy" in norm:
        target_date = local.date()

    # "el lunes", "este martes"
    for day_es, day_en in _DAY_ES_TO_EN.items():
        if re.search(rf"\b(el|este|proximo|pr[oó]ximo)\s+{day_es}\b", norm):
            weekday_target = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}[day_en]
            days_ahead = (weekday_target - local.weekday()) % 7
            if days_ahead == 0 and "proxim" not in norm:
                days_ahead = 7
            target_date = (local + timedelta(days=days_ahead)).date()
            break

    date_match = re.search(r"el\s+(\d{1,2})\s+de\s+(\w+)", norm)
    if date_match:
        day_num = int(date_match.group(1))
        month_name = date_match.group(2)
        month_num = _MONTH_ES.get(month_name)
        if month_num:
            year = local.year
            try:
                target_date = datetime(year, month_num, day_num).date()
                if target_date < local.date():
                    target_date = datetime(year + 1, month_num, day_num).date()
            except ValueError:
                return None

    en_relative = re.search(r"en\s+(\d+)\s*(hora|minuto|min)", norm)
    if en_relative:
        qty = int(en_relative.group(1))
        unit = en_relative.group(2)
        delta = timedelta(hours=qty) if unit.startswith("h") else timedelta(minutes=qty)
        return (local + delta).astimezone(timezone.utc)

    hour, minute = _parse_time_part(norm)
    try:
        dt_local = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None

    if dt_local <= local and "manana" not in norm and "pasado" not in norm:
        dt_local += timedelta(days=1)

    return dt_local.astimezone(timezone.utc)


def parse_recurring_schedule(text: str) -> tuple[CronScheduleType, str] | None:
    """Parsea rutinas recurrentes: 'cada lunes a las 9', 'todos los dias a las 8'."""
    if not text or not str(text).strip():
        return None

    norm = _normalize(str(text))

    every_n_min = re.search(r"cada\s+(\d+)\s*min", norm)
    if every_n_min:
        return CronScheduleType.EVERY_N_MINUTES, every_n_min.group(1)

    every_n_hours = re.search(r"cada\s+(\d+)\s*hora", norm)
    if every_n_hours:
        return CronScheduleType.EVERY_N_HOURS, every_n_hours.group(1)

    if re.search(r"cada\s+hora\b", norm):
        return CronScheduleType.EVERY_N_HOURS, "1"

    if re.search(r"(todos los dias|cada dia|diariamente|todas las mananas|cada manana)", norm):
        hour, minute = _parse_time_part(norm, default_hour=8)
        return CronScheduleType.DAILY_AT, f"{hour:02d}:{minute:02d}"

    for day_es, day_en in _DAY_ES_TO_EN.items():
        if re.search(rf"cada\s+{day_es}\b", norm) or re.search(rf"\bel\s+{day_es}\b", norm):
            hour, minute = _parse_time_part(norm)
            return CronScheduleType.WEEKLY_ON, f"{day_en}@{hour:02d}:{minute:02d}"

    return None


def format_spanish_datetime(dt: datetime) -> str:
    """Formato humano: 'lunes 28 de julio a las 09:00'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(timezone.utc)
    weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    weekday = weekday_names[local.weekday()]
    months = list(_MONTH_ES.keys())
    month_name = months[local.month - 1] if 1 <= local.month <= 12 else str(local.month)
    return f"{weekday} {local.day} de {month_name} a las {local.strftime('%H:%M')}"


def format_recurring_confirmation(schedule_type: CronScheduleType, schedule_value: str, message: str) -> str:
    """Confirmación humana para rutinas recurrentes."""
    msg_preview = message[:80] + ("…" if len(message) > 80 else "")

    if schedule_type == CronScheduleType.DAILY_AT:
        return f"Listo, te aviso todos los días a las {schedule_value}: {msg_preview}"

    if schedule_type == CronScheduleType.WEEKLY_ON:
        day_part, time_part = schedule_value.split("@", 1)
        day_es = _DAY_EN_TO_ES.get(day_part, day_part)
        return f"Listo, te aviso cada {day_es} a las {time_part}: {msg_preview}"

    if schedule_type in (CronScheduleType.EVERY_N_MINUTES, CronScheduleType.INTERVAL):
        return f"Listo, te aviso cada {schedule_value} minutos: {msg_preview}"

    if schedule_type == CronScheduleType.EVERY_N_HOURS:
        return f"Listo, te aviso cada {schedule_value} hora(s): {msg_preview}"

    return f"Listo, rutina programada ({schedule_value}): {msg_preview}"


def to_structured_schedule(schedule_type: CronScheduleType, schedule_value: str) -> str:
    """Convierte CronScheduleType a formato saved_automations (daily:HH:MM, weekly:mon:HH:MM)."""
    if schedule_type == CronScheduleType.DAILY_AT:
        return f"daily:{schedule_value}"
    if schedule_type == CronScheduleType.WEEKLY_ON:
        day_part, time_part = schedule_value.split("@", 1)
        return f"weekly:{day_part}:{time_part}"
    if schedule_type == CronScheduleType.EVERY_N_MINUTES:
        return f"every:{schedule_value}m"
    if schedule_type == CronScheduleType.EVERY_N_HOURS:
        return f"every:{schedule_value}h"
    return schedule_value


def extract_structured_schedule(text: str) -> str | None:
    """Extrae schedule estructurado desde texto NL ('cada lunes a las 9' → weekly:mon:09:00)."""
    parsed = parse_recurring_schedule(text)
    if not parsed:
        return None
    return to_structured_schedule(*parsed)


def format_structured_schedule_human(schedule: str) -> str:
    """Convierte daily:09:00 / weekly:mon:09:00 a texto humano en español."""
    if not schedule or schedule == "manual":
        return "manual (cuando la ejecutes tú)"

    lower = schedule.lower()
    if lower.startswith("daily:"):
        return f"todos los días a las {schedule.split(':', 1)[1]}"
    if lower.startswith("weekly:"):
        parts = schedule.split(":")
        if len(parts) >= 3:
            day_es = _DAY_EN_TO_ES.get(parts[1], parts[1])
            return f"cada {day_es} a las {parts[2]}"
    if lower.startswith("every:"):
        val = schedule.split(":", 1)[1]
        if val.endswith("m"):
            return f"cada {val[:-1]} minutos"
        if val.endswith("h"):
            return f"cada {val[:-1]} hora(s)"
    return schedule


def resolve_remind_at(arguments: dict[str, Any]) -> datetime | None:
    """Resuelve remind_at ISO o when en lenguaje natural."""
    remind_at_str = str(arguments.get("remind_at") or "").strip()
    when_str = str(arguments.get("when") or "").strip()

    if remind_at_str:
        try:
            dt = datetime.fromisoformat(remind_at_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            parsed = parse_spanish_datetime(remind_at_str)
            if parsed:
                return parsed

    if when_str:
        return parse_spanish_datetime(when_str)

    return None
