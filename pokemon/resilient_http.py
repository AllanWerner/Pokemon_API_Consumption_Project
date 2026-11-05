"""Q1 - Robust GET requests: retries, pauses and explicit handling of common HTTP errors.

Strategy:
- 429 Too Many Requests     -> wait (Retry-After header if provided, else backoff) then retry
- 500 / 502 / 503 / 504     -> temporary server failure: exponential backoff then retry
- Timeout / connection error -> exponential backoff then retry
- 400 / 401 / 403 / 404     -> client-side problem: retrying is useless, fail immediately
"""

import logging
import random
import time
from collections.abc import Callable

import requests

from pokemon.errors import (
    ApiError,
    BadRequestError,
    ForbiddenError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    UnauthorizedError,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Non-retryable statuses mapped to their dedicated exception.
CLIENT_ERRORS = {
    400: (BadRequestError, "Bad request: the parameters sent are invalid"),
    401: (UnauthorizedError, "Unauthorized: token missing or invalid"),
    403: (ForbiddenError, "Forbidden: access to this resource is denied"),
    404: (NotFoundError, "Resource not found"),
}


def compute_delay(attempt: int, backoff_factor: float, max_delay: float) -> float:
    """Exponential backoff with jitter: ~factor * 2^attempt, capped at max_delay."""
    delay = backoff_factor * (2**attempt)
    # Random jitter avoids many clients retrying at exactly the same moment.
    return min(delay + random.uniform(0, backoff_factor), max_delay)


def _retry_after_seconds(headers) -> float | None:
    """Read the Retry-After header (in seconds) when the server provides it."""
    value = headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # HTTP-date format is not handled: fall back to backoff


def classify_error_status(
    status: int, headers, url: str, attempt: int, backoff_factor: float, max_delay: float
) -> tuple[ApiError, float]:
    """Decide what to do with an HTTP error status (shared by the sync and async clients).

    Raises immediately for non-retryable statuses; otherwise returns the error to
    report if retries run out, and the delay to wait before the next attempt.
    """
    if status in CLIENT_ERRORS:
        exc_class, message = CLIENT_ERRORS[status]
        logger.warning("%s -> HTTP %s, not retried", url, status)
        raise exc_class(f"{message} ({url})", url=url)

    if status == 429:
        # Honour the server's indication when present.
        retry_after = _retry_after_seconds(headers)
        delay = (
            min(retry_after, max_delay)
            if retry_after is not None
            else compute_delay(attempt, backoff_factor, max_delay)
        )
        return RateLimitError(f"Too many requests ({url})", url=url), delay

    if status in RETRYABLE_STATUSES:
        return ServerError(f"Server error {status} ({url})", url=url), compute_delay(
            attempt, backoff_factor, max_delay
        )

    # Any other unexpected status (e.g. 418, 501): fail without retrying.
    raise ApiError(f"Unexpected HTTP status {status} ({url})", status_code=status, url=url)


def resilient_get(
    url: str,
    *,
    session: requests.Session | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 10,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    max_delay: float = 30,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """GET `url` and return its JSON body, retrying on transient failures.

    `max_retries` is the number of extra attempts after the first one.
    `sleep` is injectable so tests and demos can run without real waiting.
    Raises an `ApiError` subclass describing the failure.
    """
    http = session or requests
    last_error: ApiError | None = None

    for attempt in range(max_retries + 1):
        try:
            response = http.get(url, params=params, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = NetworkError(f"Network failure: {exc.__class__.__name__}", url=url)
            delay = compute_delay(attempt, backoff_factor, max_delay)
        else:
            status = response.status_code

            if status < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ApiError("Response body is not valid JSON", url=url) from exc

            last_error, delay = classify_error_status(
                status, response.headers, url, attempt, backoff_factor, max_delay
            )

        if attempt < max_retries:
            logger.warning("%s -> retry %d/%d in %.2fs", last_error, attempt + 1, max_retries, delay)
            sleep(delay)

    logger.error("%s -> giving up after %d attempts", url, max_retries + 1)
    raise last_error
