"""Evita que el modelo afirme haber guardado/buscado/enviado WA sin tools OK."""

from __future__ import annotations

import re
from typing import Any

from app.application.agent.grounding import (
    is_analysis_mission,
    looks_ungrounded_final,
    repair_saved_path_claim,
    wrote_ok as grounding_wrote_ok,
)


_FILE_SAVE_TOOLS = frozenset(
    {
        "writeFile",
        "download_url_to_desktop",
        "downloadUrl",
        "generate_document",
        "generate_spreadsheet",
        "save_whatsapp_media_to_desktop",
    }
)

# Intent explícito de crear/guardar archivo — NO disparar solo porque la ruta
# del usuario contiene "Escritorio" (p. ej. analizar C:\...\Escritorio\proyecto).
_FILE_INTENT = re.compile(
    r"\b(crea|crear|guarda|guardar|escribe|escribir)\b|"
    r"\b(nota|informe|documento|reporte)\.(txt|md|docx?|pdf)\b|"
    r"\b(en|al)\s+(el\s+)?(escritorio|desktop)\b",
    re.IGNORECASE,
)
_SEARCH_INTENT = re.compile(
    r"\b(busca|buscar|web|internet|noticias|referencias|bibliogr[aá]fic)",
    re.IGNORECASE,
)
_WA_SEND_INTENT = re.compile(
    r"\b(whats?app|wa\b|env[ií]a(le|me|nos)?|mand(a|arle|ame|amele)|mensaje|av[ií]same|notif[ií]came)\b",
    re.IGNORECASE,
)
_READ_DOC_INTENT = re.compile(
    r"\b(lee|leer|l[eé]eme|abre|analiz|revisa|resume|resumir|pdf|documento|docx|excel|xlsx|xls|hoja de c[aá]lculo)\b",
    re.IGNORECASE,
)
_CALENDAR_CREATE_INTENT = re.compile(
    r"\b(agenda|agendar|programa|programar|reuni[oó]n|cita|evento|calendario)\b",
    re.IGNORECASE,
)
_CALENDAR_SUCCESS_CLAIM = re.compile(
    r"\b(agend[eé]|agendado|program[eé]|programado|cita\s+agendada|evento\s+creado|"
    r"reuni[oó]n\s+agendada|✅)\b",
    re.IGNORECASE,
)
_SUMMARY_CLAIM = re.compile(
    r"\b(resumen|bullets?|puntos|hallazgos|contenido del|en\s+\d+\s+(bullets|puntos|l[ií]neas))\b",
    re.IGNORECASE,
)
_WA_SUCCESS_CLAIM = re.compile(
    r"\b(enviado|mandado|entregado|mensaje enviado|✅|exitosamente)\b",
    re.IGNORECASE,
)
_SUCCESS_CLAIM = re.compile(
    r"\b(guard[eé]|guardado|cre[eé]|creado|escrib[ií]|listo|archivo guardado|✅)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


_DOWNLOAD_INTENT = re.compile(
    r"\b(descarga|descargar|download)\b|https?://",
    re.IGNORECASE,
)

_DOCX_PATH_CLAIM = re.compile(
    r"(?i)(?:informe|documento).{0,80}\.docx|\.docx\b.{0,40}(?:escritorio|desktop|ruta)",
)


def truth_check_file_mission(
    *,
    user_text: str,
    final_text: str,
    tool_trace: list[dict[str, Any]] | None,
) -> str:
    """Corrige afirmaciones de éxito sin evidencia de tools."""
    text = final_text or ""
    trace = tool_trace or []
    user = user_text or ""

    wrote_ok = any(
        t.get("ok") and str(t.get("tool") or "") in _FILE_SAVE_TOOLS for t in trace
    )
    downloaded_ok = any(
        t.get("ok")
        and str(t.get("tool") or "") in {"download_url_to_desktop", "downloadUrl"}
        for t in trace
    )
    searched_ok = any(
        t.get("ok") and str(t.get("tool") or "") == "web_search" for t in trace
    )
    wa_sent_ok = any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {"send_whatsapp_message", "notify_whatsapp_owner"}
        for t in trace
    )
    wa_failed = [
        t
        for t in trace
        if str(t.get("tool") or "")
        in {"send_whatsapp_message", "notify_whatsapp_owner"}
        and not t.get("ok")
    ]
    read_ok = any(
        t.get("ok")
        and str(t.get("tool") or "")
        in {"read_document", "read_spreadsheet", "analyze_cv", "readFile", "parseDocument"}
        for t in trace
    )
    calendar_created_ok = any(
        t.get("ok") and str(t.get("tool") or "") == "calendar_create_event" for t in trace
    )

    # Pedido de calendario + afirmación de éxito sin calendar_create_event OK
    if (
        _CALENDAR_CREATE_INTENT.search(user)
        and _CALENDAR_SUCCESS_CLAIM.search(text)
        and not calendar_created_ok
    ):
        return (
            "Todavía no agendé el evento en Google Calendar de verdad "
            "(no se ejecutó calendar_create_event). "
            "Vinculá Google en Ajustes e intentá de nuevo."
        )

    # Pedido de WhatsApp + afirmación de éxito sin tool OK
    if _WA_SEND_INTENT.search(user) and _WA_SUCCESS_CLAIM.search(text) and not wa_sent_ok:
        if wa_failed:
            err = str(wa_failed[0].get("error") or "")
            if "bridge" in err.lower() or "secret" in err.lower():
                return (
                    "Intenté enviar el WhatsApp pero el puente local no está listo "
                    "(secreto del bridge o app DOT). Dejá DOT abierto e intentá de nuevo."
                )
            return (
                f"Intenté enviar el WhatsApp pero falló: {err or 'error desconocido'}. "
                "Revisá que WhatsApp esté vinculado y el número sea válido (+58… o 0412…)."
            )
        return (
            "Todavía no envié ese WhatsApp de verdad "
            "(no se ejecutó el envío confirmado). "
            "Reintentá con la app DOT abierta y WhatsApp vinculado."
        )

    # Resumen de documento sin haber leído con tool
    if (
        _READ_DOC_INTENT.search(user)
        and _SUMMARY_CLAIM.search(text)
        and not read_ok
        and not is_analysis_mission(user)
    ):
        return (
            "Todavía no leí el documento de verdad "
            "(no se ejecutó read_document, read_spreadsheet ni analyze_cv). "
            "No inventé un resumen. Dejá DOT abierto e intentá de nuevo."
        )

    # Pedido de descarga: exige download tool, no writeFile de texto falso
    if _DOWNLOAD_INTENT.search(user) and (
        "descarga" in user.lower() or "download" in user.lower() or ".pdf" in user.lower()
    ):
        if not downloaded_ok:
            return (
                "No completé una descarga real del archivo (hace falta download_url_to_desktop). "
                "No guardé un PDF falso como texto. Reintenta: "
                "«descarga <URL> al Escritorio»."
            )

    # Pedido de archivo + afirmación de éxito sin write/download OK
    if _FILE_INTENT.search(user) and _SUCCESS_CLAIM.search(text) and not wrote_ok:
        failed = [
            t
            for t in trace
            if str(t.get("tool") or "") in _FILE_SAVE_TOOLS and not t.get("ok")
        ]
        if failed:
            err = str(failed[0].get("error") or "")
            if "bridge" in err.lower():
                return (
                    "Intenté guardar el archivo pero el puente local no respondió. "
                    "Dejá la app DOT abierta en el PC e intentá de nuevo."
                )
            return (
                "Intenté guardar el archivo en tu PC pero no se completó. "
                "Reintentá en unos segundos."
            )
        return (
            "Todavía no pude guardar el archivo en tu PC "
            "(el asistente no ejecutó la escritura). "
            "Reintentá: «crea nota.txt en Escritorio con hola»."
        )

    # Análisis + afirma .docx guardado sin tool de escritura
    if (
        is_analysis_mission(user)
        and _DOCX_PATH_CLAIM.search(text)
        and not grounding_wrote_ok(trace)
    ):
        return (
            f"{text.rstrip()}\n\n"
            "— Nota DOT: el .docx mencionado no se generó con una tool confirmada. "
            "Pedí de nuevo «guarda el informe en DOCX» con la app abierta."
        )

    # Corregir ruta del documento si mintió pero sí hubo generate_document OK
    if grounding_wrote_ok(trace):
        text = repair_saved_path_claim(text, trace)

    # Aviso suave si el informe sigue claramente desanclado (tras nudges del runtime)
    if looks_ungrounded_final(user_text=user, final_text=text, tool_trace=trace):
        text = (
            f"{text.rstrip()}\n\n"
            "— Nota DOT: parte de este informe puede citar rutas no verificadas "
            "en esta sesión. Si algo no cuadra, pedí que vuelva a listar/leer "
            "esas carpetas concretas."
        )

    # Pedido de búsqueda/referencias sin web_search OK
    if _SEARCH_INTENT.search(user) and not searched_ok:
        return (
            "No pude completar la búsqueda web en este intento "
            "(no hay resultados confirmados). Prueba de nuevo; "
            "si falla, revisa la conexión a internet."
        )

    # Buscó OK pero la respuesta no trae URLs (pediste referencias)
    if (
        _SEARCH_INTENT.search(user)
        and searched_ok
        and re.search(r"referencias|bibliogr", user, re.IGNORECASE)
        and not _URL_RE.search(text)
    ):
        return (
            f"{text.rstrip()}\n\n"
            "Nota: pediste referencias bibliográficas y aún no aparecen URLs en la respuesta. "
            "Pide de nuevo las fuentes con enlaces."
        )

    return text
