"""Tests de TemplateService."""
from __future__ import annotations

import pytest

from app.services.template_service import (
    TemplateNotFoundError,
    TemplateService,
)


class _FakeSnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data or {}
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


def _build_fake_db(store: dict[str, dict]):
    class _TemplateDocRef:
        def __init__(self, doc_id: str):
            self._doc_id = doc_id

        @property
        def id(self):
            return self._doc_id

        def set(self, payload, merge=False):
            if merge and self._doc_id in store:
                merged = dict(store[self._doc_id])
                merged.update(payload)
                store[self._doc_id] = merged
                return
            store[self._doc_id] = dict(payload)

        def get(self):
            data = store.get(self._doc_id)
            return _FakeSnapshot(self._doc_id, dict(data) if data is not None else None)

        def delete(self):
            store.pop(self._doc_id, None)

    class _TemplatesCollection:
        def document(self, doc_id=None):
            return _TemplateDocRef(doc_id or "generated-id")

        def order_by(self, *_args, **_kwargs):
            return self

        def stream(self):
            for doc_id, data in store.items():
                yield _FakeSnapshot(doc_id, dict(data))

    class _UserDocRef:
        def collection(self, _name):
            return _TemplatesCollection()

    class _UsersCollection:
        def document(self, _uid):
            return _UserDocRef()

    class _FakeDb:
        def collection(self, _name):
            return _UsersCollection()

    return _FakeDb()


def test_template_service_create_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, dict] = {}
    monkeypatch.setattr("app.services.template_service.get_db", lambda: _build_fake_db(store))

    service = TemplateService(enabled=True)
    created = service.create_template("uid", "Carta", "docx", "Asunto {{x}}")
    assert created["id"] == "generated-id"

    listed = service.list_templates("uid")
    assert len(listed) == 1
    assert listed[0]["name"] == "Carta"
    assert listed[0]["document_type"] == "docx"


def test_template_service_render_calls_route_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    store = {
        "tpl-1": {
            "name": "Factura",
            "document_type": "txt",
            "structure": "Cliente {{cliente}}\nMonto {{monto}}",
            "created_at": "2030-01-01T10:00:00Z",
            "updated_at": "2030-01-01T10:00:00Z",
        }
    }

    captured: dict[str, object] = {}

    def _fake_route_chat(
        _text: str,
        _provider_id: str | None,
        system_prompt: str | None = None,
        include_document_action_prompt: bool = True,
    ) -> str:
        captured["include_document_action_prompt"] = include_document_action_prompt
        captured["system_prompt"] = system_prompt
        return "Contenido final"

    monkeypatch.setattr("app.services.template_service.get_db", lambda: _build_fake_db(store))
    monkeypatch.setattr("app.services.template_service.route_chat", _fake_route_chat)

    service = TemplateService(enabled=True)
    rendered = service.render_template("uid", "tpl-1", "Cliente ACME", "deepseek")
    assert rendered["document_type"] == "txt"
    assert rendered["content"] == "Contenido final"
    assert captured["include_document_action_prompt"] is False


def test_template_service_delete_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.template_service.get_db", lambda: _build_fake_db({}))
    service = TemplateService(enabled=True)
    with pytest.raises(TemplateNotFoundError):
        service.delete_template("uid", "missing")
