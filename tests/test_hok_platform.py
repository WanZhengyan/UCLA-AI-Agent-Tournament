"""AltruAgent 5v5 fixtures follow the published macro/team protocol.

Synthetic only: these are contract and behavior regressions, not gamecore wins.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from altruagent import WAIT, TERMINATE_MESSAGING
from altruagent.models import DecisionContext, GameState
from altruagent.runner import run_game
from altruagent.worker import game_outcome
from competition_agent import create_agent
from hok_platform_bot.agent import GAME_TYPE, HokTeamAgent
from hok_platform_bot.selftest import sample
import launcher


def state(raw):
    return GameState.from_mcp_state(raw)


def context(raw):
    return DecisionContext(raw["session_id"], None, GAME_TYPE, "offline", raw["camp"] - 1)


def view(raw, seat=0):
    return raw["observation"]["seats"][str(seat)]["summary"]


def add_macro(raw, seat=0, macro="macro_attack", near=3000):
    raw["legal_actions"]["actions"].append({
        "action_id": f"s{seat}:{macro}", "label": f"{macro} (nearest: x, {near} away)",
        "input": {"action": {"which_button": 3, "seat": seat}},
    })


def enemy(hp=3000, visible=True, x=2500, level=2):
    return dict(runtime_id=99, camp=2, hp=hp, max_hp=hp, level=level, visible=visible, x=x, z=0)


def only(raw, seats):
    raw["simultaneous"]["your_pending_seats"] = seats


def acknowledge(bot, raw, action):
    bot.on_action_result({"accepted": True})
    if "macro" in action:
        raw["simultaneous"]["standing_orders"][str(action["seat"])] = action["macro"]


@pytest.mark.parametrize("camp", [1, 2])
def test_five_owned_heroes_get_orders_then_realtime_waits(camp):
    raw, bot = sample(camp), HokTeamAgent()
    sent = []
    for _ in range(5):
        action = bot.choose_action(state(raw))
        sent.append(action["seat"])
        assert action["macro"] == "macro_advance"
        acknowledge(bot, raw, action)
    assert sent == raw["seats"]
    assert bot.choose_action(state(raw)) is WAIT


def test_low_hp_hero_gets_priority_before_other_heroes():
    raw = sample()
    view(raw, 4)["my_hero"]["hp"] = 500
    assert HokTeamAgent().choose_action(state(raw)) == {"seat": 4, "macro": "macro_retreat"}


def test_recovery_hysteresis_and_resume():
    raw, bot = sample(), HokTeamAgent()
    only(raw, [0])
    for hp in (500, 1600, 2200):
        view(raw)["my_hero"]["hp"] = hp
        raw["state_version"] += 5
        assert bot.choose_action(state(raw))["macro"] == "macro_retreat"
    view(raw)["my_hero"]["hp"] = 2500
    raw["state_version"] += 5
    assert bot.choose_action(state(raw))["macro"] == "macro_advance"


def test_visible_outnumbering_uses_actual_health_and_level_not_just_percent():
    raw = sample()
    only(raw, [0])
    view(raw)["my_hero"]["hp"] = 2100
    for s in (1, 2, 3, 4):
        view(raw, s)["my_hero"]["x"] = -50000
    view(raw)["other_heroes"] = [enemy(hp=8000, level=10)]
    add_macro(raw)
    assert HokTeamAgent().choose_action(state(raw))["macro"] == "macro_retreat"
    # An injured but genuinely stronger five-hero group may still fight.
    for s in (1, 2, 3, 4):
        view(raw, s)["my_hero"]["x"] = 100
    view(raw)["other_heroes"] = [enemy(hp=2000)]
    assert HokTeamAgent().choose_action(state(raw))["macro"] == "macro_attack"


def test_hidden_enemy_even_with_stale_coordinates_is_not_used():
    raw = sample()
    only(raw, [0])
    view(raw)["my_hero"]["hp"] = 2000
    view(raw)["other_heroes"] = [enemy(hp=100000, visible=False)]
    assert HokTeamAgent().choose_action(state(raw))["macro"] == "macro_advance"


def test_tower_damage_trend_overrides_attack_and_one_friendly_hero():
    raw, bot = sample(), HokTeamAgent()
    only(raw, [0])
    add_macro(raw)
    view(raw)["structures"] = [dict(camp=2, type="ACTOR_TOWER", hp=100, max_hp=8000, x=4000, z=0)]
    assert bot.choose_action(state(raw))["macro"] == "macro_attack"
    raw["state_version"] += 5
    view(raw)["my_hero"]["hp"] = 2100
    assert bot.choose_action(state(raw))["macro"] == "macro_retreat"


def test_skill_is_followed_by_attack_and_retry_uses_fresh_legality():
    raw, bot = sample(), HokTeamAgent()
    only(raw, [0])
    view(raw)["other_heroes"] = [enemy()]
    add_macro(raw)
    add_macro(raw, macro="macro_skill3")
    action = bot.choose_action(state(raw))
    assert action["macro"] == "macro_skill3"
    acknowledge(bot, raw, action)
    raw["state_version"] += 1
    action = bot.choose_action(state(raw))
    assert action["macro"] == "macro_attack"
    acknowledge(bot, raw, action)
    raw["state_version"] += 15
    assert bot.choose_action(state(raw))["macro"] == "macro_skill3"
    bot.on_action_result({"error": "INVALID_ACTION"})
    raw["legal_actions"]["actions"] = [e for e in raw["legal_actions"]["actions"] if e["action_id"] != "s0:macro_skill3"]
    assert bot.choose_action(state(raw)) is WAIT  # the accepted attack is still running
    assert bot.rejected == 1


def test_unacknowledged_or_rejected_command_is_not_treated_as_standing():
    raw, bot = sample(), HokTeamAgent()
    only(raw, [0])
    first = bot.choose_action(state(raw))
    assert bot.choose_action(state(raw)) == first
    bot.on_action_result({"error": "STALE_STATE"})
    assert bot.choose_action(state(raw)) == first


def test_skill_never_cast_just_because_available_with_no_visible_enemy():
    raw = sample()
    add_macro(raw, macro="macro_skill3")
    add_macro(raw)
    assert HokTeamAgent().choose_action(state(raw))["macro"] == "macro_attack"


@pytest.mark.parametrize("mode", ["realtime", "lockstep"])
def test_dead_hero_waits_realtime_but_fills_lockstep_with_listed_noop(mode):
    raw = sample(mode=mode)
    only(raw, [0])
    view(raw)["my_hero"]["hp"] = 0
    raw["legal_actions"]["actions"] = [e for e in raw["legal_actions"]["actions"] if "macro_" not in e["action_id"]]
    result = HokTeamAgent().choose_action(state(raw))
    assert result is WAIT if mode == "realtime" else result == {"which_button": 0, "seat": 0}


def test_lockstep_resends_standing_order_for_each_pending_hero():
    raw = sample(mode="lockstep")
    only(raw, [3])
    raw["simultaneous"]["standing_orders"] = {"3": "macro_advance"}
    assert HokTeamAgent().choose_action(state(raw)) == {"seat": 3, "macro": "macro_advance"}


def test_raw_fallback_fills_every_constraint_and_never_invents_noop():
    raw = sample(mode="lockstep")
    only(raw, [0])
    raw["legal_actions"]["actions"] = [{"action_id": "s0:button_2", "input": {"action": {
        "seat": 0, "which_button": 2, "legal_move_x": [4, 5], "legal_move_z": [7], "legal_target": [0, 1]}}}]
    assert HokTeamAgent().choose_action(state(raw)) == {"seat": 0, "which_button": 2, "move_x": 4, "move_z": 7, "target": 0}
    raw["legal_actions"]["actions"][0]["input"]["action"]["legal_target"] = []
    with pytest.raises(ValueError, match="no complete listed"):
        HokTeamAgent().choose_action(state(raw))


def test_opponents_and_mismatched_action_seats_are_never_commanded():
    raw = sample()
    only(raw, [9])
    add_macro(raw, seat=9)
    assert HokTeamAgent().choose_action(state(raw)) is WAIT
    only(raw, [0])
    raw["legal_actions"]["actions"] = [{"action_id": "s0:macro_advance", "input": {"action": {"seat": 9}}}]
    assert HokTeamAgent().choose_action(state(raw)) is WAIT


@pytest.mark.parametrize("seats", [[0, 9], [True], [10], ["0"]])
def test_malformed_or_foreign_team_rejected(seats):
    raw = sample()
    raw["seats"] = seats
    with pytest.raises(ValueError, match="team seats"):
        HokTeamAgent().choose_action(state(raw))


def test_no_starvation_when_first_hero_action_keeps_changing():
    raw, bot = sample(), HokTeamAgent()
    seen = []
    for _ in range(5):
        action = bot.choose_action(state(raw))
        seen.append(action["seat"])
        # Even without standing-order acknowledgements, rotate across heroes.
    assert seen == [0, 1, 2, 3, 4]


def test_input_immutable_and_memory_reset_for_new_game():
    raw, bot = sample(), HokTeamAgent()
    view(raw)["my_hero"]["hp"] = 500
    original = deepcopy(raw)
    bot.choose_action(state(raw))
    assert raw == original
    raw["session_id"] = "offline-new-hok"
    view(raw)["my_hero"]["hp"] = 2200
    assert bot.choose_action(state(raw))["macro"] == "macro_advance"


def test_router_isolation_no_messaging_and_jsonl_entry():
    raw, router = sample(), create_agent()
    assert router.choose_action(state(raw), context(raw))["seat"] == 0
    other = sample(camp=2)
    router.choose_action(state(other), context(other))
    assert len(router._policies) == 2
    assert router.choose_message(state(raw), context(raw)) is TERMINATE_MESSAGING
    result = subprocess.run([sys.executable, "exe_entry.py", "--jsonl"],
                            input=json.dumps(raw) + "\n", text=True, capture_output=True,
                            cwd=Path(__file__).resolve().parents[1], timeout=20, check=True,
                            env={**os.environ, "POKEMON_BOT_NO_CACHE": "1"})
    assert json.loads(result.stdout) == {"seat": 0, "macro": "macro_advance"}
    assert not result.stderr


def test_assignment_filter_accepts_exact_platform_game_name():
    from altruagent.official import OfficialAgentClient
    from types import SimpleNamespace
    hok, unsupported = SimpleNamespace(game_type=GAME_TYPE), SimpleNamespace(game_type="honor_of_kings")
    with patch.dict(os.environ, {launcher.KEY_ENV: "eak_live_" + "a" * 64,
                                "ALTRUAGENT_CONTROL_URL": launcher.CONTROL_URL}):
        client = launcher.make_official_client()
        try:
            with patch.object(OfficialAgentClient, "assignments", return_value=[unsupported, hok]):
                assert client.assignments() == [hok]
        finally:
            client.close()


class FakeGame:
    def __init__(self, mode="realtime"):
        self.raw = sample(mode=mode)
        self.sent = []
        self.waits = 0
        self.finish = False

    def get_state(self):
        raw = deepcopy(self.raw)
        raw["is_terminal"] = self.finish
        return state(raw)

    def get_game_config(self, game_type):
        assert game_type == GAME_TYPE
        return {}

    def play_action(self, action, action_id, state_version, **kwargs):
        assert action_id is None
        assert state_version == self.raw["state_version"]
        assert action["seat"] in self.raw["simultaneous"]["your_pending_seats"]
        self.sent.append(action)
        self.raw["simultaneous"]["standing_orders"][str(action["seat"])] = action["macro"]
        self.raw["simultaneous"]["your_pending_seats"].remove(action["seat"])
        if not self.raw["simultaneous"]["your_pending_seats"]:
            self.raw["is_current_actor"] = False
        return {"accepted": True, "state_version": state_version}

    def wait_for_update(self, **kwargs):
        self.waits += 1
        self.finish = True
        return self.get_state()

    def get_result(self):
        return {"is_terminal": True, "status": "finished", "termination_reason": "time_limit",
                "your_return": 0, "returns": {"offline": 0}}


@pytest.mark.parametrize("mode", ["realtime", "lockstep"])
def test_real_runner_sends_five_commands_and_handles_result_and_pacing(mode):
    game, sleeps = FakeGame(mode), []
    def sleep(seconds):
        sleeps.append(seconds)
        game.finish = True
    final = run_game(game, context(game.raw), create_agent(), sleep=sleep)
    assert [a["seat"] for a in game.sent] == [0, 1, 2, 3, 4]
    assert game_outcome(final, "offline") == "drew"
    assert sleeps == ([1.0] if mode == "realtime" else [])
    assert game.waits == (0 if mode == "realtime" else 1)


@pytest.mark.parametrize("score,expected", [(1, "won"), (0, "drew"), (-1, "lost")])
def test_hok_signed_returns_not_confused_with_tournament_points(score, expected):
    final = GameState.from_mcp_state(sample(), result={"your_return": score, "is_terminal": True})
    assert game_outcome(final, "offline") == expected


@pytest.mark.parametrize("reason", ["start_failed", "engine_failed", "match_stalled", "cancelled"])
def test_failed_engine_has_no_result_even_with_zero_return(reason):
    final = GameState.from_mcp_state(sample(), result={"your_return": 0, "termination_reason": reason, "is_terminal": True})
    assert game_outcome(final, "offline") == "no result"


def test_authoritative_winner_ids_take_precedence():
    final = GameState.from_mcp_state(sample(), result={"your_return": 0, "winner_agent_ids": ["offline"], "is_terminal": True})
    assert game_outcome(final, "offline") == "won"
