"""Servicio Signal Bridge — skeleton con signal-cli.

Gestiona el estado del canal Signal (Firestore) y el envío de mensajes via signal-cli.
Gate: SIGNAL_ENABLED=true en .env.
Requiere signal-cli instalado y una cuenta registrada (signal-cli register).

En producción, signal-cli se ejecuta como proceso dbus o via REST wrapper.
En desarrollo, se usa signal-cli directamente via subprocess (JSON-RPC o modo texto).
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.settings import settings

log = logging.getLogger("dot.signal_service")


# ─── Estado del canal ─────────────────────────────────────────────────

@dataclass
class SignalChannelStatus:
    linked: bool = False
    phone_number: str | None = None
    last_linked_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_at: str | None = None
    error: str | None = None


def get_signal_channel_state(db) -> SignalChannelStatus:
    """Obtiene el estado actual del canal Signal desde settings + env.

    En producción, esto consultaría Firestore (similar a whatsapp_link.py).
    Por ahora es un skeleton que devuelve el estado basado en env vars.
    """
    enabled = bool(settings.signal_enabled)
    phone = (os.getenv("SIGNAL_PHONE_NUMBER") or "").strip()

    return SignalChannelStatus(
        linked=enabled and bool(phone),
        phone_number=phone or None,
        last_linked_at=None,
        last_heartbeat_at=None,
        last_error_at=None,
        error=None if (enabled and phone) else "Signal no configurado",
    )


def update_signal_channel_state(
    db, *, linked: bool, phone_number: str | None = None, error: str | None = None
) -> None:
    """Actualiza el estado del canal Signal. Skeleton — en producción usa Firestore."""
    log.info(
        "signal_channel_state_update linked=%s phone=%s error=%s",
        linked,
        phone_number,
        error,
    )


def record_signal_channel_event(
    db,
    *,
    event: str,
    phone_number: str | None = None,
    error: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Registra un evento operacional del canal Signal. Skeleton."""
    log.info(
        "signal_channel_event event=%s phone=%s error=%s meta=%s",
        event,
        phone_number,
        error,
        metadata,
    )


# ─── Envío de mensajes ────────────────────────────────────────────────

def _exec_signal_cli(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Ejecuta signal-cli con argumentos dados.

    Retorna (ok, output_or_error).
    En desarrollo skeleton — requiere signal-cli en PATH.
    """
    cli_path = settings.signal_cli_path or "signal-cli"
    phone = (os.getenv("SIGNAL_PHONE_NUMBER") or "").strip()

    if not phone:
        return False, "SIGNAL_PHONE_NUMBER no configurado en variables de entorno"

    full_args = [cli_path, "-u", phone] + args

    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        output = result.stdout.strip() if ok else result.stderr.strip()
        return ok, output
    except FileNotFoundError:
        return False, (
            f"signal-cli no encontrado. Instálalo desde https://github.com/AsamK/signal-cli "
            f"o configura SIGNAL_CLI_PATH en .env. Path buscado: {cli_path}"
        )
    except subprocess.TimeoutExpired:
        return False, "signal-cli excedió el timeout de ejecución (30s)"
    except Exception as e:
        return False, f"Error ejecutando signal-cli: {e}"


def send_signal_message(
    phone: str,
    text: str,
    attachments: list[str] | None = None,
) -> dict:
    """Envía un mensaje via Signal usando signal-cli.

    Args:
        phone: Número de destino en formato internacional (+584241234567)
        text: Contenido del mensaje (máx 4096 chars)
        attachments: Lista de rutas a archivos para adjuntar

    Returns:
        dict con {ok, message_id, error}
    """
    if not settings.signal_enabled:
        return {"ok": False, "message_id": None, "error": "Canal Signal deshabilitado (SIGNAL_ENABLED=false)"}

    args = ["send", "-m", text]

    if attachments:
        for path in attachments:
            if os.path.isfile(path):
                args.extend(["-a", path])
            else:
                log.warning("signal_send attachment no existe: %s", path)

    args.append(phone)

    ok, output = _exec_signal_cli(args, timeout=45)
    msg_id = str(uuid.uuid4())[:12] if ok else None

    if ok:
        log.info("signal_send ok phone=%s msg_id=%s", phone[-8:], msg_id)
    else:
        log.warning("signal_send fail phone=%s error=%s", phone[-8:], output[:200])

    return {
        "ok": ok,
        "message_id": msg_id,
        "error": None if ok else output,
    }
