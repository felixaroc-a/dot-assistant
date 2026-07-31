"""Servicio de memoria resumida del usuario (estilo Gemini).

Almacena memoria en Firestore:
  - Legacy: users/{uid}/profile/memory → { summary, last_updated, version }
  - Hechos atómicos (FREE-M02): users/{uid}/memory/facts/{fact_id}

B02 — MASTER-EXECUTION-PLAN §B02
FREE-M01/M02 — extracción JSON + persistencia de hechos atómicos
FREE-M03/M04 — fusión inteligente + compactación periódica de hechos
FREE-M06 — embeddings locales opcionales para recuperación semántica
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

from app.firebase_db import (
    deactivate_memory_fact,
    find_memory_fact_id_by_key,
    get_db as get_firestore_client,
    list_active_memory_facts,
    set_memory_fact,
)
from app.services.ai_provider import AIProvider
from app.services.memory_embeddings import (
    embed_fact_text,
    embedding_storage_payload,
    fact_to_embed_text,
    rank_facts_by_similarity,
    truncate_embedding,
)
from app.settings import settings

log = logging.getLogger("dot.memory_service")

# FREE-M05: límite de hechos atómicos inyectados en system prompt
# FASE 3.2: aumentado de 20 a 50 con truncado a ~4000 chars
MAX_PROMPT_MEMORY_FACTS = 50

# FREE-M04: tope de hechos activos y frecuencia de compactación
# FASE 3.2: aumentado de 150 a 300 para mayor capacidad de hechos activos
MAX_ACTIVE_MEMORY_FACTS = 300
COMPACT_FACTS_EVERY_N_UPDATES = 10
FACT_SIMILARITY_THRESHOLD = 0.85

_memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dot-memory")
_memory_update_counts: dict[str, int] = {}

VALID_FACT_TYPES = {
    "identity",
    "relationship",
    "preference",
    "routine",
    "context",
    "event",
    "data",
}
VALID_FACT_ACTIONS = {"create", "update", "delete"}

# ── Prompts (prosa — fallback M01) ───────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = (
    "Eres un asistente que extrae hechos importantes sobre usuarios a partir de conversaciones. "
    "Solo extrae datos factuales (nombre, profesión, ubicación, preferencias, rutinas, "
    "familia, trabajo). No incluyas opiniones ni información trivial. "
    "Responde en español en 1-3 oraciones."
)

EXTRACTION_USER_PROMPT = (
    "Extrae hechos importantes sobre este usuario de la siguiente conversación:\n\n"
    "Usuario: {user_msg}\n\n"
    "Asistente: {assistant_resp}\n\n"
    "Hechos importantes sobre el usuario:"
)

# ── Prompts (JSON atómico — M01) ───────────────────────────────────────────

ATOMIC_EXTRACTION_SYSTEM_PROMPT = (
    "Eres un asistente que extrae hechos atómicos sobre usuarios a partir de conversaciones. "
    "Responde SOLO con JSON válido, sin markdown ni texto adicional."
)

ATOMIC_EXTRACTION_USER_PROMPT = (
    "Analiza esta interacción y extrae HECHOS NUEVOS sobre el usuario.\n\n"
    "Usuario: {user_msg}\n\n"
    "Asistente: {assistant_resp}\n\n"
    "INSTRUCCIONES:\n"
    "1. Extrae SOLO hechos nuevos o actualizaciones relevantes\n"
    "2. Cada hecho debe ser atómico (una sola pieza de información)\n"
    "3. NO extraigas información trivial\n"
    "4. Si contradice un hecho anterior, usa action \"update\"\n"
    "5. confidence: 1.0 explícito, 0.7 implícito claro, 0.5 inferencia débil\n\n"
    "FORMATO (JSON):\n"
    '{{"facts": [{{"type": "identity|relationship|preference|routine|context|event|data", '
    '"key": "nombre_corto", "value": "valor", "confidence": 0.95, "action": "create|update|delete"}}]}}\n\n'
    "Si no hay hechos nuevos, responde: {{\"facts\": []}}"
)

MERGE_SYSTEM_PROMPT = (
    "Eres un asistente que fusiona información sobre usuarios. "
    "Tienes un resumen existente y nuevos hechos. Fusiona ambos. "
    "Si hay contradicción, actualiza con los hechos nuevos. "
    "Si es redundante, omítelo. "
    "Mantén el resultado conciso (<2000 tokens). "
    "Responde en español, en prosa natural, no en lista ni bullets."
)

MERGE_USER_PROMPT = (
    "Resumen existente:\n{existing}\n\n"
    "Nuevos hechos:\n{new_facts}\n\n"
    "Resumen fusionado:"
)

# ── Patrones de mensajes triviales (no extraer memoria) ──────────────────

_TRIVIAL_MESSAGES: set[str] = {
    "hola", "hola!", "hola.", "hola,", "hi", "hey", "hello",
    "gracias", "gracias!", "gracias.", "muchas gracias", "te lo agradezco",
    "ok", "ok.", "ok!", "oki", "okey", "vale", "vale.", "bien", "bien.",
    "adios", "chao", "bye", "nos vemos", "hasta luego", "hasta pronto",
    "buenos días", "buenas tardes", "buenas noches",
    "buenos dias", "buenas tardes", "buenas noches",
    "si", "sí", "no", "nop", "nope",
    "jajaja", "jeje", "xd", "lol", "jaja",
    "entiendo", "de acuerdo", "perfecto", "genial",
}


def _is_trivial(text: str) -> bool:
    """Determina si un mensaje es trivial y no merece extracción de memoria."""
    cleaned = text.strip().lower().rstrip(".!?,;:¡¿ ")
    if cleaned in _TRIVIAL_MESSAGES:
        return True
    if len(cleaned) < 5:
        return True
    return False


# Señales de datos personales: extraer aunque sea el primer mensaje del chat.
_PERSONAL_FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(me\s+llamo|mi\s+nombre\s+(es|)\s*|soy\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]{2,})", re.I),
    re.compile(
        r"\b(trabajo\s+(como|de|en)|soy\s+(abogad|ingenier|médic|doctor|profesor|contador|"
        r"enfermer|arquitect|programad|desarrollad|diseñad|comerciant|emprendedor))",
        re.I,
    ),
    re.compile(r"\b(vivo\s+en|soy\s+de|mi\s+(ciudad|país|pais)\b)", re.I),
    re.compile(r"\b(tengo\s+\d+\s+años|nací\s+en|mi\s+edad\b)", re.I),
    re.compile(r"\b(mi\s+(espos|esposa|marido|mujer|hij|padre|madre|herman))\b", re.I),
)

# Preguntas de recuerdo → hint visible "DOT te recuerda que…"
_RECALL_INTENTS: tuple[tuple[re.Pattern[str], tuple[str, ...], str], ...] = (
    (
        re.compile(
            r"\b(c[oó]mo\s+me\s+llamo|cu[aá]l\s+es\s+mi\s+nombre|recuerdas?\s+mi\s+nombre)\b",
            re.I,
        ),
        ("nombre", "name"),
        "te llamas {value}",
    ),
    (
        re.compile(
            r"\b(qu[eé]\s+trabajo\s+hago|a\s+qu[eé]\s+me\s+dedic|"
            r"cu[aá]l\s+es\s+mi\s+(profesi[oó]n|trabajo|oficio))\b",
            re.I,
        ),
        ("profesion", "profesión", "trabajo", "oficio", "ocupacion", "ocupación"),
        "trabajas como {value}",
    ),
)


def _contains_personal_fact_signal(text: str) -> bool:
    """True si el usuario comparte o corrige datos personales (nombre, trabajo, etc.)."""
    cleaned = text.strip()
    if not cleaned or _is_trivial(cleaned):
        return False
    return any(pattern.search(cleaned) for pattern in _PERSONAL_FACT_PATTERNS)


def _get_provider() -> AIProvider:
    """Crea una instancia de AIProvider (sin DI)."""
    return AIProvider()


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _normalize_fact(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Valida y normaliza un hecho extraído del LLM."""
    if not isinstance(raw, dict):
        return None

    fact_type = str(raw.get("type", "context")).strip().lower()
    if fact_type not in VALID_FACT_TYPES:
        fact_type = "context"

    key = str(raw.get("key", "")).strip()
    if not key:
        return None

    value = raw.get("value")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        value = value.strip()

    try:
        confidence = float(raw.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    action = str(raw.get("action", "create")).strip().lower()
    if action not in VALID_FACT_ACTIONS:
        action = "create"

    category = raw.get("category")
    if category is not None:
        category = str(category).strip() or None

    return {
        "type": fact_type,
        "key": key,
        "value": value,
        "confidence": confidence,
        "action": action,
        "category": category,
    }


def _parse_atomic_facts_response(raw: str) -> list[dict[str, Any]] | None:
    """Parsea respuesta JSON del LLM; None si falla el parseo."""
    try:
        payload = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        return None

    facts: list[dict[str, Any]] = []
    for item in raw_facts:
        normalized = _normalize_fact(item)
        if normalized:
            facts.append(normalized)
    return facts


def _extract_atomic_facts(
    provider: AIProvider,
    user_msg: str,
    assistant_resp: str,
) -> list[dict[str, Any]] | None:
    """Intenta extracción atómica JSON; None si el LLM no devolvió JSON válido."""
    extraction_input = ATOMIC_EXTRACTION_USER_PROMPT.format(
        user_msg=user_msg,
        assistant_resp=assistant_resp,
    )
    raw = provider.simple_chat(extraction_input, ATOMIC_EXTRACTION_SYSTEM_PROMPT).strip()
    if not raw:
        return None
    return _parse_atomic_facts_response(raw)


def _extract_prose_facts(
    provider: AIProvider,
    user_msg: str,
    assistant_resp: str,
) -> str:
    """Fallback M01: extracción en prosa (comportamiento legacy)."""
    extraction_input = EXTRACTION_USER_PROMPT.format(
        user_msg=user_msg,
        assistant_resp=assistant_resp,
    )
    return provider.simple_chat(extraction_input, EXTRACTION_SYSTEM_PROMPT).strip()


def _facts_to_prose(facts: list[dict[str, Any]]) -> str:
    """Convierte hechos atómicos a texto para fusionar con el resumen legacy."""
    lines: list[str] = []
    for fact in facts:
        key = fact.get("key", "")
        value = fact.get("value", "")
        fact_type = fact.get("type", "context")
        lines.append(f"[{fact_type}] {key}: {value}")
    return "\n".join(lines)


def _normalize_compare_text(value: Any) -> str:
    """Normaliza texto para comparar duplicados / near-duplicates."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _fact_category_bucket(fact: dict[str, Any]) -> str:
    """Bucket de categoría para agrupar hechos similares (M03)."""
    category = fact.get("category")
    if category is not None and str(category).strip():
        return str(category).strip().lower()
    return str(fact.get("type", "context")).strip().lower() or "context"


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _facts_are_similar(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """True si comparten categoría y key/value son iguales o casi iguales."""
    if _fact_category_bucket(existing) != _fact_category_bucket(incoming):
        return False

    key_a = _normalize_compare_text(existing.get("key"))
    key_b = _normalize_compare_text(incoming.get("key"))
    val_a = _normalize_compare_text(existing.get("value"))
    val_b = _normalize_compare_text(incoming.get("value"))

    if key_a and key_b and key_a == key_b:
        return True
    if val_a and val_b and val_a == val_b:
        return True
    if key_a and key_b and _text_similarity(key_a, key_b) >= FACT_SIMILARITY_THRESHOLD:
        return True
    if val_a and val_b and _text_similarity(val_a, val_b) >= FACT_SIMILARITY_THRESHOLD:
        return True
    return False


def _find_merge_candidate(
    existing_facts: list[dict[str, Any]],
    incoming: dict[str, Any],
) -> dict[str, Any] | None:
    """Busca hecho existente por key exacta o near-duplicate (M03)."""
    incoming_key = _normalize_compare_text(incoming.get("key"))
    for existing in existing_facts:
        if not existing.get("is_active", True):
            continue
        if _normalize_compare_text(existing.get("key")) == incoming_key and incoming_key:
            return existing
    for existing in existing_facts:
        if not existing.get("is_active", True):
            continue
        if _facts_are_similar(existing, incoming):
            return existing
    return None


def _merge_fact_payload(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Fusiona hecho entrante sobre existente (confianza, valor, timestamps)."""
    now = datetime.now(timezone.utc)
    existing_conf = float(existing.get("confidence", 0.5))
    incoming_conf = float(incoming.get("confidence", 0.5))
    merged_conf = max(existing_conf, incoming_conf)
    merged_value = (
        incoming["value"]
        if incoming_conf >= existing_conf
        else existing.get("value", incoming["value"])
    )

    payload: dict[str, Any] = {
        "type": incoming.get("type") or existing.get("type", "context"),
        "key": incoming.get("key") or existing.get("key"),
        "value": merged_value,
        "confidence": merged_conf,
        "source": incoming.get("source", existing.get("source", "user_stated")),
        "is_active": True,
        "updated_at": now,
    }
    category = incoming.get("category") or existing.get("category")
    if category:
        payload["category"] = category
    _attach_embedding_if_enabled(payload)
    return payload


def _fact_compaction_score(fact: dict[str, Any], *, now_ts: float | None = None) -> float:
    """Puntaje confidence * recency para retener hechos (M04)."""
    confidence = float(fact.get("confidence", 0.5))
    ts = _coerce_fact_timestamp(fact)
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    age_days = max(0.0, (now_ts - ts) / 86400.0)
    recency = max(0.1, math.exp(-age_days / 90.0))
    return confidence * recency


def _memory_embeddings_enabled() -> bool:
    return bool(settings.memory_embeddings_enabled)


def _attach_embedding_if_enabled(doc: dict[str, Any]) -> None:
    """Añade embedding al documento si MEMORY_EMBEDDINGS_ENABLED=true."""
    if not _memory_embeddings_enabled():
        return
    text = fact_to_embed_text(doc)
    if not text.strip():
        return
    vec = embed_fact_text(text)
    doc.update(embedding_storage_payload(vec))


def _build_fact_document(fact: dict[str, Any], *, source: str = "user_stated") -> dict[str, Any]:
    """Construye payload Firestore alineado con PLAN §10 (subset M02)."""
    now = datetime.now(timezone.utc)
    doc: dict[str, Any] = {
        "type": fact["type"],
        "key": fact["key"],
        "value": fact["value"],
        "confidence": fact["confidence"],
        "source": source,
        "source_interaction_id": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
        "access_count": 0,
    }
    if fact.get("category"):
        doc["category"] = fact["category"]
    _attach_embedding_if_enabled(doc)
    return doc


def _resolve_fact_id(uid: str, candidate: dict[str, Any] | None, key: str) -> str | None:
    if candidate and candidate.get("fact_id"):
        return str(candidate["fact_id"])
    return find_memory_fact_id_by_key(uid, key)


def _persist_atomic_facts(uid: str, facts: list[dict[str, Any]]) -> int:
    """Persiste hechos en users/{uid}/memory/facts/{fact_id}. Retorna cantidad aplicada."""
    applied = 0
    existing_facts = list_active_memory_facts(uid, limit=max(MAX_ACTIVE_MEMORY_FACTS * 2, 300))

    for fact in facts:
        action = fact.get("action", "create")
        key = fact["key"]

        if action == "delete":
            candidate = _find_merge_candidate(existing_facts, fact)
            existing_id = _resolve_fact_id(uid, candidate, key)
            if existing_id and deactivate_memory_fact(uid, existing_id):
                applied += 1
                for item in existing_facts:
                    if item.get("fact_id") == existing_id:
                        item["is_active"] = False
            continue

        candidate = _find_merge_candidate(existing_facts, fact)
        if candidate and action in {"create", "update"}:
            existing_id = _resolve_fact_id(uid, candidate, key)
            if existing_id:
                payload = _merge_fact_payload(candidate, fact)
                if set_memory_fact(uid, existing_id, payload, merge=True):
                    applied += 1
                    candidate.update(payload)
                continue

        fact_id = str(uuid.uuid4())
        document = _build_fact_document(fact)
        if set_memory_fact(uid, fact_id, document):
            applied += 1
            existing_facts.append({"fact_id": fact_id, **document})

    if applied > 0:
        _maybe_compact_facts_after_update(uid)

    return applied


def _maybe_compact_facts_after_update(uid: str) -> None:
    """Dispara compactación de hechos cada N actualizaciones (M04)."""
    count = _memory_update_counts.get(uid, 0) + 1
    _memory_update_counts[uid] = count
    if count < COMPACT_FACTS_EVERY_N_UPDATES:
        return
    _memory_update_counts[uid] = 0
    deactivated = compact_memory_facts(uid)
    if deactivated:
        log.info(
            "Hechos compactados para uid=%s (%d desactivados)",
            uid[:8],
            deactivated,
        )


def _save_summary(uid: str, summary: str) -> None:
    """Guarda resumen legacy en users/{uid}/profile/memory."""
    db = get_firestore_client()
    if db is None:
        return
    db.collection("users").document(uid).collection("profile").document("memory").set(
        {
            "summary": summary,
            "last_updated": datetime.now(timezone.utc),
            "version": 2,
        }
    )


def _merge_and_save_summary(
    provider: AIProvider,
    uid: str,
    new_facts_text: str,
    existing_summary: str | None = None,
) -> str | None:
    """Fusiona hechos nuevos con resumen existente y persiste en ruta legacy."""
    if existing_summary is None:
        existing_summary = get_memory(uid)

    if not new_facts_text or len(new_facts_text) < 10:
        return None

    if existing_summary and existing_summary.strip():
        merge_input = MERGE_USER_PROMPT.format(
            existing=existing_summary,
            new_facts=new_facts_text,
        )
        final_summary = provider.simple_chat(merge_input, MERGE_SYSTEM_PROMPT).strip()
        if not final_summary:
            final_summary = f"{existing_summary}\n{new_facts_text}"
    else:
        final_summary = new_facts_text

    _save_summary(uid, final_summary)
    log.info(
        "Memoria actualizada para uid=%s (%d caracteres)",
        uid[:8],
        len(final_summary),
    )
    return final_summary


# ── API pública ───────────────────────────────────────────────────────────


def get_memory(uid: str) -> str:
    """Lee el resumen de memoria del usuario desde Firestore.

    Ruta Firestore: users/{uid}/profile/memory

    Returns:
        Resumen de memoria en texto, o cadena vacía si no existe.
    """
    try:
        db = get_firestore_client()
        if db is None:
            return ""
        doc = (
            db.collection("users")
            .document(uid)
            .collection("profile")
            .document("memory")
            .get()
        )
        if doc.exists:
            data = doc.to_dict() or {}
            return data.get("summary", "")
    except Exception:
        log.warning("Error leyendo memoria para uid=%s", uid[:8], exc_info=True)
    return ""


def get_memory_facts(uid: str, limit: int = 200) -> list[dict[str, Any]]:
    """Lista hechos atómicos activos en users/{uid}/memory/facts/{fact_id}."""
    return list_active_memory_facts(uid, limit=limit)


def forget_memory_fact(uid: str, fact_id: str) -> bool:
    """Olvida un hecho atómico (delete lógico vía is_active=false)."""
    clean_id = (fact_id or "").strip()
    if not clean_id:
        return False
    ok = deactivate_memory_fact(uid, clean_id)
    if ok:
        log.info("Hecho olvidado uid=%s fact_id=%s", uid[:8], clean_id[:8])
    return ok


def find_similar_facts(uid: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Recupera hechos similares a la consulta (FREE-M06 / Fase 1.3).

    MEMORY_EMBEDDINGS_ENABLED=true por defecto: embeddings locales (hash+BoW 256dim).
    Si el hecho almacenado no tiene vector, fallback a SequenceMatcher (texto).
    """
    if not query or not query.strip() or top_k <= 0:
        return []

    use_embeddings = _memory_embeddings_enabled()
    query_vec = embed_fact_text(query.strip()) if use_embeddings else None
    if query_vec is not None:
        query_vec = truncate_embedding(query_vec)

    try:
        facts = list_active_memory_facts(uid, limit=max(MAX_ACTIVE_MEMORY_FACTS * 2, 300))
    except Exception:
        log.warning("Error listando hechos para similitud uid=%s", uid[:8], exc_info=True)
        return []

    ranked = rank_facts_by_similarity(
        facts,
        query.strip(),
        query_vec=query_vec,
        top_k=top_k,
        use_embeddings=use_embeddings,
    )
    return [fact for fact, _score in ranked]


def _coerce_fact_timestamp(fact: dict[str, Any]) -> float:
    """Convierte updated_at/created_at a epoch para ordenar por recencia."""
    raw = fact.get("updated_at") or fact.get("created_at")
    if isinstance(raw, datetime):
        return raw.timestamp()
    if hasattr(raw, "timestamp"):
        try:
            return float(raw.timestamp())  # type: ignore[union-attr]
        except (TypeError, ValueError, OSError):
            pass
    if hasattr(raw, "to_datetime"):
        try:
            return raw.to_datetime().timestamp()  # type: ignore[union-attr]
        except (TypeError, ValueError, OSError, AttributeError):
            pass
    return 0.0


def rank_memory_facts_for_prompt(
    facts: list[dict[str, Any]],
    limit: int = MAX_PROMPT_MEMORY_FACTS,
) -> list[dict[str, Any]]:
    """Top N hechos por confianza y recencia (FREE-M05)."""
    if not facts or limit <= 0:
        return []
    ranked = sorted(
        facts,
        key=lambda fact: (
            float(fact.get("confidence", 0.5)),
            _coerce_fact_timestamp(fact),
        ),
        reverse=True,
    )
    return ranked[:limit]


# FASE 3.2: límite de caracteres para el bloque de hechos en el prompt (~4000 chars)
MAX_FORMATTED_FACTS_CHARS = 4000


def format_memory_facts_for_prompt(facts: list[dict[str, Any]]) -> str:
    """Formatea hechos atómicos para inyectar en el system prompt.
    
    FASE 3.2: trunca a MAX_FORMATTED_FACTS_CHARS (~4000) para no explotar el prompt.
    """
    lines: list[str] = []
    for fact in facts:
        key = str(fact.get("key", "")).strip()
        value = fact.get("value", "")
        fact_type = str(fact.get("type", "context")).strip() or "context"
        if not key:
            continue
        conf = fact.get("confidence")
        conf_suffix = ""
        if isinstance(conf, (int, float)):
            conf_suffix = f" (confianza {conf:.0%})"
        lines.append(f"- [{fact_type}] {key}: {value}{conf_suffix}")
    result = "\n".join(lines)
    if len(result) > MAX_FORMATTED_FACTS_CHARS:
        result = result[:MAX_FORMATTED_FACTS_CHARS] + (
            "\n... (más hechos truncados por límite de prompt)"
        )
    return result


def build_memory_prompt_block(uid: str) -> str:
    """Bloque de memoria (prosa + hechos atómicos) para system prompt."""
    parts: list[str] = []

    summary = get_memory(uid)
    if summary and summary.strip():
        parts.append(f"Resumen de conversaciones anteriores:\n{summary.strip()}")

    try:
        facts = get_memory_facts(uid)
        top_facts = rank_memory_facts_for_prompt(facts)
        facts_text = format_memory_facts_for_prompt(top_facts)
        if facts_text:
            parts.append(
                "Hechos confirmados sobre el usuario (memoria atómica):\n"
                f"{facts_text}"
            )
    except Exception:
        log.warning("Error cargando hechos atómicos para uid=%s", uid[:8], exc_info=True)

    if not parts:
        return ""

    return (
        "Información sobre el usuario (memoria persistente — confía en estos datos):\n"
        f"{'\n\n'.join(parts)}\n\n"
        "Usa esta información para personalizar tus respuestas. "
        "Si preguntan cómo se llaman, qué trabajo hacen u otros datos que aparecen aquí, "
        "responde directamente con esos datos.\n\n"
        "Si el usuario pregunta «¿dónde dejé ese archivo?» o similar, busca en el índice "
        "de archivos local: el sistema ya lo consultó y encontró archivos relacionados "
        "con su consulta en los resultados que ves más abajo."
    )


def build_memory_recall_hint(uid: str, user_query: str | None) -> str | None:
    """Hint humano para la UI cuando el usuario pregunta algo que ya está en memoria."""
    if not user_query or not user_query.strip():
        return None

    try:
        facts = get_memory_facts(uid)
    except Exception:
        log.debug("No se pudieron cargar hechos para hint uid=%s", uid[:8], exc_info=True)
        return None

    if not facts:
        return None

    ranked = rank_memory_facts_for_prompt(facts, limit=15)
    query = user_query.strip()

    for pattern, key_hints, phrase_tpl in _RECALL_INTENTS:
        if not pattern.search(query):
            continue
        for fact in ranked:
            key = _normalize_compare_text(fact.get("key"))
            fact_type = str(fact.get("type", "")).strip().lower()
            value = str(fact.get("value", "")).strip()
            if not value:
                continue
            key_match = any(h in key for h in key_hints)
            type_match = fact_type in {"identity", "relationship", "context", "data"}
            if key_match or (type_match and key):
                return f"DOT te recuerda que {phrase_tpl.format(value=value)}."

    return None


def _post_memory_persist(uid: str, user_msg: str, assistant_resp: str) -> None:
    """Actualiza snapshot markdown tras persistir hechos (sobrevive reinicios)."""
    try:
        from app.services.memory_persistence import update_snapshot_with_conversation

        update_snapshot_with_conversation(uid, user_msg, assistant_resp)
    except Exception:
        log.warning(
            "Error actualizando snapshot post-memoria para uid=%s",
            uid[:8],
            exc_info=True,
        )


def _is_significant_exchange(
    *,
    had_tool_use: bool,
    conversation_id: str | None,
    db_factory: Callable[[], Any] | None,
) -> bool:
    """True si el intercambio merece extracción de memoria (B02 / chat PC)."""
    if had_tool_use:
        return True
    if not conversation_id or not db_factory:
        return False
    try:
        from uuid import UUID

        from app.chat_models import MessageORM

        db = db_factory()
        try:
            msg_count = (
                db.query(MessageORM)
                .filter(MessageORM.conversation_id == UUID(conversation_id))
                .count()
            )
            return msg_count >= 3
        finally:
            db.close()
    except Exception:
        log.debug("No se pudo contar mensajes para significancia de memoria", exc_info=True)
        return False


def schedule_memory_update(
    uid: str,
    user_msg: str,
    assistant_resp: str,
    *,
    existing_summary: str | None = None,
    had_tool_use: bool = False,
    conversation_id: str | None = None,
    db_factory: Callable[[], Any] | None = None,
    force: bool = False,
) -> None:
    """Programa extracción de memoria en background (FREE-M07, no bloquea caller)."""

    def _run() -> None:
        try:
            should_extract = force or _contains_personal_fact_signal(user_msg)
            if not should_extract and not _is_significant_exchange(
                had_tool_use=had_tool_use,
                conversation_id=conversation_id,
                db_factory=db_factory,
            ):
                log.debug(
                    "Intercambio no significativo — omitiendo extracción de memoria para uid=%s",
                    uid[:8],
                )
                return

            existing = existing_summary if existing_summary is not None else get_memory(uid)
            update_memory(uid, user_msg, assistant_resp, existing)
        except Exception:
            log.warning("Error en extracción de memoria para uid=%s", uid[:8], exc_info=True)

    _memory_executor.submit(_run)


def update_memory(
    uid: str,
    user_msg: str,
    assistant_resp: str,
    existing_summary: str | None = None,
) -> None:
    """Extrae hechos de la conversación y los fusiona con la memoria existente.

    Flujo (FREE-M01/M02/M03/M04):
      1. Intenta extracción atómica JSON.
      2. Si hay hechos válidos, persiste con fusión inteligente (M03).
      3. Actualiza resumen legacy en users/{uid}/profile/memory (compat).
      4. Compacta hechos activos periódicamente (M04, cada N updates).
      5. Si falla JSON, usa extracción en prosa (fallback legacy).
      6. Compacta resumen si excede ~2000 tokens estimados.

    Args:
        uid: ID del usuario en Firestore.
        user_msg: Mensaje del usuario.
        assistant_resp: Respuesta del asistente.
        existing_summary: Resumen existente (se lee de Firestore si es None).
    """
    if _is_trivial(user_msg):
        log.debug("Mensaje trivial — omitiendo extracción de memoria para uid=%s", uid[:8])
        return

    try:
        provider = _get_provider()

        atomic_facts = _extract_atomic_facts(provider, user_msg, assistant_resp)
        if atomic_facts is not None:
            if not atomic_facts:
                log.debug("Extracción atómica sin hechos nuevos para uid=%s", uid[:8])
                return

            applied = _persist_atomic_facts(uid, atomic_facts)
            if applied == 0:
                log.debug("Hechos atómicos no persistidos para uid=%s", uid[:8])
                return

            new_facts_text = _facts_to_prose(atomic_facts)
            final_summary = _merge_and_save_summary(
                provider,
                uid,
                new_facts_text,
                existing_summary=existing_summary,
            )
            if final_summary and len(final_summary) > 8000:
                compact_memory(uid)
            log.info(
                "Memoria atómica actualizada para uid=%s (%d hechos aplicados)",
                uid[:8],
                applied,
            )
            _post_memory_persist(uid, user_msg, assistant_resp)
            return

        log.debug("Fallback a extracción en prosa para uid=%s", uid[:8])
        new_facts = _extract_prose_facts(provider, user_msg, assistant_resp)
        if len(new_facts) < 10:
            log.debug("No se extrajeron hechos significativos para uid=%s", uid[:8])
            return

        final_summary = _merge_and_save_summary(
            provider,
            uid,
            new_facts,
            existing_summary=existing_summary,
        )
        if final_summary and len(final_summary) > 8000:
            compact_memory(uid)
        _post_memory_persist(uid, user_msg, assistant_resp)

    except Exception:
        log.warning("Error actualizando memoria para uid=%s", uid[:8], exc_info=True)


def compact_memory_facts(uid: str, max_active: int = MAX_ACTIVE_MEMORY_FACTS) -> int:
    """Reduce hechos activos al top N por confidence*recency (M04).

    Los hechos en overflow se desactivan (delete lógico), no se borran.

    Returns:
        Cantidad de hechos desactivados.
    """
    if max_active <= 0:
        return 0

    try:
        facts = list_active_memory_facts(uid, limit=max(max_active * 2, 400))
        if len(facts) <= max_active:
            return 0

        now_ts = datetime.now(timezone.utc).timestamp()
        ranked = sorted(
            facts,
            key=lambda item: _fact_compaction_score(item, now_ts=now_ts),
            reverse=True,
        )
        overflow = ranked[max_active:]

        deactivated = 0
        for fact in overflow:
            fact_id = fact.get("fact_id")
            if fact_id and deactivate_memory_fact(uid, str(fact_id)):
                deactivated += 1

        if deactivated:
            log.info(
                "Compactación de hechos uid=%s: %d activos conservados, %d desactivados",
                uid[:8],
                max_active,
                deactivated,
            )
        return deactivated
    except Exception:
        log.warning("Error compactando hechos para uid=%s", uid[:8], exc_info=True)
        return 0


def compact_memory(uid: str, max_chars: int = 8000) -> None:
    """Comprime el resumen de memoria si excede el límite (~2000 tokens).

    Se dispara automáticamente desde update_memory cuando el resumen
    supera 8000 caracteres (~2000 tokens).

    Args:
        uid: ID del usuario en Firestore.
        max_chars: Límite de caracteres (~4 chars por token).
    """
    try:
        summary = get_memory(uid)
        if not summary or len(summary) <= max_chars:
            return

        provider = _get_provider()

        compact_input = (
            "Comprime el siguiente resumen sobre un usuario a aproximadamente "
            f"la mitad de su tamaño actual, conservando todos los hechos importantes. "
            "No pierdas información relevante, solo hazlo más conciso. "
            "Responde en español.\n\n"
            f"Resumen a comprimir:\n{summary}"
        )

        compacted = provider.simple_chat(compact_input).strip()

        if compacted and len(compacted) < len(summary):
            _save_summary(uid, compacted)
            log.info(
                "Memoria compactada para uid=%s: %d → %d chars",
                uid[:8],
                len(summary),
                len(compacted),
            )

    except Exception:
        log.warning("Error compactando memoria para uid=%s", uid[:8], exc_info=True)
