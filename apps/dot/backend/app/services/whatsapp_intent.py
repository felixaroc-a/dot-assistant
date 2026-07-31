"""Deteccion de intencion en mensajes de WhatsApp para DOT."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger("dot.whatsapp_intent")

# ---------------------------------------------------------------------------
# Patrones de intencion
# ---------------------------------------------------------------------------

INTENT_PATTERNS: dict[str, list[str]] = {
    "agendar_cita": [
        r"agend(?:a|ar|e)\s+(?:una\s+)?cita",
        r"quiero\s+agendar",
        r"reserv(?:a|ar)\s+(?:una\s+)?hora",
        r"programa\s+(?:una\s+)?reunion",
        r"necesito\s+una\s+cita",
        r"quiero\s+programar",
        r"puedo\s+agendar",
        r"me\s+gustaria\s+agendar",
    ],
    "consulta_general": [
        r"^(?:hola|buenos\s+dias|buenas\s+tardes|buenas\s+noches)",
        r"tengo\s+una\s+consulta",
        r"quiero\s+saber",
        r"me\s+informa",
        r"que\s+es",
        r"como\s+funciona",
        r"puedes\s+decirme",
        r"puedes\s+ayudarme",
    ],
    "soporte_tecnico": [
        r"no\s+funciona",
        r"tengo\s+un\s+problema",
        r"ayuda",
        r"soporte",
        r"error",
        r"falla",
        r"no\s+puedo",
        r"esta\s+roto",
        r"problema\s+tecnico",
    ],
    "recordatorio": [
        r"recuerd(?:a|ame)",
        r"recordatorio",
        r"alarma",
        r"notificame",
        r"no\s+olvides",
        r"hazme\s+recordar",
        r"pon\s+un\s+recordatorio",
    ],
    "descarga_remota": [
        r"descarg(?:a|ar)\s+(?:una\s+)?actualizacion",
        r"descarg(?:a|ar)\s+(?:un\s+)?archivo",
        r"quiero\s+descargar",
        r"baj(?:a|ar)\s+(?:un\s+)?archivo",
        r"download",
        r"ejecuta\s+(?:una\s+)?descarga",
    ],
}


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def detect_intent(text: str) -> str | None:
    """
    Detecta la intencion principal de un mensaje de WhatsApp.

    Args:
        text: Texto del mensaje del usuario.

    Returns:
        Nombre de la intencion detectada, o ``"consulta_general"`` por defecto.
    """
    text_lower = text.lower().strip()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                log.debug("Intencion detectada: %s en texto: %s", intent, text[:60])
                return intent

    return "consulta_general"


def extract_datetime_from_text(text: str) -> dict:
    """
    Extrae fecha y hora de un texto de forma simple.

    Soporta patrones como:
    - "manana a las 3pm"
    - "el 15 de junio a las 10:30"
    - "pasado manana"
    - "en 2 horas"
    - "en 30 minutos"

    Returns:
        Diccionario con claves ``date`` (YYYY-MM-DD) y ``time`` (HH:MM).
    """
    now = datetime.now()
    day = now.day
    month = now.month
    year = now.year
    hour = 9
    minute = 0

    text_lower = text.lower()

    # Detectar dia relativo
    if "pasado manana" in text_lower:
        target = now + timedelta(days=2)
        day = target.day
        month = target.month
        year = target.year
    elif "manana" in text_lower:
        target = now + timedelta(days=1)
        day = target.day
        month = target.month
        year = target.year

    # Detectar "en N horas" o "en N minutos"
    en_match = re.search(r'en\s+(\d+)\s*(hora|minuto|min)', text_lower)
    if en_match:
        cantidad = int(en_match.group(1))
        unidad = en_match.group(2)
        if unidad.startswith("h"):
            target = now + timedelta(hours=cantidad)
        else:
            target = now + timedelta(minutes=cantidad)
        day = target.day
        month = target.month
        year = target.year
        hour = target.hour
        minute = target.minute
        return {"date": f"{year:04d}-{month:02d}-{day:02d}", "time": f"{hour:02d}:{minute:02d}"}

    # Detectar "a las HH:MM am/pm"
    time_match = re.search(r'a\s+las\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text_lower)
    if time_match:
        hour_candidate = int(time_match.group(1))
        minute_candidate = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "am").lower()

        if ampm == "pm" and hour_candidate < 12:
            hour_candidate += 12
        elif ampm == "am" and hour_candidate == 12:
            hour_candidate = 0

        hour = hour_candidate
        minute = minute_candidate

    # Detectar "el N de mes"
    date_match = re.search(r'el\s+(\d{1,2})\s+de\s+(\w+)', text_lower)
    if date_match:
        day_candidate = int(date_match.group(1))
        month_name = date_match.group(2).lower()
        month_map = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
            "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
            "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        }
        mapped = month_map.get(month_name)
        if mapped:
            day = day_candidate
            month = mapped

    return {
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "time": f"{hour:02d}:{minute:02d}",
    }
