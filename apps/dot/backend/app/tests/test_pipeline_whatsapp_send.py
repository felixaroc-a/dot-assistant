"""El paso WhatsApp del pipeline debe enviar de verdad (no simular con LLM)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from worker.executor import AutomationExecutor


def test_whatsapp_integration_sends_via_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    state = MagicMock()
    state.linked = True
    state.phone_number = "+584141234567"

    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda _uid: state,
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.phone_resolver.to_e164",
        lambda x: x if str(x).startswith("+") else f"+{x}",
    )

    sent: dict[str, str] = {}

    async def fake_send(to: str, text: str):
        sent["to"] = to
        sent["text"] = text
        return True, "msg_1"

    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        fake_send,
    )

    out = AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": "Enviar por WhatsApp: hola desde pipeline",
            "integration_id": "whatsapp",
            "output_type": "whatsapp",
            "prior_output": "Resumen real del escritorio: a.txt, b.pdf",
        },
    )

    assert "enviado" in out.lower()
    assert sent["to"] == "+584141234567"
    assert "hola desde pipeline" in sent["text"]


def test_whatsapp_fails_if_not_linked(monkeypatch: pytest.MonkeyPatch) -> None:
    state = MagicMock()
    state.linked = False
    state.phone_number = None
    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda _uid: state,
    )

    with pytest.raises(RuntimeError, match="no está vinculado"):
        AutomationExecutor().execute(
            "uid-test",
            {
                "instruction": "Notificar por WhatsApp",
                "integration_id": "whatsapp",
            },
        )


def test_whatsapp_uses_prior_output_when_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    state = MagicMock()
    state.linked = True
    state.phone_number = "+584149999999"
    monkeypatch.setattr(
        "app.services.whatsapp_link.get_channel_state",
        lambda _uid: state,
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.phone_resolver.to_e164",
        lambda x: x,
    )

    sent: dict[str, str] = {}

    async def fake_send(to: str, text: str):
        sent["text"] = text
        return True, "m2"

    monkeypatch.setattr(
        "app.services.whatsapp_client.send_whatsapp_message",
        fake_send,
    )

    AutomationExecutor().execute(
        "uid-test",
        {
            "instruction": 'Enviar por WhatsApp: [Aquí se listarían los nombres]',
            "integration_id": "whatsapp",
            "prior_output": "Archivos: informe.pdf (12KB), notas.txt (1KB)",
        },
    )

    assert "informe.pdf" in sent["text"]
    assert "Aquí se listarían" not in sent["text"]
    assert '"action"' not in sent["text"]
    assert "{" not in sent["text"]
