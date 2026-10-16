"""Preview mechanics regressions, independent of draft heuristic weights."""
from dataclasses import replace

import pytest

from pokemon_bot.draft import Evaluator, _profile


def card(name, *, speed=100, ability="", item="", moves=("Tackle",), types=("Normal",)):
    return {
        "species": name, "card_id": name, "types": list(types),
        "ability": ability, "item": item, "moves": list(moves),
        "stats": {"hp": 200, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": speed},
    }


def tempo_score(weather, ours, theirs):
    # Ghost supports cannot use or receive Tackle. Remove unrelated quality and
    # pair priors so the equal-damage lead exchange exposes only move order.
    support = _profile(card("Misdreavus", moves=("Splash",), types=("Ghost",)))
    support = replace(support, quality=0, weather=weather)
    other_support = replace(support, cid="other-support")
    ours, theirs = (replace(_profile(c), quality=0) for c in (ours, theirs))
    evaluator = Evaluator([])
    evaluator.pair = lambda *_: 0
    return evaluator.lead((ours, support), (theirs, other_support))


@pytest.mark.parametrize("weather,ability", [("rain", "Swift Swim"), ("sun", "Chlorophyll")])
def test_slower_weather_mirror_does_not_receive_first_move_credit(weather, ability):
    ours = card("Golduck", speed=100, ability=ability)
    theirs = card("Kingdra", speed=180, ability=ability)
    assert tempo_score(weather, ours, theirs) < 0


@pytest.mark.parametrize("weather,ability", [
    ("rain", "Swift Swim"), ("sun", "Chlorophyll"),
    ("sand", "Sand Rush"), ("snow", "Slush Rush"),
])
def test_weather_sweeper_overtakes_faster_unboosted_opponent(weather, ability):
    ours = card("Golduck", speed=100, ability=ability)
    theirs = card("Kingdra", speed=180, ability="No Ability")
    assert tempo_score(weather, ours, theirs) > 0


@pytest.mark.parametrize("weather,ability", [
    ("rain", "Swift Swim"), ("sun", "Chlorophyll"),
    ("sand", "Sand Rush"), ("snow", "Slush Rush"),
])
def test_opponent_weather_speed_is_used_when_scoring_our_attack(weather, ability):
    ours = card("Golduck", speed=180, ability="No Ability")
    theirs = card("Kingdra", speed=100, ability=ability)
    assert tempo_score(weather, ours, theirs) < 0


def test_scarf_and_weather_speed_are_compared_for_both_sides():
    ours = card("Golduck", speed=100, ability="Swift Swim", item="Choice Scarf")
    theirs = card("Kingdra", speed=180, ability="Swift Swim")
    assert tempo_score("rain", ours, theirs) < 0


@pytest.mark.parametrize("ability", ["Protosynthesis", "Quark Drive"])
@pytest.mark.parametrize("booster_side", ["own", "foe"])
def test_booster_energy_speed_affects_preview_order(ability, booster_side):
    boosted = card("Flutter Mane", speed=140, ability=ability, item="Booster Energy")
    normal = card("Kingdra", speed=180, ability="No Ability")
    if booster_side == "own":
        assert tempo_score("", boosted, normal) > 0
    else:
        assert tempo_score("", normal, boosted) < 0


def test_sun_activates_speed_protosynthesis_without_booster():
    ours = card("Flutter Mane", speed=140, ability="Protosynthesis")
    theirs = card("Kingdra", speed=180, ability="No Ability")
    assert tempo_score("sun", ours, theirs) > 0


def test_sun_and_booster_energy_do_not_stack_the_same_activation():
    ours = card("Flutter Mane", speed=140, ability="Protosynthesis", item="Booster Energy")
    theirs = card("Kingdra", speed=240, ability="No Ability")
    assert tempo_score("sun", ours, theirs) < 0


@pytest.mark.parametrize("tied_stat", ["atk", "def", "spa", "spd"])
def test_paradox_highest_stat_ties_do_not_choose_speed(tied_stat):
    ours = card("Flutter Mane", speed=140, ability="Protosynthesis", item="Booster Energy")
    ours["stats"][tied_stat] = 140
    theirs = card("Kingdra", speed=180, ability="No Ability")
    # Avoid changing actual damage or bulk while isolating which stat wins.
    theirs["stats"][tied_stat] = 140
    assert tempo_score("", ours, theirs) < 0


@pytest.mark.parametrize("item,ability", [("Choice Scarf", "No Ability"), ("Booster Energy", "Protosynthesis")])
def test_fractional_speed_modifier_is_rounded_to_real_speed_tie(item, ability):
    ours = card("Flutter Mane", speed=151, ability=ability, item=item)
    theirs = card("Kingdra", speed=226, ability="No Ability")
    assert tempo_score("", ours, theirs) == pytest.approx(0)


@pytest.mark.parametrize("weather,ability", [("rain", "Swift Swim"), ("sun", "Chlorophyll")])
def test_umbrella_suppresses_weather_speed_but_not_sun_protosynthesis(weather, ability):
    ours = card("Golduck", speed=140, ability=ability, item="Utility Umbrella")
    theirs = card("Kingdra", speed=180, ability="No Ability")
    assert tempo_score(weather, ours, theirs) < 0
    ours["ability"] = "Protosynthesis"
    assert tempo_score("sun", ours, theirs) > 0


@pytest.mark.parametrize("breaker", ["Mold Breaker", "Teravolt", "Turboblaze"])
@pytest.mark.parametrize("defense,move", [
    ("Levitate", "Earth Power"), ("Water Absorb", "Surf"),
    ("Volt Absorb", "Thunderbolt"), ("Flash Fire", "Flamethrower"),
])
def test_shield_preserves_type_immunity_in_draft_damage(breaker, defense, move):
    attacker = _profile(card("Haxorus", ability=breaker, moves=(move,)))
    defender = _profile(card("Mew", ability=defense))
    evaluator = Evaluator([])
    assert evaluator.damage(attacker, defender) > 0
    protected = replace(defender, cid="protected", item="abilityshield")
    assert evaluator.damage(attacker, protected) == 0


def test_shield_preserves_thick_fat_type_resistance():
    attacker = _profile(card("Haxorus", ability="Mold Breaker", moves=("Ice Beam",)))
    defender = _profile(card("Mew", ability="Thick Fat"))
    protected = replace(defender, cid="protected", item="abilityshield")
    evaluator = Evaluator([])
    assert evaluator.damage(attacker, protected) == pytest.approx(evaluator.damage(attacker, defender) / 2)
