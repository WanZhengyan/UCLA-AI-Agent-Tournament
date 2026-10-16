"""Keep the simplified objective without dropping tactical responses."""
from unittest.mock import patch

import pytest

from pokemon_bot.battle import choose_battle


@pytest.mark.parametrize("outcomes,expected", [
    ([10., -2.], "attack"),  # Mean 4 beats 2 despite the losing tail.
    ([10., 10., 10., 10., -100.], "safe"),  # The fifth response still matters.
])
def test_expected_value_uses_all_retained_responses(outcomes, expected):
    wait = {"type": "pass"}
    attack = ({"type": "move", "move_id": "attack", "target": 1}, wait)
    safe = ({"type": "move", "move_id": "safe", "target": 1}, wait)
    responses = [(0., ({"type": "move", "move_id": str(i)}, wait)) for i in range(len(outcomes))]
    base = {"own": [None, None], "foe": [None, None], "field": {}}
    template = {"slots": [{"slot": 0}, {"slot": 1}]}
    memory = {}

    def simulate(_state, actions, horizon):
        assert horizon is True
        own, foe = actions
        return outcomes[int(foe[0]["move_id"])] if own == attack else 2.

    with patch("pokemon_bot.battle.build_battle", return_value=base), \
         patch("pokemon_bot.battle.enumerate_slot", return_value=[]), \
         patch("pokemon_bot.battle.opponent_slot", return_value=[]), \
         patch("pokemon_bot.battle.joint_options", side_effect=[[(1., attack), (0., safe)], responses]), \
         patch("pokemon_bot.battle.simulate", side_effect=simulate):
        action = choose_battle({}, template, memory, budget=2.)
    assert action["slot_0"]["move_id"] == expected
    assert memory["last_search"]["responses"] == len(outcomes)
