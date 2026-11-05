"""Q3 demo: shows that the 1-hour cache works.

    [1] Response time: first call (network) vs second call (cache) on the real PokéAPI
    [2] Expiration: a simulated clock jumps forward in time; data is refreshed after 1 hour
    [3] Load: the Q2 high-load scenario with and without cache (HTTP calls actually sent)

Run from the project root:  python -m scripts.q3_cache_demo
"""

import asyncio
import itertools
import logging
import time

import requests

from pokemon import api_client
from pokemon.async_http import AsyncResilientClient
from pokemon.cache import ONE_HOUR, TTLCache
from pokemon.resilient_http import resilient_get
from pokemon.services import get_type_statistics
from scripts.q2_load_simulation import ROUTES, start_backends, to_local


def timed(func):
    start = time.perf_counter()
    result = func()
    return result, (time.perf_counter() - start) * 1000


def demo_response_time() -> None:
    print("[1] Response time on the real PokéAPI")
    api_client.pokeapi_cache.clear()

    for label, func in [
        ("pokemon/pikachu", lambda: api_client.get_pokemon("pikachu")),
        ("type statistics 'fire' (~110 calls)", lambda: get_type_statistics("fire")),
    ]:
        _, first = timed(func)
        _, second = timed(func)
        print(f"    {label:<38} 1st: {first:8.1f} ms | 2nd (cache): {second:6.2f} ms  -> x{first / second:,.0f}")

    print(f"    Cache stats: {api_client.pokeapi_cache.stats()}\n")


class SimulatedClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class CountingSession(requests.Session):
    """Real HTTP session that counts the requests actually sent over the network."""

    calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return super().get(*args, **kwargs)


def demo_expiration() -> None:
    print("[2] Expiration after 1 hour (simulated clock, real PokéAPI calls)")
    clock = SimulatedClock()
    cache = TTLCache(ttl=ONE_HOUR, clock=clock)
    session = CountingSession()
    url = f"{api_client.BASE_URL}/pokemon/bulbasaur"

    for minutes in [0, 1, 30, 59.9, 60.1, 75]:
        clock.now = minutes * 60
        before = session.calls
        resilient_get(url, session=session, cache=cache)
        source = "network (HTTP call)" if session.calls > before else "cache"
        print(f"    t = {minutes:>5} min -> served from {source}")
    print(f"    HTTP calls sent: {session.calls} for 6 reads | {cache.stats()}\n")


async def load_run(total: int, cache: TTLCache | None, coalesce: bool) -> tuple[float, dict]:
    urls = (to_local(u) for u in itertools.islice(itertools.cycle(ROUTES), total))
    start = time.perf_counter()
    async with AsyncResilientClient(
        concurrency=300, backoff_factor=0.1, cache=cache, coalesce=coalesce
    ) as client:
        await client.run_bulk(urls)
    return time.perf_counter() - start, client.stats


def demo_load(total: int = 30_000) -> None:
    print(f"[3] Q2 load scenario - {total:,} requests on {len(ROUTES)} routes (local mock backends)")
    backends = start_backends()
    try:
        scenarios = [
            ("no cache (Q2 client)      ", None, False),
            ("coalescing only           ", None, True),
            ("1h cache + coalescing (Q3)", TTLCache(), True),
        ]
        for label, cache, coalesce in scenarios:
            elapsed, stats = asyncio.run(load_run(total, cache, coalesce))
            print(
                f"    {label}: {elapsed:6.2f} s | HTTP calls sent: {stats['requests']:>6,} | "
                f"cache hits: {stats['cache_hits']:>6,} | coalesced: {stats['coalesced']:>6,}"
            )
    finally:
        for process in backends:
            process.terminate()


def main() -> None:
    # Retry warnings from the mock backends' injected errors would clutter the output.
    logging.getLogger("pokemon").setLevel(logging.CRITICAL)
    demo_response_time()
    demo_expiration()
    demo_load()


if __name__ == "__main__":
    main()
