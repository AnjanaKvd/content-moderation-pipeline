import pytest
import pytest_asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../api")))

from services.cache import ModerationCache, NullCache


@pytest_asyncio.fixture
async def null_cache():
    return NullCache()


@pytest.mark.asyncio
async def test_null_cache_get_returns_none(null_cache):
    result = await null_cache.get("any_hash")
    assert result is None


@pytest.mark.asyncio
async def test_null_cache_set_returns_false(null_cache):
    result = await null_cache.set("any_hash", {"label": "toxic"})
    assert result is False


@pytest.mark.asyncio
async def test_null_cache_ping_returns_false(null_cache):
    result = await null_cache.ping()
    assert result is False


@pytest.mark.asyncio
async def test_null_cache_stats(null_cache):
    await null_cache.get("hash1")
    await null_cache.get("hash2")
    stats = null_cache.stats
    assert stats["hits"] == 0
    assert stats["misses"] == 2
    assert stats["hit_rate"] == 0.0


@pytest.mark.asyncio
async def test_moderation_cache_ping_without_redis():
    # Attempt connection to a non-existent Redis — should return False without crashing
    cache = ModerationCache(
        host="localhost",
        port=9999,
        password="",
        ssl=False,
        ttl=60,
    )
    result = await cache.ping()
    assert result is False
    await cache.close()
