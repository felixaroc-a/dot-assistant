"""Tests Loop-13: continuidad PC ↔ WhatsApp en system prompt."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.chat_models import ConversationORM, MessageORM
from app.services.chat_context import build_system_prompt
from app.services.cross_surface_context import (
    build_other_surface_context_block,
    format_other_surface_exchange,
)
from app.services.chat_crypto import encrypt_message


def _make_conv(uid: str, channel: str, title: str = "Test") -> ConversationORM:
    return ConversationORM(
        id=uuid.uuid4(),
        cliente_id=uuid.UUID(uid),
        title=title,
        channel=channel,
        updated_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
    )


def test_format_other_surface_exchange_strips_wa_prefix():
    msg = MessageORM(
        conversation_id=uuid.uuid4(),
        role="user",
        content=encrypt_message("[WA +58 412 1234567 24/07] Recuérdame llamar a mamá"),
    )
    text = format_other_surface_exchange([msg], source_surface="whatsapp")
    assert "Recuérdame llamar a mamá" in text
    assert "[WA" not in text
    assert "LO RECIENTE EN WHATSAPP" in text


def test_build_other_surface_context_block_pc_sees_whatsapp():
    uid = str(uuid.uuid4())
    wa_conv = _make_conv(uid, "whatsapp", "WhatsApp")
    user_msg = MessageORM(
        conversation_id=wa_conv.id,
        role="user",
        content=encrypt_message("¿Puedes avisarme mañana?"),
    )
    asst_msg = MessageORM(
        conversation_id=wa_conv.id,
        role="assistant",
        content=encrypt_message("Listo, te aviso mañana a las 9."),
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        wa_conv
    )
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        user_msg,
        asst_msg,
    ]

    block = build_other_surface_context_block(db, uid, "pc")

    assert "CONTINUIDAD" in block
    assert "WHATSAPP" in block
    assert "¿Puedes avisarme mañana?" in block
    assert "Listo, te aviso mañana" in block
    exchange_part = block.split("=== LO RECIENTE", 1)[-1]
    assert "canal" not in exchange_part.lower()


def test_build_system_prompt_injects_cross_surface_for_pc():
    uid = str(uuid.uuid4())
    cross_block = (
        "=== CONTINUIDAD (mismo DOT en PC y WhatsApp) ===\n"
        "=== LO RECIENTE EN WHATSAPP ===\n"
        "Tú: Recuérdame la reunión"
    )
    with patch(
        "app.services.cross_surface_context.build_other_surface_context_block",
        return_value=cross_block,
    ):
        with patch("app.services.memory_service.build_memory_prompt_block", return_value=""):
            with patch(
                "app.services.user_context_service.build_user_context_block",
                return_value="",
            ):
                prompt = build_system_prompt(uid, "¿qué te pedí por WhatsApp?", surface="pc", db=MagicMock())

    assert "Recuérdame la reunión" in prompt
    assert prompt.find("Recuérdame la reunión") < prompt.find("Eres DOT")
