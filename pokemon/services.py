"""Business logic built on top of the raw PokéAPI responses."""

from statistics import mean

from pokemon import api_client

# Mapping between API stat names and readable labels.
STAT_LABELS = {
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special-attack": "Sp. Attack",
    "special-defense": "Sp. Defense",
    "speed": "Speed",
}

# Special types exposed by the API that contain no Pokémon: hidden from the type list.
EMPTY_TYPES = {"stellar", "unknown", "shadow"}


def extract_stats(raw: dict) -> dict:
    """Convert the API 'stats' list into a flat {stat_name: base_value} dict."""
    return {s["stat"]["name"]: s["base_stat"] for s in raw["stats"]}


def get_pokemon_summary(identifier: str | int) -> dict:
    """Return a compact profile of a Pokémon instead of the full JSON payload."""
    raw = api_client.get_pokemon(identifier)
    return {
        "id": raw["id"],
        "name": raw["name"],
        "types": [t["type"]["name"] for t in raw["types"]],
        "height": raw["height"] / 10,  # decimetres -> metres
        "weight": raw["weight"] / 10,  # hectograms -> kilograms
        "stats": extract_stats(raw),
    }


def _winner(name_a: str, value_a: int, name_b: str, value_b: int) -> str:
    """Return the name with the higher value, or 'tie'."""
    if value_a == value_b:
        return "tie"
    return name_a if value_a > value_b else name_b


def compare_pokemon(first: str | int, second: str | int) -> dict:
    """Compare two Pokémon stat by stat and designate the stronger one in HP and Attack."""
    a = get_pokemon_summary(first)
    b = get_pokemon_summary(second)

    comparison = {
        stat: {
            a["name"]: a["stats"][stat],
            b["name"]: b["stats"][stat],
            "winner": _winner(a["name"], a["stats"][stat], b["name"], b["stats"][stat]),
        }
        for stat in STAT_LABELS
    }

    # Overall verdict is based on the sum of HP and Attack, as required by the brief.
    score_a = a["stats"]["hp"] + a["stats"]["attack"]
    score_b = b["stats"]["hp"] + b["stats"]["attack"]

    return {
        "pokemon": [a, b],
        "comparison": comparison,
        "hp_winner": comparison["hp"]["winner"],
        "attack_winner": comparison["attack"]["winner"],
        "overall_winner": _winner(a["name"], score_a, b["name"], score_b),
    }


def get_all_types() -> list[str]:
    """Return the names of all playable Pokémon types."""
    data = api_client.get_type_list()
    return [t["name"] for t in data["results"] if t["name"] not in EMPTY_TYPES]


def get_type_statistics(type_name: str) -> dict:
    """Count the Pokémon of a given type and compute HP, strength and typing statistics."""
    type_data = api_client.get_type(type_name)
    names = [entry["pokemon"]["name"] for entry in type_data["pokemon"]]

    # One request per Pokémon, sent concurrently (async client) to keep the response time low.
    pokemons = api_client.get_many_pokemon(names)

    result = {"type": type_data["name"], "count": len(names)}
    if not pokemons:
        return result

    # Light per-Pokémon records reused by every indicator below.
    records = []
    for p in pokemons:
        stats = extract_stats(p)
        records.append(
            {
                "name": p["name"],
                "hp": stats["hp"],
                "total": sum(stats.values()),
                "dual_type": len(p["types"]) > 1,
            }
        )

    weakest_hp = min(records, key=lambda r: r["hp"])
    strongest_hp = max(records, key=lambda r: r["hp"])
    strongest = max(records, key=lambda r: r["total"])
    dual_count = sum(r["dual_type"] for r in records)

    result.update(
        {
            "average_hp": round(mean(r["hp"] for r in records), 2),
            "min_hp": {"name": weakest_hp["name"], "hp": weakest_hp["hp"]},
            "max_hp": {"name": strongest_hp["name"], "hp": strongest_hp["hp"]},
            # "Strongest" = highest sum of the six base stats.
            "strongest": {"name": strongest["name"], "total_stats": strongest["total"]},
            "pure_type_count": len(records) - dual_count,
            "dual_type_count": dual_count,
        }
    )
    return result
