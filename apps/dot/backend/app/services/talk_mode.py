"""Talk Mode — Conversación por voz bidireccional.

Flujo:
  1. start_talk_session(uid) — inicializa sesión por usuario.
  2. process_talk_turn(uid, audio_chunk) — STT → chat → TTS → devuelve audio.
  3. get_talk_status(uid) — estado actual de la sesión.
  4. stop_talk_session(uid) — finaliza sesión.

Interrupción:
  Si el usuario habla mientras DOT está respondiendo, se marca interruption_requested.
  El cliente debe detectar interrupción localmente y llamar process_talk_turn
  con interruption=True, lo que cancela la TTS en curso y procesa el nuevo audio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from fastapi import HTTPException

from app.services.stt_service import transcribe_audio
from app.services.tts_service import synthesize_speech

log = logging.getLogger("dot.talk")

MAX_TALK_SESSIONS = 100
SESSION_TTL_SECONDS = 300  # 5 minutos de inactividad


class TalkState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


@dataclass
class TalkSession:
    uid: str
    state: TalkState = TalkState.IDLE
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    current_transcript: str = ""
    interruption_requested: bool = False

    def reset_interruption(self) -> None:
        self.interruption_requested = False


# Almacén en memoria (un TalkSession por uid)
_sessions: dict[str, TalkSession] = {}


def _cleanup_expired() -> None:
    """Elimina sesiones sin actividad (práctica conservadora)."""
    # Mantenemos las sesiones mientras dure la conversación.
    # Limpieza solo si excedemos el máximo.
    if len(_sessions) > MAX_TALK_SESSIONS:
        oldest = sorted(_sessions.keys())[: len(_sessions) - MAX_TALK_SESSIONS]
        for uid in oldest:
            del _sessions[uid]


def get_talk_session(uid: str) -> TalkSession:
    """Recupera o crea una sesión de talk mode para el usuario."""
    if uid in _sessions:
        return _sessions[uid]
    session = TalkSession(uid=uid)
    _sessions[uid] = session
    _cleanup_expired()
    return session


def start_talk_session(uid: str) -> dict[str, object]:
    """Inicializa una sesión de conversación por voz.

    Args:
        uid: ID del usuario Firebase.

    Returns:
        Estado inicial de la sesión.
    """
    session = get_talk_session(uid)
    session.state = TalkState.LISTENING
    session.conversation_history = []
    session.current_transcript = ""
    session.reset_interruption()
    log.info("talk session started uid=%s", uid[:8] if uid else "?")
    return {
        "state": session.state.value,
        "transcript": session.current_transcript,
        "history_length": len(session.conversation_history),
    }


async def process_talk_turn(
    uid: str,
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    language: str = "es",
    stt_provider: str = "auto",
    tts_provider: str = "auto",
    tts_voice: str = "auto",
    interruption: bool = False,
) -> dict[str, object]:
    """Procesa un turno de conversación: STT → almacena → (placeholder para LLM) → TTS.

    En una implementación completa, después del STT se llamaría al chat LLM
    para obtener respuesta. Por ahora devolvemos el transcript y generamos
    audio del transcript para testing del pipeline.

    Args:
        uid: ID del usuario.
        audio_bytes: Audio grabado del usuario.
        mime_type: MIME type del audio.
        language: Código de idioma.
        stt_provider: Proveedor STT ("auto", "gemini", "whisper").
        tts_provider: Proveedor TTS ("auto", "gemini", "edge", "elevenlabs").
        tts_voice: Voz para TTS o "auto".
        interruption: True si se interrumpe el audio en reproducción.

    Returns:
        dict con transcript, audio_base64, state, provider info.
    """
    session = get_talk_session(uid)

    if interruption:
        session.interruption_requested = True
        session.state = TalkState.INTERRUPTED
        log.info("talk interruption uid=%s", uid[:8] if uid else "?")

    # STT
    session.state = TalkState.LISTENING
    transcript = await transcribe_audio(
        audio_bytes, mime_type, language=language, provider=stt_provider,
    )
    session.current_transcript = transcript
    session.conversation_history.append({"role": "user", "text": transcript})

    # Placeholder para respuesta LLM (en el futuro: llamar al chat router aquí)
    session.state = TalkState.THINKING
    response_text = f"Recibí tu mensaje: {transcript}" if transcript else "No entendí tu mensaje"

    # TTS de la respuesta
    session.state = TalkState.SPEAKING
    tts_result = await synthesize_speech(
        text=response_text, voice=tts_voice, provider=tts_provider,
    )
    session.conversation_history.append({"role": "assistant", "text": response_text})

    if session.interruption_requested:
        session.state = TalkState.INTERRUPTED
        session.reset_interruption()
    else:
        session.state = TalkState.IDLE

    return {
        "state": session.state.value,
        "transcript": transcript,
        "response_text": response_text,
        "audio_base64": tts_result["audio_base64"],
        "audio_format": tts_result["format"],
        "tts_provider": tts_result.get("provider", tts_provider),
        "history_length": len(session.conversation_history),
    }


def get_talk_status(uid: str) -> dict[str, object]:
    """Devuelve el estado actual de la sesión de talk mode."""
    session = get_talk_session(uid)
    return {
        "active": session.state != TalkState.IDLE,
        "state": session.state.value,
        "transcript": session.current_transcript,
        "history_length": len(session.conversation_history),
    }


def stop_talk_session(uid: str) -> dict[str, object]:
    """Finaliza una sesión de talk mode."""
    session = _sessions.pop(uid, None)
    if session:
        log.info("talk session stopped uid=%s turns=%s", uid[:8], len(session.conversation_history))
        return {
            "stopped": True,
            "total_turns": len(session.conversation_history),
        }
    return {"stopped": False, "detail": "No hay sesión activa"}
