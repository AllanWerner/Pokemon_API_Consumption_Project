"""Unit tests for the Q1 resilient request function (no real network calls)."""

from unittest.mock import MagicMock

import pytest
import requests

from pokemon.api_client import normalize_identifier
from pokemon.errors import (
    InvalidIdentifierError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    UnauthorizedError,
)
from pokemon.resilient_http import resilient_get

URL = "https://pokeapi.co/api/v2/pokemon/pikachu"


def fake_response(status: int, body: dict | None = None, headers: dict | None = None):
    """Build a minimal stand-in for requests.Response."""
    response = MagicMock(status_code=status, headers=headers or {})
    response.json.return_value = body or {}
    return response


def fake_session(*outcomes):
    """Session whose successive .get() calls return (or raise) the given outcomes."""
    session = MagicMock()
    session.get.side_effect = list(outcomes)
    return session


def call(session, **kwargs):
    """Run resilient_get while recording the requested pauses instead of sleeping."""
    pauses = []
    result = resilient_get(URL, session=session, sleep=pauses.append, **kwargs)
    return result, pauses


def test_success_on_first_try():
    session = fake_session(fake_response(200, {"name": "pikachu"}))
    result, pauses = call(session)
    assert result == {"name": "pikachu"}
    assert pauses == []


def test_retries_server_errors_then_succeeds():
    session = fake_session(fake_response(500), fake_response(503), fake_response(200, {"ok": True}))
    result, pauses = call(session)
    assert result == {"ok": True}
    assert session.get.call_count == 3
    assert len(pauses) == 2
    assert pauses[1] > pauses[0] - 0.5  # backoff grows (jitter tolerated)


def test_429_honours_retry_after_header():
    session = fake_session(fake_response(429, headers={"Retry-After": "2"}), fake_response(200))
    _, pauses = call(session)
    assert pauses == [2.0]


def test_gives_up_after_max_retries():
    session = fake_session(*[fake_response(503)] * 4)
    with pytest.raises(ServerError):
        call(session, max_retries=3)
    assert session.get.call_count == 4  # 1 attempt + 3 retries


def test_rate_limit_error_when_429_persists():
    session = fake_session(*[fake_response(429)] * 3)
    with pytest.raises(RateLimitError):
        call(session, max_retries=2)


@pytest.mark.parametrize("status, error", [(404, NotFoundError), (401, UnauthorizedError)])
def test_client_errors_are_not_retried(status, error):
    session = fake_session(fake_response(status))
    with pytest.raises(error):
        call(session)
    assert session.get.call_count == 1


def test_network_errors_are_retried():
    session = fake_session(requests.Timeout(), requests.ConnectionError(), fake_response(200, {"ok": 1}))
    result, pauses = call(session)
    assert result == {"ok": 1}
    assert len(pauses) == 2


def test_network_error_raised_when_persistent():
    session = fake_session(*[requests.Timeout()] * 2)
    with pytest.raises(NetworkError):
        call(session, max_retries=1)


@pytest.mark.parametrize("bad", ["", "   ", "pika chu", "0", "-3", "dragon!"])
def test_invalid_identifiers_rejected_locally(bad):
    with pytest.raises(InvalidIdentifierError):
        normalize_identifier(bad)


def test_identifier_is_normalized():
    assert normalize_identifier("  Pikachu ") == "pikachu"
    assert normalize_identifier(25) == "25"
