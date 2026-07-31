"""Configuracion compartida de logging JSON estructurado + Logtail forwarding."""
from __future__ import annotations

import logging
import sys

from pythonjsonlogger import jsonlogger


def configure_logging(
    service_name: str,
    level: str = "INFO",
    logtail_token: str = "",
    logtail_host: str = "",
) -> None:
    """Configura logging JSON para stdout + forwarding opcional a Logtail.

    Args:
        service_name: Nombre del servicio (ej. "nordik.api", "auto-venta1").
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR).
        logtail_token: Source token de Logtail (Better Stack). Vacio = no forwarding.
        logtail_host: Host de Logtail (default: https://logs.betterstack.com).
    """
    # Limpiar handlers existentes
    root = logging.getLogger()
    root.handlers.clear()

    # Formateador JSON
    json_fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )

    # Handler de consola (stdout) - PM2 captura esto
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(json_fmt)
    root.addHandler(console_handler)

    # Handler de Logtail (si hay token)
    if logtail_token:
        try:
            from logtail import LogtailHandler

            lt_handler = LogtailHandler(
                source_token=logtail_token,
                host=logtail_host or "https://logs.betterstack.com",
            )
            root.addHandler(lt_handler)
        except ImportError:
            root.warning("logtail-python no instalado. Logging cloud desactivado.")

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    logger = logging.getLogger(service_name)
    logger.info(
        "Logging configurado: nivel=%s, formato=JSON, logtail=%s",
        level,
        "SI" if logtail_token else "NO",
    )
