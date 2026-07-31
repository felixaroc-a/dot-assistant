"""Transcripción de audio (STT) y síntesis de voz (TTS) para DOT.

Este módulo es un wrapper de compatibilidad. Delega a:
  - stt_service.py (STT multi-proveedor)
  - tts_service.py (TTS multi-proveedor)

Para nuevas features usa stt_service y tts_service directamente.
"""

from __future__ import annotations

from app.services.stt_service import stt_configured, transcribe_audio  # noqa: F401
from app.services.tts_service import synthesize_speech, tts_configured  # noqa: F401


def voice_stt_configured() -> bool:
    """True si hay API key para STT (activación = GEMINI_API_KEY u OPENAI_API_KEY)."""
    return stt_configured()


def voice_tts_configured() -> bool:
    """True si hay proveedor TTS configurado (GEMINI_API_KEY o edge-tts)."""
    return tts_configured()
