"""Tests FREE-M05/M07: inyección de hechos atómicos y schedule_memory_update."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.chat_context import build_system_prompt
from app.services.memory_service import (
    build_memory_prompt_block,
    build_memory_recall_hint,
    format_memory_facts_for_prompt,
    rank_memory_facts_for_prompt,
    schedule_memory_update,
    update_memory,
)


def test_rank_memory_facts_for_prompt_orders_by_confidence_then_recency():
    older = {
        "key": "old",
        "value": "1",
        "confidence": 0.9,
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    newer = {
        "key": "new",
        "value": "2",
        "confidence": 0.9,
        "updated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }
    low_conf = {
        "key": "low",
        "value": "3",
        "confidence": 0.4,
        "updated_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }

    ranked = rank_memory_facts_for_prompt([older, newer, low_conf], limit=2)

    assert [f["key"] for f in ranked] == ["new", "old"]


def test_format_memory_facts_for_prompt_includes_type_and_confidence():
    text = format_memory_facts_for_prompt(
        [
            {
                "type": "preference",
                "key": "idioma",
                "value": "español",
                "confidence": 0.95,
            }
        ]
    )
    assert "[preference] idioma: español" in text
    assert "95%" in text


def test_build_memory_prompt_block_includes_summary_and_atomic_facts():
    with patch("app.services.memory_service.get_memory", return_value="Le gusta el café."):
        with patch(
            "app.services.memory_service.get_memory_facts",
            return_value=[
                {
                    "type": "preference",
                    "key": "bebida",
                    "value": "café",
                    "confidence": 1.0,
                    "updated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                }
            ],
        ):
            block = build_memory_prompt_block("uid-test")

    assert "Le gusta el café." in block
    assert "memoria atómica" in block
    assert "[preference] bebida: café" in block


def test_schedule_memory_update_extracts_personal_facts_on_first_message():
    """Hechos personales en el primer mensaje disparan extracción sin force."""
    with patch("app.services.memory_service.update_memory") as mock_update:
        with patch("app.services.memory_service.get_memory", return_value=""):
            schedule_memory_update(
                "uid-test",
                "Me llamo Carlos y trabajo de abogado",
                "Encantado Carlos",
            )

    mock_update.assert_called_once()


def test_schedule_memory_update_skips_trivial_first_message():
    """Saludos triviales en el primer mensaje no disparan extracción."""
    with patch("app.services.memory_service.update_memory") as mock_update:
        schedule_memory_update("uid-test", "hola", "Hola, ¿cómo estás?")

    mock_update.assert_not_called()


def test_build_memory_recall_hint_for_name_question():
    with patch(
        "app.services.memory_service.get_memory_facts",
        return_value=[
            {
                "type": "identity",
                "key": "nombre",
                "value": "María",
                "confidence": 1.0,
            }
        ],
    ):
        hint = build_memory_recall_hint("uid-test", "¿Cómo me llamo?")

    assert hint == "DOT te recuerda que te llamas María."


def test_build_memory_recall_hint_for_job_question():
    with patch(
        "app.services.memory_service.get_memory_facts",
        return_value=[
            {
                "type": "identity",
                "key": "profesion",
                "value": "abogado",
                "confidence": 0.95,
            }
        ],
    ):
        hint = build_memory_recall_hint("uid-test", "¿Qué trabajo hago?")

    assert hint == "DOT te recuerda que trabajas como abogado."


def test_schedule_memory_update_force_skips_significance_check():
    with patch("app.services.memory_service.update_memory") as mock_update:
        with patch("app.services.memory_service.get_memory", return_value=""):
            schedule_memory_update(
                "uid-test",
                "Mi nombre es Ana",
                "Encantado Ana",
                force=True,
            )

    mock_update.assert_called_once_with(
        "uid-test",
        "Mi nombre es Ana",
        "Encantado Ana",
        "",
    )


def test_build_system_prompt_includes_memory_block():
    """M05: Verifica que build_system_prompt inyecta el bloque de memoria al inicio.
    
    El bloque debe aparecer ANTES del BASE_SYSTEM_PROMPT (orden en la concatenación).
    """
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
            prompt = build_system_prompt("uid-test")

    # Verificar que el bloque de memoria aparece ANTES del prompt base DOT
    assert "Usuario vive en Caracas." in prompt
    assert "memoria atómica" in prompt
    assert "[identity] profesion: abogado" in prompt
    assert "95%" in prompt

    # El bloque de memoria debe preceder a BASE_SYSTEM_PROMPT
    mem_pos = prompt.find("Usuario vive en Caracas.")
    base_pos = prompt.find("Eres DOT")
    assert mem_pos >= 0
    assert base_pos >= 0
    assert mem_pos < base_pos, "El bloque de memoria debe aparecer ANTES del prompt base DOT"


def test_update_memory_skips_trivial_messages():
    """M05: Mensajes triviales no disparan extracción de memoria."""
    with patch("app.services.memory_service._get_provider") as mock_provider:
        update_memory("uid-test", "hola", "Hola, ¿cómo estás?")
        # No debe llamar al LLM para extracción
        mock_provider.assert_not_called()


def test_update_memory_processes_significant_message():
    """M05: Mensajes con hechos personales sí disparan extracción de memoria.
    
    Verifica que el flujo completo update_memory → _extract_atomic_facts → _persist_atomic_facts
    funciona con datos simulados (mock de provider + Firestore).
    """
    with patch("app.services.memory_service._get_provider") as mock_provider:
        mock = mock_provider.return_value
        mock.simple_chat.return_value = (
            '{"facts": [{"type": "identity", "key": "nombre", "value": "María", '
            '"confidence": 1.0, "action": "create"}]}'
        )
        with patch("app.services.memory_service.set_memory_fact", return_value=True):
            with patch(
                "app.services.memory_service.list_active_memory_facts",
                return_value=[],
            ):
                with patch("app.services.memory_service._save_summary"):
                    with patch("app.services.memory_service.compact_memory"):
                        update_memory(
                            "uid-test",
                            "Mi nombre es María González y soy de Bogotá",
                            "Encantado María, ¿en qué puedo ayudarte?",
                        )

    # Debe llamar al LLM para extracción atómica
    mock_provider.assert_called_once()
    mock.simple_chat.assert_called_once()
