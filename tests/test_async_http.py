"""Tests for the Q2 async client, run against a small in-process aiohttp server."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pokemon.async_http import AsyncResilientClient
from pokemon.errors import NotFoundError, ServerError


def build_server(statuses: list[int]) -> TestServer:
    """Server whose /flaky route replays `statuses` in order, then always answers 200."""
    remaining = list(statuses)

    async def flaky(_request):
        status = remaining.pop(0) if remaining else 200
        return web.json_response({"status": status}, status=status)

    async def ok(request):
        await asyncio.sleep(0.05)  # simulated latency
        return web.json_response({"id": request.match_info["id"]})

    app = web.Application()
    app.router.add_get("/flaky", flaky)
    app.router.add_get("/item/{id}", ok)
    return TestServer(app)


def run_with_server(statuses, scenario):
    """Start the test server, run `scenario(client, base_url)`, then shut everything down."""

    async def runner():
        async with build_server(statuses) as server:
            base = str(server.make_url(""))
            async with AsyncResilientClient(concurrency=50, backoff_factor=0.01) as client:
                return await scenario(client, base), client.stats

    return asyncio.run(runner())


def test_retries_then_succeeds():
    async def scenario(client, base):
        return await client.get_json(f"{base}/flaky")

    result, stats = run_with_server([503, 500], scenario)
    assert result == {"status": 200}
    assert stats["retries"] == 2


def test_gives_up_after_max_retries():
    async def scenario(client, base):
        with pytest.raises(ServerError):
            await client.get_json(f"{base}/flaky")

    _, stats = run_with_server([503] * 10, scenario)
    assert stats["requests"] == 4  # 1 attempt + 3 retries


def test_404_not_retried():
    async def scenario(client, base):
        with pytest.raises(NotFoundError):
            await client.get_json(f"{base}/flaky")

    _, stats = run_with_server([404], scenario)
    assert stats["requests"] == 1


def test_get_many_is_concurrent_and_ordered():
    async def scenario(client, base):
        loop = asyncio.get_running_loop()
        start = loop.time()
        results = await client.get_many(f"{base}/item/{i}" for i in range(100))
        return results, loop.time() - start

    (results, elapsed), _ = run_with_server([], scenario)
    assert [r["id"] for r in results] == [str(i) for i in range(100)]
    # 100 x 50 ms sequentially would take 5 s; concurrently it takes a fraction of that.
    assert elapsed < 1.5


def test_run_bulk_streams_results_through_callback():
    seen = []

    async def scenario(client, base):
        urls = (f"{base}/item/{i}" for i in range(500))  # lazy generator
        return await client.run_bulk(urls, on_result=lambda url, data, err: seen.append(data["id"]), workers=20)

    stats, _ = run_with_server([], scenario)
    assert stats["success"] == 500
    assert sorted(seen, key=int) == [str(i) for i in range(500)]
