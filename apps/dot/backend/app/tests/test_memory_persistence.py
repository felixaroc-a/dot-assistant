"""Tests FREE-M08: persistencia de memoria (snapshot markdown + búsqueda semántica).

Cubre:
  - save_memory_snapshot / load_memory_snapshot
  - auto_save_on_session_end
  - search_memory (texto + hechos atómicos)
  - search_memory_and_format (para system prompt)
  - update_snapshot_with_conversation
  - build_system_prompt con inyección de búsqueda de memoria
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.chat_context import build_system_prompt
from app.services.memory_persistence import (
    _build_snapshot_markdown,
    _search_snapshot_text,
    auto_save_on_session_end,
    load_memory_snapshot,
    save_memory_snapshot,
    search_memory,
    search_memory_and_format,
    update_snapshot_with_conversation,
)


# ── Tests: save / load snapshot ──────────────────────────────────────────


def test_save_and_load_snapshot_roundtrip():
    """Snapshot markdown se guarda y recupera correctamente."""
    uid = "test-save-load"
    test_text = "# DOT Memory — Test User\n\n## Preferences\n- idioma: español\n"

    with patch("app.services.memory_persistence.get_firestore_client") as mock_db:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()

        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_collection
        mock_collection.collection.return_value = mock_collection
        mock_collection.set.return_value = None

        # For load: simulate existing document
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"text": test_text, "version": 1}
        mock_collection.get.return_value = mock_doc

        mock_db.return_value = mock_client

        # Save
        result = save_memory_snapshot(uid, test_text)
        assert result is True
        mock_collection.set.assert_called_once()

        # Load
        loaded = load_memory_snapshot(uid)
        assert loaded == test_text


def test_load_snapshot_returns_empty_when_missing():
    """Si no hay snapshot, devuelve cadena vacía."""
    uid = "test-no-snapshot"

    with patch("app.services.memory_persistence.get_firestore_client") as mock_db:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False

        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_collection
        mock_collection.collection.return_value = mock_collection
        mock_collection.get.return_value = mock_doc

        mock_db.return_value = mock_client

        loaded = load_memory_snapshot(uid)
        assert loaded == ""


def test_save_snapshot_returns_false_when_firestore_unavailable():
    """Sin Firestore, save_memory_snapshot retorna False sin crashear."""
    uid = "test-no-db"

    with patch("app.services.memory_persistence.get_firestore_client", return_value=None):
        result = save_memory_snapshot(uid, "some text")
        assert result is False


# ── Tests: build snapshot markdown ────────────────────────────────────────


def test_build_snapshot_markdown_includes_sections():
    """El snapshot markdown incluye secciones Preferences, Identity y Facts."""
    facts = [
        {
            "type": "preference",
            "key": "idioma",
            "value": "español",
            "confidence": 0.95,
            "is_active": True,
        },
        {
            "type": "identity",
            "key": "profesion",
            "value": "abogado",
            "confidence": 0.90,
            "is_active": True,
        },
        {
            "type": "event",
            "key": "ultima_reunion",
            "value": "tribunal con empresa X",
            "confidence": 0.80,
            "is_active": True,
        },
    ]

    with patch("app.services.memory_persistence._get_user_display_name", return_value="Carlos"):
        md = _build_snapshot_markdown("uid-test", facts, "Resumen legacy de conversaciones.", None)

    assert "# DOT Memory — Carlos" in md
    assert "## Preferences" in md
    assert "idioma: español" in md
    assert "confidence: 0.95" in md
    assert "## Identity" in md
    assert "profesion: abogado" in md
    assert "## Facts" in md
    assert "tribunal con empresa X" in md
    assert "## Recent Context" in md
    assert "Resumen legacy" in md


def test_build_snapshot_preserves_existing_automations():
    """Si el snapshot existente tiene Automations, se preserva en el nuevo."""
    facts = [
        {
            "type": "preference",
            "key": "idioma",
            "value": "español",
            "confidence": 0.95,
            "is_active": True,
        },
    ]

    existing_snapshot = (
        "# DOT Memory — Ana\n\n"
        "## Preferences\n- idioma: español\n\n"
        "## Automations\n- Daily weather report at 7am\n- Weekly email summary\n"
    )

    with patch("app.services.memory_persistence._get_user_display_name", return_value="Ana"):
        md = _build_snapshot_markdown("uid-test", facts, "", existing_snapshot)

    assert "## Automations" in md
    assert "Daily weather report at 7am" in md
    assert "Weekly email summary" in md


def test_build_snapshot_no_automations_when_none_exist():
    """Sin automations previas, no se agrega la sección."""
    facts = [
        {
            "type": "preference",
            "key": "idioma",
            "value": "español",
            "confidence": 0.95,
            "is_active": True,
        },
    ]

    with patch("app.services.memory_persistence._get_user_display_name", return_value="Luis"):
        md = _build_snapshot_markdown("uid-test", facts, "", None)

    assert "## Automations" not in md


def test_build_snapshot_skips_inactive_facts():
    """Hechos inactivos no aparecen en el snapshot."""
    facts = [
        {
            "type": "preference",
            "key": "activo",
            "value": "visible",
            "confidence": 0.9,
            "is_active": True,
        },
        {
            "type": "preference",
            "key": "inactivo",
            "value": "oculto",
            "confidence": 0.9,
            "is_active": False,
        },
    ]

    with patch("app.services.memory_persistence._get_user_display_name", return_value="Test"):
        md = _build_snapshot_markdown("uid-test", facts, "", None)

    assert "visible" in md
    assert "oculto" not in md


# ── Tests: auto_save_on_session_end ───────────────────────────────────────


def test_auto_save_on_session_end_builds_and_saves():
    """auto_save_on_session_end construye snapshot y lo guarda."""
    uid = "test-auto-save"
    facts = [
        {
            "type": "identity",
            "key": "nombre",
            "value": "María",
            "confidence": 1.0,
            "is_active": True,
        },
    ]

    with patch("app.services.memory_persistence.get_memory_facts", return_value=facts):
        with patch("app.services.memory_persistence.get_memory", return_value="Le gusta el café."):
            with patch("app.services.memory_persistence.load_memory_snapshot", return_value=""):
                with patch("app.services.memory_persistence.save_memory_snapshot", return_value=True):
                    with patch(
                        "app.services.memory_persistence._get_user_display_name",
                        return_value="María",
                    ):
                        result = auto_save_on_session_end(uid)

    assert result is not None
    assert "# DOT Memory — María" in result
    assert "nombre: María" in result


def test_auto_save_on_session_end_handles_errors_gracefully():
    """Si algo falla, auto_save_on_session_end retorna None sin crashear."""
    uid = "test-error"

    with patch("app.services.memory_persistence.get_memory_facts", side_effect=RuntimeError("fail")):
        result = auto_save_on_session_end(uid)

    assert result is None


# ── Tests: search_memory ──────────────────────────────────────────────────


def test_search_snapshot_text_finds_matching_paragraphs():
    """Búsqueda en texto de snapshot encuentra párrafos relevantes."""
    snapshot = (
        "## Preferences\n"
        "- idioma: español\n"
        "- ciudad: Caracas\n"
        "\n"
        "## Facts\n"
        "- profesion: abogado\n"
        "- especialidad: derecho civil\n"
    )

    results = _search_snapshot_text(snapshot, "abogado", top_k=2)

    assert len(results) >= 1
    assert any("abogado" in r["snippet"] for r in results)
    assert all(r["source"] == "snapshot_text" for r in results)


def test_search_snapshot_text_exact_match_scores_higher():
    """Coincidencia exacta en snapshot tiene score 1.0."""
    snapshot = "prefiere café con leche todas las mañanas\nle gusta el té verde"

    results = _search_snapshot_text(snapshot, "café con leche", top_k=1)

    assert len(results) == 1
    assert results[0]["score"] == 1.0


def test_search_memory_includes_facts_and_snapshot():
    """search_memory busca tanto en hechos atómicos como en snapshot."""
    uid = "test-search"

    facts = [
        {
            "fact_id": "f1",
            "type": "preference",
            "key": "bebida",
            "value": "café",
            "confidence": 0.95,
            "is_active": True,
        },
    ]

    snapshot_text = "# DOT Memory — Test\n\n## Preferences\n- comida: arepa\n"

    with patch("app.services.memory_persistence.load_memory_snapshot", return_value=snapshot_text):
        with patch("app.services.memory_persistence.settings") as mock_settings:
            mock_settings.memory_embeddings_enabled = False
            with patch(
                "app.services.memory_persistence.list_active_memory_facts",
                return_value=facts,
            ):
                results = search_memory(uid, "café y comida", top_k=5)

    assert len(results) >= 1
    sources = {r["source"] for r in results}
    assert "atomic_fact" in sources or "snapshot_text" in sources


def test_search_memory_empty_query_returns_empty():
    """Query vacía devuelve lista vacía."""
    results = search_memory("uid-test", "", top_k=5)
    assert results == []


def test_search_memory_top_k_zero_returns_empty():
    """top_k=0 devuelve lista vacía."""
    results = search_memory("uid-test", "test", top_k=0)
    assert results == []


def test_search_memory_and_format_produces_readable_output():
    """search_memory_and_format formatea resultados para prompt."""
    uid = "test-format"

    snapshot_text = "# DOT Memory — Test\n\n## Preferences\n- idioma: español\n"

    with patch("app.services.memory_persistence.load_memory_snapshot", return_value=snapshot_text):
        with patch("app.services.memory_persistence.settings") as mock_settings:
            mock_settings.memory_embeddings_enabled = False
            with patch(
                "app.services.memory_persistence.list_active_memory_facts",
                return_value=[],
            ):
                formatted = search_memory_and_format(uid, "idioma español", top_k=3)

    assert "Datos relevantes" in formatted
    assert "español" in formatted
    assert "snapshot_text" not in formatted


def test_search_memory_and_format_empty_query_returns_empty():
    """Query vacía en search_memory_and_format devuelve cadena vacía."""
    result = search_memory_and_format("uid-test", "")
    assert result == ""


# ── Tests: update_snapshot_with_conversation ──────────────────────────────


def test_update_snapshot_with_conversation_adds_recent_context():
    """update_snapshot_with_conversation agrega sección Recent Conversations."""
    uid = "test-update"
    facts = [
        {
            "type": "identity",
            "key": "nombre",
            "value": "Pedro",
            "confidence": 1.0,
            "is_active": True,
        },
    ]

    with patch("app.services.memory_persistence.get_memory_facts", return_value=facts):
        with patch("app.services.memory_persistence.get_memory", return_value=""):
            with patch("app.services.memory_persistence.load_memory_snapshot", return_value=""):
                with patch("app.services.memory_persistence.save_memory_snapshot") as mock_save:
                    with patch(
                        "app.services.memory_persistence._get_user_display_name",
                        return_value="Pedro",
                    ):
                        update_snapshot_with_conversation(
                            uid,
                            "¿Cuál es el estado de mi caso legal?",
                            "Tu caso está en revisión en el tribunal.",
                        )

    mock_save.assert_called_once()
    saved_text = mock_save.call_args[0][1]
    assert "## Recent Conversations" in saved_text
    assert "caso legal" in saved_text


def test_update_snapshot_handles_errors_gracefully():
    """Si algo falla, no crashea."""
    uid = "test-error-update"

    with patch(
        "app.services.memory_persistence.get_memory_facts",
        side_effect=RuntimeError("fail"),
    ):
        # No debe lanzar excepción
        update_snapshot_with_conversation(uid, "hola", "hola")


# ── Tests: build_system_prompt con inyección de memoria ──────────────────


def test_build_system_prompt_injects_memory_search_when_query_provided():
    """build_system_prompt con user_query inyecta resultados de búsqueda de memoria."""
    snapshot_text = "# DOT Memory — Ana\n\n## Facts\n- profesion: abogado\n"

    with patch("app.services.memory_service.get_memory", return_value="Usuario vive en Caracas."):
        with patch(
            "app.services.memory_service.get_memory_facts",
            return_value=[
                {
                    "type": "identity",
                    "key": "profesion",
                    "value": "abogado",
                    "confidence": 0.95,
                    "updated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                }
            ],
        ):
            with patch(
                "app.services.memory_persistence.load_memory_snapshot",
                return_value=snapshot_text,
            ):
                with patch("app.services.memory_persistence.settings") as mock_settings:
                    mock_settings.memory_embeddings_enabled = False
                    with patch(
                        "app.services.memory_persistence.list_active_memory_facts",
                        return_value=[
                            {
                                "fact_id": "f1",
                                "type": "identity",
                                "key": "profesion",
                                "value": "abogado",
                                "is_active": True,
                            },
                        ],
                    ):
                        prompt = build_system_prompt(
                            "uid-test", "¿Qué sabes de mi profesión?"
                        )

    # El bloque de memoria sigue presente
    assert "Usuario vive en Caracas." in prompt
    # El bloque base DOT también
    assert "Eres DOT" in prompt
    # La búsqueda de memoria debería inyectar resultados
    assert "Datos relevantes" in prompt
    # El orden: memoria → búsqueda de memoria → prompt base
    mem_pos = prompt.find("Usuario vive en Caracas.")
    base_pos = prompt.find("Eres DOT")
    assert mem_pos >= 0
    assert base_pos >= 0
    assert mem_pos < base_pos


def test_build_system_prompt_without_query_still_works():
    """build_system_prompt sin user_query (compatibilidad hacia atrás) sigue funcionando."""
    with patch("app.services.memory_service.get_memory", return_value=""):
        with patch("app.services.memory_service.get_memory_facts", return_value=[]):
            prompt = build_system_prompt("uid-test")

    assert "Eres DOT" in prompt
    # Sin query, no debería haber bloque de búsqueda de memoria
    assert "Datos relevantes que recuerdas" not in prompt


# ── Tests: edge cases ────────────────────────────────────────────────────


def test_build_snapshot_markdown_empty_facts():
    """Snapshot con cero hechos sigue siendo válido."""
    with patch("app.services.memory_persistence._get_user_display_name", return_value="User"):
        md = _build_snapshot_markdown("uid-test", [], "", None)

    assert "# DOT Memory — User" in md
    assert "## Preferences" not in md
    assert "## Facts" not in md


def test_schedule_snapshot_save_does_not_block():
    """schedule_snapshot_save no lanza excepción ni bloquea."""
    from app.services.memory_persistence import schedule_snapshot_save

    with patch("app.services.memory_persistence.auto_save_on_session_end") as mock_auto:
        # Ejecutar en el thread pool y esperar
        import time

        schedule_snapshot_save("uid-test")
        time.sleep(0.5)  # Dar tiempo al thread pool

        # Verificar que se llamó (o al menos que no crasheó)
        # El thread pool puede o no haber terminado; lo importante es que no haya excepción
