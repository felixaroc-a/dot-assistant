"""Tests F4/F5: heartbeat + curated skills."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.store.curated_skills import (
    CURATED_STORE_SKILLS,
    get_curated_skill,
    list_curated_skills,
)
from app.services.agent_heartbeat import run_agent_heartbeat


def test_curated_skills_at_least_five():
    assert len(CURATED_STORE_SKILLS) >= 5
    assert get_curated_skill("skill_alerta_dolar") is not None
    assert len(list_curated_skills()) >= 5


def test_agent_heartbeat_audit_without_execute():
    fake_doc = MagicMock()
    fake_doc.id = "uid12345678"
    fake_doc.to_dict.return_value = {
        "saved_automations": [
            {
                "id": "a1",
                "active": True,
                "schedule": "manual",
                "instruction": "Si confirman cita por WA, créala",
                "name": "Citas",
            }
        ]
    }
    fake_db = MagicMock()
    fake_db.collection.return_value.limit.return_value.stream.return_value = [fake_doc]
    fake_db.collection.return_value.document.return_value.set = MagicMock()

    with patch("app.firebase_db.get_db", return_value=fake_db):
        result = run_agent_heartbeat(max_users=5)

    assert result["ok"] is True
    assert result["scanned"] >= 1
    assert result["with_mandates"] >= 1
    assert result["execute_mode"] is False


def test_mandate_evaluator_module_importable():
    from app.application.whatsapp import mandate_evaluator as me

    assert hasattr(me, "evaluate_mandates_async")
