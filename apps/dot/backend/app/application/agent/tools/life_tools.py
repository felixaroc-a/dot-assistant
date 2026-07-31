"""Life tools: seguridad, salud y comunicacion para DOT Agent Runtime.

15 tool handlers agrupados en 3 categorias:
- SECURITY: password check/generate, URL scan, temp cleanup,
            find sensitive data, wipe metadata
- HEALTH: symptom triage, medication reminders, diet planner,
           exercise routine, sleep tracker, first aid
- COMMUNICATION: QR generator, auto-responder, follow-up reminder

Cada handler recibe (uid: str, arguments: dict) y retorna ToolResult.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import secrets
import string
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult
from app.application.agent.tools.local_files import execute_local_tool_via_bridge
from app.services.provider_router import route_chat

log = logging.getLogger("dot.agent.tools.life")


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════

_PASSWORD_SPECIAL = "!@#$%^&*()_+-=[]{}|;:,.<>?"
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_ID_NUMBER_PATTERN = re.compile(
    r"\b(V|E|J|G)?-?\d{6,9}-?\d?\b", re.IGNORECASE
)
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|password|token|auth)\s*[:=]\s*[\'\"][^\'\"]+[\'\"]",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _calc_entropy(password: str) -> float:
    """Calcula entropia de Shannon de la contrasena."""
    if not password:
        return 0.0
    freq: dict[str, int] = {}
    for ch in password:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(password)
    entropy = 0.0
    for count in freq.values():
        p = count / n
        entropy -= p * math.log2(p)
    return entropy


def _password_strength(password: str) -> tuple[str, list[str]]:
    """Evalua fortaleza de contrasena. Retorna (categoria, lista_sugerencias)."""
    suggestions: list[str] = []
    score = 0

    # Length scoring
    length = len(password)
    if length >= 16:
        score += 3
    elif length >= 12:
        score += 2
    elif length >= 8:
        score += 1
    else:
        suggestions.append("Usa al menos 12 caracteres (ideal 16+).")

    # Character variety
    has_lower = bool(re.search(r"[a-z]", password))
    has_upper = bool(re.search(r"[A-Z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", password))

    if has_lower:
        score += 1
    else:
        suggestions.append("Incluye letras minusculas.")
    if has_upper:
        score += 1
    else:
        suggestions.append("Incluye letras mayusculas.")
    if has_digit:
        score += 1
    else:
        suggestions.append("Incluye numeros.")
    if has_special:
        score += 1
    else:
        suggestions.append("Incluye caracteres especiales (!@#$…).")

    # Entropy bonus
    entropy = _calc_entropy(password)
    if entropy >= 3.5:
        score += 2
    elif entropy >= 2.5:
        score += 1

    # Common patterns penalty
    common_patterns = [
        r"123", r"abc", r"qwerty", r"password", r"admin", r"letmein",
        r"welcome", r"monkey", r"dragon", r"master", r"111", r"aaa",
    ]
    lowered = password.lower()
    for pat in common_patterns:
        if pat in lowered:
            score = max(0, score - 2)
            suggestions.append(f"Evita patrones comunes como '{pat}'.")
            break

    # Repeated chars penalty
    if re.search(r"(.)\1{2,}", password):
        score = max(0, score - 1)
        suggestions.append("Evita caracteres repetidos (ej: aaa, 111).")

    # Strength category
    if score >= 8:
        category = "strong"
    elif score >= 5:
        category = "medium"
    else:
        category = "weak"

    return category, suggestions


def _ensure_desktop_path() -> Path:
    """Retorna ruta al Escritorio del usuario Windows."""
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Desktop"


def _build_iso_date(days_from_now: int = 0) -> str:
    """Construye fecha ISO 8601 a N dias desde hoy a las 09:00 UTC."""
    target = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    target = target.replace(hour=9, minute=0, second=0, microsecond=0)
    return target.isoformat()


# ═══════════════════════════════════════════════════════════════════════
# SECURITY
# ═══════════════════════════════════════════════════════════════════════

def security_check_password(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza fortaleza de una contrasena: longitud, complejidad, entropia."""
    try:
        password = str(arguments.get("password") or "")

        if not password:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'password'.",
            )

        category, suggestions = _password_strength(password)
        entropy = _calc_entropy(password)
        length = len(password)
        masked = password[0] + "*" * (length - 2) + password[-1] if length > 2 else "***"

        lines = [
            f"Analisis de contrasena: {masked}",
            f"Longitud: {length} caracteres",
            f"Entropia: {entropy:.2f} bits por caracter",
            f"Fortaleza: {category.upper()}",
        ]

        has_lower = bool(re.search(r"[a-z]", password))
        has_upper = bool(re.search(r"[A-Z]", password))
        has_digit = bool(re.search(r"\d", password))
        has_special = bool(re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", password))

        lines.append("")
        lines.append("Complejidad:")
        lines.append(f"  Minusculas: {'Si' if has_lower else 'No'}")
        lines.append(f"  Mayusculas: {'Si' if has_upper else 'No'}")
        lines.append(f"  Numeros:    {'Si' if has_digit else 'No'}")
        lines.append(f"  Especiales: {'Si' if has_special else 'No'}")

        if suggestions:
            lines.append("")
            lines.append("Sugerencias:")
            for s in suggestions:
                lines.append(f"  - {s}")
        else:
            lines.append("")
            lines.append("Contrasena robusta. No requiere mejoras.")

        return ToolResult(
            ok=True,
            output="\n".join(lines),
        )
    except Exception as e:
        log.warning("security_check_password error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def security_generate_password(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera contrasena aleatoria segura con secrets + string."""
    try:
        length = int(arguments.get("length") or 16)
        if length < 8:
            length = 16
        if length > 128:
            length = 128

        include_lower = bool(arguments.get("include_lower", True))
        include_upper = bool(arguments.get("include_upper", True))
        include_digits = bool(arguments.get("include_digits", True))
        include_special = bool(arguments.get("include_special", True))

        charset = ""
        guarantees: list[str] = []  # al menos uno de cada tipo pedido

        if include_lower:
            charset += string.ascii_lowercase
            guarantees.append(secrets.choice(string.ascii_lowercase))
        if include_upper:
            charset += string.ascii_uppercase
            guarantees.append(secrets.choice(string.ascii_uppercase))
        if include_digits:
            charset += string.digits
            guarantees.append(secrets.choice(string.digits))
        if include_special:
            charset += _PASSWORD_SPECIAL
            guarantees.append(secrets.choice(_PASSWORD_SPECIAL))

        if not charset:
            return ToolResult(
                ok=False,
                output="",
                error="Debes incluir al menos un tipo de caracter.",
            )

        remaining = length - len(guarantees)
        if remaining < 0:
            remaining = 0
            guarantees = guarantees[:length]

        password_chars = guarantees + [
            secrets.choice(charset) for _ in range(remaining)
        ]
        secrets.SystemRandom().shuffle(password_chars)
        password = "".join(password_chars)

        category, _ = _password_strength(password)

        return ToolResult(
            ok=True,
            output=(
                f"Contrasena generada ({length} caracteres, fortaleza: {category}):\n"
                f"{password}"
            ),
        )
    except Exception as e:
        log.warning("security_generate_password error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def security_scan_url(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza si una URL es potencialmente maliciosa o phishing via IA."""
    try:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'url'.",
            )

        prompt = (
            f"Is this URL potentially malicious or a phishing site?\n\n"
            f"URL: {url}\n\n"
            f"Analyze the URL structure, domain patterns, and common phishing "
            f"indicators. Answer with exactly one of: SAFE or SUSPICIOUS. "
            f"If SUSPICIOUS, briefly explain why in one sentence."
        )

        result = route_chat(prompt)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("security_scan_url error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def security_clean_temp(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza archivos temporales. Read-only: solo lista y sugiere limpieza."""
    try:
        tmp_dir = Path(tempfile.gettempdir())
        if not tmp_dir.exists():
            return ToolResult(
                ok=True,
                output="No se encontro la carpeta temporal del sistema.",
            )

        files_info: list[tuple[str, int]] = []
        total_size = 0
        try:
            for entry in os.listdir(str(tmp_dir)):
                full = tmp_dir / entry
                try:
                    if full.is_file():
                        size = full.stat().st_size
                        files_info.append((entry, size))
                        total_size += size
                except OSError:
                    pass
        except PermissionError:
            pass

        old_files = []
        cutoff = datetime.now() - timedelta(days=7)
        for name, size in files_info:
            try:
                mtime = datetime.fromtimestamp((tmp_dir / name).stat().st_mtime)
                if mtime < cutoff:
                    old_files.append(name)
            except OSError:
                old_files.append(name)

        size_mb = total_size / (1024 * 1024)

        lines = [
            f"Analisis de carpeta temporal: {tmp_dir}",
            f"Archivos encontrados: {len(files_info)}",
            f"Tamaño total: {size_mb:.2f} MB",
            f"Archivos de hace >7 dias: {len(old_files)}",
            "",
        ]

        if old_files:
            lines.append("Sugerencia de limpieza:")
            lines.append(
                f"  Puedes eliminar {len(old_files)} archivos antiguos para "
                f"liberar aproximadamente {size_mb:.2f} MB."
            )
            lines.append("")
            lines.append("Para limpiar, abre 'Ejecutar' (Win+R) y escribe: %temp%")
            lines.append(
                "Selecciona todo (Ctrl+A) y elimina. Algunos archivos en uso "
                "no se podran borrar."
            )
        else:
            lines.append("Carpeta temporal limpia. No requiere accion.")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("security_clean_temp error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def security_find_sensitive(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca datos sensibles en un archivo (tarjetas, cedulas, telefonos, claves)."""
    try:
        path_arg = str(arguments.get("path") or "").strip()
        if not path_arg:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'path' (ruta del archivo a analizar).",
            )

        expanded = os.path.expandvars(os.path.expanduser(path_arg))
        bridge_result = execute_local_tool_via_bridge("readFile", path=expanded)

        if not bridge_result.get("ok"):
            err = bridge_result.get("error", "No se pudo leer el archivo.")
            return ToolResult(
                ok=False,
                output="",
                error=f"Error al leer archivo: {err}",
            )

        content = str(bridge_result.get("content") or bridge_result.get("output") or "")

        if not content:
            return ToolResult(
                ok=True,
                output=f"Archivo leido: {path_arg}\nEl archivo esta vacio. Sin datos sensibles detectados.",
            )

        findings: dict[str, list[str]] = {}

        credit_cards = _CREDIT_CARD_PATTERN.findall(content)
        if credit_cards:
            findings["Tarjetas de credito/debito"] = [
                c.strip()[:4] + "-****-****-****" for c in credit_cards
            ]

        id_numbers = _ID_NUMBER_PATTERN.findall(content)
        if id_numbers:
            findings["Posibles numeros de identificacion (cedula, pasaporte)"] = [
                i[:3] + "****" for i in id_numbers
            ]

        phones = _PHONE_PATTERN.findall(content)
        if phones:
            findings["Numeros de telefono"] = [
                p[:3] + "****" + p[-3:] if len(p) > 6 else "***" for p in phones
            ]

        emails = _EMAIL_PATTERN.findall(content)
        if emails:
            findings["Correos electronicos"] = [
                e[0] + "***@" + e.split("@")[1] if "@" in e else e for e in emails
            ]

        ssns = _SSN_PATTERN.findall(content)
        if ssns:
            findings["Posibles SSN (seguro social)"] = ["***-**-" + s[-4:] for s in ssns]

        keys = _KEY_PATTERN.findall(content)
        if keys:
            findings["Posibles claves/tokens en texto plano"] = [
                k.split(":")[0] + ": ****" if ":" in k else k[:8] + "****" for k in keys
            ]

        lines = [
            f"Analisis de datos sensibles: {path_arg}",
            f"Caracteres analizados: {len(content):,}",
            "",
        ]

        if findings:
            lines.append("DATOS SENSIBLES ENCONTRADOS:")
            total_found = 0
            for category, items in findings.items():
                unique = list(dict.fromkeys(items))[:5]
                lines.append(f"\n  {category} ({len(items)} ocurrencias):")
                for item in unique:
                    lines.append(f"    - {item}")
                if len(unique) < len(items):
                    lines.append(f"    ... y {len(items) - len(unique)} mas.")
                total_found += len(items)
            lines.insert(2, f"Total hallazgos: {total_found}")
            lines.append("")
            lines.append(
                "ADVERTENCIA: Este archivo contiene informacion sensible. "
                "Considera cifrarlo, moverlo a una ubicacion segura o eliminar "
                "los datos si no son necesarios."
            )
        else:
            lines.append("No se detectaron datos sensibles comunes.")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("security_find_sensitive error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def security_wipe_metadata(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza metadatos de un archivo y explica como eliminarlos."""
    try:
        path_arg = str(arguments.get("path") or "").strip()
        if not path_arg:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'path' (ruta del archivo).",
            )

        expanded = os.path.expandvars(os.path.expanduser(path_arg))
        bridge_result = execute_local_tool_via_bridge("readFile", path=expanded)

        if not bridge_result.get("ok"):
            err = bridge_result.get("error", "No se pudo leer el archivo.")
            return ToolResult(
                ok=False,
                output="",
                error=f"Error al leer archivo: {err}",
            )

        fname = Path(path_arg).name.lower()
        ext = Path(path_arg).suffix.lower()

        lines = [
            f"Guia para limpiar metadatos: {path_arg}",
            "",
            "Metadatos que podria contener este archivo:",
        ]

        if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"):
            lines.append("  - Camara/telefono usado (marca, modelo)")
            lines.append("  - Coordenadas GPS (latitud, longitud, altitud)")
            lines.append("  - Fecha y hora exacta de captura")
            lines.append("  - Configuracion de camara (ISO, apertura, velocidad)")
            lines.append("  - Software de edicion usado")
            lines.append("  - Miniatura (thumbnail) original incrustada")
            lines.append("")
            lines.append("Como eliminar metadatos de imagenes:")
            lines.append("  1. Windows: Click derecho > Propiedades > Detalles >")
            lines.append("     'Quitar propiedades e informacion personal'")
            lines.append("  2. Online: Usa exifremove.com o similares")
            lines.append("  3. Herramienta: ExifTool (gratis, linea de comandos)")
            lines.append(
                "     exiftool -all= -overwrite_original imagen.jpg"
            )
            lines.append("  4. Screenshot: Abre la imagen y toma captura nueva (sin metadatos)")

        elif ext in (".pdf",):
            lines.append("  - Autor del documento")
            lines.append("  - Software usado (ej: Microsoft Word, Adobe)")
            lines.append("  - Fecha de creacion y modificacion")
            lines.append("  - Titulo y asunto del documento")
            lines.append("  - Ruta del archivo en el sistema original")
            lines.append("")
            lines.append("Como eliminar metadatos de PDF:")
            lines.append("  1. Imprime el PDF a 'Microsoft Print to PDF'")
            lines.append("     (esto crea una copia sin metadatos)")
            lines.append("  2. Adobe Acrobat Pro: Herramientas > Proteger >")
            lines.append("     Eliminar informacion oculta")
            lines.append("  3. Online: pdfmetaeditor.com o similares")

        elif ext in (".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"):
            lines.append("  - Autor y ultimo editor")
            lines.append("  - Empresa/Organizacion")
            lines.append("  - Tiempo total de edicion")
            lines.append("  - Fechas de creacion, modificacion, acceso e impresion")
            lines.append("  - Revisiones y cambios anteriores (track changes)")
            lines.append("  - Comentarios y notas ocultas")
            lines.append("  - Rutas de archivos vinculados/imagenes")
            lines.append("")
            lines.append("Como eliminar metadatos de Office:")
            lines.append("  1. Archivo > Informacion > Inspeccionar documento >")
            lines.append("     Inspeccionar > Eliminar todo")
            lines.append("  2. Archivo > Informacion > Propiedades >")
            lines.append("     Propiedades avanzadas > limpiar campos")
            lines.append("  3. Guarda como 'Documento PDF' o copia el contenido a")
            lines.append("     un archivo nuevo en blanco")

        elif ext in (".mp3", ".wav", ".flac", ".aac", ".m4a"):
            lines.append("  - Artista, album, titulo, genero")
            lines.append("  - Numero de pista, año")
            lines.append("  - Software de grabacion/edicion")
            lines.append("  - Caratula del album incrustada")
            lines.append("")
            lines.append("Como eliminar metadatos de audio:")
            lines.append("  1. Windows: Click derecho > Propiedades > Detalles >")
            lines.append("     'Quitar propiedades e informacion personal'")
            lines.append("  2. VLC: Convertir > Perfil audio sin metadatos")
            lines.append("  3. ffmpeg: ffmpeg -i entrada.mp3 -map_metadata -1 salida.mp3")

        else:
            lines.append("  - Fecha de creacion, modificacion y acceso (timestamps del SO)")
            lines.append("  - Autor/propietario (segun el tipo de archivo)")
            lines.append("  - Atributos extendidos del sistema (xattrs)")
            lines.append("")
            lines.append("Como eliminar metadatos genericos:")
            lines.append("  1. Windows: Click derecho > Propiedades > Detalles >")
            lines.append("     'Quitar propiedades e informacion personal'")
            lines.append("  2. Copia el contenido y pegalo en un archivo nuevo")
            lines.append("  3. Comprime con ZIP sin incluir metadatos extendidos")

        lines.append("")
        lines.append("NOTA: Esta herramienta NO modifica el archivo.")
        lines.append("Solo informa que metadatos podria tener y como limpiarlos.")
        lines.append("Siempre haz una copia de seguridad antes de limpiar metadatos.")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("security_wipe_metadata error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════

def health_symptom_triage(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Triaje de sintomas via IA: orientacion NO medica."""
    try:
        symptoms = str(arguments.get("symptoms") or "").strip()
        age = str(arguments.get("age") or "adulto").strip()

        if not symptoms:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'symptoms'.",
            )

        prompt = (
            f"Given these symptoms: {symptoms}, age: {age}.\n\n"
            f"Suggest possible causes and urgency level. Choose exactly one urgency: "
            f"pharmacy, doctor_today, or emergency.\n\n"
            f"IMPORTANT: This is NOT a medical diagnosis, only general health orientation. "
            f"Always recommend consulting a real doctor. "
            f"Include a clear disclaimer at the start.\n\n"
            f"Format your response as:\n"
            f"DISCLAIMER: [one line warning]\n"
            f"URGENCY: [pharmacy|doctor_today|emergency]\n"
            f"POSSIBLE CAUSES: [bullet points]\n"
            f"RECOMMENDATIONS: [bullet points of what to do now]\n"
            f"WHEN TO SEEK IMMEDIATE HELP: [warning signs]"
        )

        result = route_chat(prompt)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("health_symptom_triage error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def health_medication_reminder(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea recordatorios de medicacion usando schedule_reminder o plan textual."""
    try:
        medication = str(arguments.get("medication_name") or "").strip()
        schedule_str = str(arguments.get("schedule") or "").strip()

        if not medication:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'medication_name'.",
            )
        if not schedule_str:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'schedule' (ej: '08:00,20:00').",
            )

        times = [t.strip() for t in schedule_str.split(",") if t.strip()]
        if not times:
            return ToolResult(
                ok=False,
                output="",
                error=f"Formato de horario invalido: '{schedule_str}'. Usa '08:00,20:00'.",
            )

        today = datetime.now(timezone.utc).date()
        scheduled: list[str] = []
        failed: list[str] = []

        # Intentar usar schedule_reminder si esta disponible
        try:
            from app.application.agent.tools.schedule_reminder import (
                schedule_reminder_handler,
            )

            for t in times:
                try:
                    hour, minute = int(t.split(":")[0]), int(t.split(":")[1])
                    remind_dt = datetime(
                        today.year, today.month, today.day,
                        hour, minute, 0,
                        tzinfo=timezone.utc,
                    )
                    # Si la hora ya paso hoy, programar para manana
                    now = datetime.now(timezone.utc)
                    if remind_dt <= now:
                        remind_dt += timedelta(days=1)

                    result = schedule_reminder_handler(
                        uid,
                        {
                            "remind_at": remind_dt.isoformat(),
                            "message": f"Medicacion: {medication}",
                            "channel": "notify",
                        },
                    )

                    if result.ok:
                        scheduled.append(t)
                    else:
                        failed.append(f"{t}: {result.error}")
                except (ValueError, IndexError):
                    failed.append(f"{t}: formato de hora invalido")

            if scheduled:
                lines = [
                    f"Recordatorios de medicacion creados para: {medication}",
                    f"Horarios programados: {', '.join(scheduled)}",
                ]
                if failed:
                    lines.append(f"No se programaron: {', '.join(failed)}")
                return ToolResult(ok=True, output="\n".join(lines))
            else:
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"No se pudo programar ningun recordatorio: {'; '.join(failed)}",
                )
        except ImportError:
            # Fallback: plan textual
            pass

        # Si schedule_reminder no esta disponible, devolver plan textual
        lines = [
            f"Plan de medicacion para: {medication}",
            f"Horario: {', '.join(times)}",
            "",
            "Configura estos recordatorios manualmente:",
        ]
        for t in times:
            lines.append(f"  - Diario a las {t}: tomar {medication}")
        lines.append("")
        lines.append(
            "Puedes usar la app Reloj de Windows (Alarmas y reloj) para "
            "configurar alarmas recurrentes a estas horas."
        )

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("health_medication_reminder error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def health_diet_planner(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera plan de comidas semanal via IA."""
    try:
        goal = str(arguments.get("goal") or "salud general").strip()
        restrictions = str(arguments.get("restrictions") or "ninguna").strip()
        calories = str(arguments.get("calories") or "2000").strip()

        prompt = (
            f"Create a 7-day weekly meal plan with these parameters:\n"
            f"Goal: {goal}\n"
            f"Dietary restrictions: {restrictions}\n"
            f"Daily calorie target: {calories} kcal\n\n"
            f"Include for each day: Breakfast, Lunch, Dinner, and 1-2 snacks.\n"
            f"For each meal, list the food items and approximate calories.\n"
            f"Keep it practical with foods available in Spanish-speaking countries.\n"
            f"Use a clear structured format. Include a total calories summary per day.\n\n"
            f"DISCLAIMER at top: This is a general suggestion. Consult a nutritionist "
            f"for a personalized plan."
        )

        result = route_chat(prompt)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("health_diet_planner error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def health_exercise_routine(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera rutina de ejercicios semanal via IA."""
    try:
        level = str(arguments.get("level") or "principiante").strip()
        equipment = str(arguments.get("equipment") or "sin equipo").strip()
        goal_ex = str(arguments.get("goal") or "salud general").strip()

        prompt = (
            f"Create a 7-day weekly workout routine with these parameters:\n"
            f"Fitness level: {level}\n"
            f"Available equipment: {equipment}\n"
            f"Goal: {goal_ex}\n\n"
            f"Include rest days. For each workout day, list exercises with:\n"
            f"- Exercise name\n"
            f"- Sets x Reps (or duration for cardio/stretching)\n"
            f"- Brief form notes\n"
            f"- Warm-up and cool-down instructions at the top and bottom\n\n"
            f"DISCLAIMER at top: Consult a doctor before starting any exercise program. "
            f"Stop if you feel pain."
        )

        result = route_chat(prompt)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("health_exercise_routine error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def health_sleep_tracker(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Registra horas de sueno en CSV en Escritorio y analiza tendencias."""
    try:
        hours_str = str(arguments.get("hours_slept") or "").strip()
        quality_str = str(arguments.get("quality") or "3").strip()
        notes = str(arguments.get("notes") or "").strip()

        try:
            hours = float(hours_str)
        except ValueError:
            return ToolResult(
                ok=False,
                output="",
                error=f"'hours_slept' debe ser un numero. Recibido: '{hours_str}'.",
            )

        try:
            quality = int(quality_str)
        except ValueError:
            return ToolResult(
                ok=False,
                output="",
                error=f"'quality' debe ser un numero del 1 al 5. Recibido: '{quality_str}'.",
            )

        if quality < 1 or quality > 5:
            return ToolResult(
                ok=False,
                output="",
                error=f"'quality' debe estar entre 1 y 5. Recibido: {quality}.",
            )

        if hours < 0 or hours > 24:
            return ToolResult(
                ok=False,
                output="",
                error=f"'hours_slept' debe estar entre 0 y 24. Recibido: {hours}.",
            )

        desktop = _ensure_desktop_path()
        csv_path = desktop / "dot_sleep_tracker.csv"

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        weekday = now.strftime("%A")

        # Escribir/actualizar CSV
        file_exists = csv_path.exists()
        with open(str(csv_path), "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["date", "weekday", "hours_slept", "quality_1_5", "notes"])
            writer.writerow([date_str, weekday, hours, quality, notes])

        # Analizar tendencias
        records: list[tuple[str, float, int]] = []
        with open(str(csv_path), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    records.append((
                        row.get("date", ""),
                        float(row.get("hours_slept", 0)),
                        int(row.get("quality_1_5", 3)),
                    ))
                except (ValueError, KeyError):
                    pass

        total_records = len(records)
        avg_hours = sum(r[1] for r in records) / total_records if total_records else 0
        avg_quality = sum(r[2] for r in records) / total_records if total_records else 0

        # Ultimos 7 dias
        last_7 = records[-7:]
        avg_last7_hours = sum(r[1] for r in last_7) / len(last_7) if last_7 else 0
        avg_last7_quality = sum(r[2] for r in last_7) / len(last_7) if last_7 else 0

        lines = [
            f"Registro de sueno guardado: {csv_path}",
            "",
            f"Hoy: {hours} horas, calidad {quality}/5",
            "",
            "--- TENDENCIAS ---",
            f"Total de registros: {total_records}",
            f"Promedio historico: {avg_hours:.1f} horas, calidad {avg_quality:.1f}/5",
            f"Promedio ultimos 7 dias: {avg_last7_hours:.1f} horas, calidad {avg_last7_quality:.1f}/5",
            "",
        ]

        # Recomendaciones basicas
        if avg_last7_hours < 6 and len(last_7) >= 3:
            lines.append("ALERTA: Promedio de sueno bajo (<6h). Recomendaciones:")
            lines.append("  - Intenta acostarte 30 min antes")
            lines.append("  - Evita pantallas 1h antes de dormir")
            lines.append("  - Manten un horario fijo todos los dias")
        elif avg_last7_hours > 9 and len(last_7) >= 3:
            lines.append("Nota: Duermes mas de 9h en promedio. Si te sientes cansado/a")
            lines.append("a pesar de dormir mucho, considera consultar a un medico.")
        elif 7 <= avg_last7_hours <= 9:
            lines.append("Promedio de sueno saludable. Buen trabajo.")
        else:
            lines.append("Sigue registrando para ver tendencias (minimo 3 registros).")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("health_sleep_tracker error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def health_first_aid(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Guia de primeros auxilios para emergencia especifica via IA."""
    try:
        emergency = str(arguments.get("emergency_type") or "").strip()

        if not emergency:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'emergency_type' (ej: 'quemadura', 'corte', 'atragantamiento').",
            )

        prompt = (
            f"Step-by-step first aid for: {emergency}\n\n"
            f"Structure your response exactly like this:\n"
            f"1. ASSESSMENT: What to check first (consciousness, breathing, bleeding)\n"
            f"2. WHAT TO DO: Numbered step-by-step instructions. Be specific and practical.\n"
            f"3. WHAT NOT TO DO: Common mistakes to avoid.\n"
            f"4. WHEN TO CALL EMERGENCY: Specific warning signs that require 911/emergency services.\n"
            f"5. AFTERCARE: What to do after the immediate situation is under control.\n\n"
            f"DISCLAIMER at start: This is general first aid guidance. "
            f"In a real emergency, call local emergency services immediately. "
            f"This does not replace professional medical training."
        )

        result = route_chat(prompt)
        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("health_first_aid error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════════════
# COMMUNICATION
# ═══════════════════════════════════════════════════════════════════════

def comm_generate_qr(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera QR code: intenta con libreria qrcode, fallback a enlace API."""
    try:
        data = str(arguments.get("data") or "").strip()
        if not data:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'data' (texto/URL a codificar en QR).",
            )

        # Intentar con libreria qrcode si esta disponible
        try:
            import qrcode as qr_lib
            import io

            qr = qr_lib.QRCode(version=1, box_size=2, border=1)
            qr.add_data(data)
            qr.make(fit=True)

            # Generar ASCII art del QR
            matrix = qr.modules
            qr_size = len(matrix)
            ascii_lines = []
            for y in range(0, qr_size, 2):
                line = ""
                for x in range(qr_size):
                    top = matrix[y][x] if y < qr_size else False
                    bottom = matrix[y + 1][x] if (y + 1) < qr_size else False
                    if top and bottom:
                        line += "█"
                    elif top:
                        line += "▀"
                    elif bottom:
                        line += "▄"
                    else:
                        line += " "
                ascii_lines.append(line)

            qr_ascii = "\n".join(ascii_lines)

            return ToolResult(
                ok=True,
                output=(
                    f"QR generado para: {data[:80]}{'...' if len(data) > 80 else ''}\n\n"
                    f"{qr_ascii}\n\n"
                    f"Tambien puedes ver el QR en:\n"
                    f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data="
                    f"{data.replace(' ', '%20')}"
                ),
            )
        except ImportError:
            pass

        # Fallback: API externa
        encoded = data.replace(" ", "%20").replace("\n", "%0A")
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"

        result = route_chat(
            f"Generate an ASCII-art QR code that encodes this data: {data}. "
            f"Create it using Unicode block characters (█, ▀, ▄, space) for best contrast. "
            f"Make it at least 25x25 cells. Below the QR art, include the direct link: "
            f"{qr_url}"
        )

        return ToolResult(ok=True, output=result)
    except Exception as e:
        log.warning("comm_generate_qr error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def comm_auto_responder(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Guarda configuracion de auto-respondedor en JSON en Escritorio."""
    try:
        reply_message = str(arguments.get("reply_message") or "").strip()
        active_start = str(arguments.get("active_start") or "00:00").strip()
        active_end = str(arguments.get("active_end") or "23:59").strip()

        if not reply_message:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'reply_message'.",
            )

        desktop = _ensure_desktop_path()
        config_path = desktop / "dot_auto_responder.json"

        config: dict[str, Any] = {
            "uid": uid[:8],
            "enabled": True,
            "reply_message": reply_message,
            "active_hours": {
                "start": active_start,
                "end": active_end,
            },
            "configured_at": datetime.now(timezone.utc).isoformat(),
            "tool": "comm_auto_responder",
        }

        # Leer config existente si hay
        existing: dict[str, Any] = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        # Mantener configs previas de otras keys
        if isinstance(existing, dict):
            existing["auto_responder"] = config
        else:
            existing = {"auto_responder": config}

        config_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        lines = [
            "Auto-respondedor configurado:",
            f"  Archivo: {config_path}",
            f"  Mensaje: \"{reply_message[:100]}{'...' if len(reply_message) > 100 else ''}\"",
            f"  Horario activo: {active_start} a {active_end}",
            "",
            "NOTA: Esta herramienta guarda la configuracion localmente.",
            "Para activar el auto-respondedor en WhatsApp, ve a la seccion",
            "de Automatizaciones en DOT y activa 'Auto-respondedor'.",
        ]

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("comm_auto_responder error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


def comm_follow_up(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea recordatorio de seguimiento en N dias con mensaje."""
    try:
        days = int(arguments.get("days") or 3)
        message = str(arguments.get("message") or "").strip()
        context = str(arguments.get("context") or "").strip()

        if days < 1:
            return ToolResult(
                ok=False,
                output="",
                error="'days' debe ser al menos 1.",
            )

        if not message:
            return ToolResult(
                ok=False,
                output="",
                error="Falta el parametro 'message' (mensaje del seguimiento).",
            )

        remind_dt = datetime.now(timezone.utc) + timedelta(days=days)
        remind_dt = remind_dt.replace(hour=9, minute=0, second=0, microsecond=0)

        full_message = f"Seguimiento ({days} dias): {message}"
        if context:
            full_message += f" | Contexto: {context}"

        # Intentar schedule_reminder
        try:
            from app.application.agent.tools.schedule_reminder import (
                schedule_reminder_handler,
            )

            result = schedule_reminder_handler(
                uid,
                {
                    "remind_at": remind_dt.isoformat(),
                    "message": full_message,
                    "channel": "notify",
                },
            )

            if result.ok:
                return ToolResult(
                    ok=True,
                    output=(
                        f"Recordatorio de seguimiento programado:\n"
                        f"  Fecha: {remind_dt.strftime('%d/%m/%Y %H:%M')} (en {days} dias)\n"
                        f"  Mensaje: {message}"
                    ),
                )
            else:
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"No se pudo programar: {result.error}",
                )
        except ImportError:
            pass

        # Fallback textual
        return ToolResult(
            ok=True,
            output=(
                f"Plan de seguimiento (guardalo en tu agenda):\n"
                f"  Fecha: {remind_dt.strftime('%d/%m/%Y %H:%M')} (en {days} dias)\n"
                f"  Mensaje: {message}\n\n"
                f"Puedes crear un recordatorio manual en la app 'Alarmas y reloj' "
                f"de Windows para esta fecha."
            ),
        )
    except Exception as e:
        log.warning("comm_follow_up error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════════════
# EXPORT: lista de (name, handler) para registro
# ═══════════════════════════════════════════════════════════════════════

TOOLS: list[tuple[str, Any]] = [
    # SECURITY
    ("security_check_password", security_check_password),
    ("security_generate_password", security_generate_password),
    ("security_scan_url", security_scan_url),
    ("security_clean_temp", security_clean_temp),
    ("security_find_sensitive", security_find_sensitive),
    ("security_wipe_metadata", security_wipe_metadata),
    # HEALTH
    ("health_symptom_triage", health_symptom_triage),
    ("health_medication_reminder", health_medication_reminder),
    ("health_diet_planner", health_diet_planner),
    ("health_exercise_routine", health_exercise_routine),
    ("health_sleep_tracker", health_sleep_tracker),
    ("health_first_aid", health_first_aid),
    # COMMUNICATION
    ("comm_generate_qr", comm_generate_qr),
    ("comm_auto_responder", comm_auto_responder),
    ("comm_follow_up", comm_follow_up),
]
