# DEPRECADO — Migrando a agent-loop.cjs en Electron (M2S4-A)
# Las tools locales ahora se ejecutan en el cliente.
# Este módulo se mantiene como fallback para clientes sin Electron.
#
# Cuando FLAG_USE_LOCAL_AGENT=True y local_tools=True, run_agent() solo
# actúa como proxy DeepSeek (un turno, sin ejecutar tools).
"""Agent Runtime — loop model → tool_calls → execute → observation → repeat."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from app.application.agent.ports import AgentResult
from app.application.agent.registry import ToolRegistry
from app.application.agent.tool_protocol import (
    format_observation,
    parse_tool_calls,
    strip_tool_calls_json,
    tools_system_hint,
)
from app.application.agent.grounding import (
    grounding_nudge_message,
    looks_ungrounded_final,
    repair_saved_path_claim,
)
from app.settings import settings

log = logging.getLogger("dot.agent.runtime")

DEFAULT_MAX_STEPS = 20
HARD_MAX_STEPS = 30
WHATSAPP_HARD_MAX_STEPS = 60


def _resolve_steps_cap(channel: str, max_steps: int) -> int:
    """Tope duro por canal: WhatsApp admite tareas más largas; resto sin cambio."""
    hard = WHATSAPP_HARD_MAX_STEPS if channel == "whatsapp" else HARD_MAX_STEPS
    return max(1, min(int(max_steps or DEFAULT_MAX_STEPS), hard))
# Cuántas veces podemos empujar al modelo si corta a medias (dentro del steps_cap).
MAX_INCOMPLETE_NUDGES = 4

# M2S4-A: Flag de migración del agent loop.
# True = proxy de un turno cuando electron_proxy=True (agent-loop.cjs en Electron).
# False = loop multi-tool en backend vía bridge (chat PC y WA usan este path).
FLAG_USE_LOCAL_AGENT = False

# Herramientas IPC en Electron (readFile, gmail_*, etc.).
# browser_* NO va aquí: se ejecuta en backend vía bridge CDP (/v1/tools/execute).
_LOCAL_TOOL_PREFIXES = (
    "gmail_",
    "calendar_",
    "whatsapp_",
)

_LOCAL_TOOL_EXACT = frozenset({
    "readFile",
    "writeFile",
    "listFiles",
    "deleteFile",
    "downloadUrl",
    "download_url_to_desktop",
    "searchFiles",
    "parseDocument",
})


def _is_local_tool(tool_name: str) -> bool:
    """True si la herramienta debe delegarse a IPC Electron (no bridge CDP)."""
    if tool_name.startswith("browser_"):
        return False
    if tool_name in _LOCAL_TOOL_EXACT:
        return True
    return tool_name.startswith(_LOCAL_TOOL_PREFIXES)

# model_fn(user_text, system_prompt) -> object con .content, opcional .usage, .model
ModelFn = Callable[[str, str], Any]

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_DOWNLOAD_VERB_RE = re.compile(
    r"\b(descarga|descargar|download|baj[aá]|bajar)\b", re.IGNORECASE
)
_SAVE_INTENT_RE = re.compile(
    r"\b(guarda|guardar|crea|crear|escribe|escribir|salv[ae]|save)\b",
    re.IGNORECASE,
)
_DESKTOP_RE = re.compile(r"\b(escritorio|desktop)\b", re.IGNORECASE)
_SEARCH_INTENT_RE = re.compile(
    r"\b(busca|buscar|noticias|web|internet)\b",
    re.IGNORECASE,
)
_READ_DOC_INTENT_RE = re.compile(
    r"\b(lee|leer|l[eé]eme|abre|analiz|revisa|resume|resumir|pdf|documento|docx|excel|xlsx|xls|hoja de c[aá]lculo|curr[ií]culum|cv\b)\b",
    re.IGNORECASE,
)
_WA_NOTIFY_INTENT_RE = re.compile(
    r"\b(m[aá]ndame|env[ií]ame|av[ií]same|notif[ií]came|whats?app|wa\b|por\s+whatsapp)\b",
    re.IGNORECASE,
)
_CALENDAR_CREATE_INTENT_RE = re.compile(
    r"\b("
    r"agenda|agendar|agend[aá]|programa|programar|crea|crear|pon|poner|"
    r"marc[aá]|reserva|reservar|aparta|apartar|bloquea|bloquear"
    r")\b.*\b("
    r"reuni[oó]n|cita|evento|compromiso|call|llamada|calendario"
    r")\b|"
    r"\b(reuni[oó]n|cita|evento)\b.*\b("
    r"agenda|agendar|programa|programar|ma[nñ]ana|pasado\s+ma[nñ]ana|"
    r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
    r"a\s+las\s+\d|@\d"
    r")\b",
    re.IGNORECASE,
)
_CALENDAR_REMIND_INTENT_RE = re.compile(
    r"\b(recu[eé]rdame|recordatorio|recuerdo|av[ií]same|notif[ií]came|av[ií]so|alerta)\b",
    re.IGNORECASE,
)
_GMAIL_REPLY_INTENT_RE = re.compile(
    r"\b(responde|responder|contesta|contestar|replica|replicar|reply)\b"
    r".*\b(correo|correos|email|mail|mensaje)\b|"
    r"\b(correo|email|mail)\b.*\b(responde|responder|contesta|contestar)\b",
    re.IGNORECASE,
)
_GMAIL_ARCHIVE_INTENT_RE = re.compile(
    r"\b(archiva|archivar|limpia|limpiar|mueve|mover|saca|sacar)\b"
    r".*\b(correo|correos|email|spam|promoc|basura|newsletter|publicidad|bandeja)\b|"
    r"\b(spam|promociones|newsletters?|publicidad)\b.*\b(archiva|archivar|elimina|borra|limpia|limpiar)\b",
    re.IGNORECASE,
)
_GMAIL_INBOX_INTENT_RE = re.compile(
    r"\b(correo|correos|email|emails|gmail|bandeja|inbox)\b.*\b("
    r"no\s+le[ií]d|sin\s+leer|nuevos?|pendientes?|tengo|importantes?"
    r")\b|"
    r"\b(qu[eé]\s+tengo|revisa|revisar|mu[eé]strame|lista|listar)\b.*\b("
    r"correo|correos|email|gmail|bandeja"
    r")\b|"
    r"\b(correos?\s+sin\s+leer|bandeja\s+de\s+entrada)\b",
    re.IGNORECASE,
)
_GMAIL_ATTACH_INTENT_RE = re.compile(
    r"\b(adjunt|adjunta|adjunto|attachment)\b",
    re.IGNORECASE,
)
_GENERATE_DOC_INTENT_RE = re.compile(
    r"\b(genera|generar|crea|crear|elabora|elaborar|prepara|preparar|redacta|haz|hacer)\b",
    re.IGNORECASE,
)
_REPORT_DOC_INTENT_RE = re.compile(
    r"\b(informe|reporte|documento|docx|pdf|pptx|presentaci[oó]n|excel|xlsx|hoja)\b",
    re.IGNORECASE,
)
_GENERATED_DOC_TOOLS = frozenset({
    "generate_document",
    "pptx_generate",
    "generate_spreadsheet",
})
_PDF_RE = re.compile(r"\b(pdf|\.pdf)\b", re.IGNORECASE)
_FILENAME_RE = re.compile(
    r"(?:como|named?|llamad[oa]|archivo\s+)\s*[«\"']?([A-Za-z0-9_\-]+\.(?:txt|md|csv))[»\"']?",
    re.IGNORECASE,
)
_FILENAME_BARE_RE = re.compile(r"\b([A-Za-z0-9_\-]{3,80}\.(?:txt|md|csv))\b", re.IGNORECASE)
_CON_CONTENT_RE = re.compile(
    r"\bcon\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Respuestas que suenan a “todavía no terminé” (estilo Cursor: seguir hasta cerrar).
_INCOMPLETE_FINAL_RE = re.compile(
    r"(?i)\b("
    r"voy a (usar|listar|leer|analizar|crear|guardar|generar|buscar|enviar|escribir)|"
    r"ahora (voy|procedo|paso|empiezo)|"
    r"siguiente paso|"
    r"todav[ií]a no (pude|puedo|logr[eé])|"
    r"reintent[aá]|"
    r"en el pr[oó]ximo|"
    r"continuar[eé]|"
    r"dame un momento|"
    r"empezar[eé]|"
    r"proceder[eé]|"
    r"enseguida (lo |te )?(hago|analizo|genero)|"
    r"d[eé]jame (revisar|analizar|listar)"
    r")\b"
)

_CONTINUE_AFTER_TOOLS = (
    "Continúa la misión hasta terminarla del todo. "
    "Si falta trabajo, emite más tool_calls. "
    "Si ya terminaste, escribe la respuesta FINAL completa y útil al usuario "
    "(hallazgos, rutas, resumen extendido). "
    "Prohibido cortar con 'voy a…' o pedir que reintente."
)

_NUDGE_INCOMPLETE = (
    "Tu respuesta anterior quedó incompleta o aplazó el trabajo. "
    "NO digas qué vas a hacer: hazlo ahora con tools si hace falta, "
    "y luego entrega el resultado FINAL completo en español."
)


def _extract_download_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;:)")


def _desktop_path_for_url(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    base = path.rsplit("/", 1)[-1] if path else ""
    if not base or "." not in base:
        base = f"dot-download-{int(time.time())}.bin"
    safe = re.sub(r'[<>:"|?*\\]', "_", base)[:120]
    return f"~/Desktop/{safe}"


def _latest_user_utterance(text: str) -> str:
    """Evita que el historial (con URLs viejas) dispare force_download / bloquee write."""
    raw = (text or "").strip()
    marker = "Nuevo mensaje del usuario:"
    if marker in raw:
        return raw.split(marker)[-1].strip()
    return raw


def _wants_url_download(text: str) -> bool:
    t = _latest_user_utterance(text)
    if not _extract_download_url(t):
        return False
    if _DOWNLOAD_VERB_RE.search(t):
        return True
    lower = t.lower()
    return any(ext in lower for ext in (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".docx"))


def _wants_desktop_save(text: str) -> bool:
    t = _latest_user_utterance(text)
    if not _SAVE_INTENT_RE.search(t):
        return False
    return bool(_DESKTOP_RE.search(t) or _FILENAME_BARE_RE.search(t))


def _extract_desktop_filename(text: str) -> str:
    t = _latest_user_utterance(text)
    m = _FILENAME_RE.search(t)
    if m:
        return m.group(1).strip()
    m2 = _FILENAME_BARE_RE.search(t)
    if m2:
        return m2.group(1).strip()
    return f"dot-nota-{int(time.time())}.txt"


def _extract_inline_content(text: str) -> str | None:
    """'crea X en Escritorio con hola' → 'hola'."""
    t = _latest_user_utterance(text)
    # Evitar capturar toda la misión de búsqueda como "contenido"
    if _SEARCH_INTENT_RE.search(t):
        return None
    m = _CON_CONTENT_RE.search(t)
    if not m:
        return None
    content = m.group(1).strip().strip("«»\"'")
    if len(content) < 1 or len(content) > 4000:
        return None
    if re.search(r"\b(escritorio|desktop|archivo)\b", content, re.IGNORECASE):
        return None
    return content


def _clean_summary_for_file(text: str) -> str:
    raw = strip_tool_calls_json(text or "") or (text or "")
    raw = re.sub(
        r"\{[\s\S]*\"action\"\s*:\s*\"(?:local_tool|gmail_send|create_document)\"[\s\S]*\}",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    # Quitar frases de "voy a guardar" sin sustancia
    lines = [
        ln
        for ln in raw.splitlines()
        if not re.search(
            r"voy a (usar|guardar|crear)|ejecut[eé] writeFile|tool_calls",
            ln,
            re.IGNORECASE,
        )
    ]
    cleaned = "\n".join(lines).strip()
    return cleaned


def _wrote_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {
            "writeFile",
            "download_url_to_desktop",
            "generate_document",
            "generate_spreadsheet",
            "pptx_generate",
        }
        for t in tool_trace
    )


def _searched_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(t.get("ok") and str(t.get("tool") or "") == "web_search" for t in tool_trace)


def _read_doc_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {
            "read_document",
            "read_spreadsheet",
            "analyze_cv",
            "readFile",
            "parseDocument",
            "gmail_read_message",
        }
        for t in tool_trace
    )


def _wa_sent_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {"send_whatsapp_message", "notify_whatsapp_owner", "send_whatsapp_document"}
        for t in tool_trace
    )


def _generated_doc_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok") and str(t.get("tool") or "") in _GENERATED_DOC_TOOLS
        for t in tool_trace
    )


def _wa_doc_sent_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok") and str(t.get("tool") or "") == "send_whatsapp_document"
        for t in tool_trace
    )


def _wants_generate_and_wa_doc(text: str) -> bool:
    t = _latest_user_utterance(text)
    return bool(
        _GENERATE_DOC_INTENT_RE.search(t)
        and _REPORT_DOC_INTENT_RE.search(t)
        and _WA_NOTIFY_INTENT_RE.search(t)
    )


def _wants_read_and_wa(text: str) -> bool:
    t = _latest_user_utterance(text)
    return bool(_READ_DOC_INTENT_RE.search(t) and _WA_NOTIFY_INTENT_RE.search(t))


def _wants_smart_calendar(text: str) -> bool:
    """Agendar evento + pedir aviso (WA o recordatorio)."""
    t = _latest_user_utterance(text)
    has_create = bool(_CALENDAR_CREATE_INTENT_RE.search(t))
    has_notify = bool(
        _WA_NOTIFY_INTENT_RE.search(t) or _CALENDAR_REMIND_INTENT_RE.search(t)
    )
    return has_create and has_notify


def _wants_gmail_reply(text: str) -> bool:
    return bool(_GMAIL_REPLY_INTENT_RE.search(_latest_user_utterance(text)))


def _wants_gmail_bulk_archive(text: str) -> bool:
    return bool(_GMAIL_ARCHIVE_INTENT_RE.search(_latest_user_utterance(text)))


def _wants_gmail_inbox(text: str) -> bool:
    return bool(_GMAIL_INBOX_INTENT_RE.search(_latest_user_utterance(text)))


def _gmail_listed_or_searched_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {"gmail_list_unread", "gmail_search", "gmail_summarize_unread"}
        for t in tool_trace
    )


def _gmail_read_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok") and str(t.get("tool") or "") == "gmail_read_message"
        for t in tool_trace
    )


def _gmail_replied_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "") in {"gmail_auto_reply", "gmail_send"}
        for t in tool_trace
    )


def _gmail_archived_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok") and str(t.get("tool") or "") == "gmail_archive"
        for t in tool_trace
    )


def _gmail_tool_used(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        str(t.get("tool") or "").startswith("gmail_") for t in tool_trace
    )


def _calendar_event_created_ok(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok") and str(t.get("tool") or "") == "calendar_create_event"
        for t in tool_trace
    )


def _calendar_notify_done(tool_trace: list[dict[str, Any]]) -> bool:
    return any(
        t.get("ok")
        and str(t.get("tool") or "") in {"notify_whatsapp_owner", "schedule_reminder"}
        for t in tool_trace
    )


def _extract_calendar_event_from_trace(
    tool_trace: list[dict[str, Any]],
) -> dict[str, str] | None:
    for t in reversed(tool_trace):
        if not t.get("ok") or str(t.get("tool") or "") != "calendar_create_event":
            continue
        preview = str(t.get("preview") or t.get("output") or "").strip()
        m = re.search(
            r"Evento creado:\s*[«\"']?(.+?)[»\"']?\s+el\s+(.+?)\s+\(ISO:",
            preview,
            re.IGNORECASE,
        )
        if m:
            return {
                "summary": m.group(1).strip(),
                "when_human": m.group(2).strip(),
                "start_iso": "",
                "preview": preview,
            }
        m2 = re.search(r"Evento creado:\s*(.+?)\s*\(([^)]+)\)", preview, re.IGNORECASE)
        if m2:
            return {
                "summary": m2.group(1).strip().strip("«»\"'"),
                "when_human": m2.group(2).strip(),
                "start_iso": m2.group(2).strip(),
                "preview": preview,
            }
        return {"summary": "Evento", "when_human": "", "start_iso": "", "preview": preview}
    return None


def _calendar_confirmation_message(
    event: dict[str, str], *, for_reminder: bool = False
) -> str:
    title = event.get("summary") or "Evento"
    when = event.get("when_human") or event.get("start_iso") or "la hora acordada"
    if for_reminder:
        return f"Recordatorio: {title} — {when}"
    return f"✅ Reunión agendada: «{title}» el {when}."


def _wants_desktop_pdf_read(text: str) -> bool:
    t = _latest_user_utterance(text)
    if not _DESKTOP_RE.search(t):
        return False
    return bool(_PDF_RE.search(t) or _READ_DOC_INTENT_RE.search(t))


def _extract_read_preview(tool_trace: list[dict[str, Any]]) -> str:
    for t in reversed(tool_trace):
        if not t.get("ok"):
            continue
        if str(t.get("tool") or "") not in {
            "read_document",
            "read_spreadsheet",
            "analyze_cv",
            "readFile",
            "parseDocument",
            "gmail_read_message",
        }:
            continue
        preview = str(t.get("preview") or t.get("output") or "").strip()
        if preview:
            return preview[:4000]
    return ""


def _summary_for_wa(final_text: str, tool_trace: list[dict[str, Any]]) -> str:
    spoken = strip_tool_calls_json(final_text or "") or (final_text or "")
    spoken = spoken.strip()
    if len(spoken) >= 40:
        return spoken[:1500]
    preview = _extract_read_preview(tool_trace)
    if preview:
        return preview[:1500]
    return spoken or "Resumen del documento solicitado."


def _looks_incomplete_final(
    text: str,
    *,
    had_tools: bool,
    step: int,
    steps_cap: int,
) -> bool:
    """True si el modelo cortó a medias y aún podemos empujarlo a seguir."""
    if step >= steps_cap:
        return False
    t = (text or "").strip()
    if not t:
        return bool(had_tools)
    if _INCOMPLETE_FINAL_RE.search(t):
        return True
    # Tras tools: un stub corto no es un entregable (salvo confirmaciones / negativas claras).
    if had_tools and len(t) < 120:
        lower = t.lower()
        if any(
            m in lower
            for m in (
                "listo",
                "guardé",
                "guarde",
                "enviado",
                "descargué",
                "descargue",
                "✅",
                "creado",
                "documento",
                "no puedo",
                "no puedo usar",
                "no disponible",
                "no tengo",
                "error",
                "falló",
                "fallo",
            )
        ):
            return False
        return True
    return False


def _ensure_desktop_save(
    *,
    uid: str,
    user_text: str,
    final_text: str,
    reg: ToolRegistry,
    tool_names: list[str],
    tool_trace: list[dict[str, Any]],
    channel: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Si el usuario pidió guardar en Escritorio y no hubo writeFile OK, forzarlo.

    Igual que force_download: el modelo a menudo resume y afirma haber guardado
    sin emitir la tool. truth_check entonces bloquea con un mensaje confuso.
    """
    if "writeFile" not in tool_names:
        log.info("agent_force_write_skip uid=%s reason=no_writeFile_tool", uid[:8] if uid else "?")
        return final_text, tool_trace
    if not _wants_desktop_save(user_text):
        log.info(
            "agent_force_write_skip uid=%s reason=no_desktop_save_intent text=%s",
            uid[:8] if uid else "?",
            (_latest_user_utterance(user_text) or "")[:120],
        )
        return final_text, tool_trace
    if _wrote_ok(tool_trace):
        return final_text, tool_trace
    # Descargas URL las cubre force_download; no inventar .pdf con writeFile
    # Solo mirar el mensaje nuevo (no historial con PDFs previos).
    if _wants_url_download(user_text):
        log.info(
            "agent_force_write_skip uid=%s reason=url_download_intent text=%s",
            uid[:8] if uid else "?",
            (_latest_user_utterance(user_text) or "")[:120],
        )
        return final_text, tool_trace

    intent = _latest_user_utterance(user_text)
    log.info(
        "agent_force_write_attempt uid=%s channel=%s intent=%s",
        uid[:8] if uid else "?",
        channel,
        intent[:120],
    )
    filename = _extract_desktop_filename(intent)
    path = f"~/Desktop/{filename}"
    content = _extract_inline_content(intent)
    if not content:
        content = _clean_summary_for_file(final_text)

    # Buscar+guardar: necesitamos texto real. Si el modelo ya buscó pero solo dijo
    # "listo", re-ejecutar web_search para armar el archivo (el trace no guarda output).
    search_output = ""
    wants_search = bool(_SEARCH_INTENT_RE.search(intent))
    content_weak = (
        not content
        or len(content.strip()) < 40
        or re.search(
            r"no (pude|hay|encontr)|ya lo guard|listo[,.]?\s*$|voy a ",
            content or "",
            re.IGNORECASE,
        )
    )
    if wants_search and content_weak and "web_search" in tool_names:
        q = re.sub(
            r"\b(guarda|guardar|crea|crear|escribe|en mi escritorio|como\s+\S+\.txt).*$",
            "",
            intent,
            flags=re.IGNORECASE,
        ).strip() or intent
        t0 = time.perf_counter()
        sres = reg.execute(uid, "web_search", {"query": q[:200]})
        ms = int((time.perf_counter() - t0) * 1000)
        tool_trace.append(
            {
                "tool": "web_search",
                "ok": sres.ok,
                "ms": sres.duration_ms or ms,
                "step": 0,
                "channel": f"{channel}:forced",
            }
        )
        if sres.ok:
            search_output = sres.output or ""
        log.info(
            "agent_force_web_search uid=%s ok=%s ms=%s",
            uid[:8] if uid else "?",
            sres.ok,
            ms,
        )

    if search_output and (
        not content
        or len(content) < 40
        or re.search(r"no (pude|hay|encontr)|ya lo guard|listo", content, re.IGNORECASE)
    ):
        content = search_output
    if not content or len(content.strip()) < 1:
        return (
            "No pude armar el contenido para guardar. "
            "Prueba: «crea nota.txt en Escritorio con hola».",
            tool_trace,
        )

    t0 = time.perf_counter()
    result = reg.execute(uid, "writeFile", {"path": path, "content": content, "confirm": True})
    ms = int((time.perf_counter() - t0) * 1000)
    tool_trace.append(
        {
            "tool": "writeFile",
            "ok": result.ok,
            "ms": result.duration_ms or ms,
            "step": 0,
            "channel": f"{channel}:forced",
        }
    )
    log.info(
        "agent_force_writeFile uid=%s ok=%s ms=%s path=%s",
        uid[:8] if uid else "?",
        result.ok,
        ms,
        path,
    )
    if result.ok:
        abs_path = (result.output or "").replace("Archivo guardado en: ", "").strip() or path
        preview = content if len(content) <= 600 else content[:600] + "…"
        msg = (
            f"{preview}\n\n"
            f"✅ Archivo guardado en tu Escritorio ({filename}).\n"
            f"Ruta: {abs_path}"
        )
        return msg, tool_trace
    err = result.error or "error"
    if "bridge_unreachable" in err or "bridge_secret" in err:
        return (
            "Intenté guardar el archivo pero el puente local no respondió. "
            "Dejá la app DOT abierta en el PC e intentá de nuevo.",
            tool_trace,
        )
    return (
        f"Intenté guardar {filename} en tu Escritorio pero falló ({err}).",
        tool_trace,
    )


def _maybe_force_download(
    *,
    uid: str,
    text: str,
    reg: ToolRegistry,
    tool_names: list[str],
) -> tuple[list[dict[str, Any]], str] | None:
    """OpenClaw-style: intención clara de descarga → ejecutar sin esperar al modelo."""
    if "download_url_to_desktop" not in tool_names:
        return None
    if not _wants_url_download(text):
        return None
    url = _extract_download_url(text)
    if not url:
        return None

    dest = _desktop_path_for_url(url)
    t0 = time.perf_counter()
    result = reg.execute(uid, "download_url_to_desktop", {"url": url, "path": dest})
    ms = int((time.perf_counter() - t0) * 1000)
    trace = [
        {
            "tool": "download_url_to_desktop",
            "ok": result.ok,
            "ms": result.duration_ms or ms,
            "step": 0,
            "channel": "forced",
        }
    ]
    obs = format_observation(
        "download_url_to_desktop", result.ok, result.output, result.error
    )
    follow = (
        f"Resultado de descarga automática:\n{obs}\n\n"
        "Confirma al usuario en español claro (ruta/bytes si ok). "
        "NUNCA digas que no puedes descargar PDFs o binarios."
    )
    log.info(
        "agent_force_download uid=%s ok=%s ms=%s",
        uid[:8] if uid else "?",
        result.ok,
        ms,
    )
    return trace, follow


def _maybe_force_desktop_pdf_read(
    *,
    uid: str,
    text: str,
    reg: ToolRegistry,
    tool_names: list[str],
) -> tuple[list[dict[str, Any]], str] | None:
    """Si piden PDF del Escritorio sin ruta, buscar antes de que el modelo alucine."""
    if "file_search" not in tool_names:
        return None
    if not _wants_desktop_pdf_read(text):
        return None

    t0 = time.perf_counter()
    result = reg.execute(
        uid,
        "file_search",
        {"query": "pdf", "searchRoot": "desktop"},
    )
    ms = int((time.perf_counter() - t0) * 1000)
    trace = [
        {
            "tool": "file_search",
            "ok": result.ok,
            "ms": result.duration_ms or ms,
            "step": 0,
            "channel": "forced",
            "preview": (result.output or result.error or "")[:2500],
        }
    ]
    obs = format_observation("file_search", result.ok, result.output, result.error)
    follow = (
        f"Búsqueda automática de PDF en Escritorio:\n{obs}\n\n"
        "Continúa la misión: lee el PDF encontrado con read_document, "
        "resume en el formato pedido y envía con notify_whatsapp_owner si lo pidió. "
        "No inventes rutas ni contenido."
    )
    log.info(
        "agent_force_desktop_pdf uid=%s ok=%s ms=%s",
        uid[:8] if uid else "?",
        result.ok,
        ms,
    )
    return trace, follow


def _ensure_whatsapp_notify(
    *,
    uid: str,
    user_text: str,
    final_text: str,
    reg: ToolRegistry,
    tool_names: list[str],
    tool_trace: list[dict[str, Any]],
    channel: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Si leyó documento y pidió WA pero no notificó, forzar notify_whatsapp_owner."""
    if "notify_whatsapp_owner" not in tool_names:
        return final_text, tool_trace
    if _wants_generate_and_wa_doc(user_text):
        return final_text, tool_trace
    if not _WA_NOTIFY_INTENT_RE.search(_latest_user_utterance(user_text)):
        return final_text, tool_trace
    if _wa_sent_ok(tool_trace):
        return final_text, tool_trace
    if not _read_doc_ok(tool_trace):
        return final_text, tool_trace

    message = _summary_for_wa(final_text, tool_trace)
    if len(message.strip()) < 10:
        return final_text, tool_trace

    log.info(
        "agent_force_wa_notify uid=%s channel=%s msg_len=%s",
        uid[:8] if uid else "?",
        channel,
        len(message),
    )
    t0 = time.perf_counter()
    result = reg.execute(uid, "notify_whatsapp_owner", {"message": message, "confirm": True})
    ms = int((time.perf_counter() - t0) * 1000)
    tool_trace.append(
        {
            "tool": "notify_whatsapp_owner",
            "ok": result.ok,
            "ms": result.duration_ms or ms,
            "step": 0,
            "channel": f"{channel}:forced",
            "preview": (result.output or result.error or "")[:500],
        }
    )
    if result.ok:
        spoken = strip_tool_calls_json(final_text or "") or (final_text or "")
        msg = (
            f"{spoken.rstrip()}\n\n"
            f"✅ Te envié el resumen por WhatsApp al número vinculado."
        ).strip()
        return msg, tool_trace
    err = result.error or "error desconocido"
    if "no vinculado" in err.lower() or "not linked" in err.lower():
        return (
            "Leí el documento y preparé el resumen, pero WhatsApp no está vinculado. "
            "Vinculá tu número en Configuración → WhatsApp e intentá de nuevo.",
            tool_trace,
        )
    return (
        f"Leí el documento pero no pude enviarte el WhatsApp: {err}",
        tool_trace,
    )


def _ensure_calendar_notify(
    *,
    uid: str,
    user_text: str,
    final_text: str,
    reg: ToolRegistry,
    tool_names: list[str],
    tool_trace: list[dict[str, Any]],
    channel: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Si creó evento y pidió aviso pero no notificó, forzar WA o recordatorio."""
    if not _wants_smart_calendar(user_text):
        return final_text, tool_trace
    if not _calendar_event_created_ok(tool_trace):
        return final_text, tool_trace
    if _calendar_notify_done(tool_trace):
        return final_text, tool_trace

    event = _extract_calendar_event_from_trace(tool_trace)
    if not event:
        return final_text, tool_trace

    utterance = _latest_user_utterance(user_text)
    wants_wa = bool(_WA_NOTIFY_INTENT_RE.search(utterance))
    explicit_reminder = bool(
        re.search(r"\b(recu[eé]rdame|recordatorio)\b", utterance, re.IGNORECASE)
    )
    spoken = strip_tool_calls_json(final_text or "") or (final_text or "")
    extras: list[str] = []

    if wants_wa and "notify_whatsapp_owner" in tool_names:
        message = _calendar_confirmation_message(event)
        log.info(
            "agent_force_calendar_wa uid=%s channel=%s",
            uid[:8] if uid else "?",
            channel,
        )
        t0 = time.perf_counter()
        result = reg.execute(
            uid, "notify_whatsapp_owner", {"message": message, "confirm": True}
        )
        ms = int((time.perf_counter() - t0) * 1000)
        tool_trace.append(
            {
                "tool": "notify_whatsapp_owner",
                "ok": result.ok,
                "ms": result.duration_ms or ms,
                "step": 0,
                "channel": f"{channel}:calendar_forced",
                "preview": (result.output or result.error or "")[:500],
            }
        )
        if result.ok:
            extras.append("✅ Te envié la confirmación por WhatsApp al número vinculado.")
        else:
            err = result.error or "error desconocido"
            extras.append(f"No pude enviarte el WhatsApp: {err}")

    if explicit_reminder and "schedule_reminder" in tool_names:
        when = event.get("start_iso") or event.get("when_human") or utterance
        remind_msg = _calendar_confirmation_message(event, for_reminder=True)
        channel_rem = "whatsapp" if wants_wa else "notify"
        log.info(
            "agent_force_calendar_reminder uid=%s channel=%s",
            uid[:8] if uid else "?",
            channel,
        )
        t0 = time.perf_counter()
        result = reg.execute(
            uid,
            "schedule_reminder",
            {
                "message": remind_msg,
                "when": when,
                "channel": channel_rem,
            },
        )
        ms = int((time.perf_counter() - t0) * 1000)
        tool_trace.append(
            {
                "tool": "schedule_reminder",
                "ok": result.ok,
                "ms": result.duration_ms or ms,
                "step": 0,
                "channel": f"{channel}:calendar_forced",
                "preview": (result.output or result.error or "")[:500],
            }
        )
        if result.ok:
            extras.append(result.output or "Recordatorio programado.")
        elif not wants_wa:
            extras.append(f"No pude programar el recordatorio: {result.error or 'error'}")

    if not extras and not wants_wa and not explicit_reminder:
        return final_text, tool_trace

    if not extras and wants_wa and "notify_whatsapp_owner" not in tool_names:
        return final_text, tool_trace

    msg = spoken.rstrip()
    if extras:
        msg = f"{msg}\n\n" + "\n".join(extras) if msg else "\n".join(extras)
    return msg.strip(), tool_trace


def _extract_generated_doc_path(tool_trace: list[dict[str, Any]]) -> str | None:
    from app.application.agent.grounding import extract_saved_path_from_trace

    return extract_saved_path_from_trace(tool_trace)


def _ensure_whatsapp_document_send(
    *,
    uid: str,
    user_text: str,
    final_text: str,
    reg: ToolRegistry,
    tool_names: list[str],
    tool_trace: list[dict[str, Any]],
    channel: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Si generó documento y pidió WA como archivo, forzar send_whatsapp_document."""
    if "send_whatsapp_document" not in tool_names:
        return final_text, tool_trace
    if not _wants_generate_and_wa_doc(user_text):
        return final_text, tool_trace
    if _wa_doc_sent_ok(tool_trace):
        return final_text, tool_trace
    if not _generated_doc_ok(tool_trace):
        return final_text, tool_trace

    raw_path = _extract_generated_doc_path(tool_trace)
    if not raw_path:
        return final_text, tool_trace

    from app.services.document_output_service import resolve_document_path_for_send

    resolved = resolve_document_path_for_send(raw_path)
    if resolved is None:
        return final_text, tool_trace

    abs_path = str(resolved)
    log.info(
        "agent_force_wa_document uid=%s channel=%s path=%s",
        uid[:8] if uid else "?",
        channel,
        abs_path,
    )
    t0 = time.perf_counter()
    result = reg.execute(
        uid,
        "send_whatsapp_document",
        {"path": abs_path, "confirm": True},
    )
    ms = int((time.perf_counter() - t0) * 1000)
    tool_trace.append(
        {
            "tool": "send_whatsapp_document",
            "ok": result.ok,
            "ms": result.duration_ms or ms,
            "step": 0,
            "channel": f"{channel}:forced",
            "preview": (result.output or result.error or "")[:500],
        }
    )
    if result.ok:
        spoken = strip_tool_calls_json(final_text or "") or (final_text or "")
        msg = (
            f"{spoken.rstrip()}\n\n"
            f"{result.output or '✅ Te envié el documento por WhatsApp.'}"
        ).strip()
        return msg, tool_trace

    err = result.error or "error desconocido"
    if "no vinculado" in err.lower() or "not linked" in err.lower():
        return (
            "Generé el informe en tu Escritorio, pero WhatsApp no está vinculado. "
            f"Ruta: {abs_path}\n"
            "Vinculá tu número en Configuración → WhatsApp e intentá de nuevo.",
            tool_trace,
        )
    return (
        f"Generé el documento en {abs_path}, pero no pude enviarlo por WhatsApp: {err}",
        tool_trace,
    )


def _default_model_fn(user_text: str, system_prompt: str) -> Any:
    from app.services.provider_router import route_chat_detailed

    return route_chat_detailed(
        user_text,
        "deepseek",
        system_prompt,
        include_document_action_prompt=False,
    )


# ─── Patrones de alucinación ───

_FABRICATION_PATTERNS = [
    # Archivos/carpetas inventados
    re.compile(
        r"(?:archivo|archivos|file|files|documento|documentos|carpeta|carpetas)\s+"
        r"(?:que|en|con|llamado|llamada|como|titulado)[\s\S]{0,200}"
        r"(?:\.pdf|\.txt|\.xlsx|\.docx|\.py|\.js|\.csv|\.json|\.html|\.md)",
        re.IGNORECASE,
    ),
    # "Encontré / veo / hallé" sin haber ejecutado tools
    re.compile(
        r"(?:encontr[éeó]|halle|hall[éeó]|veo|observo|detect[éeó]|localic[éeó])\s+"
        r"(?:que|un|una|varios|varias|los|las|el|la)\s",
        re.IGNORECASE,
    ),
    # Precios inventados
    re.compile(
        r"(?:precio|precios|cuesta|cuestan|vale|valen|monto|total)\s+"
        r"(?:aproximadamente|alrededor|unos|unas|de|es)?\s*\$?\s?\d[\d,.]*",
        re.IGNORECASE,
    ),
    # "Tienes / hay / existen" + archivos
    re.compile(
        r"(?:tienes|tiene|hay|existen|cuentas\s+con)\s+(?:un|una|varios|varias|los|las|el|la)\s+"
        r"(?:archivo|archivos|carpeta|carpetas|documento|documentos)",
        re.IGNORECASE,
    ),
    # Datos climáticos inventados
    re.compile(
        r"(?:clima|temperatura|pron[oó]stico|humedad|viento)\s+"
        r"(?:actual|hoy|ahora|en\s+\w+)\s+(?:es|est[aá]|de|hay)",
        re.IGNORECASE,
    ),
    # "Aquí está tu X" sin haber generado nada
    re.compile(
        r"(?:aqu[ií]\s+(?:est[aá]|tienes)|te\s+(?:muestro|presento|comparto|env[ií]o))\s+(?:tu|el|la|los|las)\s",
        re.IGNORECASE,
    ),
]

def _detect_fabricated_data(content: str, tool_trace: list) -> bool:
    """Detecta si el modelo está inventando datos sin haber ejecutado herramientas."""
    if not content:
        return False
    if tool_trace:
        return False
    for pattern in _FABRICATION_PATTERNS:
        if pattern.search(content):
            return True
    return False


def run_agent(
    *,
    uid: str,
    channel: str,
    text: str,
    system_prompt: str,
    history: str = "",
    registry: ToolRegistry | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    local_tools: bool = False,
    electron_proxy: bool = False,
    model_fn: ModelFn | None = None,
    on_step_complete: Callable[[int, str, str, bool], None] | None = None,
    on_complete: Callable[[str, list[dict[str, Any]]], None] | None = None,
    cancel_event: Any | None = None,
    # FASE 2.2: plan generado por reasoning.py para ejecución con planner.py
    prebuilt_plan: Any | None = None,
) -> AgentResult:
    """Orquestador único. Con registry vacío / tools=[] → un turno modelo = hoy.

    FASE 2.2: si se pasa ``prebuilt_plan`` (PlanArtifact con >=2 steps) y
    PLANNER_ENABLED=True, el flujo deriva a planner.py en lugar del loop genérico.

    Callbacks (opcionales, para streaming en tiempo real):
    - on_step_complete(step, tool_name, output_preview, ok): tras cada tool
    - on_complete(final_text, artifacts): al terminar con éxito

    cancel_event: threading.Event opcional; si está set, el loop corta entre pasos
    (steer/interrupt de AgentRunQueue).

    Returns:
        AgentResult con final_text + tool_trace + artifacts (sin secretos).
    """
    if not (text or "").strip():
        return AgentResult(final_text="", steps=0, artifacts=[])

    from app.services.destructive_confirm_service import destructive_confirm_scope

    with destructive_confirm_scope(channel):
        return _run_agent_loop(
            uid=uid,
            channel=channel,
            text=text,
            system_prompt=system_prompt,
            history=history,
            registry=registry,
            max_steps=max_steps,
            local_tools=local_tools,
            electron_proxy=electron_proxy,
            model_fn=model_fn,
            on_step_complete=on_step_complete,
            on_complete=on_complete,
            cancel_event=cancel_event,
            prebuilt_plan=prebuilt_plan,
        )


def _run_agent_loop(
    *,
    uid: str,
    channel: str,
    text: str,
    system_prompt: str,
    history: str = "",
    registry: ToolRegistry | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    local_tools: bool = False,
    electron_proxy: bool = False,
    model_fn: ModelFn | None = None,
    on_step_complete: Callable[[int, str, str, bool], None] | None = None,
    on_complete: Callable[[str, list[dict[str, Any]]], None] | None = None,
    cancel_event: Any | None = None,
    prebuilt_plan: Any | None = None,
) -> AgentResult:
    """Cuerpo del agent loop (envuelto por destructive_confirm_scope en run_agent)."""
    steps_cap = _resolve_steps_cap(channel, max_steps)
    reg = registry if registry is not None else ToolRegistry()
    call_model = model_fn or _default_model_fn

    # FASE 2.2: si hay plan pre-generado por reasoning con >=2 steps, derivar a planner.py
    if settings.planner_enabled and prebuilt_plan is not None:
        steps = getattr(prebuilt_plan, "steps", None)
        if steps and isinstance(steps, list) and len(steps) >= 2:
            from app.application.agent.planner import Plan, PlanStep, run_planner
            from app.application.agent.reasoning import convert_plan_artifact_to_planner_plan

            goal, plan_steps = convert_plan_artifact_to_planner_plan(prebuilt_plan)
            planner_plan = Plan(goal=goal, steps=plan_steps)
            log.info(
                "FASE 2.2: derivando a planner uid=%s goal=%s steps=%d",
                uid[:8] if uid else "?",
                goal[:80],
                len(plan_steps),
            )
            executed_plan, summary = run_planner(uid, goal, reg, prebuilt_plan=planner_plan)
            if on_complete:
                try:
                    on_complete(summary, [])
                except Exception:
                    pass
            return AgentResult(
                final_text=summary,
                tool_trace=[],
                steps=len(plan_steps),
                model_usage=getattr(prebuilt_plan, "usage", None),
                model_name=getattr(prebuilt_plan, "model", None),
                artifacts=[],
            )

    tool_names = [s.name for s in reg.list_specs()]
    sys_prompt = (system_prompt or "").rstrip() + tools_system_hint(reg)

    # ─── Instrucción por paso ───
    _step_0_instruction = (
        "\n\n─── PRIMER PASO ───\n"
        "Analiza lo que el usuario pide. ¿Necesitas datos que no tienes?\n"
        "Si SÍ → ejecuta las herramientas necesarias AHORA.\n"
        "Si NO → responde directamente.\n"
        "NUNCA inventes. Si no puedes obtener los datos, dilo.\n"
        "Nota: el planificador multi-paso de DOT está ACTIVO — "
        "si la tarea es compleja, el planificador puede orquestar los pasos automáticamente."
    )
    sys_prompt = sys_prompt + _step_0_instruction

    user_block = (text or "").strip()
    if (history or "").strip():
        user_block = f"{history.strip()}\n\nNuevo mensaje del usuario:\n{user_block}"

    working_text = user_block

    # M2S4-A: Si el agent loop vive en Electron, solo actuar como proxy DeepSeek
    # (un turno, sin ejecutar tools). El loop multi-turno se ejecuta en agent-loop.cjs.
    # M2S4-A: proxy solo cuando Electron ejecuta agent-loop.cjs (electron_proxy=True).
    if FLAG_USE_LOCAL_AGENT and local_tools and electron_proxy:
        t0 = time.perf_counter()
        try:
            ai_result = call_model(working_text, sys_prompt)
        except Exception as e:
            log.exception(
                "agent_proxy_error uid=%s channel=%s",
                uid[:8] if uid else "?",
                channel,
            )
            from app.services.error_messages import translate_error
            return AgentResult(
                final_text=translate_error(str(e)),
                tool_trace=[],
                steps=0,
                model_usage=None,
                model_name=None,
                artifacts=[],
            )
        content = (getattr(ai_result, "content", None) or str(ai_result) or "").strip()
        model_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "agent_proxy_mode uid=%s channel=%s ms=%s (FLAG_USE_LOCAL_AGENT=True, sin tools)",
            uid[:8] if uid else "?",
            channel,
            model_ms,
        )
        return AgentResult(
            final_text=content,
            tool_trace=[],
            steps=1,
            model_usage=getattr(ai_result, "usage", None),
            model_name=getattr(ai_result, "model", None),
            artifacts=[],
        )

    tool_trace: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    last_usage: dict[str, Any] | None = None
    last_model: str | None = None
    steps_used = 0

    def _cancelled() -> bool:
        return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())

    if _cancelled():
        return AgentResult(
            final_text="(Tarea cancelada: llegó un mensaje más reciente.)",
            tool_trace=[],
            steps=0,
            model_usage=None,
            model_name=None,
            artifacts=[],
        )
    incomplete_nudges = 0

    forced = _maybe_force_download(
        uid=uid, text=text, reg=reg, tool_names=tool_names
    )
    if forced:
        forced_trace, follow = forced
        tool_trace.extend(forced_trace)
        working_text = f"{user_block}\n\n{follow}"
    else:
        forced_pdf = _maybe_force_desktop_pdf_read(
            uid=uid, text=text, reg=reg, tool_names=tool_names
        )
        if forced_pdf:
            forced_trace, follow = forced_pdf
            tool_trace.extend(forced_trace)
            working_text = f"{user_block}\n\n{follow}"

    for step in range(1, steps_cap + 1):
        if _cancelled():
            partial = (
                "Detuve esa tarea porque llegó un mensaje más reciente. "
                "Dime cómo quieres continuar."
            )
            if on_complete:
                try:
                    on_complete(partial, all_artifacts)
                except Exception:
                    pass
            return AgentResult(
                final_text=partial,
                tool_trace=tool_trace,
                steps=steps_used,
                model_usage=last_usage,
                model_name=last_model,
                artifacts=all_artifacts,
            )
        steps_used = step
        t0 = time.perf_counter()
        # ─── Instrucción dinámica por paso ───
        _step_hint = (
            f"\n\n─── PASO {step} ───\n"
            "¿Ya tienes TODA la información que necesitas?\n"
            "Si SÍ → responde al usuario con los datos REALES que obtuviste.\n"
            "Si NO → ejecuta MÁS herramientas para conseguir lo que falta.\n"
            "NUNCA inventes datos. Solo reporta lo que REALMENTE obtuviste de las herramientas.\n"
            "El planificador multi-paso está ACTIVO — no necesitas prefijo 'plan:'."
        )
        call_prompt = sys_prompt + _step_hint
        try:
            ai_result = call_model(working_text, call_prompt)
        except Exception as e:
            log.exception(
                "agent_model_error uid=%s channel=%s step=%s",
                uid[:8] if uid else "?",
                channel,
                step,
            )
            from app.services.error_messages import translate_error
            return AgentResult(
                final_text=translate_error(str(e)),
                tool_trace=tool_trace,
                steps=steps_used,
                model_usage=last_usage,
                model_name=last_model,
                artifacts=all_artifacts,
            )

        content = (getattr(ai_result, "content", None) or str(ai_result) or "").strip()
        usage = getattr(ai_result, "usage", None)
        if isinstance(usage, dict):
            last_usage = usage
        model_name = getattr(ai_result, "model", None)
        if model_name:
            last_model = str(model_name)

        model_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "agent_model_turn uid=%s channel=%s step=%s ms=%s tools_available=%s",
            uid[:8] if uid else "?",
            channel,
            step,
            model_ms,
            len(tool_names),
        )

        if not tool_names:
            if on_complete:
                try:
                    on_complete(content, all_artifacts)
                except Exception:
                    pass
            return AgentResult(
                final_text=content,
                tool_trace=tool_trace,
                steps=steps_used,
                model_usage=last_usage,
                model_name=last_model,
                artifacts=all_artifacts,
            )

        calls = parse_tool_calls(content)
        
        # ─── Anti-alucinación ───
        if not calls and _detect_fabricated_data(content, tool_trace):
            nudge = (
                "⚠️ DETECTÉ DATOS INVENTADOS. No ejecutaste ninguna herramienta, "
                "pero tu respuesta contiene información que solo podrías obtener "
                "con herramientas (archivos, precios, hechos concretos).\n\n"
                "SI INVENTASTE ESOS DATOS, CORRIGE TU RESPUESTA AHORA y di "
                "'No tengo acceso a esa información. ¿Quieres que use [herramienta]?'\n\n"
                "SI LOS OBTUVISTE DE UNA FUENTE REAL (no de herramientas), "
                "explica DE DÓNDE salieron.\n\n"
                "Vuelve a responder siendo COMPLETAMENTE HONESTO."
            )
            working_text = f"{working_text}\n\n{nudge}"
            incomplete_nudges += 1
            continue
        
        if not calls:
            spoken = strip_tool_calls_json(content) or content
            if tool_trace and any(
                t.get("tool") == "download_url_to_desktop" and t.get("ok")
                for t in tool_trace
            ):
                lower = spoken.lower()
                if "no tengo capacidad" in lower or "no puedo descargar" in lower:
                    spoken = (
                        "Listo: descargué el archivo a tu Escritorio. "
                        "Ábrelo desde ahí (el PDF real, no un texto)."
                    )

            # Como Cursor: si cortó a medias, empujar a seguir dentro del presupuesto.
            if incomplete_nudges < MAX_INCOMPLETE_NUDGES and _looks_incomplete_final(
                spoken,
                had_tools=bool(tool_trace),
                step=step,
                steps_cap=steps_cap,
            ):
                incomplete_nudges += 1
                log.info(
                    "agent_incomplete_nudge uid=%s channel=%s step=%s nudge=%s",
                    uid[:8] if uid else "?",
                    channel,
                    step,
                    incomplete_nudges,
                )
                working_text = (
                    f"{user_block}\n\n"
                    f"(Paso {step} del agente — respuesta incompleta)\n"
                    f"Borrador parcial:\n{spoken}\n\n"
                    f"{_NUDGE_INCOMPLETE}"
                )
                continue

            # Informe con rutas inventadas / DOCX mentiroso → reescribir anclado a tools
            if incomplete_nudges < MAX_INCOMPLETE_NUDGES and looks_ungrounded_final(
                user_text=text,
                final_text=spoken,
                tool_trace=tool_trace,
            ):
                incomplete_nudges += 1
                nudge = grounding_nudge_message(
                    user_text=text,
                    final_text=spoken,
                    tool_trace=tool_trace,
                )
                log.info(
                    "agent_grounding_nudge uid=%s channel=%s step=%s nudge=%s",
                    uid[:8] if uid else "?",
                    channel,
                    step,
                    incomplete_nudges,
                )
                working_text = (
                    f"{user_block}\n\n"
                    f"(Paso {step} del agente — borrador sin anclar)\n"
                    f"Borrador rechazado:\n{spoken[:6000]}\n\n"
                    f"{nudge}"
                )
                continue

            # FASE 2.2: nudge _wants_read_and_wa reemplazado por planificador multi-paso
            # (comentado — el planificador cubre leer+enviar WA como pasos separados)
            # if (
            #     incomplete_nudges < MAX_INCOMPLETE_NUDGES
            #     and _wants_read_and_wa(text)
            #     and not _wants_generate_and_wa_doc(text)
            #     and _read_doc_ok(tool_trace)
            #     and not _wa_sent_ok(tool_trace)
            # ):
            #     ...

            # Generó documento pero falta envío del archivo por WhatsApp
            if (
                incomplete_nudges < MAX_INCOMPLETE_NUDGES
                and _wants_generate_and_wa_doc(text)
                and _generated_doc_ok(tool_trace)
                and not _wa_doc_sent_ok(tool_trace)
            ):
                incomplete_nudges += 1
                doc_path = _extract_generated_doc_path(tool_trace) or "(ruta del generate_document)"
                log.info(
                    "agent_wa_doc_nudge uid=%s channel=%s step=%s",
                    uid[:8] if uid else "?",
                    channel,
                    step,
                )
                working_text = (
                    f"{user_block}\n\n"
                    f"(Paso {step} — falta enviar archivo por WhatsApp)\n"
                    f"Ya generaste el documento ({doc_path}). "
                    "Ahora DEBES usar send_whatsapp_document con esa Ruta exacta "
                    "(sin «to» si te lo manda a ti). "
                    "No cierres con solo notify_whatsapp_owner ni texto; envía el archivo."
                )
                continue

            # Creó evento pero falta aviso en misión calendario+WhatsApp/recordatorio
            if (
                incomplete_nudges < MAX_INCOMPLETE_NUDGES
                and _wants_smart_calendar(text)
                and _calendar_event_created_ok(tool_trace)
                and not _calendar_notify_done(tool_trace)
            ):
                incomplete_nudges += 1
                log.info(
                    "agent_calendar_nudge uid=%s channel=%s step=%s",
                    uid[:8] if uid else "?",
                    channel,
                    step,
                )
                working_text = (
                    f"{user_block}\n\n"
                    f"(Paso {step} — falta aviso de calendario)\n"
                    "Ya creaste el evento. Ahora DEBES avisar al usuario: "
                    "notify_whatsapp_owner (confirm:true) si pidió WhatsApp/avísame, "
                    "y/o schedule_reminder con when=hora del evento si pidió recordatorio. "
                    "No cierres hasta confirmar el aviso o reportar el error real."
                )
                continue

            # FASE 2.2: nudge _wants_gmail_inbox reemplazado por planificador multi-paso
            # if (
            #     incomplete_nudges < MAX_INCOMPLETE_NUDGES
            #     and _wants_gmail_inbox(text)
            #     and not _wants_gmail_reply(text)
            #     and not _wants_gmail_bulk_archive(text)
            #     and not _gmail_tool_used(tool_trace)
            # ):
            #     ...

            # FASE 2.2: nudge _wants_gmail_reply reemplazado por planificador multi-paso
            # if (
            #     incomplete_nudges < MAX_INCOMPLETE_NUDGES
            #     and _wants_gmail_reply(text)
            #     and (_gmail_listed_or_searched_ok(tool_trace) or _gmail_read_ok(tool_trace))
            #     and not _gmail_replied_ok(tool_trace)
            # ):
            #     ...

            # FASE 2.2: nudge _wants_gmail_bulk_archive reemplazado por planificador multi-paso
            # if (
            #     incomplete_nudges < MAX_INCOMPLETE_NUDGES
            #     and _wants_gmail_bulk_archive(text)
            #     and _gmail_listed_or_searched_ok(tool_trace)
            #     and not _gmail_archived_ok(tool_trace)
            # ):
            #     ...

            spoken, tool_trace = _ensure_desktop_save(
                uid=uid,
                user_text=text,
                final_text=spoken,
                reg=reg,
                tool_names=tool_names,
                tool_trace=tool_trace,
                channel=channel,
            )
            spoken, tool_trace = _ensure_whatsapp_notify(
                uid=uid,
                user_text=text,
                final_text=spoken,
                reg=reg,
                tool_names=tool_names,
                tool_trace=tool_trace,
                channel=channel,
            )
            spoken, tool_trace = _ensure_calendar_notify(
                uid=uid,
                user_text=text,
                final_text=spoken,
                reg=reg,
                tool_names=tool_names,
                tool_trace=tool_trace,
                channel=channel,
            )
            spoken, tool_trace = _ensure_whatsapp_document_send(
                uid=uid,
                user_text=text,
                final_text=spoken,
                reg=reg,
                tool_names=tool_names,
                tool_trace=tool_trace,
                channel=channel,
            )
            spoken = repair_saved_path_claim(spoken, tool_trace)
            if on_complete:
                try:
                    on_complete(spoken, all_artifacts)
                except Exception:
                    pass
            return AgentResult(
                final_text=spoken,
                tool_trace=tool_trace,
                steps=steps_used,
                model_usage=last_usage,
                model_name=last_model,
                artifacts=all_artifacts,
            )

        observations: list[str] = []
        for call in calls:
            if call.name == "download_url_to_desktop" and any(
                t.get("tool") == "download_url_to_desktop" and t.get("ok")
                for t in tool_trace
            ):
                observations.append(
                    format_observation(
                        call.name, True, "Ya descargado en el paso forzado.", None
                    )
                )
                continue
            exec_t0 = time.perf_counter()
            if local_tools and _is_local_tool(call.name):
                # Delegar a Electron — emitir marcador sin ejecutar en backend
                marker = {"action": "local_tool", "tool": call.name, "params": call.arguments}
                exec_ms = 0
                trace_entry = {
                    "tool": call.name,
                    "ok": True,
                    "ms": 0,
                    "step": step,
                    "channel": channel,
                    "preview": f"[LOCAL] {call.name} — delegado a Electron",
                }
                tool_trace.append(trace_entry)
                all_artifacts.append(marker)
                log.info(
                    "agent_tool_local uid=%s channel=%s tool=%s",
                    uid[:8] if uid else "?",
                    channel,
                    call.name,
                )
                observations.append(
                    format_observation(call.name, True, f"[LOCAL] Herramienta delegada a Electron: {call.name}", None)
                )
                # Callback de progreso
                if on_step_complete:
                    try:
                        on_step_complete(step, call.name, f"[LOCAL] {call.name}", True)
                    except Exception:
                        pass
            else:
                result = reg.execute(uid, call.name, call.arguments)
                exec_ms = int((time.perf_counter() - exec_t0) * 1000)
                trace_entry = {
                    "tool": call.name,
                    "ok": result.ok,
                    "ms": result.duration_ms or exec_ms,
                    "step": step,
                    "channel": channel,
                    # Evidencia para anclaje (truth_check / grounding); truncada a propósito
                    "preview": (result.output or result.error or "")[:2500],
                }
                tool_trace.append(trace_entry)
                # Colectar artifacts producidos por la tool
                for art in result.artifacts:
                    if isinstance(art, dict):
                        all_artifacts.append(art)
                log.info(
                    "agent_tool uid=%s channel=%s tool=%s ok=%s ms=%s",
                    uid[:8] if uid else "?",
                    channel,
                    call.name,
                    result.ok,
                    trace_entry["ms"],
                )
                observations.append(
                    format_observation(call.name, result.ok, result.output, result.error)
                )
                # Callback de progreso
                if on_step_complete:
                    try:
                        preview = result.output[:200] if result.output else (result.error or "")[:200]
                        on_step_complete(step, call.name, preview, result.ok)
                    except Exception:
                        pass

        spoken = strip_tool_calls_json(content)
        obs_block = "\n\n".join(observations)
        working_text = (
            f"{user_block}\n\n"
            f"(Paso {step} del agente)\n"
            f"{('Respuesta parcial: ' + spoken) if spoken else ''}\n"
            f"Resultados de herramientas:\n{obs_block}\n\n"
            f"{_CONTINUE_AFTER_TOOLS}"
        )

    log.warning(
        "agent_max_steps uid=%s channel=%s max_steps=%s",
        uid[:8] if uid else "?",
        channel,
        steps_cap,
    )
    final_text = (
        "Llegué al límite de pasos de esta tarea. "
        "Puedes pedirme que continúe desde donde quedé."
    )
    final_text, tool_trace = _ensure_desktop_save(
        uid=uid,
        user_text=text,
        final_text=final_text,
        reg=reg,
        tool_names=tool_names,
        tool_trace=tool_trace,
        channel=channel,
    )
    final_text, tool_trace = _ensure_whatsapp_notify(
        uid=uid,
        user_text=text,
        final_text=final_text,
        reg=reg,
        tool_names=tool_names,
        tool_trace=tool_trace,
        channel=channel,
    )
    final_text, tool_trace = _ensure_whatsapp_document_send(
        uid=uid,
        user_text=text,
        final_text=final_text,
        reg=reg,
        tool_names=tool_names,
        tool_trace=tool_trace,
        channel=channel,
    )
    if on_complete:
        try:
            on_complete(final_text, all_artifacts)
        except Exception:
            pass
    return AgentResult(
        final_text=final_text,
        tool_trace=tool_trace,
        steps=steps_used,
        model_usage=last_usage,
        model_name=last_model,
        artifacts=all_artifacts,
    )
