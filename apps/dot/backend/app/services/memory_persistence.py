"""Persistencia de memoria persistente estilo MEMORY.md (equivalente OpenClaw).

Almacena snapshots markdown en Firestore:
  - users/{uid}/memory/snapshot → { text, updated_at, version }

Funciones clave:
  - save_memory_snapshot: guarda texto markdown
  - load_memory_snapshot: carga último snapshot
  - auto_save_on_session_end: vuelca hechos + preferencias a markdown
  - search_memory: búsqueda híbrida (embeddings + texto) sobre snapshot + hechos
"""

from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.firebase_db import get_db as get_firestore_client, get_user_profile, list_active_memory_facts
from app.services.memory_embeddings import (
    embed_fact_text,
    fact_to_embed_text,
    rank_facts_by_similarity,
    truncate_embedding,
)
from app.services.memory_service import (
    MAX_ACTIVE_MEMORY_FACTS,
    _memory_embeddings_enabled,
    format_memory_facts_for_prompt,
    get_memory,
    get_memory_facts,
    rank_memory_facts_for_prompt,
)
from app.settings import settings

log = logging.getLogger("dot.memory_persistence")

SNAPSHOT_VERSION = 1

_persistence_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dot-memory-snap")


# ── Snapshot save / load ──────────────────────────────────────────────────


def save_memory_snapshot(uid: str, memory_text: str) -> bool:
    """Guarda un snapshot markdown en users/{uid}/memory/snapshot.

    Returns:
        True si se guardó correctamente, False si Firestore no está disponible.
    """
    db = get_firestore_client()
    if db is None:
        log.warning("Firestore no disponible — snapshot no guardado para uid=%s", uid[:8])
        return False

    try:
        payload: dict[str, Any] = {
            "text": memory_text,
            "version": SNAPSHOT_VERSION,
            "updated_at": datetime.now(timezone.utc),
        }
        db.collection("users").document(uid).collection("memory").document("snapshot").set(payload)
        log.info("Snapshot de memoria guardado para uid=%s (%d chars)", uid[:8], len(memory_text))
        return True
    except Exception:
        log.warning("Error guardando snapshot de memoria para uid=%s", uid[:8], exc_info=True)
        return False


def load_memory_snapshot(uid: str) -> str:
    """Carga el último snapshot markdown desde users/{uid}/memory/snapshot.

    Returns:
        Texto del snapshot o cadena vacía si no existe.
    """
    db = get_firestore_client()
    if db is None:
        return ""

    try:
        doc = (
            db.collection("users")
            .document(uid)
            .collection("memory")
            .document("snapshot")
            .get()
        )
        if doc.exists:
            data = doc.to_dict() or {}
            return str(data.get("text", ""))
    except Exception:
        log.warning("Error cargando snapshot de memoria para uid=%s", uid[:8], exc_info=True)

    return ""


# ── Construcción del snapshot markdown ────────────────────────────────────


def _get_user_display_name(uid: str) -> str:
    """Obtiene el nombre visible del usuario desde el perfil Firestore."""
    try:
        profile = get_user_profile(uid)
        if profile:
            name = profile.get("display_name") or profile.get("nombre")
            if name and str(name).strip():
                return str(name).strip()
    except Exception:
        log.debug("Error leyendo display_name para uid=%s", uid[:8], exc_info=True)
    return uid[:8]


def _build_snapshot_markdown(
    uid: str,
    facts: list[dict[str, Any]],
    legacy_summary: str,
    snapshot: str | None = None,
) -> str:
    """Construye el snapshot markdown estructurado a partir de hechos atómicos.

    Sections:
      - # DOT Memory — {user_name}
      - ## Preferences
      - ## Facts
      - ## Recent Context (from legacy summary)
      - ## Automations (placeholders for future)
    """
    user_name = _get_user_display_name(uid)

    # Agrupar hechos por tipo
    preferences: list[dict[str, Any]] = []
    identity_facts: list[dict[str, Any]] = []
    other_facts: list[dict[str, Any]] = []

    for fact in facts:
        if not fact.get("is_active", True):
            continue
        fact_type = str(fact.get("type", "context")).strip().lower()
        if fact_type == "preference":
            preferences.append(fact)
        elif fact_type in ("identity", "relationship"):
            identity_facts.append(fact)
        else:
            other_facts.append(fact)

    lines: list[str] = []
    lines.append(f"# DOT Memory — {user_name}")

    # ── Preferences ──
    if preferences:
        lines.append("")
        lines.append("## Preferences")
        for fact in preferences:
            key = str(fact.get("key", "")).strip()
            value = fact.get("value", "")
            conf = fact.get("confidence")
            if isinstance(conf, (int, float)):
                lines.append(f"- {key}: {value} (confidence: {conf:.2f})")
            else:
                lines.append(f"- {key}: {value}")

    # ── Identity facts ──
    if identity_facts:
        lines.append("")
        lines.append("## Identity")
        for fact in identity_facts:
            key = str(fact.get("key", "")).strip()
            value = fact.get("value", "")
            conf = fact.get("confidence")
            if isinstance(conf, (int, float)):
                lines.append(f"- {key}: {value} (confidence: {conf:.2f})")
            else:
                lines.append(f"- {key}: {value}")

    # ── Other facts ──
    if other_facts:
        lines.append("")
        lines.append("## Facts")
        for fact in other_facts:
            key = str(fact.get("key", "")).strip()
            value = fact.get("value", "")
            fact_type = str(fact.get("type", "context")).strip() or "context"
            conf = fact.get("confidence")
            if isinstance(conf, (int, float)):
                lines.append(f"- [{fact_type}] {key}: {value} (confidence: {conf:.2f})")
            else:
                lines.append(f"- [{fact_type}] {key}: {value}")

    # ── Recent Context (from legacy summary) ──
    if legacy_summary and legacy_summary.strip():
        lines.append("")
        lines.append("## Recent Context")
        summary_text = legacy_summary.strip()
        lines.append(summary_text)

    snapshot_text = "\n".join(lines)

    # ── Automations section (placeholder: se poblará cuando haya automation service integrado) ──
    if snapshot:
        existing_automations = _extract_section(snapshot, "## Automations")
        if existing_automations:
            snapshot_text += f"\n\n## Automations\n{existing_automations}"

    return snapshot_text


def _extract_section(text: str, heading: str) -> str | None:
    """Extrae el contenido de una sección markdown por su heading."""
    pattern = rf"{re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        if content:
            return content
    return None


def _merge_recent_conversations(
    snapshot: str | None,
    new_context: str,
) -> str:
    """Preserva la sección Recent Conversations si existe en el snapshot anterior."""
    if not snapshot:
        return new_context

    existing_context = _extract_section(snapshot, "## Recent Context")
    if not existing_context:
        return new_context

    merged = f"{new_context.strip()}\n\n---\n*Previously:*\n{existing_context.strip()}"
    return merged


# ── Auto-save on session end ──────────────────────────────────────────────


def auto_save_on_session_end(uid: str) -> str | None:
    """Vuelca todos los hechos atómicos activos + preferencias a un snapshot markdown.

    Se llama al final de una sesión de chat o periódicamente (cada 1h para usuarios activos).

    Returns:
        Texto del snapshot guardado, o None si no se pudo guardar.
    """
    try:
        facts = get_memory_facts(uid, limit=max(MAX_ACTIVE_MEMORY_FACTS, 200))
        legacy_summary = get_memory(uid)
        existing_snapshot = load_memory_snapshot(uid)

        snapshot_text = _build_snapshot_markdown(
            uid=uid,
            facts=facts,
            legacy_summary=legacy_summary,
            snapshot=existing_snapshot,
        )

        if save_memory_snapshot(uid, snapshot_text):
            return snapshot_text

    except Exception:
        log.warning("Error en auto_save_on_session_end para uid=%s", uid[:8], exc_info=True)

    return None


def schedule_snapshot_save(uid: str) -> None:
    """Programa guardado de snapshot en background (no bloquea al caller)."""

    def _run() -> None:
        try:
            auto_save_on_session_end(uid)
        except Exception:
            log.warning("Error en snapshot programado para uid=%s", uid[:8], exc_info=True)

    _persistence_executor.submit(_run)


# ── Búsqueda semántica sobre snapshot + hechos ────────────────────────────


def _search_snapshot_text(snapshot_text: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Busca en el texto del snapshot por fragmentos relevantes usando similitud de texto.

    Divide el snapshot en párrafos y los rankea por similitud con la query.
    """
    if not snapshot_text.strip() or not query.strip():
        return []

    paragraphs = [p.strip() for p in snapshot_text.split("\n") if p.strip()]
    if not paragraphs:
        return []

    query_norm = query.strip().lower()

    scored: list[tuple[str, float]] = []
    for para in paragraphs:
        para_norm = para.lower()
        if query_norm in para_norm:
            scored.append((para, 1.0))
        else:
            sim = SequenceMatcher(None, query_norm, para_norm).ratio()
            if sim > 0.3:
                scored.append((para, sim))

    scored.sort(key=lambda item: item[1], reverse=True)
    top = scored[:top_k]

    return [
        {
            "snippet": para,
            "score": round(score, 4),
            "source": "snapshot_text",
        }
        for para, score in top
    ]


def search_memory(
    uid: str,
    query: str,
    top_k: int = 5,
    *,
    include_snapshot: bool = True,
    include_facts: bool = True,
) -> list[dict[str, Any]]:
    """Búsqueda híbrida sobre snapshot markdown + hechos atómicos (Fase 1.3).

    MEMORY_EMBEDDINGS_ENABLED=true por defecto: embeddings locales (hash+BoW 256dim).
    Fallback a SequenceMatcher si no hay vectores almacenados en el hecho.

    Args:
        uid: ID del usuario.
        query: Texto de búsqueda.
        top_k: Cantidad máxima de resultados.
        include_snapshot: Si incluir resultados del snapshot text.
        include_facts: Si incluir resultados de hechos atómicos.

    Returns:
        Lista de resultados con snippet, score y source.
    """
    if not query or not query.strip() or top_k <= 0:
        return []

    results: list[dict[str, Any]] = []
    limit_per_source = max(top_k, 2)

    # ── Búsqueda en hechos atómicos ──
    if include_facts:
        try:
            from app.services.memory_service import find_similar_facts

            similar_facts = find_similar_facts(uid, query, top_k=limit_per_source)
            for fact in similar_facts:
                fact_text = fact_to_embed_text(fact)
                conf = fact.get("confidence")
                results.append({
                    "snippet": fact_text,
                    "score": round(float(conf or 0.5), 4) if isinstance(conf, (int, float)) else 0.5,
                    "source": "atomic_fact",
                    "fact_id": str(fact.get("fact_id", "")),
                    "fact_type": str(fact.get("type", "context")),
                })
        except Exception:
            log.warning("Error buscando hechos para uid=%s", uid[:8], exc_info=True)

    # ── Búsqueda en snapshot text ──
    if include_snapshot:
        try:
            snapshot_text = load_memory_snapshot(uid)
            if snapshot_text:
                snapshot_results = _search_snapshot_text(snapshot_text, query, top_k=limit_per_source)
                results.extend(snapshot_results)
        except Exception:
            log.warning("Error buscando en snapshot para uid=%s", uid[:8], exc_info=True)

    # ── Ordenar por score descendente y limitar a top_k ──
    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return results[:top_k]


# FASE 3.2: bridge HTTP para búsqueda de archivos vía file-indexer (Electron)
_FILE_SEARCH_BRIDGE_TIMEOUT = 3.0  # segundos


def _search_files_via_bridge(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Busca archivos indexados localmente vía bridge HTTP (file-indexer en Electron).

    Returns:
        Lista de resultados con path, name, relevance, o lista vacía si el bridge no responde.
    """
    bridge_url = settings.whatsapp_bridge_url.strip().rstrip("/")
    secret = settings.whatsapp_bridge_secret.strip()
    if not bridge_url:
        return []

    try:
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"

        with httpx.Client(timeout=_FILE_SEARCH_BRIDGE_TIMEOUT) as client:
            resp = client.post(
                f"{bridge_url}/v1/memory/search-files",
                json={"query": query, "limit": limit},
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if not isinstance(data, dict) or not data.get("ok"):
                return []
            results = data.get("results", [])
            return results if isinstance(results, list) else []
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        log.debug("Bridge file-indexer no disponible (consulta: %.40s)", query)
        return []
    except Exception:
        log.debug("Error inesperado en bridge file-indexer", exc_info=True)
        return []


def search_memory_and_format(uid: str, query: str, top_k: int = 5) -> str:
    """Busca en memoria y formatea resultados para inyectar en system prompt (Fase 1.3).

    MEMORY_EMBEDDINGS_ENABLED=true por defecto: usa embeddings para búsqueda semántica.
    Fallback a SequenceMatcher si no hay vectores almacenados.

    FASE 3.2: incluye resultados de búsqueda de archivos vía bridge si el file-indexer responde.

    Returns:
        Bloque de texto con resultados relevantes, o cadena vacía.
    """
    if not query or not query.strip():
        return ""

    results = search_memory(uid, query, top_k=top_k)

    lines: list[str] = []
    if results:
        lines.append("Datos relevantes que recuerdas del usuario:")
        for result in results:
            snippet = str(result.get("snippet", "")).strip()
            if snippet:
                lines.append(f"- {snippet}")

    # FASE 3.2: incluir búsqueda de archivos si el bridge responde
    try:
        file_results = _search_files_via_bridge(query, limit=top_k)
        if file_results:
            lines.append("\nArchivos del usuario relacionados:")
            for f in file_results:
                name = f.get("name", "")
                path = f.get("path", "")
                relevance = f.get("relevance", 0)
                if name:
                    rel_pct = f" (relevancia {relevance:.0%})" if isinstance(relevance, (int, float)) else ""
                    lines.append(f"- {name}: {path}{rel_pct}")
    except Exception:
        log.debug("Error incluyendo file-indexer en search_memory_and_format", exc_info=True)

    if not lines:
        return ""

    return "\n".join(lines) + "\n\nUsa estos datos si responden la pregunta del usuario."


# ── Snapshot con contexto de conversación reciente ────────────────────────


def update_snapshot_with_conversation(
    uid: str,
    user_msg: str,
    assistant_resp: str,
) -> None:
    """Actualiza el snapshot con contexto de la conversación más reciente.

    Se llama después de cada respuesta del asistente para mantener el snapshot
    actualizado con las últimas interacciones.
    """
    try:
        existing = load_memory_snapshot(uid)
        facts = get_memory_facts(uid, limit=max(MAX_ACTIVE_MEMORY_FACTS, 200))
        legacy_summary = get_memory(uid)

        # Extraer líneas clave de la conversación reciente para contexto
        user_short = user_msg[:200].strip()
        if len(user_msg) > 200:
            user_short += "..."

        # Construir línea de contexto reciente
        new_context_line = f"- Last exchange: User asked about: {user_short}"

        snapshot_text = _build_snapshot_markdown(
            uid=uid,
            facts=facts,
            legacy_summary=legacy_summary,
            snapshot=existing,
        )

        # Inyectar contexto reciente si no existe sección Recent Conversations
        existing_recent = _extract_section(snapshot_text, "## Recent Conversations")
        if not existing_recent:
            snapshot_text += f"\n\n## Recent Conversations\n{new_context_line}"
        else:
            recent_lines = existing_recent.split("\n")
            # Mantener últimas 5 interacciones
            recent_lines = [new_context_line] + recent_lines[:4]
            snapshot_text = re.sub(
                r"## Recent Conversations\n.*?(?=\n## |\Z)",
                "## Recent Conversations\n" + "\n".join(recent_lines),
                snapshot_text,
                flags=re.DOTALL,
            )

        save_memory_snapshot(uid, snapshot_text)

    except Exception:
        log.warning(
            "Error actualizando snapshot con conversación para uid=%s",
            uid[:8],
            exc_info=True,
        )
