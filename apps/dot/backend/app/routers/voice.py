"""Router de voz — STT (transcripción), TTS (síntesis) y Talk Mode para DOT.

Proveedores STT: Gemini, Whisper (OpenAI). auto → mejor disponible.
Proveedores TTS: Gemini, Edge (gratis), ElevenLabs. auto → mejor disponible.
Talk Mode: conversación bidireccional por voz (STT → chat → TTS).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_deps import claims_cliente_id, claims_uid, check_usage_limit
from app.billing_db import get_billing_db
from app.services.stt_service import (
    get_available_stt_providers,
    stt_configured,
    transcribe_audio,
)
from app.services.talk_mode import (
    get_talk_status,
    process_talk_turn,
    start_talk_session,
    stop_talk_session,
)
from app.services.tts_service import (
    get_available_tts_providers,
    synthesize_speech,
    tts_configured,
)
from app.services.usage_service import OPERATION_VISION, calc_vision_cost_usd, record_usage
from app.settings import settings

log = logging.getLogger("dot.voice")

router = APIRouter(prefix="/v1/voice", tags=["voice"])

MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB


# ─── Status ───────────────────────────────────────────────────────────────


@router.get("/status")
async def voice_status(claims: dict = Depends(check_usage_limit)):
    """Estado de STT, TTS y proveedores disponibles."""
    _ = claims
    stt_ok = stt_configured()
    tts_ok = tts_configured()
    return {
        "ok": stt_ok or tts_ok,
        "stt": "ready" if stt_ok else "needs_api_key",
        "tts": "ready" if tts_ok else "needs_api_key",
        "providers": {
            "stt": get_available_stt_providers(),
            "tts": get_available_tts_providers(),
        },
        "detail": None
        if (stt_ok or tts_ok)
        else "La voz no está configurada en el servidor.",
    }


# ─── STT / Transcribe ─────────────────────────────────────────────────────


@router.post("/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form("es"),
    provider: str = Form("auto"),
    claims: dict = Depends(check_usage_limit),
    db: Session = Depends(get_billing_db),
):
    """Transcribe un audio grabado en el cliente (MediaRecorder).

    Parámetros:
        file: Audio (máx 8 MB).
        language: Código de idioma (es, en, etc.).
        provider: "auto" (mejor disponible), "gemini", "whisper".
    """
    uid = claims_uid(claims)
    contents = await file.read()
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(400, detail="Audio demasiado grande (máx. 8 MB).")

    mime = file.content_type or "audio/webm"
    text = await transcribe_audio(
        contents, mime, language=language, provider=provider,
    )
    log.info(
        "voice_transcribe ok uid=%s bytes=%s chars=%s lang=%s provider=%s",
        uid[:8] if uid else "?",
        len(contents),
        len(text),
        language[:8],
        provider,
    )

    model = (
        settings.gemini_vertex_model
        if settings.normalized_gemini_provider == "vertex"
        else settings.gemini_model
    )
    record_usage(
        db,
        cliente_id=claims_cliente_id(claims),
        modelo=model,
        cost_usd=calc_vision_cost_usd(),
        operation=OPERATION_VISION,
    )

    return {"text": text, "ok": bool(text.strip()), "provider": provider}


# ─── Schemas para TTS ─────────────────────────────────────────────────────


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "auto"
    provider: str = "auto"


class SynthesizeResponse(BaseModel):
    audio_base64: str
    format: str = "mp3"
    provider: str = "auto"


# ─── TTS / Synthesize ─────────────────────────────────────────────────────


@router.post("/synthesize", response_model=SynthesizeResponse)
async def voice_synthesize(
    body: SynthesizeRequest,
    claims: dict = Depends(check_usage_limit),
):
    """Sintetiza texto a voz (TTS). Devuelve audio MP3 en base64.

    Parámetros:
        text: Texto a sintetizar.
        voice: Voz o "auto" para default del proveedor.
        provider: "auto" (mejor disponible), "gemini", "edge", "elevenlabs".
    """
    uid = claims_uid(claims)
    log.info(
        "voice_synthesize request uid=%s chars=%s voice=%s provider=%s",
        uid[:8] if uid else "?",
        len(body.text),
        body.voice,
        body.provider,
    )

    result = await synthesize_speech(
        text=body.text, voice=body.voice, provider=body.provider,
    )
    return SynthesizeResponse(
        audio_base64=result["audio_base64"],
        format=result["format"],
        provider=result.get("provider", body.provider),
    )


# ─── Talk Mode ────────────────────────────────────────────────────────────


class TalkTurnRequest(BaseModel):
    """Audio de una interacción en talk mode."""
    language: str = "es"
    stt_provider: str = "auto"
    tts_provider: str = "auto"
    tts_voice: str = "auto"
    interruption: bool = False


class TalkTurnResponse(BaseModel):
    state: str
    transcript: str
    response_text: str
    audio_base64: str
    audio_format: str
    tts_provider: str
    history_length: int


@router.post("/talk/start")
async def talk_start(claims: dict = Depends(check_usage_limit)):
    """Inicia una sesión de conversación por voz."""
    uid = claims_uid(claims)
    result = start_talk_session(uid)
    return result


@router.post("/talk/turn", response_model=TalkTurnResponse)
async def talk_turn(
    file: UploadFile = File(...),
    options_json: str = Form("{}"),
    claims: dict = Depends(check_usage_limit),
):
    """Procesa un turno de conversación por voz: STT → TTS.

    Envía un chunk de audio del usuario; recibe transcripción + audio de respuesta.

    Parámetros (vía form):
        file: Audio grabado del usuario.
        options_json: JSON con {language, stt_provider, tts_provider, tts_voice, interruption}.
    """
    import json as _json

    uid = claims_uid(claims)
    contents = await file.read()
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(400, detail="Audio demasiado grande (máx. 8 MB).")

    try:
        options = _json.loads(options_json)
    except (_json.JSONDecodeError, TypeError):
        options = {}

    mime = file.content_type or "audio/webm"
    result = await process_talk_turn(
        uid=uid,
        audio_bytes=contents,
        mime_type=mime,
        language=options.get("language", "es"),
        stt_provider=options.get("stt_provider", "auto"),
        tts_provider=options.get("tts_provider", "auto"),
        tts_voice=options.get("tts_voice", "auto"),
        interruption=options.get("interruption", False),
    )

    return TalkTurnResponse(
        state=result["state"],
        transcript=result["transcript"],
        response_text=result["response_text"],
        audio_base64=result["audio_base64"],
        audio_format=result["audio_format"],
        tts_provider=result["tts_provider"],
        history_length=result["history_length"],
    )


@router.get("/talk/status")
async def talk_status(claims: dict = Depends(check_usage_limit)):
    """Estado actual de la sesión de talk mode."""
    uid = claims_uid(claims)
    return get_talk_status(uid)


@router.post("/talk/stop")
async def talk_stop(claims: dict = Depends(check_usage_limit)):
    """Finaliza la sesión de talk mode."""
    uid = claims_uid(claims)
    result = stop_talk_session(uid)
    return result
