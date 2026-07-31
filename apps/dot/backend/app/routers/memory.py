"""Router de memoria del usuario (T08) + búsqueda semántica sobre snapshot.

Endpoints:
  - GET  /users/me/memory          → resumen legacy
  - PATCH /users/me/memory          → actualizar resumen
  - DELETE /users/me/memory         → borrar resumen
  - GET  /v1/memory                 → resumen + hechos atómicos (UI)
  - GET  /v1/memory/search?q=&top_k= → búsqueda semántica
  - DELETE /v1/memory/facts/{fact_id} → olvidar un hecho
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth_deps import claims_uid, require_product_jwt
from app.firebase_db import merge_user_profile
from app.services.memory_persistence import search_memory
from app.services.memory_service import forget_memory_fact, get_memory, get_memory_facts
from app.services.metrics_service import metrics

router = APIRouter(prefix="/users/me", tags=["memory"])

# Router de búsqueda semántica (prefijo /v1/memory)
search_router = APIRouter(prefix="/v1/memory", tags=["memory_search"])


def _serialize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif hasattr(value, "to_datetime"):
        try:
            dt = value.to_datetime()  # type: ignore[union-attr]
        except (TypeError, ValueError, AttributeError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _serialize_fact_for_api(fact: dict[str, Any]) -> dict[str, Any]:
    """Expone hechos al cliente sin vectores de embedding."""
    return {
        "fact_id": fact.get("fact_id"),
        "type": fact.get("type"),
        "key": fact.get("key"),
        "value": fact.get("value"),
        "confidence": fact.get("confidence"),
        "updated_at": _serialize_timestamp(
            fact.get("updated_at") or fact.get("created_at")
        ),
    }


@router.get("/memory")
def get_user_memory(claims: dict = Depends(require_product_jwt)):
    uid = claims_uid(claims)
    memory = get_memory(uid)
    return memory or {"facts": [], "preferences": [], "version": 1}


@router.patch("/memory")
def patch_user_memory(
    body: dict,
    claims: dict = Depends(require_product_jwt),
):
    uid = claims_uid(claims)
    merge_user_profile(uid, {"memory_summary": body})
    return {"ok": True}


@router.delete("/memory")
def delete_user_memory(claims: dict = Depends(require_product_jwt)):
    uid = claims_uid(claims)
    merge_user_profile(uid, {"memory_summary": None})
    return {"ok": True}


@search_router.get("")
def get_user_memory_overview(
    limit: int = Query(default=200, ge=1, le=300, description="Máximo de hechos"),
    claims: dict = Depends(require_product_jwt),
):
    """Resumen en prosa y hechos atómicos activos para la UI «Lo que recuerdo»."""
    uid = claims_uid(claims)
    summary = get_memory(uid) or ""
    facts = get_memory_facts(uid, limit=limit)
    serialized = [_serialize_fact_for_api(fact) for fact in facts]
    metrics.track_memory_operation("recall")
    return {
        "summary": summary,
        "facts": serialized,
        "total": len(serialized),
    }


@search_router.delete("/facts/{fact_id}")
def forget_user_memory_fact(
    fact_id: str,
    claims: dict = Depends(require_product_jwt),
):
    """Marca un hecho atómico como inactivo (olvidar)."""
    uid = claims_uid(claims)
    if not forget_memory_fact(uid, fact_id):
        raise HTTPException(status_code=404, detail="Hecho no encontrado")
    metrics.track_memory_operation("forget")
    return {"ok": True, "fact_id": fact_id.strip()}


@search_router.get("/search")
def search_user_memory(
    q: str = Query(..., min_length=1, description="Texto de búsqueda"),
    top_k: int = Query(default=5, ge=1, le=20, description="Cantidad máxima de resultados"),
    claims: dict = Depends(require_product_jwt),
):
    """Búsqueda semántica sobre la memoria del usuario.

    Busca en:
      - Snapshot markdown (users/{uid}/memory/snapshot)
      - Hechos atómicos (users/{uid}/memory/facts/*)

    Si MEMORY_EMBEDDINGS_ENABLED=true usa cosine sobre embeddings;
    si no, usa similitud de texto (SequenceMatcher).

    Returns:
        Lista de resultados con snippet, score y source.
    """
    uid = claims_uid(claims)
    results = search_memory(uid, q, top_k=top_k)
    metrics.track_memory_operation("search")
    return {
        "query": q,
        "results": results,
        "total": len(results),
    }
