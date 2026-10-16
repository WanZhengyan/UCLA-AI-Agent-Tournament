"""Offline Gen 9 Pokemon metadata and exact unmodified stat calculations.

Data: Pokemon Showdown 0.11.11 (MIT), bundled in dex_data.json.
This module returns static metadata, not a complete Showdown rules engine.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
_STAT_ALIASES = {
    "hp": "hp", "hitpoints": "hp", "attack": "atk", "atk": "atk",
    "defense": "def", "defence": "def", "def": "def",
    "specialattack": "spa", "spattack": "spa", "spa": "spa", "satk": "spa",
    "specialdefense": "spd", "specialdefence": "spd", "spdefense": "spd", "spd": "spd", "sdef": "spd",
    "speed": "spe", "spe": "spe",
}


def idnorm(value: Any) -> str:
    """Use the Showdown ID convention; accept identifier dictionaries too."""
    if isinstance(value, dict):
        value = next((value[k] for k in ("id", "move_id", "species", "name", "move") if value.get(k)), "")
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


@lru_cache(maxsize=1)
def _data() -> dict:
    with Path(__file__).with_name("dex_data.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _resolve(value: Any, table: str) -> str:
    key = idnorm(value)
    data = _data()
    seen = set()
    while key not in data[table] and key in data.get("aliases", {}) and key not in seen:
        seen.add(key)
        key = idnorm(data["aliases"][key])
    return key


def _card(card: Any) -> dict:
    if not isinstance(card, dict):
        return {"species": str(card or "")}
    # Public fixed-set cards sometimes come wrapped in a config/set object.
    result = {}
    for key in ("config", "set", "pokemon", "pokemon_set", "build"):
        nested = card.get(key)
        if isinstance(nested, dict):
            result.update(nested)
    result.update(card)
    return result


def species(name: Any) -> dict:
    """Return raw Showdown species metadata, including types and baseStats."""
    if isinstance(name, dict):
        name = _card(name)
        name = name.get("species") or name.get("species_name") or name.get("name") or name.get("id")
    key = _resolve(name, "species")
    entry = _data()["species"].get(key)
    if entry is not None:
        return entry.copy()
    return {"id": key, "name": str(name or "Unknown"), "exists": False,
            "baseSpecies": str(name or "Unknown"), "types": ["Normal"],
            "baseStats": {k: 80 for k in _STAT_KEYS}, "abilities": {},
            "weightkg": 50, "bst": 480}


def move(name: Any) -> dict:
    """Return raw Showdown static move fields, preserving the original names."""
    overrides = name if isinstance(name, dict) else None
    key = _resolve(name, "moves")
    entry = _data()["moves"].get(key)
    result = entry.copy() if entry else {
        "id": key, "name": str(name or "Unknown"), "exists": False,
        "type": "Normal", "category": "Status", "basePower": 0,
        "accuracy": 100, "priority": 0, "target": "normal", "pp": 10, "flags": {},
    }
    if overrides:
        # Public observed static attributes can fill gaps in an unknown move.
        aliases = {"base_power": "basePower", "move_type": "type", "move_category": "category"}
        for field in ("basePower", "accuracy", "priority", "category", "target", "type"):
            if field in overrides and field != "type":
                result[field] = overrides[field]
        for field, destination in aliases.items():
            if field in overrides:
                result[destination] = overrides[field]
        if overrides.get("type") not in (None, "move", "switch", "pass"):
            result["type"] = str(overrides["type"]).title()
        if isinstance(result.get("category"), str):
            result["category"] = result["category"].title()
    return result


def nature(name: Any) -> dict:
    key = _resolve(name, "natures")
    return _data()["natures"].get(key, {"id": key, "name": str(name or "Hardy"), "exists": False}).copy()


def item(name: Any) -> dict:
    key = _resolve(name, "items")
    return _data()["items"].get(key, {"id": key, "name": str(name or ""), "exists": False}).copy()


def ability(name: Any) -> dict:
    key = _resolve(name, "abilities")
    return _data()["abilities"].get(key, {"id": key, "name": str(name or ""), "exists": False, "rating": 0}).copy()


def effectiveness(move_type: Any, defender_types: Any) -> float:
    """Gen 9 type-chart multiplier (abilities, Tera and move exceptions separate)."""
    if isinstance(defender_types, dict):
        defender_types = defender_types.get("types") or species(defender_types).get("types", [])
    if isinstance(defender_types, str):
        defender_types = [defender_types]
    attack = str(move_type or "Normal").title()
    answer = 1.0
    for defense in defender_types or []:
        row = _data()["types"].get(idnorm(defense), {})
        relation = row.get("damageTaken", {}).get(attack, 0)
        answer *= {0: 1.0, 1: 2.0, 2: 0.5, 3: 0.0}.get(relation, 1.0)
    return answer


def _stat_map(values: Any) -> dict:
    if not isinstance(values, dict):
        return {}
    output = {}
    for key, value in values.items():
        key = _STAT_ALIASES.get(idnorm(key))
        if key and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            output[key] = int(value)
    return output


def stats(card: Any) -> dict[str, int]:
    """Calculate unboosted stats from a fixed set, defaulting to level 50/31 IVs.

    Explicit actual_stats/stats fields override calculations. base_stats fields
    are base species stats, never current battle stats. Missing EVs mean zero;
    explicitly provided zero IVs are preserved. Boosts, status and items are
    deliberately left to the battle evaluator.
    """
    card = _card(card)
    info = species(card)
    base = dict(info["baseStats"])
    base.update(_stat_map(card.get("baseStats") or card.get("base_stats")))
    try:
        level = max(1, min(100, int(card.get("level", 50) or 50)))
    except (TypeError, ValueError):
        level = 50
    evs = _stat_map(card.get("evs") or card.get("effort_values"))
    ivs = _stat_map(card.get("ivs") or card.get("individual_values"))
    nat = nature(card.get("nature", "Hardy"))
    output = {}
    for key in _STAT_KEYS:
        ev = max(0, min(252, evs.get(key, 0)))
        iv = max(0, min(31, ivs.get(key, 31)))
        intermediate = ((2 * base[key] + iv + ev // 4) * level) // 100
        if key == "hp":
            output[key] = 1 if info.get("id") == "shedinja" else intermediate + level + 10
        else:
            value = intermediate + 5
            if nat.get("plus") == key:
                value = value * 110 // 100
            elif nat.get("minus") == key:
                value = value * 90 // 100
            output[key] = value
    actual = _stat_map(card.get("actual_stats") or card.get("stats"))
    output.update({key: value for key, value in actual.items() if value > 0})
    # Summaries expose real maximum HP, which is exact even if EVs are hidden.
    max_hp = card.get("max_hp", card.get("maxhp"))
    if isinstance(max_hp, (int, float)) and not isinstance(max_hp, bool) and max_hp > 0 and math.isfinite(max_hp):
        output["hp"] = int(max_hp)
    return output


def common_moves(name: Any, limit: int = 8) -> list[str]:
    """Public static move priors, ONLY for estimating unseen opponent threats.

    The priors are Pokemon Showdown's Gen 9 random doubles set movepools, with
    random singles fallback. They do not assert a tournament opponent's moves.
    """
    info = species(name)
    key = info["id"]
    data = _data()
    entry = data.get("doublesSets", {}).get(key) or data.get("randomSets", {}).get(key)
    if not entry:
        key = idnorm(info.get("baseSpecies", key))
        entry = data.get("doublesSets", {}).get(key) or data.get("randomSets", {}).get(key) or {}
    candidates = []
    for set_ in entry.get("sets", []):
        for candidate in set_.get("movepool", []):
            candidate = idnorm(candidate)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    # Preserve utility moves while placing the first set's attacks first.
    return candidates[:max(0, int(limit))]


get_species = species
get_move = move
calculate_stats = stats
type_effectiveness = effectiveness
