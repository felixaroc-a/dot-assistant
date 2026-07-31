"""Anclaje a evidencia de tools: evita informes con rutas inventadas."""

from __future__ import annotations

import logging
import re
from pathlib import PurePath
from typing import Any

log = logging.getLogger("dot.grounding")

# Pedidos de análisis de carpeta/código + informe
_ANALYSIS_INTENT = re.compile(
    r"\b(analiz|informe|reporte|auditor[ií]a|mejorar[ií]as?|code\s*review|"
    r"revis(a|ar)\s+(el\s+)?(c[oó]digo|proyecto|carpeta)|"
    r"qu[eé]\s+mejorar[ií]as)\b",
    re.IGNORECASE,
)

# Rutas de código/docs citadas en la respuesta
_CLAIMED_PATH_RE = re.compile(
    r"(?:"
    r"`([^`\n]{3,180}\.(?:py|ts|tsx|js|cjs|mjs|md|yml|yaml|toml|json|css|html))`"
    r"|"
    r"((?:apps|docs|services|frontend|packages|infra|auto-venta1|"
    r"Chatbot-Cobro|graphify-out)[/\\][A-Za-z0-9_./\\-]{2,160}\."
    r"(?:py|ts|tsx|js|cjs|mjs|md|yml|yaml|toml|json|css))"
    r"|"
    r"((?:[A-Za-z]:)?[/\\]Users[/\\][^\s|*]{5,200}\."
    r"(?:py|ts|tsx|js|cjs|md|docx|pdf|yml|yaml|toml|json))"
    r")",
    re.IGNORECASE,
)

_DOCX_CLAIM_RE = re.compile(
    r"(?i)(?:\.docx\b|documento creado|informe completo se encuentra|"
    r"guardado en|ruta:\s*|se encuentra en)"
)

_SAVE_PATH_FROM_TOOL = re.compile(
    r"(?im)^(?:Ruta|Archivo guardado en|Documento creado)[:\s]+(.+)$"
)


def is_analysis_mission(user_text: str) -> bool:
    return bool(_ANALYSIS_INTENT.search(user_text or ""))


def extract_claimed_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _CLAIMED_PATH_RE.finditer(text or ""):
        raw = next((g for g in m.groups() if g), "")
        path = raw.strip().strip("\"'")
        if not path:
            continue
        key = path.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


def evidence_blob_from_trace(tool_trace: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for t in tool_trace or []:
        if not t.get("ok"):
            continue
        preview = str(t.get("preview") or t.get("output") or "")
        tool = str(t.get("tool") or "")
        if preview:
            parts.append(f"{tool}\n{preview}")
    return "\n".join(parts)


def path_supported_by_evidence(path: str, evidence: str) -> bool:
    if not path or not evidence:
        return False
    ev = evidence.replace("\\", "/").lower()
    norm = path.replace("\\", "/").lower()
    if norm in ev:
        return True
    base = PurePath(path.replace("\\", "/")).name.lower()
    if len(base) >= 4 and base in ev:
        return True
    # Padre relativo tipo apps/dot/backend
    parts = [p for p in PurePath(norm).parts if p not in {".", "/"}]
    if len(parts) >= 2:
        tail = "/".join(parts[-2:])
        if tail in ev:
            return True
    return False


def ungrounded_paths(claimed: list[str], evidence: str) -> list[str]:
    return [p for p in claimed if not path_supported_by_evidence(p, evidence)]


def extract_saved_path_from_trace(tool_trace: list[dict[str, Any]] | None) -> str | None:
    for t in reversed(tool_trace or []):
        if not t.get("ok"):
            continue
        tool = str(t.get("tool") or "")
        if tool not in {
            "writeFile",
            "generate_document",
            "generate_spreadsheet",
            "pptx_generate",
            "download_url_to_desktop",
            "downloadUrl",
            "browser_screenshot",
            "browser_pdf",
        }:
            continue
        preview = str(t.get("preview") or t.get("output") or "")
        # Preferir línea "Ruta:" (absoluta) sobre "Documento creado: nombre.docx"
        for line in preview.splitlines():
            m = re.match(r"(?i)^Ruta:\s*(.+)$", line.strip())
            if m:
                return m.group(1).strip()
        m = re.search(r"(?im)^Archivo guardado en:\s*(.+)$", preview)
        if m:
            return m.group(1).strip()
        for line in preview.splitlines():
            if re.search(r"\.(docx|txt|md|xlsx|pptx|pdf|png|jpe?g)\b", line, re.I) and (
                ":\\" in line or "/" in line
            ):
                # Evitar "Documento creado: foo.docx" sin path
                if "creado:" in line.lower() and ":\\" not in line and not line.strip().startswith("/"):
                    continue
                if line.lower().startswith("ruta"):
                    return line.split(":", 1)[-1].strip()
                return line.strip()
    return None


def wrote_ok(tool_trace: list[dict[str, Any]] | None) -> bool:
    save_tools = {
        "writeFile",
        "generate_document",
        "generate_spreadsheet",
        "pptx_generate",
        "download_url_to_desktop",
        "downloadUrl",
        "browser_screenshot",
        "browser_pdf",
    }
    return any(
        t.get("ok") and str(t.get("tool") or "") in save_tools for t in (tool_trace or [])
    )


def read_ok(tool_trace: list[dict[str, Any]] | None) -> bool:
    read_tools = {
        "listFiles", "readFile", "file_search", "searchFiles",
        "read_document", "read_spreadsheet", "analyze_cv",
    }
    return any(
        t.get("ok") and str(t.get("tool") or "") in read_tools for t in (tool_trace or [])
    )


# Patrones adicionales de alucinación en respuestas finales
_UNGOUNDED_EXTRAS = [
    # Precios sin fuente
    (re.compile(r"(?:cuesta|vale|precio|monto|total)\s+(?:aproximadamente|alrededor|de|es)?\s*\$?\s?\d[\d,.]*(?:\s*(?:USD|EUR|bs|bol[ií]vares|d[oó]lares))?", re.IGNORECASE), "precio sin fuente"),
    # Archivos específicos mencionados sin tool trace
    (re.compile(r"el\s+archivo\s+[\"']?[\w\-]+\.(?:pdf|txt|xlsx|docx|py|js|csv|json)[\"']?", re.IGNORECASE), "archivo mencionado sin evidencia de lectura"),
    # URLs específicas sin web_fetch
    (re.compile(r"(?:visita|revisa|mira|consulta)\s+(?:https?://[^\s]+|el\s+sitio\s+web)", re.IGNORECASE), "URL sugerida sin fetch"),
    # Datos climáticos inventados sin web_get_weather
    (re.compile(r"(?:clima|temperatura|pron[oó]stico)\s+(?:actual|hoy|ahora|en\s+\w+)\s+(?:es|est[aá]|de)\s+\d+", re.IGNORECASE), "clima sin consultar API"),
    # "Escaneé/encontré" sin listFiles/file_search
    (re.compile(r"(?:escane[éeé]|analic[éeé]|revis[éeé])\s+(?:tu|el|la)\s+(?:PC|computador|escritorio|disco)", re.IGNORECASE), "escaneo inventado sin herramientas"),
]

def _detect_general_fabrication(final_text: str, tool_trace: list | None) -> bool:
    """Detecta alucinaciones en respuestas no relacionadas con archivos."""
    if not final_text:
        return False
    # Si ya ejecutó herramientas, confiamos
    if tool_trace:
        return False
    for pattern, label in _UNGOUNDED_EXTRAS:
        if pattern.search(final_text):
            log.info("grounding_fabrication_detected label=%s", label)
            return True
    return False


def looks_ungrounded_final(
    *,
    user_text: str,
    final_text: str,
    tool_trace: list[dict[str, Any]] | None,
) -> bool:
    """True si el informe cita demasiado material no visto en tools."""
    if not is_analysis_mission(user_text):
        # Para misiones NO de análisis, verificar patrones de alucinación generales
        if _detect_general_fabrication(final_text, tool_trace):
            return True
        return False
    evidence = evidence_blob_from_trace(tool_trace)
    claimed = extract_claimed_paths(final_text)
    bad = ungrounded_paths(claimed, evidence)

    # Inventó muchas rutas concretas sin evidencia
    if len(bad) >= 3:
        return True
    if len(claimed) >= 4 and len(bad) >= max(2, len(claimed) // 2):
        return True

    # Afirma docx/guardado sin tool de escritura OK
    if _DOCX_CLAIM_RE.search(final_text or "") and (
        ".docx" in (final_text or "").lower() or "guardado" in (final_text or "").lower()
    ):
        if not wrote_ok(tool_trace):
            return True

    # Análisis profundo sin haber listado/leído nada
    if len(final_text or "") > 800 and not read_ok(tool_trace):
        return True

    return False


def grounding_nudge_message(
    *,
    user_text: str,
    final_text: str,
    tool_trace: list[dict[str, Any]] | None,
) -> str:
    evidence = evidence_blob_from_trace(tool_trace)
    claimed = extract_claimed_paths(final_text)
    bad = ungrounded_paths(claimed, evidence)[:8]
    lines = [
        "Tu borrador NO está anclado a evidencia de tools.",
        "REGLAS OBLIGATORIAS:",
        "1. Solo cita rutas/archivos que aparecieron en [tool_result] (listFiles/readFile/file_search).",
        "2. Si no leíste un archivo, NO inventes su contenido ni hallazgos sobre él.",
        "3. Si falta evidencia, usa más listFiles/readFile en subcarpetas reales (apps/, docs/, packages/).",
        "4. Si generas DOCX, usa generate_document o writeFile y copia la Ruta exacta que devolvió la tool.",
        "5. Reescribe el informe completo solo con hechos verificados.",
    ]
    if bad:
        lines.append("Rutas citadas sin evidencia (eliminar o verificar leyéndolas):")
        lines.extend(f"  - {p}" for p in bad)
    if not read_ok(tool_trace):
        lines.append("Aún no hay listFiles/readFile OK: empieza listando la carpeta pedida.")
    if _DOCX_CLAIM_RE.search(final_text or "") and not wrote_ok(tool_trace):
        lines.append("Afirmaste un documento guardado pero no hay generate_document/writeFile OK.")
    return "\n".join(lines)


def repair_saved_path_claim(final_text: str, tool_trace: list[dict[str, Any]] | None) -> str:
    """Si mintió la ruta del docx, sustituye por la ruta real de la tool."""
    text = final_text or ""
    real = extract_saved_path_from_trace(tool_trace)
    if not real or not wrote_ok(tool_trace):
        return text
    # Reemplazar rutas .docx inventadas por la real
    fake_docx = re.findall(
        r"[A-Za-z]:\\[^\s|*]+\.docx|/[^\s|*]+\.docx|`[^`]+\.docx`",
        text,
        flags=re.IGNORECASE,
    )
    out = text
    for fake in fake_docx:
        clean = fake.strip("`")
        if clean.replace("\\", "/").lower() != real.replace("\\", "/").lower():
            out = out.replace(fake, real if not fake.startswith("`") else f"`{real}`")
    if real not in out and (".docx" in text.lower() or "documento" in text.lower()):
        out = (
            f"{out.rstrip()}\n\n"
            f"— Documento real generado por DOT: `{real}`"
        )
    return out
