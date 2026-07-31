"""Tests FREE-M03/M04: fusión inteligente y compactación de hechos atómicos."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.memory_service import (
    COMPACT_FACTS_EVERY_N_UPDATES,
    _fact_compaction_score,
    _facts_are_similar,
    _find_merge_candidate,
    _merge_fact_payload,
    _persist_atomic_facts,
    compact_memory_facts,
)


def test_facts_are_similar_same_category_and_near_duplicate_value():
    existing = {
        "type": "preference",
        "category": "personal",
        "key": "bebida_favorita",
        "value": "café con leche",
    }
    incoming = {
        "type": "preference",
        "category": "personal",
        "key": "bebida",
        "value": "cafe con leche",
    }

    assert _facts_are_similar(existing, incoming) is True


def test_facts_are_similar_rejects_different_category():
    existing = {
        "type": "preference",
        "category": "work",
        "key": "idioma",
        "value": "español",
    }
    incoming = {
        "type": "preference",
        "category": "personal",
        "key": "idioma",
        "value": "español",
    }

    assert _facts_are_similar(existing, incoming) is False


def test_find_merge_candidate_prefers_exact_key():
    existing = [
        {
            "fact_id": "fact-1",
            "type": "identity",
            "key": "nombre",
            "value": "Ana",
            "is_active": True,
        },
        {
            "fact_id": "fact-2",
            "type": "identity",
            "key": "ciudad",
            "value": "Caracas",
            "is_active": True,
        },
    ]
    incoming = {"type": "identity", "key": "nombre", "value": "Ana María"}

    candidate = _find_merge_candidate(existing, incoming)

    assert candidate is not None
    assert candidate["fact_id"] == "fact-1"


def test_merge_fact_payload_keeps_higher_confidence_value():
    existing = {
        "type": "identity",
        "key": "empleador",
        "value": "Empresa A",
        "confidence": 0.6,
    }
    incoming = {
        "type": "identity",
        "key": "empleador",
        "value": "Empresa B",
        "confidence": 0.95,
        "action": "update",
    }

    merged = _merge_fact_payload(existing, incoming)

    assert merged["value"] == "Empresa B"
    assert merged["confidence"] == 0.95
    assert merged["is_active"] is True
    assert merged["updated_at"] is not None


def test_fact_compaction_score_favors_recent_high_confidence():
    now = datetime(2026, 7, 24, tzinfo=timezone.utc).timestamp()
    recent = {
        "confidence": 0.9,
        "updated_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
    }
    old = {
        "confidence": 0.9,
        "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    low_conf = {
        "confidence": 0.3,
        "updated_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
    }

    assert _fact_compaction_score(recent, now_ts=now) > _fact_compaction_score(old, now_ts=now)
    assert _fact_compaction_score(recent, now_ts=now) > _fact_compaction_score(low_conf, now_ts=now)


@patch("app.services.memory_service.deactivate_memory_fact", return_value=True)
@patch("app.services.memory_service.list_active_memory_facts")
def test_compact_memory_facts_deactivates_overflow(mock_list, mock_deactivate):
    facts = [
        {
            "fact_id": f"fact-{idx}",
            "key": f"k{idx}",
            "value": f"v{idx}",
            "confidence": 0.5 + (idx * 0.01),
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "is_active": True,
        }
        for idx in range(5)
    ]
    facts[4]["confidence"] = 0.99
    facts[4]["updated_at"] = datetime(2026, 7, 1, tzinfo=timezone.utc)
    mock_list.return_value = facts

    deactivated = compact_memory_facts("uid-test", max_active=3)

    assert deactivated == 2
    assert mock_deactivate.call_count == 2


@patch("app.services.memory_service._maybe_compact_facts_after_update")
@patch("app.services.memory_service.set_memory_fact", return_value=True)
@patch("app.services.memory_service.list_active_memory_facts")
def test_persist_atomic_facts_merges_near_duplicate(mock_list, mock_set, mock_compact):
    mock_list.return_value = [
        {
            "fact_id": "existing-1",
            "type": "identity",
            "category": "work",
            "key": "empleador",
            "value": "Empresas Polar",
            "confidence": 0.7,
            "is_active": True,
        }
    ]

    applied = _persist_atomic_facts(
        "uid-test",
        [
            {
                "type": "identity",
                "category": "work",
                "key": "empresa_actual",
                "value": "Empresa Polar",
                "confidence": 0.95,
                "action": "create",
            }
        ],
    )

    assert applied == 1
    mock_set.assert_called_once()
    args, kwargs = mock_set.call_args
    assert args[0] == "uid-test"
    assert args[1] == "existing-1"
    assert args[2]["confidence"] == 0.95
    assert kwargs.get("merge") is True
    mock_compact.assert_called_once_with("uid-test")


@patch("app.services.memory_service._maybe_compact_facts_after_update")
@patch("app.services.memory_service.set_memory_fact", return_value=True)
@patch("app.services.memory_service.list_active_memory_facts")
def test_persist_atomic_facts_does_not_duplicate_exact_same_fact(mock_list, mock_set, mock_compact):
    """M03: Dos hechos idénticos (misma key, mismo valor) deben mergearse, no duplicarse.
    
    El primero crea (1 set_memory_fact), el segundo mergea sobre el mismo fact_id (otro set_memory_fact con merge=True).
    """
    mock_list.return_value = [
        {
            "fact_id": "fact-a",
            "type": "identity",
            "key": "nombre",
            "value": "Carlos",
            "confidence": 0.9,
            "is_active": True,
        }
    ]

    # Primera inserción: misma key "nombre", mismo valor "Carlos" → debe mergear
    applied = _persist_atomic_facts(
        "uid-test",
        [
            {
                "type": "identity",
                "key": "nombre",
                "value": "Carlos",
                "confidence": 1.0,
                "action": "create",
            }
        ],
    )

    assert applied == 1
    # Debe llamar a set_memory_fact con merge=True (no crear un fact nuevo)
    mock_set.assert_called_once()
    args, kwargs = mock_set.call_args
    assert args[1] == "fact-a"  # usa el fact_id existente
    assert kwargs.get("merge") is True  # merge, no create
    assert args[2]["value"] == "Carlos"  # mantiene valor
    assert args[2]["confidence"] == 1.0  # actualiza a confianza mayor


@patch("app.services.memory_service._maybe_compact_facts_after_update")
@patch("app.services.memory_service.set_memory_fact", return_value=True)
@patch("app.services.memory_service.list_active_memory_facts")
def test_persist_atomic_facts_creates_new_when_no_match(mock_list, mock_set, mock_compact):
    """M03: Hecho sin candidato de merge existente se crea como nuevo fact."""
    mock_list.return_value = [
        {
            "fact_id": "fact-x",
            "type": "preference",
            "key": "musica",
            "value": "salsa",
            "is_active": True,
        }
    ]

    applied = _persist_atomic_facts(
        "uid-test",
        [
            {
                "type": "identity",
                "key": "nombre",
                "value": "Laura",
                "confidence": 1.0,
                "action": "create",
            }
        ],
    )

    assert applied == 1
    mock_set.assert_called_once()
    args, kwargs = mock_set.call_args
    assert args[1] != "fact-x"  # NO reusa el fact_id existente (keys diferentes)
    assert kwargs.get("merge") is not True  # es un create, no merge


@patch("app.services.memory_service._maybe_compact_facts_after_update")
@patch("app.services.memory_service.set_memory_fact", return_value=True)
@patch("app.services.memory_service.list_active_memory_facts")
def test_persist_atomic_facts_delete_deactivates(mock_list, mock_set, mock_compact):
    """M03: Acción delete debe desactivar el hecho existente, no crear ni mergear."""
    mock_list.return_value = [
        {
            "fact_id": "fact-del",
            "type": "identity",
            "key": "nombre",
            "value": "Pedro",
            "is_active": True,
        }
    ]

    with patch("app.services.memory_service.deactivate_memory_fact", return_value=True) as mock_deact:
        applied = _persist_atomic_facts(
            "uid-test",
            [
                {
                    "type": "identity",
                    "key": "nombre",
                    "value": "Pedro",
                    "confidence": 0.5,
                    "action": "delete",
                }
            ],
        )

    assert applied == 1
    mock_set.assert_not_called()  # delete no usa set_memory_fact
    mock_deact.assert_called_once_with("uid-test", "fact-del")


def test_maybe_compact_triggers_on_nth_update(monkeypatch):
    from app.services import memory_service

    compact_mock = patch.object(memory_service, "compact_memory_facts", return_value=1)
    memory_service._memory_update_counts["uid-test"] = COMPACT_FACTS_EVERY_N_UPDATES - 1

    with compact_mock as mock_compact:
        memory_service._maybe_compact_facts_after_update("uid-test")

    mock_compact.assert_called_once_with("uid-test")
    assert memory_service._memory_update_counts["uid-test"] == 0
