"""Flask application exposing the PokéAPI features as a small JSON REST API."""

import asyncio
import logging

from flask import Flask, jsonify, request

from pokemon.api_client import pokeapi_cache
from pokemon.battle import simulate_battle
from pokemon.errors import ApiError
from pokemon.services import (
    compare_pokemon,
    get_all_types,
    get_pokemon_summary,
    get_type_statistics,
)
from scripts.q1_error_handling_demo import run_simulated_scenarios
from scripts.q2_load_simulation import in_process_load_test

# Upper bounds for the on-demand load test, to keep the dev server responsive.
MAX_LOAD_TOTAL = 50_000
MAX_LOAD_CONCURRENCY = 500

app = Flask(__name__)
app.json.sort_keys = False  # keep a readable, logical key order in responses


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@app.errorhandler(ApiError)
def handle_api_error(exc: ApiError):
    """Translate API-layer exceptions into a clean JSON error with the matching status code."""
    return jsonify(error=str(exc), type=exc.__class__.__name__), exc.status_code


@app.get("/")
def index():
    return jsonify(
        endpoints=[
            "/pokemon/<name_or_id>",
            "/compare/<first>/<second>",
            "/types",
            "/type/<type_name>",
            "/battle/<first>/<second>?seed=<int>",
            "/cache/stats",
            "POST /cache/clear",
            "/demo/resilience",
            "/demo/load?total=<int>&concurrency=<int>&cache=<0|1>",
        ]
    )


@app.get("/pokemon/<identifier>")
def pokemon_stats(identifier: str):
    return jsonify(get_pokemon_summary(identifier))


@app.get("/compare/<first>/<second>")
def pokemon_compare(first: str, second: str):
    return jsonify(compare_pokemon(first, second))


@app.get("/types")
def list_types():
    return jsonify(types=get_all_types())


@app.get("/type/<type_name>")
def type_statistics(type_name: str):
    return jsonify(get_type_statistics(type_name))


@app.get("/battle/<first>/<second>")
def battle(first: str, second: str):
    # Optional ?seed=... replays exactly the same fight.
    seed = request.args.get("seed", type=int)
    return jsonify(simulate_battle(first, second, seed=seed))


@app.get("/cache/stats")
def cache_stats():
    """Expose cache metrics (hits, misses, hit rate) to monitor its efficiency."""
    return jsonify(pokeapi_cache.stats())


@app.post("/cache/clear")
def cache_clear():
    """Empty the cache (useful to demonstrate a cold vs warm cache)."""
    pokeapi_cache.clear()
    return jsonify(pokeapi_cache.stats())


@app.get("/demo/resilience")
def demo_resilience():
    """Q1: replay simulated failures (429, 5xx, timeouts, 401, 404) through the retry layer."""
    return jsonify(scenarios=run_simulated_scenarios(backoff_factor=0.1))


@app.get("/demo/load")
def demo_load():
    """Q2/Q3: run a bounded load test against an in-process mock of api.example.com/data1..3."""
    total = min(request.args.get("total", 5_000, type=int), MAX_LOAD_TOTAL)
    concurrency = min(request.args.get("concurrency", 200, type=int), MAX_LOAD_CONCURRENCY)
    use_cache = request.args.get("cache", "0") == "1"
    if total <= 0 or concurrency <= 0:
        return jsonify(error="total and concurrency must be positive"), 400
    return jsonify(asyncio.run(in_process_load_test(total, concurrency, use_cache)))


if __name__ == "__main__":
    app.run(debug=True)
