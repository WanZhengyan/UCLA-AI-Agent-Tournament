"""Regressions for public VGC mechanics and robust candidate selection."""
import copy
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from pokemon_bot.battle import evaluate, joint_options, simulate
from pokemon_bot.state import normalize_mon


PASS = {"type": "pass"}


def mon(name, moves=(), **kwargs):
    return normalize_mon(dict(species=name, moves=list(moves), current_hp_fraction=1., **kwargs), {})


def move(name, target=1):
    return {"type": "move", "move_id": name, "target": target}


def state(ours, theirs):
    return dict(own=[ours, None], foe=[theirs, None], own_bench=[], foe_bench=[], field={})


def resolved(base, actions):
    snapshots = []
    def capture(board, benches, field, horizon=True):
        snapshots.append(copy.deepcopy((board, benches, field)))
        return evaluate(board, benches, field, horizon)
    with patch("pokemon_bot.battle.evaluate", side_effect=capture):
        value = simulate(base, actions, horizon=False)
    return value, snapshots[-1]


@pytest.mark.parametrize("trickroom", [False, True])
def test_equal_speed_ohko_is_not_an_automatic_win(trickroom):
    p = mon("Gengar", ["shadowball"])
    p["hp"] = .1
    base = state(p, copy.deepcopy(p))
    base["field"]["trickroom"] = trickroom
    assert simulate(base, ((move("shadowball"), PASS), (move("shadowball"), PASS)), False) == pytest.approx(0.)


def test_sucker_punch_fails_after_extreme_speed():
    base = state(mon("Kingambit", ["suckerpunch"]), mon("Dragonite", ["extremespeed"]))
    a = simulate(base, ((move("suckerpunch"), PASS), (move("extremespeed"), PASS)), False)
    b = simulate(base, ((move("splash", 0), PASS), (move("extremespeed"), PASS)), False)
    assert a == pytest.approx(b)


def test_sucker_punch_still_hits_before_a_normal_attack():
    base = state(mon("Kingambit", ["suckerpunch"]), mon("Dragonite", ["dragonclaw"]))
    a = simulate(base, ((move("suckerpunch"), PASS), (move("dragonclaw"), PASS)), False)
    b = simulate(base, ((move("splash", 0), PASS), (move("dragonclaw"), PASS)), False)
    assert a > b + .1


@pytest.mark.parametrize("attack,target,ability,item,expected", [
    ("snarl", "Milotic", "Competitive", "", {"spa": 1}),
    ("icywind", "Kingambit", "Defiant", "", {"spe": -1, "atk": 2}),
    ("icywind", "Kingambit", "Defiant", "Clear Amulet", {}),
    ("partingshot", "Kingambit", "Defiant", "", {"atk": 3, "spa": -1}),
    ("partingshot", "Serperior", "Contrary", "", {"atk": 1, "spa": 1}),
])
def test_stat_drop_interactions(attack, target, ability, item, expected):
    base = state(mon("Tornadus", [attack]), mon(target, ability=ability, item=item))
    _, (board, _, _) = resolved(base, ((move(attack), PASS), (PASS, PASS)))
    assert board[1][0]["boosts"] == expected


def test_defiant_does_not_trigger_for_an_already_minimum_stat():
    base = state(mon("Tornadus", ["icywind"]), mon("Kingambit", ability="Defiant"))
    base["foe"][0]["boosts"] = {"spe": -6}
    _, (board, _, _) = resolved(base, ((move("icywind"), PASS), (PASS, PASS)))
    assert board[1][0]["boosts"] == {"spe": -6}


def test_contrary_reverses_self_inflicted_drops():
    base = state(mon("Serperior", ["overheat"], ability="Contrary"), mon("Snorlax"))
    _, (board, _, _) = resolved(base, ((move("overheat"), PASS), (PASS, PASS)))
    assert board[0][0]["boosts"]["spa"] == 2


def test_ice_spinner_clears_terrain_for_the_next_attacker():
    base = state(mon("Chien-Pao", ["icespinner"]), mon("Indeedee-F", ["expandingforce"]))
    base["field"]["terrain"] = "psychicterrain"
    _, (_, _, field) = resolved(base, ((move("icespinner"), PASS), (move("expandingforce"), PASS)))
    assert field["terrain"] == ""


@pytest.mark.parametrize("attack", ["brickbreak", "psychicfangs"])
def test_screen_breaking_damage_is_not_reduced_by_the_screen(attack):
    base = state(mon("Dragonite", [attack]), mon("Snorlax"))
    actions = ((move(attack), PASS), (PASS, PASS))
    normal, _ = resolved(base, actions)
    base["field"]["foe_reflect"] = True
    screened, _ = resolved(base, actions)
    assert screened == pytest.approx(normal)


def test_defensive_switch_survives_attack_candidate_pruning():
    own = mon("Pikachu", ["grassknot"])
    own["hp"] = .1
    foe = mon("Garchomp", ["earthquake"])
    reserve = mon("Tornadus", ["hurricane"])
    choices = [[move("grassknot"), {"type": "switch", "species": "tornadus"}], [PASS]]
    candidates = joint_options(choices, [[own, None], [foe, None]], [reserve], {}, 0, cap=1)
    assert any(pair[0].get("type") == "switch" for _, pair in candidates)


def test_original_observation_is_unchanged_by_tie_search():
    base = state(mon("Gengar", ["shadowball"]), mon("Gengar", ["shadowball"]))
    original = copy.deepcopy(base)
    simulate(base, ((move("shadowball"), PASS), (move("shadowball"), PASS)))
    assert base == original


@pytest.mark.skipif(not os.environ.get("SHOWDOWN_NODE"), reason="Set SHOWDOWN_NODE to run the independent rules-engine checks")
def test_showdown_confirms_tactical_mechanics():
    script = Path(__file__).with_name("showdown_mechanics.js")
    completed = subprocess.run([os.environ["SHOWDOWN_NODE"], str(script)], capture_output=True, text=True, timeout=30, check=True)
    report = json.loads(completed.stdout)
    assert report["checks"] == 8
    assert report["engine"] == "pokemon-showdown@0.11.11"
