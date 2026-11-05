"""Tests for the battle engine (pure functions, no network calls)."""

from pokemon.battle import MAX_TURNS, Fighter, level_stats, run_battle, type_multiplier

RELATIONS = {
    "water": {"double_damage_to": ["fire", "rock"], "half_damage_to": ["water"], "no_damage_to": []},
    "fire": {"double_damage_to": ["grass"], "half_damage_to": ["water", "rock"], "no_damage_to": []},
    "normal": {"double_damage_to": [], "half_damage_to": ["rock"], "no_damage_to": ["ghost"]},
    "ghost": {"double_damage_to": ["ghost"], "half_damage_to": [], "no_damage_to": ["normal"]},
}


def make_fighter(name, types, hp=100, atk=100, df=100, spa=100, spd=100, speed=100):
    stats = level_stats(
        {"hp": hp, "attack": atk, "defense": df, "special-attack": spa, "special-defense": spd, "speed": speed}
    )
    return Fighter(name, name, types, stats, stats["hp"])


def test_level_stats_formula():
    # Pikachu base HP 35 / Speed 90 -> 110 HP and 110 Speed at level 50.
    stats = level_stats({"hp": 35, "speed": 90})
    assert stats == {"hp": 110, "speed": 110}


def test_type_multiplier_dual_type_and_immunity():
    assert type_multiplier("water", ["fire", "rock"], RELATIONS) == 4
    assert type_multiplier("fire", ["water"], RELATIONS) == 0.5
    assert type_multiplier("normal", ["ghost"], RELATIONS) == 0


def test_same_seed_gives_same_fight():
    results = [
        run_battle(make_fighter("a", ["water"]), make_fighter("b", ["fire"]), RELATIONS, seed=123)
        for _ in range(2)
    ]
    assert results[0] == results[1]


def test_ko_ends_the_fight_and_survivor_wins():
    strong = make_fighter("strong", ["water"], atk=200, speed=150)
    weak = make_fighter("weak", ["fire"], hp=20, df=30)
    result = run_battle(strong, weak, RELATIONS, seed=1)
    assert result["reason"] == "ko"
    assert result["ko"] == "weak"
    assert result["winner"] == "strong"
    assert result["turns_played"] < MAX_TURNS
    # The KO'd Pokémon did not strike back in the final turn.
    assert result["turns"][-1]["actions"][-1]["defender_hp"] == 0


def test_no_ko_after_five_turns_total_damage_decides():
    # Huge HP/defenses so nobody is KO'd; "a" hits clearly harder than "b".
    tank_a = make_fighter("a", ["water"], hp=255, df=230, spd=230, atk=80, spa=80)
    tank_b = make_fighter("b", ["water"], hp=255, df=230, spd=230, atk=30, spa=30)
    result = run_battle(tank_a, tank_b, RELATIONS, seed=5)
    assert result["turns_played"] == MAX_TURNS
    assert result["reason"] == "damage"
    assert result["winner"] == "a"
    damage = {f["label"]: f["total_damage"] for f in result["fighters"]}
    assert damage["a"] > damage["b"]


def test_immune_defender_takes_no_damage():
    normal = make_fighter("normal", ["normal"])
    ghost = make_fighter("ghost", ["ghost"])
    result = run_battle(normal, ghost, RELATIONS, seed=3)
    dealt_by_normal = [
        act["damage"] for turn in result["turns"] for act in turn["actions"] if act["attacker"] == "normal"
    ]
    assert set(dealt_by_normal) == {0}


def test_faster_pokemon_attacks_first():
    fast = make_fighter("fast", ["water"], speed=150)
    slow = make_fighter("slow", ["water"], speed=20)
    result = run_battle(slow, fast, RELATIONS, seed=9)
    assert all(turn["actions"][0]["attacker"] == "fast" for turn in result["turns"])
