from __future__ import annotations

from unittest.mock import MagicMock

from app.services.automation_bootstrap import hydrate_all_scheduled_automations
from app.services.automation_scheduler import AutomationScheduler


def test_on_trigger_enqueues_task(tmp_path, monkeypatch):
    scheduler = AutomationScheduler()
    db_path = tmp_path / "tasks.db"
    enqueued: list[tuple[str, str, dict]] = []

    class _FakeQueue:
        def __init__(self, *_args, **_kwargs):
            pass

        def has_active_task_for_automation(self, uid, auto_id):
            return False

        def enqueue(self, task_id, uid, payload):
            enqueued.append((task_id, uid, payload))

    try:
        monkeypatch.setattr("worker.task_queue.TaskQueue", _FakeQueue)
        monkeypatch.setattr("worker.task_queue.DEFAULT_DB_PATH", db_path)

        auto = {
            "id": "auto-1",
            "name": "Test Daily",
            "instruction": "resumir correos",
            "schedule": "daily:09:00",
            "active": True,
            "output_type": "chat",
        }
        scheduler._on_trigger("uid-123", auto)

        assert len(enqueued) == 1
        task_id, uid, payload = enqueued[0]
        assert uid == "uid-123"
        assert payload["id"] == "auto-1"
        assert task_id.startswith("auto_uid-123")
    finally:
        scheduler.shutdown()


def test_execute_now_runs_executor(monkeypatch):
    scheduler = AutomationScheduler()
    captured: dict[str, object] = {}

    class _FakeExecutor:
        def execute(self, uid, auto):
            captured["uid"] = uid
            captured["auto"] = auto
            return "ok-result"

        def save_result(self, *args, **kwargs):
            captured["saved"] = True

        def mark_pending(self, *args, **kwargs):
            captured["pending"] = True

    class _FakeSandbox:
        def __init__(self, timeout_seconds=30):
            pass

        def run(self, fn, context=""):
            return fn()

    try:
        monkeypatch.setattr("worker.executor.AutomationExecutor", _FakeExecutor)
        monkeypatch.setattr("worker.sandbox.ExecutionSandbox", _FakeSandbox)
        monkeypatch.setattr("worker.sandbox.validate_automation_payload", lambda _auto: None)

        result = scheduler.execute_now(
            "uid-1",
            {
                "id": "auto-1",
                "name": "Auto Gmail",
                "integration_id": "gmail",
                "instruction": "listar no leidos",
                "output_type": "chat",
            },
        )
        assert result == "ok-result"
        assert captured.get("saved") is True
        assert captured.get("pending") is True
    finally:
        scheduler.shutdown()


def test_hydrate_loads_users_with_scheduled_automations(monkeypatch):
    scheduler = MagicMock()

    class _FakeDoc:
        def __init__(self, doc_id, data):
            self.id = doc_id
            self._data = data

        def to_dict(self):
            return self._data

    class _FakeCollection:
        def stream(self):
            yield _FakeDoc(
                "uid-a",
                {
                    "saved_automations": [
                        {
                            "id": "a1",
                            "active": True,
                            "schedule": "daily:09:00",
                            "instruction": "hola",
                        }
                    ]
                },
            )
            yield _FakeDoc("uid-b", {"saved_automations": []})

    class _FakeDb:
        def collection(self, _name):
            return _FakeCollection()

    monkeypatch.setattr(
        "app.services.automation_bootstrap.get_firestore_client",
        lambda: _FakeDb(),
    )
    monkeypatch.setattr(
        "app.services.automation_bootstrap._resolve_plan",
        lambda _uid: "mensual",
    )

    loaded = hydrate_all_scheduled_automations(scheduler)
    assert loaded == 1
    scheduler.load_user_automations.assert_called_once_with(uid="uid-a", plan="mensual")
