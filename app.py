"""Flask application exposing the PokéAPI features as a small JSON REST API."""

import logging

from flask import Flask, jsonify

from pokemon.errors import ApiError
from pokemon.services import (
    compare_pokemon,
    get_all_types,
    get_pokemon_summary,
    get_type_statistics,
)

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


if __name__ == "__main__":
    app.run(debug=True)
