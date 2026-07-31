"""WebSocket para notificaciones en tiempo real.

P0 (Manual Maestro): rechaza conexiones anónimas; requiere JWT válido.
CERTIFICADO (Jul 2026): NO existe bypass de desarrollo. Toda conexión sin
JWT válido es rechazada con WS_1008_POLICY_VIOLATION independientemente
del entorno. Si en el futuro se agrega bypass para desarrollo, gatearlo con:
  if not settings.is_production: ...
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.services.ws_manager import connect
from app.jwt_keys import get_jwt_signing_config, jwt_configured
from app.jwt_util import decode_product_token

log = logging.getLogger("dot.ws_router")

router = APIRouter(tags=["ws"])


def _extract_token(ws: WebSocket) -> str | None:
    """Extrae JWT de query param o header Authorization: Bearer."""
    token = ws.query_params.get("token", "").strip()
    if token:
        return token
    auth_header = ws.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


@router.websocket("/ws/notifications")
async def websocket_notifications(ws: WebSocket) -> None:
    token = _extract_token(ws)
    if not token:
        log.warning("WS rechazado: sin token de autenticación")
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token requerido")
        return

    if not jwt_configured():
        log.critical("WS rechazado: JWT no configurado en el servidor")
        await ws.close(code=status.WS_1011_INTERNAL_ERROR, reason="Servidor no configurado")
        return

    try:
        cfg = get_jwt_signing_config()
        payload = decode_product_token(token, cfg)
        usuario_id = str(payload.get("sub", ""))
        if not usuario_id:
            log.warning("WS rechazado: JWT sin subject")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token inválido")
            return
    except Exception as e:
        # Sin traceback: JWT expirado es ruido normal de sesión vieja (no es fallo del server).
        err_name = type(e).__name__
        if "Expired" in err_name:
            log.info("WS rechazado: JWT expirado")
        else:
            log.warning("WS rechazado: token JWT inválido (%s)", err_name)
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token inválido o expirado")
        return

    try:
        async for _ in connect(usuario_id, ws):
            while True:
                data = await ws.receive_text()
                # Por ahora ignoramos mensajes del cliente
                # En futuro: heartbeats, subscripciones
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error en WebSocket para usuario=%s", usuario_id)
