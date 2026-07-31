"""Interfaz abstracta para transportes WhatsApp (backend).

Define el contrato que toda implementación de transporte WhatsApp debe
cumplir en el backend, independientemente del proveedor (OpenClaw, mock, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class SendResult:
    """Resultado de un intento de envío de mensaje."""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class TransportStatus:
    """Estado actual del transporte WhatsApp."""

    state: str = "idle"
    linked: bool = False
    daemon_running: bool = False
    phone_number: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class WhatsappTransport(Protocol):
    """Protocolo que define la interfaz del transporte WhatsApp.

    Toda implementación concreta (OpenClawTransport, MockTransport) debe
    cumplir este protocolo.
    """

    async def send_message(self, to: str, text: str) -> SendResult:
        """Envía un mensaje WhatsApp.

        Args:
            to: Destino en formato E.164.
            text: Texto del mensaje.

        Returns:
            SendResult con éxito/fallo.
        """
        ...

    async def get_status(self) -> TransportStatus:
        """Obtiene el estado actual del transporte.

        Returns:
            TransportStatus con estado actual.
        """
        ...

    async def health_check(self) -> bool:
        """Verifica si el transporte está operativo.

        Returns:
            True si el transporte responde.
        """
        ...

    async def disconnect(self) -> bool:
        """Solicita la desconexión del canal WhatsApp.

        Returns:
            True si la desconexión fue exitosa.
        """
        ...

    async def request_qr(self) -> Optional[str]:
        """Solicita un nuevo QR para vinculación.

        Returns:
            Payload del QR como string, o None si no está disponible.
        """
        ...
