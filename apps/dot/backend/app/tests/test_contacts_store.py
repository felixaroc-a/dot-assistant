import pytest

from app.application.agent.tools.crm_tools import contact_find_handler
from app.services import contacts_store as store


def test_score_contact_match_first_name():
    contact = {"name": "María González", "phone": "+584141234567", "email": "maria@test.com"}
    assert store.score_contact_match(contact, "maria") >= 90
    assert store.score_contact_match(contact, "gonzalez") >= 75


def test_score_contact_match_accent_insensitive():
    contact = {"name": "José Pérez", "phone": "", "email": ""}
    assert store.score_contact_match(contact, "jose") >= 90


def test_search_contacts_returns_best_match():
    contacts = [
        {"name": "María González", "phone": "+584141234567"},
        {"name": "María Pérez", "phone": "+584129999999"},
        {"name": "Pedro López", "phone": "+584121111111"},
    ]
    matches = store.search_contacts("María", contacts=contacts)
    assert len(matches) == 2
    assert matches[0][1]["name"] in {"María González", "María Pérez"}


def test_format_find_result_single_whatsapp_ready():
    contact = store._ensure_contact_shape({"name": "María González", "phone": "04141234567"})
    output = store.format_find_result("María", [(100, contact)], for_whatsapp=True)
    assert "+584141234567" in output
    assert "send_whatsapp_message" in output


def test_merge_contacts_dedupes_by_phone():
    existing = [store._ensure_contact_shape({"name": "María", "phone": "+584141234567"})]
    incoming = [{"name": "María G.", "phone": "04141234567", "email": "m@test.com"}]
    merged, added, updated = store.merge_contacts(existing, incoming)
    assert added == 0
    assert updated == 1
    assert len(merged) == 1
    assert merged[0]["email"] == "m@test.com"


def test_parse_email_sender():
    assert store.parse_email_sender("María López <maria@test.com>") == ("María López", "maria@test.com")
    assert store.parse_email_sender("maria@test.com")[1] == "maria@test.com"


def test_add_contact_persists_via_bridge(monkeypatch):
    saved: dict = {}

    def fake_bridge(op, **kwargs):
        if op == "readFile":
            return {"ok": True, "content": "[]"}
        if op == "writeFile":
            saved["content"] = kwargs.get("content")
            return {"ok": True}
        return {"ok": False}

    monkeypatch.setattr(store, "_default_bridge_reader", lambda: fake_bridge)
    ok, contact, message = store.add_contact(name="Ana", phone="04141234567")
    assert ok
    assert contact
    assert "Ana" in message
    assert saved.get("content")
    assert "+584141234567" in saved["content"]


def test_contact_find_handler_whatsapp_hint(monkeypatch):
    contacts = [
        store._ensure_contact_shape({"name": "María González", "phone": "+584141234567"}),
    ]

    def fake_bridge(op, **kwargs):
        if op == "readFile":
            import json

            return {"ok": True, "content": json.dumps(contacts)}
        return {"ok": True}

    monkeypatch.setattr(store, "_default_bridge_reader", lambda: fake_bridge)
    result = contact_find_handler("uid-test", {"query": "María"})
    assert result.ok
    assert "+584141234567" in result.output
    assert "send_whatsapp_message" in result.output
