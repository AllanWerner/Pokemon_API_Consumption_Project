"""Flask application exposing the PokéAPI features as a small JSON REST API."""

import requests
from flask import Flask, jsonify

from pokemon.services import (
    compare_pokemon,
    get_all_types,
    get_pokemon_summary,
    get_type_statistics,
)

app = Flask(__name__)
app.json.sort_keys = False  # keep a readable, logical key order in responses


@app.errorhandler(requests.HTTPError)
def handle_upstream_error(exc: requests.HTTPError):
    """Forward PokéAPI errors (e.g. 404 unknown Pokémon) with a clean JSON message."""
    status = exc.response.status_code if exc.response is not None else 502
    return jsonify(error=f"PokéAPI request failed: {exc}"), status


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
