"""Formatea salidas de pipeline/automatización para humanos (sin JSON crudo)."""
from __future__ import annotations

import json
import re
from typing import Any


_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _looks_like_json(text: str) -> bool:
    s = text.strip()
    return s.startswith("{") and s.endswith("}") and '"action"' in s


def _humanize_action_dict(data: dict[str, Any]) -> str:
    action = str(data.get("action") or data.get("type") or "").strip().lower()
    if action in {"create_document", "generate_document", "docx", "txt", "pdf"}:
        title = str(data.get("title") or data.get("filename") or "documento").strip()
        doc_type = str(data.get("type") or "documento").strip()
        content = str(data.get("content") or "").strip()
        lines = [f"Documento generado ({doc_type}): {title}"]
        if content:
            # Resumen corto del contenido, sin plantillas vacías con [placeholders]
            preview = content
            if re.search(r"\[[^\]]+\]", preview) and len(preview) > 280:
                preview = preview[:280].rsplit(" ", 1)[0] + "…"
            elif len(preview) > 500:
                preview = preview[:500].rsplit(" ", 1)[0] + "…"
            lines.append(preview)
        return "\n".join(lines)

    if action in {"read_file", "file", "leer"}:
        path = str(data.get("path") or data.get("filename") or "archivo").strip()
        content = str(data.get("content") or data.get("error") or "").strip()
        if content.lower().startswith("no se encontró") or "no encontrado" in content.lower():
            return f"No se pudo leer «{path}»: {content}"
        if content:
            preview = content if len(content) <= 600 else content[:600].rsplit(" ", 1)[0] + "…"
            return f"Archivo «{path}»:\n{preview}"
        return f"Archivo leído: {path}"

    if action in {"send_whatsapp", "whatsapp"}:
        msg = str(data.get("message") or data.get("text") or data.get("content") or "").strip()
        to = str(data.get("to") or data.get("phone") or "").strip()
        if to and msg:
            return f"WhatsApp a {to}: {msg}"
        return msg or "Notificación WhatsApp"

    # Genérico: preferir campos legibles
    for key in ("summary", "result", "message", "text", "content", "output"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def humanize_step_output(raw: str) -> str:
    """Convierte salida de un paso (posible JSON) a texto legible."""
    text = (raw or "").strip()
    if not text:
        return ""

    # Un solo objeto JSON
    if _looks_like_json(text):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                human = _humanize_action_dict(data)
                if human:
                    return human
        except json.JSONDecodeError:
            pass

    # Varios bloques JSON mezclados con texto
    parts: list[str] = []
    last = 0
    for m in _JSON_OBJECT_RE.finditer(text):
        before = text[last : m.start()].strip()
        if before and not before.startswith("{"):
            parts.append(before)
        chunk = m.group(0)
        try:
            data = json.loads(chunk)
            if isinstance(data, dict) and ("action" in data or "content" in data):
                human = _humanize_action_dict(data)
                if human:
                    parts.append(human)
                    last = m.end()
                    continue
        except json.JSONDecodeError:
            pass
        parts.append(chunk)
        last = m.end()
    tail = text[last:].strip()
    if tail:
        parts.append(tail)

    if parts:
        joined = "\n\n".join(p for p in parts if p.strip())
        # Si aún queda mucho JSON crudo, limpiar llaves sueltas de action
        if '"action"' in joined and joined.count("{") > 1:
            cleaned = []
            for block in joined.split("\n\n"):
                cleaned.append(humanize_step_output(block) if _looks_like_json(block) else block)
            return "\n\n".join(c for c in cleaned if c.strip())
        return joined

    return text


def build_whatsapp_user_message(*, title: str, prior_outputs: list[str]) -> str:
    """Arma el cuerpo del WhatsApp: título + resumen humano de pasos previos."""
    title_clean = (title or "").strip()
    # Quitar prefijos técnicos del título
    for prefix in (
        "Enviar por WhatsApp:",
        "Enviar por WhatsApp",
        "Notificar por WhatsApp:",
        "Notificar por WhatsApp",
    ):
        if title_clean.lower().startswith(prefix.lower()):
            title_clean = title_clean[len(prefix) :].strip(" :.-")
            break

    lines: list[str] = []
    # Descartar títulos placeholder del LLM ([Aquí se listarían…], etc.)
    if title_clean and not title_clean.startswith("{"):
        if not (title_clean.startswith("[") and "]" in title_clean and "aquí" in title_clean.lower()):
            if "aquí se listar" not in title_clean.lower():
                lines.append(title_clean)

    human_bits = []
    for raw in prior_outputs:
        h = humanize_step_output(raw)
        if not h:
            continue
        # No reenviar confirmaciones de envío previas
        if h.lower().startswith("mensaje whatsapp enviado"):
            continue
        human_bits.append(h)

    if human_bits:
        if lines:
            lines.append("")
        lines.append("Resumen:")
        for i, bit in enumerate(human_bits, 1):
            # Indentación simple por paso
            indented = bit.replace("\n", "\n  ")
            lines.append(f"{i}. {indented}")

    body = "\n".join(lines).strip()
    # Último filtro: si aún parece JSON puro, forzar humanize completo
    if '"action"' in body or body.startswith("{"):
        body = humanize_step_output(body)
    return body[:3500]
