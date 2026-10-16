from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import launcher
from altruagent import WAIT, WithReasoning
from altruagent.models import DecisionContext, GameState
from competition_agent import create_agent
from redalert_bot.selftest import sample


def context(game="red_alert", session="offline-router", seat="one"):
    return DecisionContext(session, None, game, seat, 0, game_config={"rules": {}})


def red_state():
    raw = sample()
    raw["session_id"] = "offline-router"
    return GameState.from_mcp_state(raw)


def test_router_plays_real_redalert_deploy_and_wait():
    bot, state, ctx = create_agent(), red_state(), context()
    assert bot.choose_action(state, ctx)["orders"][0] == {"cmd": "deploy", "units": [1]}
    assert bot.choose_action(state, ctx) is WAIT


def test_pokemon_route_preserves_original_state_and_context():
    bot = create_agent()
    ctx = context("pokemon_vgc_doubles_draft")
    state = SimpleNamespace(raw={"game_type": ctx.game_type}, session_id=ctx.session_id)
    result = {"type": "doubles_turn"}
    with patch("pokemon_bot.agent.PokemonAgent.choose_action", return_value=result) as pokemon, \
         patch("redalert_bot.agent.RedAlertAgent.choose_action") as redalert:
        assert bot.choose_action(state, ctx) is result
    pokemon.assert_called_once_with(state, ctx)
    redalert.assert_not_called()


def test_same_match_different_seats_have_independent_redalert_memory():
    bot, state = create_agent(), red_state()
    for seat in ("one", "two"):
        assert bot.choose_action(state, context(seat=seat))["orders"][0]["cmd"] == "deploy"
    assert len(bot._policies) == 2


def test_fresh_factories_have_no_shared_policy_memory():
    a, b = create_agent(), create_agent()
    state, ctx = red_state(), context()
    assert a.choose_action(state, ctx)["orders"]
    assert a.choose_action(state, ctx) is WAIT
    assert b.choose_action(state, ctx)["orders"]


def test_result_callback_reaches_original_policy_and_releases_failed_order():
    bot, state, ctx = create_agent(), red_state(), context()
    bot.choose_action(state, ctx)
    key = ("red_alert", ctx.session_id, ctx.agent_id)
    policy = bot._policies[key]
    bot.on_action_result({"error": "INVALID_ACTION", "detail": "[0] deploy: invalid"}, ctx)
    memory = policy.sessions[ctx.session_id]
    assert memory["failures"]
    assert not memory["cooldowns"]
    assert bot._policies[key] is policy


def test_callback_for_another_seat_cannot_modify_existing_memory():
    bot, state, ctx = create_agent(), red_state(), context()
    bot.choose_action(state, ctx)
    policy = next(iter(bot._policies.values()))
    before = deepcopy(policy.sessions)
    bot.on_action_result({"error": "INVALID_ACTION"}, context(seat="other"))
    assert policy.sessions == before
    assert len(bot._policies) == 1


def test_unknown_game_is_not_assumed_to_be_pokemon():
    bot = create_agent()
    ctx = context("werewolf")
    state = SimpleNamespace(raw={"game_type": ctx.game_type}, session_id=ctx.session_id)
    with pytest.raises(ValueError, match="Unsupported game"):
        bot.choose_action(state, ctx)
    assert not bot._policies


def test_assignment_and_observation_game_mismatch_is_rejected():
    bot = create_agent()
    with pytest.raises(ValueError, match="mismatch"):
        bot.choose_action(red_state(), context("pokemon_vgc_doubles_draft"))
    assert not bot._policies


def test_state_game_type_is_used_if_context_is_missing():
    assert create_agent().choose_action(red_state())["orders"][0]["cmd"] == "deploy"


def test_offline_passes_game_config_and_serializes_realtime_wait():
    config = {"rules": {"units": {"harv": {"cost": 1100}}}}
    payload = {"state": sample(), "game_config": config}
    def choose(state, ctx):
        assert ctx.game_type == "red_alert"
        assert ctx.game_config is config
        return WAIT
    assert launcher._offline_action(payload, choose) == {"type": "wait"}


def test_offline_unwraps_reasoned_actions():
    action = {"type": "orders", "orders": [{"cmd": "deploy", "units": [1]}]}
    assert launcher._offline_action(sample(), lambda *_: WithReasoning(action, "Deploy.")) == action


def test_launcher_selftest_checks_both_games_without_authentication():
    with patch("pokemon_bot.selftest.run", return_value=0) as pokemon, \
         patch("redalert_bot.selftest.run", return_value=0) as redalert, \
         patch.object(launcher, "runtime_self_test", return_value={"worker": True}), \
         patch.object(launcher, "load_configuration") as auth:
        assert launcher.main(["--self-test"]) == 0
    pokemon.assert_called_once_with()
    redalert.assert_called_once_with()
    auth.assert_not_called()


def test_real_jsonl_entry_routes_both_games_and_preserves_wait_state():
    from pokemon_bot.selftest import fixture
    from pokemon_bot.legal import validate_action
    pokemon = fixture()
    payloads = [sample(), pokemon, sample()]
    completed = subprocess.run(
        [sys.executable, "exe_entry.py", "--jsonl"],
        cwd=Path(__file__).resolve().parents[1],
        input="".join(json.dumps(raw) + "\n" for raw in payloads),
        capture_output=True, text=True, timeout=20, check=True,
        env={**os.environ, "POKEMON_BOT_NO_CACHE": "1"},
    )
    actions = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(actions) == 3
    assert actions[0]["orders"][0] == {"cmd": "deploy", "units": [1]}
    assert validate_action(actions[1], pokemon["legal_actions"]["actions"][0]["input"]["action"])
    assert actions[2] == {"type": "wait"}
    assert not completed.stderr
