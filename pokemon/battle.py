"""Battle simulation between two Pokémon, based on their base stats.

Rules:
- Base stats are converted to level-50 stats (official formula, IV 31, no EV, neutral nature)
  so that HP and damage are on the same scale as in the games.
- Each turn, the faster Pokémon attacks first (random draw on a Speed tie).
- Each attacker uses its best option: physical (Attack vs Defense) or special
  (Sp. Attack vs Sp. Defense), with the move type that is most effective on the defender.
- Damage = simplified official formula x type effectiveness x STAB (1.5) x random(0.85-1.0).
- A KO ends the fight immediately: the survivor wins.
- Otherwise, after 5 turns, the Pokémon that dealt the most total damage wins.
- A seed makes a fight fully reproducible.
"""

import random
from dataclasses import dataclass, field

from pokemon import api_client
from pokemon.services import get_pokemon_summary

LEVEL = 50
MOVE_POWER = 60
STAB = 1.5  # Same Type Attack Bonus: the move shares the attacker's type
MAX_TURNS = 5
RANDOM_RANGE = (0.85, 1.0)


@dataclass
class Fighter:
    label: str  # unique display name (handles mirror matches like pikachu vs pikachu)
    name: str
    types: list[str]
    stats: dict  # level-50 stats
    max_hp: int
    hp: int = field(init=False)
    total_damage: int = 0

    def __post_init__(self):
        self.hp = self.max_hp


def level_stats(base_stats: dict, level: int = LEVEL) -> dict:
    """Convert base stats to in-game stats at `level` (IV 31, EV 0, neutral nature)."""
    stats = {}
    for name, base in base_stats.items():
        core = (2 * base + 31) * level // 100
        stats[name] = core + level + 10 if name == "hp" else core + 5
    return stats


def type_multiplier(attack_type: str, defender_types: list[str], relations: dict) -> float:
    """Effectiveness of `attack_type` against every type of the defender (multiplied)."""
    rel = relations[attack_type]
    multiplier = 1.0
    for defender_type in defender_types:
        if defender_type in rel["no_damage_to"]:
            multiplier *= 0
        elif defender_type in rel["double_damage_to"]:
            multiplier *= 2
        elif defender_type in rel["half_damage_to"]:
            multiplier *= 0.5
    return multiplier


def compute_attack(attacker: Fighter, defender: Fighter, relations: dict, rng: random.Random) -> dict:
    """Compute one attack: chosen category and type, effectiveness and damage dealt."""
    # Physical or special: whichever ratio is better for the attacker.
    physical = attacker.stats["attack"] / defender.stats["defense"]
    special = attacker.stats["special-attack"] / defender.stats["special-defense"]
    category, ratio = ("physical", physical) if physical >= special else ("special", special)

    # Pick the attacker's type that hits the defender the hardest.
    move_type = max(attacker.types, key=lambda t: type_multiplier(t, defender.types, relations))
    effectiveness = type_multiplier(move_type, defender.types, relations)

    base = ((2 * LEVEL / 5 + 2) * MOVE_POWER * ratio) / 50 + 2
    damage = int(base * effectiveness * STAB * rng.uniform(*RANDOM_RANGE))

    return {
        "attacker": attacker.label,
        "defender": defender.label,
        "category": category,
        "move_type": move_type,
        "effectiveness": effectiveness,
        "damage": damage,
    }


def turn_order(a: Fighter, b: Fighter, rng: random.Random) -> tuple[Fighter, Fighter]:
    """Faster Pokémon first; a coin flip breaks Speed ties."""
    if a.stats["speed"] != b.stats["speed"]:
        return (a, b) if a.stats["speed"] > b.stats["speed"] else (b, a)
    return (a, b) if rng.random() < 0.5 else (b, a)


def run_battle(a: Fighter, b: Fighter, relations: dict, seed: int) -> dict:
    """Pure battle engine (no API call): plays up to MAX_TURNS turns and returns the full log."""
    rng = random.Random(seed)
    turns, ko = [], None

    for number in range(1, MAX_TURNS + 1):
        actions = []
        first, second = turn_order(a, b, rng)
        for attacker, defender in ((first, second), (second, first)):
            action = compute_attack(attacker, defender, relations, rng)
            # Damage cannot exceed the defender's remaining HP.
            dealt = min(action["damage"], defender.hp)
            defender.hp -= dealt
            attacker.total_damage += dealt
            action.update(damage=dealt, defender_hp=defender.hp)
            actions.append(action)
            if defender.hp == 0:
                ko = defender
                break  # a KO'd Pokémon cannot strike back
        turns.append({"turn": number, "actions": actions})
        if ko:
            break

    if ko:
        winner, reason = (b if ko is a else a).label, "ko"
    elif a.total_damage != b.total_damage:
        winner, reason = (a if a.total_damage > b.total_damage else b).label, "damage"
    else:
        winner, reason = "tie", "tie"

    return {
        "seed": seed,
        "fighters": [
            {"label": f.label, "name": f.name, "types": f.types, "max_hp": f.max_hp,
             "remaining_hp": f.hp, "total_damage": f.total_damage, "level_stats": f.stats}
            for f in (a, b)
        ],
        "turns": turns,
        "turns_played": len(turns),
        "ko": ko.label if ko else None,
        "winner": winner,
        "reason": reason,
    }


def simulate_battle(first: str | int, second: str | int, seed: int | None = None) -> dict:
    """Fetch both Pokémon and their types' damage relations, then run the battle."""
    summaries = [get_pokemon_summary(first), get_pokemon_summary(second)]

    # Damage relations of every attacking type involved (cached API calls).
    attack_types = {t for s in summaries for t in s["types"]}
    relations = {t: _damage_relations(t) for t in attack_types}

    labels = [s["name"] for s in summaries]
    if labels[0] == labels[1]:
        labels = [f"{labels[0]} (1)", f"{labels[1]} (2)"]  # mirror match

    fighters = []
    for label, summary in zip(labels, summaries):
        stats = level_stats(summary["stats"])
        fighters.append(Fighter(label, summary["name"], summary["types"], stats, stats["hp"]))

    # A random seed is drawn when none is given and returned, so any fight can be replayed.
    seed = seed if seed is not None else random.randrange(1_000_000)
    result = run_battle(*fighters, relations=relations, seed=seed)
    for fighter, summary in zip(result["fighters"], summaries):
        fighter["sprite"] = summary["sprite"]
    return result


def _damage_relations(type_name: str) -> dict:
    """Return {relation: [type names]} for the offensive relations of a type."""
    relations = api_client.get_type(type_name)["damage_relations"]
    return {
        key: [t["name"] for t in relations[key]]
        for key in ("double_damage_to", "half_damage_to", "no_damage_to")
    }
