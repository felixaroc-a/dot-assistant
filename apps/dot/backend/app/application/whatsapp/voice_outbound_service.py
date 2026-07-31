"""WhatsApp outbound voice notes — TTS → archivo de audio → Baileys PTT."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import HTTPException

from app.application.agent.tools.local_files import execute_local_tool_via_bridge

log = logging.getLogger("dot.whatsapp.voice_outbound")

MAX_VOICE_CHARS = 4000

# Copia guiada (paridad con voice.speak_unavailable del pendrive, commit 61d228e5).
WHATSAPP_TTS_UNAVAILABLE_PREFIX = (
    "No pude enviar nota de voz ahora. La voz de DOT aún no está activa en tu pendrive. "
    "Te lo escribo:\n\n"
)

WHATSAPP_VOICE_SEND_FAILED_PREFIX = (
    "No pude enviar el audio por WhatsApp. Te lo escribo:\n\n"
)


def _truncate_message(text: str) -> str:
    body = (text or "").strip()
    if len(body) <= MAX_VOICE_CHARS:
        return body
    return f"{body[: MAX_VOICE_CHARS - 1].rstrip()}…"


def _voice_note_relative_path() -> str:
    return f"~/Desktop/nota-voz-dot-{int(time.time())}.mp3"


async def _synthesize_voice_audio(message: str) -> bytes | None:
    from app.services.tts_service import synthesize_speech

    try:
        result = await synthesize_speech(message, voice="auto", provider="auto")
    except HTTPException as exc:
        log.warning("WA voice note TTS unavailable: %s", exc.detail)
        return None
    except Exception as exc:
        log.warning("WA voice note TTS error: %s", exc)
        return None

    import base64

    raw_b64 = str(result.get("audio_base64") or "").strip()
    if not raw_b64:
        return None
    try:
        audio = base64.b64decode(raw_b64, validate=True)
    except Exception:
        return None
    return audio if audio else None


def _write_voice_file(audio_bytes: bytes) -> str | None:
    import base64

    rel_path = _voice_note_relative_path()
    raw = execute_local_tool_via_bridge(
        "writeFileBytes",
        path=rel_path,
        content=base64.b64encode(audio_bytes).decode("ascii"),
    )
    if not raw.get("ok"):
        log.warning("WA voice note write failed: %s", raw.get("error"))
        return None
    saved = str(raw.get("path") or rel_path).strip()
    return saved or rel_path


async def _send_text_fallback(to: str, message: str, *, prefix: str) -> tuple[bool, str | None, Literal["text_fallback"]]:
    from app.services.whatsapp_client import send_whatsapp_message

    text = f"{prefix}{message}".strip()
    ok, msg_id_or_err = await send_whatsapp_message(to, text)
    err = None if ok else msg_id_or_err
    return ok, err, "text_fallback"


async def send_whatsapp_voice_note_outbound(
    to: str,
    message: str,
) -> tuple[bool, str | None, Literal["voice", "text_fallback"]]:
    """Sintetiza TTS, envía nota de voz real; si TTS/bridge falla, texto guiado en español."""
    dest = (to or "").strip()
    body = _truncate_message(message)
    if not dest:
        return False, "missing_recipient", "text_fallback"
    if not body:
        return False, "missing_message", "text_fallback"

    audio_bytes = await _synthesize_voice_audio(body)
    if not audio_bytes:
        return await _send_text_fallback(dest, body, prefix=WHATSAPP_TTS_UNAVAILABLE_PREFIX)

    saved_path = _write_voice_file(audio_bytes)
    if not saved_path:
        return await _send_text_fallback(dest, body, prefix=WHATSAPP_TTS_UNAVAILABLE_PREFIX)

    from app.services.whatsapp_client import send_whatsapp_voice_note

    ok, err = await send_whatsapp_voice_note(dest, saved_path)
    if ok:
        return True, None, "voice"

    log.warning("WA voice note bridge send failed to=%s err=%s", dest, err)
    return await _send_text_fallback(dest, body, prefix=WHATSAPP_VOICE_SEND_FAILED_PREFIX)


def send_whatsapp_voice_note_sync(to: str, message: str) -> tuple[bool, str | None, Literal["voice", "text_fallback"]]:
    """Wrapper síncrono para handlers de tools."""
    return asyncio.run(send_whatsapp_voice_note_outbound(to, message))
