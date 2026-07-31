"""Adjuntos WhatsApp inbound → sandbox/Escritorio del PC (B08).

El worker Baileys envía media_data_base64 inline (como notas de voz).
Este módulo cachea el adjunto reciente y lo persiste vía bridge writeFileBytes.
"""
from __future__ import annotations

import base64
import logging
import re
import threading
import time
from dataclasses import dataclass

from app.application.agent.tools.local_files import execute_local_tool_via_bridge
from app.domain.whatsapp.message import InboundWhatsAppMessage

log = logging.getLogger("dot.whatsapp.media")

MAX_INLINE_BYTES = 10 * 1024 * 1024
_CACHE_TTL_SECONDS = 30 * 60
_MAX_CACHE_ENTRIES = 200

_SAVE_INTENT_RE = re.compile(
    r"\b("
    r"gu[aá]rd(?:a|ame|ar|alo|ala|alos|alas|émela|emela|émelo|emelo)|"
    r"salv(?:a|ar|alo|ala)|"
    r"descarg(?:a|ar|alo|ala)|"
    r"baj(?:a|ar|alo|ala)|"
    r"pon(?:lo|la|los|las|me)?\s+(?:en|al)\s+(?:mi\s+)?(?:escritorio|desktop)|"
    r"save(?:\s+this|\s+it|\s+the)?"
    r")\b",
    re.IGNORECASE,
)

_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "text/plain": ".txt",
}


@dataclass(frozen=True)
class CachedWhatsAppMedia:
    uid: str
    message_id: str
    mime_type: str
    data_base64: str
    filename_hint: str | None
    kind: str  # image | document
    cached_at: float


@dataclass(frozen=True)
class WhatsAppMediaSaveResult:
    ok: bool
    path: str | None = None
    filename: str | None = None
    kind: str | None = None
    error: str | None = None
    human_message: str | None = None


_cache: dict[str, CachedWhatsAppMedia] = {}
_latest_by_uid: dict[str, str] = {}
_cache_lock = threading.Lock()


def detect_save_media_intent(text: str) -> bool:
    """True si el usuario pide guardar un adjunto del chat."""
    body = (text or "").strip()
    if not body:
        return False
    return bool(_SAVE_INTENT_RE.search(body))


def media_kind_from_message(message: InboundWhatsAppMessage) -> str | None:
    if message.has_document:
        return "document"
    if message.has_image:
        return "image"
    mime = (message.media_mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("application/") or mime.startswith("text/"):
        return "document"
    return None


def has_saveable_inbound_media(message: InboundWhatsAppMessage) -> bool:
    kind = media_kind_from_message(message)
    if not kind or not message.media_data_base64:
        return False
    try:
        raw = base64.b64decode(message.media_data_base64, validate=True)
    except Exception:
        return False
    return 64 <= len(raw) <= MAX_INLINE_BYTES


def cache_inbound_media(uid: str, message: InboundWhatsAppMessage) -> None:
    """Guarda adjunto en memoria para tools / auto-save."""
    if not uid or not has_saveable_inbound_media(message):
        return
    kind = media_kind_from_message(message) or "document"
    mid = (message.message_id or "").strip() or f"wa_media_{int(time.time())}"
    entry = CachedWhatsAppMedia(
        uid=uid,
        message_id=mid,
        mime_type=(message.media_mime_type or "application/octet-stream").strip(),
        data_base64=message.media_data_base64 or "",
        filename_hint=(message.media_filename or "").strip() or None,
        kind=kind,
        cached_at=time.time(),
    )
    with _cache_lock:
        _cache[mid] = entry
        _latest_by_uid[uid] = mid
        if len(_cache) > _MAX_CACHE_ENTRIES:
            oldest = sorted(_cache.values(), key=lambda e: e.cached_at)[:50]
            for old in oldest:
                _cache.pop(old.message_id, None)
    log.info(
        "WA media cache uid=%s message_id=%s kind=%s mime=%s",
        uid[:8],
        mid[:16],
        kind,
        entry.mime_type,
    )


def _resolve_cache(uid: str, message_id: str | None) -> CachedWhatsAppMedia | None:
    now = time.time()
    with _cache_lock:
        if message_id:
            entry = _cache.get(message_id.strip())
            if entry and entry.uid == uid and now - entry.cached_at <= _CACHE_TTL_SECONDS:
                return entry
            return None
        latest_id = _latest_by_uid.get(uid)
        if not latest_id:
            return None
        entry = _cache.get(latest_id)
        if entry and entry.uid == uid and now - entry.cached_at <= _CACHE_TTL_SECONDS:
            return entry
    return None


def _safe_filename(name: str, ext: str) -> str:
    base = re.sub(r'[<>:"|?*\x00-\x1f\\]', "_", (name or "").strip())
    base = base.replace("/", "_").replace("\\", "_").strip(" .")
    if not base:
        base = f"whatsapp-{int(time.time())}"
    lower = base.lower()
    if ext and not lower.endswith(ext.lower()):
        base = f"{base}{ext}"
    return base[:120]


def suggest_dest_relative_path(
    *,
    mime_type: str,
    filename_hint: str | None,
    kind: str,
) -> str:
    ext = _MIME_EXT.get(mime_type.lower(), "")
    if not ext and filename_hint and "." in filename_hint:
        ext = "." + filename_hint.rsplit(".", 1)[-1].lower()
    if not ext:
        ext = ".jpg" if kind == "image" else ".pdf" if "pdf" in mime_type else ".bin"

    if filename_hint:
        name = _safe_filename(filename_hint, ext if not filename_hint.lower().endswith(ext) else "")
    else:
        prefix = "foto" if kind == "image" else "documento"
        name = f"{prefix}-whatsapp-{int(time.time())}{ext}"
    return f"~/Desktop/{name}"


def build_save_confirmation_message(result: WhatsAppMediaSaveResult) -> str:
    if not result.ok:
        if result.error == "bridge_unreachable":
            return "No pude guardar el archivo porque la app DOT no está abierta en tu PC."
        if result.error == "no_media_cached":
            return "No encuentro el adjunto reciente. Envíalo otra vez con tu pedido."
        return result.human_message or "No pude guardar el adjunto en tu PC. Intenta de nuevo."

    fname = result.filename or "archivo"
    if result.kind == "image":
        return f"Guardé la foto en tu Escritorio ({fname})."
    if result.kind == "document":
        return f"Guardé el PDF en tu Escritorio ({fname})." if fname.lower().endswith(".pdf") else f"Guardé el documento en tu Escritorio ({fname})."
    return f"Guardé el archivo en tu Escritorio ({fname})."


def save_whatsapp_media_to_desktop(
    uid: str,
    *,
    message_id: str | None = None,
    dest_path: str | None = None,
    cached: CachedWhatsAppMedia | None = None,
) -> WhatsAppMediaSaveResult:
    """Persiste adjunto cacheado en Escritorio/sandbox vía bridge."""
    entry = cached or _resolve_cache(uid, message_id)
    if not entry:
        return WhatsAppMediaSaveResult(ok=False, error="no_media_cached")

    rel_path = (dest_path or "").strip() or suggest_dest_relative_path(
        mime_type=entry.mime_type,
        filename_hint=entry.filename_hint,
        kind=entry.kind,
    )

    raw = execute_local_tool_via_bridge(
        "writeFileBytes",
        path=rel_path,
        content=entry.data_base64,
    )
    if not raw.get("ok"):
        err = str(raw.get("error") or "save_failed")
        human = {
            "bridge_unreachable": "bridge_unreachable",
            "bridge_secret_not_configured": "bridge_unreachable",
            "bridge_unauthorized": "bridge_unreachable",
        }.get(err, err)
        log.warning(
            "WA media save fail uid=%s message_id=%s err=%s",
            uid[:8],
            entry.message_id[:16],
            err,
        )
        return WhatsAppMediaSaveResult(ok=False, error=human)

    saved_path = str(raw.get("path") or rel_path)
    filename = saved_path.replace("\\", "/").rsplit("/", 1)[-1]
    log.info(
        "WA media saved uid=%s message_id=%s path=%s bytes=%s",
        uid[:8],
        entry.message_id[:16],
        saved_path,
        raw.get("bytes"),
    )
    return WhatsAppMediaSaveResult(
        ok=True,
        path=saved_path,
        filename=filename,
        kind=entry.kind,
        human_message=build_save_confirmation_message(
            WhatsAppMediaSaveResult(ok=True, filename=filename, kind=entry.kind)
        ),
    )


def try_auto_save_inbound_media(
    uid: str,
    message: InboundWhatsAppMessage,
) -> WhatsAppMediaSaveResult | None:
    """Auto-guardado cuando el texto pide guardar el adjunto."""
    if not detect_save_media_intent(message.text):
        return None
    if not has_saveable_inbound_media(message):
        return None
    cache_inbound_media(uid, message)
    return save_whatsapp_media_to_desktop(uid, message_id=message.message_id)


def clear_media_cache_for_tests() -> None:
    with _cache_lock:
        _cache.clear()
        _latest_by_uid.clear()
