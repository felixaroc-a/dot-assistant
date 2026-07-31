"""Servicio de analytics para el dashboard administrativo (E06).

Proporciona metricas agregadas desde la BD billing (Postgres):
- Usuarios activos (hoy, semana, mes)
- Consumo IA del mes
- Pendrives activos, recargas, churn estimado
- Top usuarios por consumo
- Serie diaria de actividad
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.billing_models import ClienteORM, UsageTokenORM
from app.settings import settings

log = logging.getLogger("dot.admin_analytics")

USAGE_LIMIT_CODE = "ai_usage_limit_exceeded"


def _billing_today() -> date:
    from app.services.usage_service import billing_today

    return billing_today()


def _today() -> date:
    return _billing_today()


def _first_of_month() -> date:
    today = _today()
    return date(today.year, today.month, 1)


# ─── Active Users ───────────────────────────────────────


def _count_distinct_clients(db: Session, *, since: date) -> int:
    cnt = db.scalar(
        select(func.count(func.distinct(UsageTokenORM.cliente_id))).where(
            UsageTokenORM.fecha >= since,
        )
    )
    return int(cnt or 0)


def usuarios_activos_hoy(db: Session) -> int:
    return _count_distinct_clients(db, since=_today())


def usuarios_activos_semana(db: Session) -> int:
    return _count_distinct_clients(db, since=_today() - timedelta(days=7))


def usuarios_activos_mes(db: Session) -> int:
    return _count_distinct_clients(db, since=_today() - timedelta(days=30))


# ─── IA Consumption ─────────────────────────────────────


def consumo_ia_mes(db: Session) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(UsageTokenORM.costo_total), 0)).where(
            UsageTokenORM.fecha >= _first_of_month(),
            UsageTokenORM.fecha <= _today(),
            UsageTokenORM.operation != "recarga_ia",
            UsageTokenORM.costo_total > 0,
        )
    )
    return Decimal(str(total or 0))


def ganancia_estimada(db: Session) -> Decimal:
    consumo = consumo_ia_mes(db)
    return (consumo * Decimal("0.25")).quantize(Decimal("0.01"))


# ─── Pendrives & Recargas ───────────────────────────────


def pendrives_activos(db: Session) -> int:
    cnt = db.scalar(
        select(func.count(ClienteORM.id)).where(
            ClienteORM.pendrive_status == "active",
        )
    )
    return int(cnt or 0)


def recargas_solicitadas_mes(db: Session) -> int:
    cnt = db.scalar(
        select(func.count(UsageTokenORM.id)).where(
            UsageTokenORM.operation == "recarga_ia",
            UsageTokenORM.fecha >= _first_of_month(),
            UsageTokenORM.fecha <= _today(),
        )
    )
    return int(cnt or 0)


# ─── Churn ──────────────────────────────────────────────


def tasa_churn_estimada(db: Session) -> float:
    total = db.scalar(select(func.count(ClienteORM.id)))
    total = int(total or 0)
    if total == 0:
        return 0.0
    inactivos = _count_distinct_clients(db, since=_today() - timedelta(days=30))
    activos_recientes = inactivos
    # Inactivos = total - usuarios que estuvieron activos en los ultimos 30 dias
    churn_count = max(0, total - activos_recientes)
    return round((churn_count / total) * 100, 1)


# ─── Overview ───────────────────────────────────────────


def build_overview(db: Session) -> dict:
    consumo = consumo_ia_mes(db)
    return {
        "usuarios_activos_hoy": usuarios_activos_hoy(db),
        "usuarios_activos_semana": usuarios_activos_semana(db),
        "usuarios_activos_mes": usuarios_activos_mes(db),
        "consumo_ia_total_mes": round(float(consumo), 2),
        "ganancia_estimada": round(float(ganancia_estimada(db)), 2),
        "pendrives_activos": pendrives_activos(db),
        "recargas_solicitadas": recargas_solicitadas_mes(db),
        "tasa_churn_estimada": tasa_churn_estimada(db),
        "periodo": {
            "hoy": _today().isoformat(),
            "inicio_mes": _first_of_month().isoformat(),
        },
    }


# ─── Daily Time Series ──────────────────────────────────


def build_daily_series(db: Session, *, days: int = 30) -> list[dict]:
    if days <= 0:
        days = 30
    start = _today() - timedelta(days=days - 1)

    rows = (
        db.execute(
            select(
                UsageTokenORM.fecha,
                func.count(func.distinct(UsageTokenORM.cliente_id)).label("logins"),
                func.count(UsageTokenORM.id)
                .filter(UsageTokenORM.operation == "chat")
                .label("mensajes_chat"),
                func.count(UsageTokenORM.id)
                .filter(UsageTokenORM.operation.in_(["wa_outbound", "wa_inbound"]))
                .label("mensajes_wa"),
                func.coalesce(
                    func.sum(UsageTokenORM.costo_total).filter(UsageTokenORM.costo_total > 0),
                    0,
                ).label("costo_ia"),
            )
            .where(
                UsageTokenORM.fecha >= start,
                UsageTokenORM.fecha <= _today(),
            )
            .group_by(UsageTokenORM.fecha)
            .order_by(UsageTokenORM.fecha)
        )
        .mappings()
        .all()
    )

    lookup = {
        row["fecha"]: {
            "fecha": row["fecha"].isoformat(),
            "logins": int(row["logins"] or 0),
            "mensajes_chat": int(row["mensajes_chat"] or 0),
            "mensajes_wa": int(row["mensajes_wa"] or 0),
            "costo_ia": round(float(row["costo_ia"] or 0), 4),
            "nuevos_usuarios": 0,
        }
        for row in rows
    }

    # Rellenar dias sin datos
    result = []
    cursor = start
    while cursor <= _today():
        iso = cursor.isoformat()
        if cursor in lookup:
            result.append(lookup[cursor])
        else:
            result.append(
                {
                    "fecha": iso,
                    "logins": 0,
                    "mensajes_chat": 0,
                    "mensajes_wa": 0,
                    "costo_ia": 0,
                    "nuevos_usuarios": 0,
                }
            )
        cursor += timedelta(days=1)

    return result


# ─── Top Users ──────────────────────────────────────────


def build_top_users(db: Session, *, limit: int = 20) -> list[dict]:
    first = _first_of_month()
    today = _today()

    rows = (
        db.execute(
            select(
                UsageTokenORM.cliente_id,
                ClienteORM.nombre,
                func.coalesce(
                    func.sum(UsageTokenORM.costo_total).filter(UsageTokenORM.costo_total > 0),
                    0,
                ).label("consumo_usd"),
                func.count(UsageTokenORM.id).label("mensajes_totales"),
            )
            .join(ClienteORM, UsageTokenORM.cliente_id == ClienteORM.id)
            .where(
                UsageTokenORM.fecha >= first,
                UsageTokenORM.fecha <= today,
                UsageTokenORM.operation != "recarga_ia",
            )
            .group_by(UsageTokenORM.cliente_id, ClienteORM.nombre)
            .order_by(text("consumo_usd DESC"))
            .limit(limit)
        )
        .mappings()
        .all()
    )

    return [
        {
            "cliente_id": str(row["cliente_id"]),
            "nombre": row["nombre"] or "Sin nombre",
            "consumo_usd": round(float(row["consumo_usd"] or 0), 4),
            "mensajes_totales": int(row["mensajes_totales"] or 0),
        }
        for row in rows
    ]
