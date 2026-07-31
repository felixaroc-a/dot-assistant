"""Endpoints de analytics para el dashboard administrativo (E06).

GET /v1/admin/analytics/overview   — metricas resumen del mes
GET /v1/admin/analytics/daily      — serie diaria de actividad
GET /v1/admin/analytics/top-users  — top 20 usuarios por consumo IA
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.billing_db import get_billing_db
from app.services.admin_analytics_service import (
    build_daily_series,
    build_overview,
    build_top_users,
)
from app.settings import settings

router = APIRouter(tags=["admin"])
log = logging.getLogger("dot.admin_analytics")


def _require_admin_key(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> None:
    configured = settings.admin_api_key.strip()
    if not configured:
        raise HTTPException(status_code=403, detail="Admin API key no configurada en el servidor.")
    if not x_admin_key or x_admin_key.strip() != configured:
        raise HTTPException(status_code=403, detail="Admin API key invalida.")


@router.get("/v1/admin/analytics/overview")
def analytics_overview(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_billing_db),
):
    """Metricas resumen del mes actual.

    Requiere X-Admin-Key.
    """
    _require_admin_key(x_admin_key)
    return build_overview(db)


@router.get("/v1/admin/analytics/daily")
def analytics_daily(
    days: int = Query(default=30, ge=1, le=365, description="Dias hacia atras desde hoy"),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_billing_db),
):
    """Serie diaria de actividad (logins, mensajes, costo IA, nuevos usuarios).

    Requiere X-Admin-Key.
    """
    _require_admin_key(x_admin_key)
    return build_daily_series(db, days=days)


@router.get("/v1/admin/analytics/top-users")
def analytics_top_users(
    limit: int = Query(default=20, ge=1, le=100),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    db: Session = Depends(get_billing_db),
):
    """Top N usuarios por consumo IA del mes.

    Requiere X-Admin-Key.
    """
    _require_admin_key(x_admin_key)
    return build_top_users(db, limit=limit)
