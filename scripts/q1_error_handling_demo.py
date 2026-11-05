"""Q1 demo: shows how resilient_get reacts to the most common API failures.

Transient errors (429, 5xx, timeouts) are simulated with a fake session so the
scenarios are reproducible; the 404 and invalid-ID cases hit the real PokéAPI.

Run from the project root:  python -m scripts.q1_error_handling_demo
"""

import logging
import sys
from unittest.mock import MagicMock

import requests

from pokemon import api_client
from pokemon.errors import ApiError
from pokemon.resilient_http import resilient_get

# Logs go to stdout so they interleave correctly with the printed results.
logging.basicConfig(level=logging.INFO, format="    %(levelname)s: %(message)s", stream=sys.stdout)

URL = "https://pokeapi.co/api/v2/pokemon/pikachu"


def scripted_session(*outcomes):
    """Fake session replaying a predefined sequence of responses/exceptions."""
    responses = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            responses.append(outcome)
            continue
        status, headers = outcome if isinstance(outcome, tuple) else (outcome, {})
        resp = MagicMock(status_code=status, headers=headers)
        resp.json.return_value = {"name": "pikachu", "status": status}
        responses.append(resp)
    session = MagicMock()
    session.get.side_effect = responses
    return session


def run(title, func):
    print(f"\n--- {title}")
    try:
        print(f"    RESULT: {func()}")
    except ApiError as exc:
        print(f"    FAILED: [{exc.__class__.__name__}, status {exc.status_code}] {exc}")


def main():
    # Small backoff factor so the demo runs in a few seconds while still really pausing.
    fast = {"backoff_factor": 0.2}

    run(
        "Server errors 500 then 503, then success",
        lambda: resilient_get(URL, session=scripted_session(500, 503, 200), **fast),
    )
    run(
        "429 Too Many Requests with 'Retry-After: 1', then success",
        lambda: resilient_get(URL, session=scripted_session((429, {"Retry-After": "1"}), 200), **fast),
    )
    run(
        "Timeout then connection error, then success",
        lambda: resilient_get(
            URL, session=scripted_session(requests.Timeout(), requests.ConnectionError(), 200), **fast
        ),
    )
    run(
        "503 persists: gives up after 1 attempt + 3 retries",
        lambda: resilient_get(URL, session=scripted_session(*[503] * 4), **fast),
    )
    run(
        "401 Unauthorized: not retried",
        lambda: resilient_get(URL, session=scripted_session(401), **fast),
    )
    run("Real API - unknown Pokémon (404, not retried)", lambda: api_client.get_pokemon("pikachuuu"))
    run("Invalid ID rejected locally (no request sent)", lambda: api_client.get_pokemon("-5"))
    run("Real API - valid call", lambda: api_client.get_pokemon("pikachu")["name"])


if __name__ == "__main__":
    main()
