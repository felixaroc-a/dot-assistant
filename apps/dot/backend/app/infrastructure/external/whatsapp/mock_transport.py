"""Implementación Mock del transporte WhatsApp para el backend.

Usada en pruebas o cuando WHATSAPP_TRANSPORT=mock en el backend.
Devuelve respuestas fijas simulando el comportamiento real.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.domain.whatsapp.transport import SendResult, TransportStatus

log = logging.getLogger("dot.mock_transport")


class MockBackendTransport:
    """Implementación simulada del transporte WhatsApp.

    Todas las operaciones responden con datos fijos sin depender de
    OpenClaw ni del bridge de Electron.
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._phone_number: Optional[str] = "+584144001856"
        self._messages_sent: list[dict] = []

    async def send_message(self, to: str, text: str) -> SendResult:
        """Simula el envío de un mensaje WhatsApp."""
        if not to.strip():
            return SendResult(success=False, error="Destino vacío")
        if not text.strip():
            return SendResult(success=False, error="Texto vacío")

        message_id = f"mock_{hash(to + text) & 0xFFFFFFFF:08x}"
        self._messages_sent.append({
            "to": to.strip(),
            "text": text.strip(),
            "message_id": message_id,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        })
        log.info("[MOCK] Mensaje enviado a %s: %s", to, message_id)
        return SendResult(success=True, message_id=message_id)

    async def get_status(self) -> TransportStatus:
        """Retorna el estado actual simulado."""
        return TransportStatus(
            state="connected" if self._connected else "disconnected",
            linked=self._connected,
            daemon_running=self._connected,
            phone_number=self._phone_number,
        )

    async def health_check(self) -> bool:
        return self._connected

    async def disconnect(self) -> bool:
        self._connected = False
        log.info("[MOCK] Transporte desconectado")
        return True

    async def request_qr(self) -> Optional[str]:
        return "MOCK_QR_DATA_SIMULATED_FOR_TESTS"

    def set_connected(self, connected: bool) -> None:
        """Helper para tests: cambia estado simulado."""
        self._connected = connected

    def set_phone(self, phone: Optional[str]) -> None:
        """Helper para tests: cambia teléfono simulado."""
        self._phone_number = phone

    def get_messages_sent(self) -> list[dict]:
        """Helper para tests: obtiene mensajes enviados."""
        return list(self._messages_sent)

    def clear_messages(self) -> None:
        """Helper para tests: limpia mensajes enviados."""
        self._messages_sent.clear()


# Singleton
_instance: MockBackendTransport | None = None


def get_mock_backend_transport() -> MockBackendTransport:
    global _instance
    if _instance is None:
        _instance = MockBackendTransport()
    return _instance
