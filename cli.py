"""Interactive command-line interface: asks the user for input and prints readable results."""

import requests

from pokemon.services import (
    STAT_LABELS,
    compare_pokemon,
    get_all_types,
    get_pokemon_summary,
    get_type_statistics,
)


def display_pokemon_stats() -> None:
    """Ask for a Pokémon name/ID and print its base statistics."""
    identifier = input("Pokémon name or ID: ")
    p = get_pokemon_summary(identifier)

    print(f"\n#{p['id']} {p['name'].capitalize()}  [{', '.join(p['types'])}]")
    print(f"Height: {p['height']} m | Weight: {p['weight']} kg")
    for key, label in STAT_LABELS.items():
        print(f"  {label:<12} {p['stats'][key]:>4}")


def compare_two_pokemon() -> None:
    """Ask for two Pokémon and print a side-by-side comparison."""
    first = input("First Pokémon: ")
    second = input("Second Pokémon: ")
    result = compare_pokemon(first, second)
    a, b = (p["name"] for p in result["pokemon"])

    print(f"\n{'Stat':<12} {a:>12} {b:>12}   Winner")
    for key, label in STAT_LABELS.items():
        row = result["comparison"][key]
        print(f"{label:<12} {row[a]:>12} {row[b]:>12}   {row['winner']}")

    print(f"\nStronger in HP     : {result['hp_winner']}")
    print(f"Stronger in Attack : {result['attack_winner']}")
    print(f"Overall (HP + Atk) : {result['overall_winner']}")


def display_type_statistics() -> None:
    """Ask for a type and print the number of Pokémon and their average HP."""
    # Optionally list the available types so the user does not have to guess them.
    if input("Do you want to see all available types first? (y/n): ").strip().lower() in ("y", "yes"):
        print("Available types: " + ", ".join(get_all_types()))

    type_name = input("Pokémon type (fire, dragon, ...): ")
    print("Fetching every Pokémon of this type, please wait...")
    stats = get_type_statistics(type_name)
    print(f"\nType '{stats['type']}': {stats['count']} Pokémon")
    if stats["count"] == 0:
        return

    print(f"  Average HP      : {stats['average_hp']}")
    print(f"  Min HP          : {stats['min_hp']['hp']} ({stats['min_hp']['name']})")
    print(f"  Max HP          : {stats['max_hp']['hp']} ({stats['max_hp']['name']})")
    print(f"  Strongest       : {stats['strongest']['name']} (total base stats {stats['strongest']['total_stats']})")
    print(f"  Pure / dual type: {stats['pure_type_count']} / {stats['dual_type_count']}")


MENU = {
    "1": ("Show a Pokémon's stats", display_pokemon_stats),
    "2": ("Compare two Pokémon", compare_two_pokemon),
    "3": ("Statistics for a type", display_type_statistics),
}


def main() -> None:
    while True:
        print("\n=== PokéAPI explorer ===")
        for key, (label, _) in MENU.items():
            print(f"{key}. {label}")
        print("q. Quit")

        choice = input("> ").strip().lower()
        if choice == "q":
            break
        if choice not in MENU:
            print("Invalid choice.")
            continue

        try:
            MENU[choice][1]()
        except requests.HTTPError as exc:
            # Most common case: unknown Pokémon/type -> 404.
            print(f"API error: {exc}")


if __name__ == "__main__":
    main()
