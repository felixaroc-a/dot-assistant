"""Tests para TaskQueue."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from worker.task_queue import TaskQueue


@pytest.fixture
def queue():
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_tasks.db"
    q = TaskQueue(db_path)
    yield q
    # Cerrar conexiones SQLite antes de limpiar
    try:
        os.unlink(str(db_path))
    except OSError:
        pass
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass


class TestTaskQueue:
    def test_enqueue_and_dequeue(self, queue: TaskQueue):
        queue.enqueue("task-1", "uid-1", {"name": "test", "instruction": "hello"})
        task = queue.dequeue(timeout=1.0)
        assert task is not None
        assert task["id"] == "task-1"
        assert task["uid"] == "uid-1"
        assert task["payload"]["name"] == "test"

    def test_dequeue_empty(self, queue: TaskQueue):
        task = queue.dequeue(timeout=0.5)
        assert task is None

    def test_fifo_order(self, queue: TaskQueue):
        queue.enqueue("task-1", "uid-1", {"order": 1})
        queue.enqueue("task-2", "uid-2", {"order": 2})

        t1 = queue.dequeue(timeout=1.0)
        t2 = queue.dequeue(timeout=1.0)

        assert t1["id"] == "task-1"
        assert t2["id"] == "task-2"

    def test_complete(self, queue: TaskQueue):
        queue.enqueue("task-1", "uid-1", {"name": "test"})
        task = queue.dequeue(timeout=1.0)
        assert task is not None

        queue.complete("task-1", "resultado ok")
        # Verificar que no queda pendiente
        assert queue.pending_count() == 0

    def test_fail(self, queue: TaskQueue):
        queue.enqueue("task-1", "uid-1", {"name": "test"})
        task = queue.dequeue(timeout=1.0)
        assert task is not None

        queue.fail("task-1", "error de prueba")
        assert queue.pending_count() == 0

    def test_pending_count(self, queue: TaskQueue):
        assert queue.pending_count() == 0
        queue.enqueue("task-1", "uid-1", {})
        queue.enqueue("task-2", "uid-1", {})
        assert queue.pending_count() == 2
        assert queue.pending_count(uid="uid-1") == 2
        assert queue.pending_count(uid="uid-2") == 0

    def test_reset_stale(self, queue: TaskQueue):
        import time as time_module

        queue.enqueue("task-1", "uid-1", {})
        task = queue.dequeue(timeout=1.0)
        assert task is not None

        time_module.sleep(0.1)
        recovered = queue.reset_stale(max_seconds=0)
        assert recovered >= 1

    def test_clear_old(self, queue: TaskQueue):
        queue.enqueue("old-task", "uid-1", {})
        task = queue.dequeue(timeout=1.0)
        assert task is not None
        queue.complete("old-task", "done")

        cleared = queue.clear_old(max_age_days=0)
        assert cleared >= 1
