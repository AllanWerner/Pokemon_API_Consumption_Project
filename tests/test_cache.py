"""Tests for the Q3 TTL cache and its integration in the sync and async clients."""

import asyncio
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import TestServer

from pokemon.async_http import AsyncResilientClient
from pokemon.cache import ONE_HOUR, TTLCache
from pokemon.resilient_http import resilient_get


class FakeClock:
    """Manually advanced clock to test expiration without waiting."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_entry_valid_until_ttl_then_expires():
    clock = FakeClock()
    cache = TTLCache(ttl=ONE_HOUR, clock=clock)
    cache.set("k", {"v": 1})

    clock.now = ONE_HOUR - 1
    assert cache.get("k") == {"v": 1}

    clock.now = ONE_HOUR
    assert cache.get("k") is None
    assert cache.stats()["expired"] == 1
    assert len(cache) == 0


def test_lru_eviction_when_full():
    cache = TTLCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # "a" becomes most recently used
    cache.set("c", 3)  # evicts "b"
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_hit_rate_statistics():
    cache = TTLCache()
    cache.set("k", 1)
    cache.get("k")
    cache.get("missing")
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1
    assert cache.stats()["hit_rate"] == 0.5


def test_sync_client_uses_cache_and_refreshes_after_expiry():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    response = MagicMock(status_code=200, headers={})
    response.json.return_value = {"name": "pikachu"}
    session = MagicMock()
    session.get.return_value = response

    url = "https://pokeapi.co/api/v2/pokemon/pikachu"
    for _ in range(5):
        assert resilient_get(url, session=session, cache=cache) == {"name": "pikachu"}
    assert session.get.call_count == 1  # 4 answers came from the cache

    clock.now = ONE_HOUR + 1
    resilient_get(url, session=session, cache=cache)
    assert session.get.call_count == 2  # expired -> fetched again


def test_errors_are_not_cached():
    cache = TTLCache()
    session = MagicMock()
    session.get.side_effect = [MagicMock(status_code=503, headers={}), MagicMock(status_code=503, headers={})]
    try:
        resilient_get("http://x/y", session=session, cache=cache, max_retries=1, sleep=lambda _: None)
    except Exception:
        pass
    assert len(cache) == 0


def test_async_cache_and_request_coalescing():
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return web.json_response({"calls": calls})

    async def scenario():
        app = web.Application()
        app.router.add_get("/data", handler)
        async with TestServer(app) as server:
            url = str(server.make_url("/data"))
            async with AsyncResilientClient(cache=TTLCache()) as client:
                # 200 simultaneous identical requests -> a single HTTP call (coalescing).
                await asyncio.gather(*(client.get_json(url) for _ in range(200)))
                # Subsequent requests are served from the cache.
                await client.get_many([url] * 100)
                return client.stats

    stats = asyncio.run(scenario())
    assert calls == 1
    assert stats["requests"] == 1
    assert stats["coalesced"] == 199
    assert stats["cache_hits"] == 100
