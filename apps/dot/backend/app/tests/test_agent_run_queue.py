"""Tests mínimos de AgentRunQueue (Día 1)."""
from __future__ import annotations

import threading
import time

import pytest

from app.application.agent.run_queue import (
    MAX_CONCURRENT,
    AgentRunSuperseded,
    enqueue_agent_run,
    reset_run_queue_for_tests,
)
from app.application.agent.session_key import build_session_key


@pytest.fixture(autouse=True)
def _clean_queue():
    reset_run_queue_for_tests()
    yield
    reset_run_queue_for_tests()


def test_build_session_key_whatsapp():
    key = build_session_key("uid-1", "whatsapp", chat_jid="54911@g.us")
    assert key == "uid-1|whatsapp|jid:54911@g.us"


def test_build_session_key_chat_pc():
    key = build_session_key("uid-1", "chat", conversation_id="conv-abc")
    assert key == "uid-1|chat|conv:conv-abc"


def test_one_active_per_lane():
    lane_key = "uid-a|whatsapp|jid:1@g.us"
    active = threading.Event()
    release = threading.Event()
    overlap = threading.Event()
    started = threading.Event()

    def slow_run() -> str:
        started.set()
        active.set()
        release.wait(timeout=5)
        active.clear()
        return "first"

    t1 = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, slow_run),
        daemon=True,
    )
    t1.start()
    assert started.wait(timeout=2)

    def probe() -> str:
        if active.is_set():
            overlap.set()
        time.sleep(0.05)
        return "second"

    t2 = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, probe),
        daemon=True,
    )
    t2.start()
    time.sleep(0.15)
    assert overlap.is_set() is False

    release.set()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert t1.is_alive() is False
    assert t2.is_alive() is False


def test_second_queued_until_first_finishes():
    lane_key = "uid-b|chat|conv:1"
    order: list[str] = []
    gate = threading.Event()

    def first() -> str:
        order.append("start-1")
        gate.wait(timeout=3)
        order.append("end-1")
        return "one"

    def second() -> str:
        order.append("start-2")
        order.append("end-2")
        return "two"

    t1 = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, first),
        daemon=True,
    )
    t2 = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, second),
        daemon=True,
    )
    t1.start()
    time.sleep(0.1)
    t2.start()
    time.sleep(0.1)
    assert order == ["start-1"]

    gate.set()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert order == ["start-1", "end-1", "start-2", "end-2"]


def test_idle_lane_starts_next_run():
    lane_key = "uid-c|automation"
    seen: list[int] = []

    for i in range(3):
        def run(n: int = i) -> int:
            seen.append(n)
            return n

        assert enqueue_agent_run(lane_key, lambda n=i: run(n)) == i

    assert seen == [0, 1, 2]


def test_interrupt_drops_queued_not_started():
    lane_key = "uid-d|whatsapp|jid:2@g.us"
    release = threading.Event()
    outcomes: list[str] = []

    def slow() -> str:
        release.wait(timeout=3)
        return "slow"

    t_slow = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, slow),
        daemon=True,
    )
    t_slow.start()
    time.sleep(0.05)

    def queued() -> str:
        time.sleep(0.2)
        return "queued"

    def run_queued() -> None:
        try:
            enqueue_agent_run(lane_key, queued)
            outcomes.append("queued-ran")
        except AgentRunSuperseded:
            outcomes.append("superseded")

    t_q = threading.Thread(target=run_queued, daemon=True)
    t_q.start()
    time.sleep(0.05)

    result = enqueue_agent_run(lane_key, lambda: "interrupt", mode="interrupt")
    assert result == "interrupt"

    t_q.join(timeout=2)
    assert t_q.is_alive() is False
    assert "superseded" in outcomes

    release.set()
    t_slow.join(timeout=3)


def test_interrupt_cancels_active_via_event():
    """mode=interrupt señaliza cancel_event al run activo."""
    lane_key = "uid-e|pc|conv:cancel"
    saw_cancel = threading.Event()
    release = threading.Event()

    def slow(cancel_event=None) -> str:
        release.wait(timeout=0.2)
        if cancel_event is not None and cancel_event.wait(timeout=2):
            saw_cancel.set()
            return "cancelled"
        return "finished"

    t1 = threading.Thread(
        target=lambda: enqueue_agent_run(lane_key, slow),
        daemon=True,
    )
    t1.start()
    time.sleep(0.05)
    result = enqueue_agent_run(lane_key, lambda: "newer", mode="interrupt")
    assert result == "newer"
    t1.join(timeout=3)
    assert saw_cancel.is_set()


def test_global_max_concurrent():
    """Hasta MAX_CONCURRENT lanes distintos pueden correr a la vez."""
    barrier = threading.Barrier(MAX_CONCURRENT, timeout=3)
    release = threading.Event()
    concurrent = {"n": 0, "max": 0}
    lock = threading.Lock()

    def hold(lane: str) -> str:
        with lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        barrier.wait(timeout=3)
        release.wait(timeout=3)
        with lock:
            concurrent["n"] -= 1
        return lane

    threads = [
        threading.Thread(
            target=lambda k=f"uid|lane|{i}": enqueue_agent_run(k, lambda: hold(k)),
            daemon=True,
        )
        for i in range(MAX_CONCURRENT)
    ]
    for t in threads:
        t.start()
    time.sleep(0.3)
    assert concurrent["max"] == MAX_CONCURRENT

    release.set()
    for t in threads:
        t.join(timeout=5)
