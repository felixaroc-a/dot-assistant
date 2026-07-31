"""Tests de integracion para PersistentCache."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from app.services.cache_service import PersistentCache


@pytest.fixture
def cache():
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_cache.db"
    c = PersistentCache(db_path)
    yield c
    try:
        os.unlink(str(db_path))
    except OSError:
        pass
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass


class TestPersistentCache:
    def test_set_and_get(self, cache: PersistentCache):
        cache.set("key1", {"data": "hello"}, ttl_seconds=60)
        result = cache.get("key1")
        assert result == {"data": "hello"}

    def test_get_expired(self, cache: PersistentCache):
        cache.set("expired", "value", ttl_seconds=0)
        time.sleep(0.01)
        result = cache.get("expired")
        assert result is None

    def test_get_nonexistent(self, cache: PersistentCache):
        result = cache.get("nonexistent")
        assert result is None

    def test_delete(self, cache: PersistentCache):
        cache.set("delete-me", "value", ttl_seconds=60)
        cache.delete("delete-me")
        assert cache.get("delete-me") is None

    def test_invalidate_pattern(self, cache: PersistentCache):
        cache.set("user:1:profile", {"name": "Ana"}, ttl_seconds=60)
        cache.set("user:2:profile", {"name": "Luis"}, ttl_seconds=60)
        cache.set("other:key", "value", ttl_seconds=60)

        deleted = cache.invalidate_pattern("user:")
        assert deleted == 2
        assert cache.get("user:1:profile") is None
        assert cache.get("other:key") is not None

    def test_clear_expired(self, cache: PersistentCache):
        cache.set("fresh", "value", ttl_seconds=60)
        cache.set("stale", "old", ttl_seconds=0)
        time.sleep(0.01)

        cleared = cache.clear_expired()
        assert cleared >= 1
        assert cache.get("fresh") is not None
        assert cache.get("stale") is None

    def test_clear_all(self, cache: PersistentCache):
        cache.set("a", 1, ttl_seconds=60)
        cache.set("b", 2, ttl_seconds=60)
        cache.clear_all()
        assert cache.size() == 0

    def test_size(self, cache: PersistentCache):
        assert cache.size() == 0
        cache.set("a", 1, ttl_seconds=60)
        assert cache.size() == 1
        cache.set("b", 2, ttl_seconds=60)
        assert cache.size() == 2
