"""Low-level HTTP access to the PokéAPI."""

import re

import requests

from pokemon.errors import InvalidIdentifierError
from pokemon.resilient_http import resilient_get

BASE_URL = "https://pokeapi.co/api/v2"
DEFAULT_TIMEOUT = 10  # seconds

# A shared session reuses TCP connections across calls (faster than one-off requests).
_session = requests.Session()

# PokéAPI names: lowercase letters/digits, dash-separated words (e.g. "mr-mime"), no leading dash.
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def fetch_json(url: str) -> dict:
    """GET a PokéAPI URL through the resilient request layer (retries + error mapping)."""
    return resilient_get(url, session=_session, timeout=DEFAULT_TIMEOUT)


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


def get_type_list() -> dict:
    """Fetch the list of every Pokémon type known by the API."""
    # limit=100 guarantees all types are returned in a single page.
    return fetch_json(f"{BASE_URL}/type?limit=100")


def get_type(type_name: str) -> dict:
    """Fetch raw data for a Pokémon type (e.g. 'fire', 'dragon')."""
    return fetch_json(f"{BASE_URL}/type/{normalize_identifier(type_name)}")
