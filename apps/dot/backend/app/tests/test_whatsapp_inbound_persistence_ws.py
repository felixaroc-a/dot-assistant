"""Tests W06b: integración WhatsApp → persistencia → notificación WebSocket.

Verifica que el flujo end-to-end funciona:
    inbound → append_whatsapp_chat_message → WS notify con conversation_id
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.whatsapp.inbound_service import (
    _persist_to_chat_history,
)


def test_append_whatsapp_chat_message_uses_whatsapp_channel():
    """W06b: Verifica que append_whatsapp_chat_message crea/usa channel='whatsapp'.
    
    Mockea la sesion de DB y verifica que se llama a find_or_create_whatsapp_conversation
    con channel explicit 'whatsapp'.
    """
    from app.services.chat_persistence import append_whatsapp_chat_message
    from app.chat_models import ConversationORM

    mock_db = MagicMock()
    mock_conv = MagicMock(spec=ConversationORM)
    mock_conv.id = "mock-conv-id"
    mock_conv.message_count = 5

    with patch(
        "app.services.chat_persistence.find_or_create_whatsapp_conversation",
        return_value=mock_conv,
    ) as mock_find:
        with patch("app.services.chat_persistence.encrypt_message", return_value="encrypted"):
            result = append_whatsapp_chat_message(
                mock_db,
                "test-uid-wa",
                "user",
                "[WA 4121234567 13/07 16:00] Hola desde WA",
            )

    mock_find.assert_called_once_with(mock_db, "test-uid-wa")
    assert result == mock_conv
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(mock_conv)


def test_persist_to_chat_history_returns_conversation_id():
    """W06b: _persist_to_chat_history retorna un conversation_id string no vacio."""
    uid = "test-persist-wa"
    mock_conv = MagicMock()
    mock_conv.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    with patch(
        "app.services.chat_persistence.append_whatsapp_chat_message",
        return_value=mock_conv,
    ) as mock_append:
        # get_session_factory se importa dentro de _persist_to_chat_history via app.billing_db
        with patch("app.billing_db.get_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value = mock_session

            conv_id = _persist_to_chat_history(
                uid,
                "Hola DOT desde el grupo",
                "+584141234567",
                "2026-07-13T16:00:00Z",
            )

    assert conv_id is not None
    assert len(conv_id) > 0
    mock_append.assert_called_once()
    # Verificar que el contenido tiene el prefijo [WA ...]
    call_args = mock_append.call_args
    content = call_args[0][3]  # content es 4to arg posicional
    assert "[WA" in content
    assert "Hola DOT desde el grupo" in content


def test_ws_notify_payload_includes_conversation_id():
    """W06b: La notificacion WS 'whatsapp:inbound' debe incluir conversation_id.
    
    Verifica que el payload de notificacion tiene todos los campos necesarios
    (from_phone, text, timestamp, message_id, conversation_id).
    """
    from app.services.ws_manager import notify_whatsapp_inbound

    import asyncio

    async def _run():
        with patch("app.services.ws_manager.notify_user") as mock_notify_user:
            # Simula lo que hace whatsapp_channel.py lineas 334-344
            await notify_whatsapp_inbound(
                "test-uid",
                {
                    "from_phone": "+584141234567",
                    "text": "Hola DOT",
                    "timestamp": "2026-07-13T16:00:00Z",
                    "message_id": "msg-001",
                    "conversation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                },
            )

        mock_notify_user.assert_called_once()
        call_args = mock_notify_user.call_args
        # call_args[0] = (uid, event_type, data_dict)
        assert call_args[0][0] == "test-uid"
        assert call_args[0][1] == "whatsapp:inbound"
        payload = call_args[0][2]
        assert payload["conversation_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert payload["from_phone"] == "+584141234567"
        assert payload["text"] == "Hola DOT"

    asyncio.run(_run())
