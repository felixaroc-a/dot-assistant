"""Job diario de retención D5 (T11) con APScheduler (AsyncIOScheduler).

T01: Migrado a AsyncIOScheduler (Jul 2026).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.settings import settings

log = logging.getLogger("dot.retention_service")


class RetentionService:
    """Programa el scan diario de purga por inactividad / no pago (3 meses)."""

    def __init__(self, enabled: bool):
        self._enabled = enabled
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        if not enabled:
            log.warning(
                "RetentionService deshabilitado (Firebase/settings); no se programará cron D5."
            )
            return

        hour = max(0, min(23, int(settings.retention_job_cron_hour_utc)))
        self._scheduler.add_job(
            self.run_once,
            trigger=CronTrigger(hour=hour, minute=0),
            id="dot_retention_d5_daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info(
            "RetentionService iniciado (cron diario %02d:00 UTC, retention_days=%d)",
            hour,
            settings.retention_days,
        )

    def run_once(self) -> dict[str, object]:
        """Ejecuta un ciclo de retención (también usable en tests / admin)."""
        if not self._enabled:
            return {"status": "disabled"}

        from app.billing_db import get_session_factory
        from app.services.data_retention import run_retention_scan

        session = get_session_factory()()
        try:
            return run_retention_scan(session)
        finally:
            session.close()

    def shutdown(self) -> None:
        if self._enabled and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("RetentionService detenido")
