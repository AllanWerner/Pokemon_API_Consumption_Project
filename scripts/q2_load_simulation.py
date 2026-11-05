"""Q2 - Simulate a very high load of calls against several routes.

Target routes (from the brief):
    https://api.example.com/data1, /data2, /data3

Each route is served by its own local mock backend process (see mock_api_server.py),
with random latency and 429/500/503 errors, so retries are exercised for real.
Request coalescing (Q3) is disabled here so that every request really hits the backends.

Steps:
    1. Baseline: N requests sent one by one with the synchronous Q1 client
    2. Same N requests with the async client -> speed-up
    3. High load: --total requests (default 100 000) streamed through the worker pool

Run from the project root:
    python -m scripts.q2_load_simulation
    python -m scripts.q2_load_simulation --total 1000000 --concurrency 500
"""

import argparse
import asyncio
import itertools
import logging
import multiprocessing
import socket
import time
from urllib.parse import urlparse

import requests
from aiohttp import web

from pokemon.async_http import AsyncResilientClient
from pokemon.cache import TTLCache
from pokemon.resilient_http import resilient_get
from scripts.mock_api_server import build_app, serve

ROUTES = [
    "https://api.example.com/data1",
    "https://api.example.com/data2",
    "https://api.example.com/data3",
]

# One local backend per route (separate processes = separate CPUs, like distinct services).
LOCAL_BACKENDS = {"/data1": 8081, "/data2": 8082, "/data3": 8083}


def to_local(url: str) -> str:
    """Redirect an api.example.com URL to its local mock backend."""
    path = urlparse(url).path
    return f"http://127.0.0.1:{LOCAL_BACKENDS[path]}{path}"


def url_stream(total: int):
    """Lazy generator of `total` URLs cycling over the routes (never stored in memory)."""
    return (to_local(url) for url in itertools.islice(itertools.cycle(ROUTES), total))


def start_backends() -> list[multiprocessing.Process]:
    processes = [multiprocessing.Process(target=serve, args=(port,), daemon=True) for port in LOCAL_BACKENDS.values()]
    for process in processes:
        process.start()
    # Wait until every backend accepts connections.
    for port in LOCAL_BACKENDS.values():
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
    return processes


def run_sequential(n: int) -> float:
    """Baseline: Q1 client, one request at a time."""
    session = requests.Session()
    start = time.perf_counter()
    for url in url_stream(n):
        try:
            resilient_get(url, session=session, backoff_factor=0.1)
        except Exception:
            pass  # failures are irrelevant for the timing comparison
    return time.perf_counter() - start


async def run_async(n: int, concurrency: int) -> float:
    start = time.perf_counter()
    async with AsyncResilientClient(concurrency=concurrency, backoff_factor=0.1, coalesce=False) as client:
        await client.get_many(url_stream(n))
    return time.perf_counter() - start


async def run_high_load(total: int, concurrency: int) -> None:
    done = 0
    step = max(total // 10, 1)
    start = time.perf_counter()

    def progress(url, data, error):
        # Called for each finished request: only a counter is kept, results are discarded.
        nonlocal done
        done += 1
        if done % step == 0:
            elapsed = time.perf_counter() - start
            print(f"    {done:>10,} / {total:,}  ({done / elapsed:,.0f} req/s)")

    async with AsyncResilientClient(concurrency=concurrency, backoff_factor=0.1, coalesce=False) as client:
        stats = await client.run_bulk(url_stream(total), on_result=progress)

    elapsed = time.perf_counter() - start
    failed = {k: v for k, v in stats.items() if k.startswith("failed_")}
    print(f"\n    Duration        : {elapsed:.1f} s")
    print(f"    Throughput      : {total / elapsed:,.0f} logical requests/s")
    print(f"    HTTP calls sent : {stats['requests']:,} (including {stats['retries']:,} retries)")
    print(f"    Succeeded       : {stats['success']:,} ({stats['success'] / total:.4%})")
    print(f"    Failed          : {sum(failed.values()):,} {failed or ''}")


async def in_process_load_test(
    total: int, concurrency: int, use_cache: bool = False
) -> dict:
    """Lighter load test for the web front end: mock backend and client share one event loop.

    Throughput is lower than with separate backend processes (one CPU does both sides),
    but no extra process has to be started from the Flask server.
    """
    # access_log=None: logging every request would dominate the measured time.
    runner = web.AppRunner(build_app(), access_log=None)
    await runner.setup()
    with socket.socket() as probe:  # find a free local port
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    await web.TCPSite(runner, "127.0.0.1", port).start()

    try:
        urls = (
            f"http://127.0.0.1:{port}{urlparse(u).path}"
            for u in itertools.islice(itertools.cycle(ROUTES), total)
        )
        cache = TTLCache() if use_cache else None
        start = time.perf_counter()
        async with AsyncResilientClient(
            concurrency=concurrency, backoff_factor=0.1, cache=cache, coalesce=use_cache
        ) as client:
            stats = await client.run_bulk(urls)
        elapsed = time.perf_counter() - start
    finally:
        await runner.cleanup()

    failed = sum(v for k, v in stats.items() if k.startswith("failed_"))
    return {
        "total": total,
        "concurrency": concurrency,
        "cache": use_cache,
        "duration_s": round(elapsed, 3),
        "throughput_rps": round(total / elapsed),
        "http_calls": stats["requests"],
        "retries": stats["retries"],
        "cache_hits": stats["cache_hits"],
        "succeeded": stats["success"],
        "failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--total", type=int, default=100_000, help="requests for the high-load phase")
    parser.add_argument("--concurrency", type=int, default=300, help="max simultaneous requests")
    parser.add_argument("--baseline", type=int, default=300, help="requests for the sync vs async comparison")
    args = parser.parse_args()

    # Thousands of retries are expected under load: they are counted in the report instead of logged.
    logging.getLogger("pokemon").setLevel(logging.CRITICAL)

    print("Starting 3 mock backends (data1, data2, data3)...")
    backends = start_backends()
    try:
        print(f"\n[1] Sequential (Q1 client) - {args.baseline} requests")
        seq = run_sequential(args.baseline)
        print(f"    {seq:.2f} s  ->  {args.baseline / seq:,.0f} req/s")

        print(f"\n[2] Async (concurrency {args.concurrency}) - same {args.baseline} requests")
        asy = asyncio.run(run_async(args.baseline, args.concurrency))
        print(f"    {asy:.2f} s  ->  {args.baseline / asy:,.0f} req/s   (x{seq / asy:.0f} faster)")

        print(f"\n[3] High load - {args.total:,} requests over {len(ROUTES)} routes, concurrency {args.concurrency}")
        asyncio.run(run_high_load(args.total, args.concurrency))
    finally:
        for process in backends:
            process.terminate()


if __name__ == "__main__":
    main()
