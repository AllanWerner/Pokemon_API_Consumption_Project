"""Low-level HTTP access to the PokéAPI."""

import requests

BASE_URL = "https://pokeapi.co/api/v2"
DEFAULT_TIMEOUT = 10  # seconds

# A shared session reuses TCP connections across calls (faster than one-off requests).
_session = requests.Session()


def fetch_json(url: str) -> dict:
    """Perform a GET request and return the decoded JSON body."""
    response = _session.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_pokemon(identifier: str | int) -> dict:
    """Fetch raw data for a Pokémon by name or ID."""
    # The API only accepts lowercase names.
    key = str(identifier).strip().lower()
    return fetch_json(f"{BASE_URL}/pokemon/{key}")


def get_type_list() -> dict:
    """Fetch the list of every Pokémon type known by the API."""
    # limit=100 guarantees all types are returned in a single page.
    return fetch_json(f"{BASE_URL}/type?limit=100")


def get_type(type_name: str) -> dict:
    """Fetch raw data for a Pokémon type (e.g. 'fire', 'dragon')."""
    key = type_name.strip().lower()
    return fetch_json(f"{BASE_URL}/type/{key}")
