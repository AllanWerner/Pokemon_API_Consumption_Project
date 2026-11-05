"""Q2 - Asynchronous version of the resilient client, designed for very high request volumes.

Why it scales:
- asyncio: while one request waits for the network, hundreds of others progress
  on a single thread (I/O-bound work does not need one thread per request).
- One shared aiohttp session: TCP connections are pooled and reused (keep-alive).
- Bounded concurrency (semaphore + connector limit): we never open more sockets than
  the server / OS can handle, which also limits 429 responses.
- `run_bulk` uses a fixed pool of workers fed by a bounded queue: memory stays
  constant whether you send 1 000 or 10 000 000 requests (URLs are consumed lazily).
- Same retry policy as Q1 (shared `classify_error_status`), with non-blocking pauses.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable

import aiohttp

from pokemon.errors import ApiError, NetworkError
from pokemon.resilient_http import classify_error_status, compute_delay

logger = logging.getLogger(__name__)

ResultCallback = Callable[[str, dict | None, ApiError | None], Awaitable[None] | None]


class AsyncResilientClient:
    """Async HTTP client with retries, bounded concurrency and built-in metrics.

    Usage:
        async with AsyncResilientClient(concurrency=200) as client:
            data = await client.get_json(url)
    """

    def __init__(
        self,
        *,
        concurrency: int = 100,
        timeout: float = 10,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        max_delay: float = 30,
    ):
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._session: aiohttp.ClientSession | None = None
        # Counters exposed for monitoring: requests sent, retries, successes, failures by type.
        self.stats: Counter = Counter()

    async def __aenter__(self) -> "AsyncResilientClient":
        connector = aiohttp.TCPConnector(limit=self.concurrency, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(connector=connector, timeout=self._timeout)
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._session.close()

    async def get_json(self, url: str) -> dict:
        """GET `url` and return its JSON body, retrying transient failures (429, 5xx, network)."""
        last_error: ApiError | None = None

        for attempt in range(self.max_retries + 1):
            # The semaphore is held only during the request, not during the backoff pause,
            # so a sleeping retry does not block a slot other requests could use.
            async with self._semaphore:
                self.stats["requests"] += 1
                try:
                    async with self._session.get(url) as response:
                        if response.status < 400:
                            try:
                                return await response.json(content_type=None)
                            except ValueError as exc:
                                raise ApiError("Response body is not valid JSON", url=url) from exc
                        last_error, delay = classify_error_status(
                            response.status, response.headers, url, attempt,
                            self.backoff_factor, self.max_delay,
                        )
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as exc:
                    last_error = NetworkError(f"Network failure: {exc.__class__.__name__}", url=url)
                    delay = compute_delay(attempt, self.backoff_factor, self.max_delay)

            if attempt < self.max_retries:
                self.stats["retries"] += 1
                logger.debug("%s -> retry %d/%d in %.2fs", last_error, attempt + 1, self.max_retries, delay)
                await asyncio.sleep(delay)  # non-blocking pause: other requests keep running

        logger.debug("%s -> giving up after %d attempts", url, self.max_retries + 1)
        raise last_error

    async def get_many(self, urls: Iterable[str]) -> list[dict | ApiError]:
        """Fetch a moderate list of URLs concurrently, preserving order.

        Failures are returned in place (not raised) so one bad URL does not cancel the others.
        Suitable for hundreds/thousands of URLs; use `run_bulk` for millions.
        """
        return await asyncio.gather(*(self._safe_get(url) for url in urls))

    async def _safe_get(self, url: str) -> dict | ApiError:
        try:
            return await self.get_json(url)
        except ApiError as exc:
            return exc

    async def run_bulk(
        self,
        urls: Iterable[str],
        on_result: ResultCallback | None = None,
        workers: int | None = None,
    ) -> Counter:
        """Process a (possibly huge / lazy) stream of URLs with a fixed pool of workers.

        Results are not accumulated: each one is handed to `on_result(url, data, error)`,
        which keeps memory usage flat regardless of the number of requests.
        """
        workers = workers or self.concurrency
        # Bounded queue = back-pressure: the producer waits when workers are busy.
        queue: asyncio.Queue = asyncio.Queue(maxsize=workers * 2)

        async def worker() -> None:
            while (url := await queue.get()) is not None:
                data, error = None, None
                try:
                    data = await self.get_json(url)
                    self.stats["success"] += 1
                except ApiError as exc:
                    error = exc
                    self.stats[f"failed_{exc.__class__.__name__}"] += 1
                if on_result is not None:
                    outcome = on_result(url, data, error)
                    if asyncio.iscoroutine(outcome):
                        await outcome

        tasks = [asyncio.create_task(worker()) for _ in range(workers)]
        for url in urls:
            await queue.put(url)
        for _ in tasks:
            await queue.put(None)  # one stop signal per worker
        await asyncio.gather(*tasks)
        return self.stats
