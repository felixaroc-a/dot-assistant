"""Servicio de búsqueda full-text con pg_trgm similarity.

En Postgres, usa la extensión pg_trgm para búsqueda por similitud
trigráfica con ranking. En SQLite, usa ILIKE como fallback.

Auto-detection: PG_TRGM_ENABLED se determina al hacer una query
de prueba contra la BD. Si la extensión no existe, usa ILIKE.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("dot.search")

_TRGM_SIMILARITY_THRESHOLD = 0.15  # Mínimo para similarity (0.0-1.0)
_TRGM_WORD_SIMILARITY_THRESHOLD = 0.3  # Mínimo para word_similarity

# Cache: True si pg_trgm está disponible, False si no, None si no verificado
_pg_trgm_available: bool | None = None
_pg_trgm_checked: bool = False


def _detect_pg_trgm(db: Session) -> bool:
    """Detecta si la extensión pg_trgm está instalada en la BD.

    Hace una query ligera contra pg_extension. Cachea el resultado
    por sesión de proceso.
    """
    global _pg_trgm_available, _pg_trgm_checked

    if _pg_trgm_checked:
        return _pg_trgm_available is True

    _pg_trgm_checked = True

    try:
        dialect_name = db.bind.dialect.name if db.bind else ""
        if dialect_name != "postgresql":
            _pg_trgm_available = False
            log.debug("pg_trgm: no aplica para %s, usando ILIKE fallback", dialect_name)
            return False

        result = db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        ).scalar()
        _pg_trgm_available = result == 1
        if _pg_trgm_available:
            log.info("pg_trgm: extensión detectada, usando similarity para búsqueda")
        else:
            log.warning(
                "pg_trgm: extensión NO instalada en Postgres. "
                "Ejecuta: psql -d nordik_billing -f infra/billing/pg_trgm.sql"
            )
        return _pg_trgm_available
    except Exception as exc:
        log.warning("pg_trgm: no se pudo verificar extensión (%s), usando ILIKE fallback", exc)
        _pg_trgm_available = False
        return False


def full_text_search(
    db: Session,
    table_name: str,
    column_name: str,
    query: str,
    threshold: float = _TRGM_SIMILARITY_THRESHOLD,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Búsqueda full-text con pg_trgm similarity + ranking.

    En Postgres con pg_trgm:
        SELECT *, similarity(col, query) AS score
        FROM table
        WHERE similarity(col, query) > threshold
        ORDER BY score DESC
        LIMIT N

    En SQLite / sin pg_trgm:
        SELECT * FROM table WHERE col ILIKE '%query%' LIMIT N

    Args:
        db: Sesión SQLAlchemy activa.
        table_name: Nombre de la tabla (ej: "chat_conversations").
        column_name: Nombre de la columna a buscar (ej: "title").
        query: Texto de búsqueda.
        threshold: Umbral de similitud para pg_trgm (0.0-1.0).
        limit: Máximo de resultados.

    Returns:
        Lista de diccionarios con las filas encontradas + campo "score".
    """
    needle = (query or "").strip()
    if not needle:
        return []

    if _detect_pg_trgm(db):
        # Postgres con pg_trgm: similarity + ranking
        sql = text(f"""
            SELECT
                *,
                similarity({column_name}, :needle) AS score
            FROM {table_name}
            WHERE similarity({column_name}, :needle) > :threshold
            ORDER BY score DESC
            LIMIT :limit
        """)
        result = db.execute(sql, {
            "needle": needle,
            "threshold": threshold,
            "limit": limit,
        })

        rows = []
        for row in result:
            row_dict = dict(row._mapping)
            rows.append(row_dict)
        return rows
    else:
        # SQLite / fallback: ILIKE
        sql = text(f"""
            SELECT *
            FROM {table_name}
            WHERE {column_name} ILIKE :pattern
            LIMIT :limit
        """)
        result = db.execute(sql, {
            "pattern": f"%{needle}%",
            "limit": limit,
        })

        rows = []
        for row in result:
            row_dict = dict(row._mapping)
            row_dict["score"] = 0.0  # Sin ranking en ILIKE
            rows.append(row_dict)
        return rows


def pg_trgm_status(db: Session) -> dict[str, Any]:
    """Devuelve el estado de pg_trgm para monitoreo/health checks.

    Returns:
        Dict con: enabled, dialect, extension_installed, message.
    """
    try:
        dialect_name = db.bind.dialect.name if db.bind else "unknown"
    except Exception:
        dialect_name = "unknown"

    available = _detect_pg_trgm(db)

    if dialect_name == "sqlite" or dialect_name == "sqlite+pysqlite":
        return {
            "enabled": False,
            "dialect": dialect_name,
            "extension_installed": False,
            "mode": "ILIKE (fallback)",
            "message": "SQLite no soporta pg_trgm; usando ILIKE como fallback.",
        }

    if available:
        return {
            "enabled": True,
            "dialect": dialect_name,
            "extension_installed": True,
            "mode": "pg_trgm similarity",
            "message": "pg_trgm activo con índices GIN y ranking por similarity.",
        }

    return {
        "enabled": False,
        "dialect": dialect_name,
        "extension_installed": False,
        "mode": "ILIKE (fallback)",
        "message": (
            "pg_trgm NO instalado. Ejecuta: "
            "psql -d nordik_billing -f infra/billing/pg_trgm.sql"
        ),
    }
