"""FREE-M06: embeddings locales ligeros para hechos de memoria.

Implementación sin dependencias pesadas: feature hashing bag-of-words
normalizado (TF-IDF-like). Cosine similarity para búsqueda semántica aproximada.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from difflib import SequenceMatcher
from typing import Any

EMBED_DIM = 256
MAX_STORED_DIM = 128
EMBED_PRECISION = 4
MAX_EMBEDDING_FIELD_BYTES = 4000

_TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokeniza texto en palabras alfanuméricas (español básico)."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _hash_bucket(token: str, dim: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def bag_of_words_vector(tokens: list[str], dim: int = EMBED_DIM) -> list[float]:
    """Vector bag-of-words con feature hashing; L2-normalizado."""
    if dim <= 0:
        return []
    if not tokens:
        return [0.0] * dim

    vec = [0.0] * dim
    for token in tokens:
        idx = _hash_bucket(token, dim)
        vec[idx] += 1.0

    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0.0:
        return vec
    return [x / norm for x in vec]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Similitud coseno entre dos vectores del mismo tamaño."""
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def embed_fact_text(text: str, *, dim: int = EMBED_DIM) -> list[float]:
    """Genera embedding local normalizado para un hecho o consulta."""
    tokens = tokenize(text)
    return bag_of_words_vector(tokens, dim=dim)


def fact_to_embed_text(fact: dict[str, Any]) -> str:
    """Texto canónico de un hecho para embedding o similitud de strings."""
    key = str(fact.get("key", "")).strip()
    value = fact.get("value", "")
    fact_type = str(fact.get("type", "context")).strip() or "context"
    if isinstance(value, str):
        value = value.strip()
    return f"[{fact_type}] {key}: {value}"


def truncate_embedding(vec: list[float], max_dim: int = MAX_STORED_DIM) -> list[float]:
    """Recorta vector para reducir tamaño en Firestore."""
    if max_dim <= 0:
        return []
    return list(vec[:max_dim])


def round_embedding(vec: list[float], precision: int = EMBED_PRECISION) -> list[float]:
    """Redondea floats para payload más compacto."""
    if precision < 0:
        return list(vec)
    return [round(x, precision) for x in vec]


def embedding_storage_payload(vec: list[float]) -> dict[str, Any]:
    """Prepara campo(s) de embedding para Firestore; hash si el payload es grande."""
    stored = round_embedding(truncate_embedding(vec))
    try:
        encoded = json.dumps(stored, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded = ""

    if encoded and len(encoded.encode("utf-8")) <= MAX_EMBEDDING_FIELD_BYTES:
        return {"embedding": stored, "embedding_dim": len(stored)}

    digest = hashlib.sha256(json.dumps(vec, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"embedding_hash": digest[:32], "embedding_dim": len(vec)}


def parse_stored_embedding(fact: dict[str, Any]) -> list[float] | None:
    """Recupera vector almacenado en un hecho, si existe."""
    raw = fact.get("embedding")
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [float(x) for x in raw]
    except (TypeError, ValueError):
        return None


def string_similarity_score(query: str, fact: dict[str, Any]) -> float:
    """Fallback de similitud basado en texto cuando no hay vectores."""
    fact_text = fact_to_embed_text(fact)
    if not query.strip() or not fact_text.strip():
        return 0.0
    query_norm = query.strip().lower()
    fact_norm = fact_text.strip().lower()
    if query_norm == fact_norm:
        return 1.0
    return SequenceMatcher(None, query_norm, fact_norm).ratio()


def score_fact_similarity(
    fact: dict[str, Any],
    *,
    query: str,
    query_vec: list[float] | None,
    use_embeddings: bool,
) -> float:
    """Puntúa un hecho frente a una consulta (vector o string fallback)."""
    if use_embeddings and query_vec is not None:
        stored = parse_stored_embedding(fact)
        if stored is not None:
            if len(stored) != len(query_vec):
                stored = truncate_embedding(stored, len(query_vec))
            score = cosine_similarity(query_vec, stored)
            if score > 0.0:
                return score
    return string_similarity_score(query, fact)


def rank_facts_by_similarity(
    facts: list[dict[str, Any]],
    query: str,
    *,
    query_vec: list[float] | None = None,
    top_k: int = 5,
    use_embeddings: bool = False,
) -> list[tuple[dict[str, Any], float]]:
    """Ordena hechos por similitud descendente."""
    if not facts or top_k <= 0 or not query.strip():
        return []

    scored: list[tuple[dict[str, Any], float]] = []
    for fact in facts:
        if not fact.get("is_active", True):
            continue
        score = score_fact_similarity(
            fact,
            query=query,
            query_vec=query_vec,
            use_embeddings=use_embeddings,
        )
        scored.append((fact, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]
