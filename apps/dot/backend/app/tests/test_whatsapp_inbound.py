"""Pruebas del procesamiento inbound WhatsApp (T04 + política DOT group)."""
from __future__ import annotations

import base64

from app.application.whatsapp.inbound_service import (
    WHATSAPP_STT_FAILURE_MESSAGE,
    build_message_id,
    get_message_store,
    is_dot_group_name,
    normalize_inbound_text,
    process_inbound_message,
    should_allow_auto_reply,
    text_mentions_dot,
)
from app.domain.whatsapp.message import InboundWhatsAppMessage
from app.infrastructure.whatsapp.phone_resolver import resolve_uid_by_to_phone, to_e164
from app.services.whatsapp_link import clear_channel_state, update_channel_state
from app.settings import settings


def test_normalize_inbound_text_returns_clean_text():
    """Baileys entrega texto limpio, sin prefijos que limpiar."""
    raw = "Hola DOT"
    assert normalize_inbound_text(raw) == "Hola DOT"
    assert normalize_inbound_text("  Hola DOT  ") == "Hola DOT"


def test_to_e164_normalizes_ve_local_numbers():
    assert to_e164("04141234567") == "+584141234567"
    assert to_e164("4141234567") == "+584141234567"
    assert to_e164("584141234567") == "+584141234567"
    assert to_e164("+584141234567") == "+584141234567"


def test_resolve_uid_by_to_phone_with_saved_linked_number():
    uid = "test-wa-resolve-01"
    linked = "+580000000101"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)

    assert resolve_uid_by_to_phone(linked) == uid
    assert resolve_uid_by_to_phone("0000000101") == uid

    clear_channel_state(uid)


def test_process_inbound_persists_for_linked_user():
    uid = "test-wa-inbound-01"
    linked = "+580000000201"
    peer = "+580000000202"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)
    get_message_store().clear_uid(uid)

    message = InboundWhatsAppMessage(
        message_id="msg-001",
        from_phone=peer,
        to_phone=linked,
        text="Hola desde WhatsApp",
        timestamp="2026-07-13T16:00:00Z",
    )

    result = process_inbound_message(message)
    assert result["status"] == "ok"
    assert result["uid"] == uid
    assert result["stored"] is True
    # Remitente externo 1:1: se ingiere pero no se auto-responde
    assert result["allow_auto_reply"] is False

    stored = get_message_store().list_for_uid(uid, limit=10)
    assert len(stored) == 1
    assert stored[0].text == "Hola desde WhatsApp"
    assert stored[0].direction == "inbound"

    clear_channel_state(uid)
    get_message_store().clear_uid(uid)


def test_dot_group_mention_helpers():
    assert is_dot_group_name("DOT") is True
    assert is_dot_group_name("grupo DOT") is True
    assert is_dot_group_name("VAMOS A LA PLAYA") is False
    assert text_mentions_dot("Hola DOT") is True
    assert text_mentions_dot("@DOT ayúdame") is True
    assert text_mentions_dot("solo hola") is False


def test_dot_group_mention_allows_only_owner_in_dot_group(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_reply_policy", "dot_group_mention")
    monkeypatch.setattr(settings, "whatsapp_reply_require_mention", True)
    monkeypatch.setattr(settings, "whatsapp_reply_require_self", True)

    uid = "test-wa-inbound-dot"
    linked = "+580000000301"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)
    get_message_store().clear_uid(uid)

    # 1:1 self — NO
    assert (
        should_allow_auto_reply(
            from_phone=linked,
            linked_phone=linked,
            text="Hola DOT",
            is_group=False,
            group_name=None,
        )
        is False
    )

    # Otro grupo + mención — NO
    assert (
        should_allow_auto_reply(
            from_phone=linked,
            linked_phone=linked,
            text="Hola DOT",
            is_group=True,
            group_name="VAMOS A LA PLAYA",
        )
        is False
    )

    # Grupo DOT sin mención — NO
    assert (
        should_allow_auto_reply(
            from_phone=linked,
            linked_phone=linked,
            text="hola sin mencionar",
            is_group=True,
            group_name="DOT",
        )
        is False
    )

    # Extrano en grupo DOT con mención — NO (require_self)
    assert (
        should_allow_auto_reply(
            from_phone="+580000000399",
            linked_phone=linked,
            text="DOT hola",
            is_group=True,
            group_name="DOT",
        )
        is False
    )

    # Remitente LID (no E.164) en grupo DOT con mención — SI (workaround Baileys)
    assert (
        should_allow_auto_reply(
            from_phone="93952543879213",
            linked_phone=linked,
            text="@DOT di hola",
            is_group=True,
            group_name="DOT",
        )
        is True
    )

    # Dueño en grupo DOT con mención — SI
    assert (
        should_allow_auto_reply(
            from_phone=linked,
            linked_phone=linked,
            text="DOT resume esto",
            is_group=True,
            group_name="DOT",
        )
        is True
    )

    message = InboundWhatsAppMessage(
        message_id="msg-dot-001",
        from_phone=linked,
        to_phone=linked,
        text="DOT soy yo",
        timestamp="2026-07-13T16:05:00Z",
        is_group=True,
        group_name="DOT",
    )
    result = process_inbound_message(message)
    assert result["stored"] is True
    assert result["allow_auto_reply"] is True

    clear_channel_state(uid)
    get_message_store().clear_uid(uid)


def test_self_only_policy_still_works(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_reply_policy", "self_only")
    linked = "+580000000401"
    assert should_allow_auto_reply(from_phone=linked, linked_phone=linked, text="x") is True
    assert (
        should_allow_auto_reply(from_phone="+580000000499", linked_phone=linked, text="x")
        is False
    )


def test_build_message_id_is_stable_without_external_id():
    message = InboundWhatsAppMessage(
        message_id="",
        from_phone="+580000000401",
        to_phone="+580000000402",
        text="ping",
        timestamp="2026-07-13T16:00:00Z",
    )
    first = build_message_id(message)
    second = build_message_id(message)
    assert first == second
    assert first.startswith("wa_in_")


def test_voice_note_transcription_feeds_effective_text(monkeypatch):
    uid = "test-wa-voice-01"
    linked = "+580000000501"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)
    get_message_store().clear_uid(uid)

    async def mock_transcribe(audio_bytes, mime_type, language="es", provider="auto"):
        assert len(audio_bytes) >= 64
        assert mime_type.startswith("audio/")
        return "Hola DOT desde nota de voz"

    monkeypatch.setattr(
        "app.services.voice_service.transcribe_audio",
        mock_transcribe,
    )

    audio_bytes = b"x" * 128
    message = InboundWhatsAppMessage(
        message_id="msg-voice-001",
        from_phone=linked,
        to_phone=linked,
        text="[media]",
        timestamp="2026-07-13T16:10:00Z",
        is_group=True,
        group_name="DOT",
        has_audio=True,
        media_mime_type="audio/ogg",
        media_data_base64=base64.b64encode(audio_bytes).decode("ascii"),
    )

    result = process_inbound_message(message)
    assert result["status"] == "ok"
    assert result["voice_transcribed"] is True
    assert result["effective_text"] == "Hola DOT desde nota de voz"
    assert result["stt_failed"] is False
    assert result["allow_auto_reply"] is True

    stored = get_message_store().list_for_uid(uid, limit=10)
    assert stored[0].text == "Hola DOT desde nota de voz"

    clear_channel_state(uid)
    get_message_store().clear_uid(uid)


def test_voice_note_stt_failure_marks_stt_failed(monkeypatch):
    uid = "test-wa-voice-02"
    linked = "+580000000502"
    clear_channel_state(uid)
    update_channel_state(uid, linked=True, phone_number=linked)
    get_message_store().clear_uid(uid)

    async def mock_transcribe_fail(*args, **kwargs):
        raise RuntimeError("STT unavailable")

    monkeypatch.setattr(
        "app.services.voice_service.transcribe_audio",
        mock_transcribe_fail,
    )

    message = InboundWhatsAppMessage(
        message_id="msg-voice-002",
        from_phone=linked,
        to_phone=linked,
        text="[media]",
        timestamp="2026-07-13T16:11:00Z",
        is_group=True,
        group_name="DOT",
        has_audio=True,
        media_mime_type="audio/ogg",
        media_data_base64=base64.b64encode(b"y" * 128).decode("ascii"),
    )

    result = process_inbound_message(message)
    assert result["stt_failed"] is True
    assert result["effective_text"] == ""
    assert result["voice_transcribed"] is False
    assert WHATSAPP_STT_FAILURE_MESSAGE == "No pude escuchar el audio, ¿me lo escribes?"

    clear_channel_state(uid)
    get_message_store().clear_uid(uid)
