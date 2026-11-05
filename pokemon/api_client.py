"""Low-level HTTP access to the PokéAPI."""

import asyncio
import re

import requests

from pokemon.async_http import AsyncResilientClient
from pokemon.cache import ONE_HOUR, TTLCache
from pokemon.errors import InvalidIdentifierError
from pokemon.resilient_http import resilient_get

BASE_URL = "https://pokeapi.co/api/v2"
DEFAULT_TIMEOUT = 10  # seconds
POKEAPI_CONCURRENCY = 20  # simultaneous requests allowed towards PokéAPI

# Shared cache for every PokéAPI call (sync and async): Pokémon data rarely changes,
# so entries are kept 1 hour, bounded to 10 000 responses to cap memory usage.
pokeapi_cache = TTLCache(ttl=ONE_HOUR, max_size=10_000)

# A shared session reuses TCP connections across calls (faster than one-off requests).
_session = requests.Session()

# PokéAPI names: lowercase letters/digits, dash-separated words (e.g. "mr-mime"), no leading dash.
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def fetch_json(url: str) -> dict:
    """GET a PokéAPI URL through the resilient request layer (retries + error mapping)."""
    return resilient_get(url, session=_session, timeout=DEFAULT_TIMEOUT, cache=pokeapi_cache)


def normalize_identifier(identifier: str | int) -> str:
    """Validate a name/ID locally to avoid sending requests that are bound to fail."""
    key = str(identifier).strip().lower()
    if not key:
        raise InvalidIdentifierError("Identifier must not be empty")
    if not _IDENTIFIER_PATTERN.match(key):
        raise InvalidIdentifierError(f"Invalid identifier '{identifier}': use letters, digits or '-'")
    if key.isdigit() and int(key) <= 0:
        raise InvalidIdentifierError(f"Invalid ID '{identifier}': IDs start at 1")
    return key


def get_pokemon(identifier: str | int) -> dict:
    """Fetch raw data for a Pokémon by name or ID."""
    return fetch_json(f"{BASE_URL}/pokemon/{normalize_identifier(identifier)}")


def get_many_pokemon(identifiers: list[str | int]) -> list[dict]:
    """Fetch several Pokémon concurrently (Q2 async client) instead of one by one."""
    urls = [f"{BASE_URL}/pokemon/{normalize_identifier(i)}" for i in identifiers]

    async def _fetch() -> list:
        # Moderate concurrency: PokéAPI is a free public service with a fair-use policy.
        async with AsyncResilientClient(
            concurrency=POKEAPI_CONCURRENCY, timeout=DEFAULT_TIMEOUT, cache=pokeapi_cache
        ) as client:
            return await client.get_many(urls)

    results = asyncio.run(_fetch())
    # Surface the first failure, consistent with the single-call behaviour.
    for result in results:
        if isinstance(result, Exception):
            raise result
    return results


def get_type_list() -> dict:
    """Fetch the list of every Pokémon type known by the API."""
    # limit=100 guarantees all types are returned in a single page.
    return fetch_json(f"{BASE_URL}/type?limit=100")


def get_type(type_name: str) -> dict:
    """Fetch raw data for a Pokémon type (e.g. 'fire', 'dragon')."""
    return fetch_json(f"{BASE_URL}/type/{normalize_identifier(type_name)}")
