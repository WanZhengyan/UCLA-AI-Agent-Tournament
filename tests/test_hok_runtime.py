"""MCP-contract tests; the local server double is not a combat simulator."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from altruagent import WAIT
from altruagent.mcp_transport import MCPToolError
from altruagent.models import DecisionContext, GameState
from altruagent.runner import DecisionError, run_game
from competition_agent import create_agent


GAME = "honor_of_kings_5v5"


def context():
    return DecisionContext("hok-runtime", None, GAME, "team-one", 0)


class TeamServer:
    """Require one legal action per owned hero and the current lockstep version."""

    def __init__(self, mode="realtime", *, error=None, queued=False):
        self.mode = mode
        self.error = error
        self.queued = queued
        self.pending = list(range(5))
        self.orders = {}
        self.version = 40
        self.actions = []
        self.waits = []
        self.reads = 0
        self.rounds = 0
        self.config_reads = 0

    def raw(self, terminal=False):
        entries = []
        for seat in self.pending:
            entries.append({
                "action_id": f"s{seat}:macro_advance", "label": "advance",
                "input": {"action": {"seat": seat, "macro": "macro_advance"}},
            })
        return {
            "game_type": GAME, "session_id": "hok-runtime", "camp": 1,
            "seats": list(range(5)), "state_version": self.version,
            "is_terminal": terminal, "is_current_actor": not self.queued,
            "phase": "finished" if terminal else "queued" if self.queued else "moving",
            "pacing": {"mode": self.mode, "step_interval_s": 0.2},
            "simultaneous": {"your_pending_seats": list(self.pending),
                             "standing_orders": dict(self.orders)},
            "observation": {"seats": {
                str(seat): {"summary": {
                    "my_hero": {"hp": 1000, "max_hp": 1000, "camp": 1,
                                "x": 0, "z": 0, "level": 1},
                    "other_heroes": [], "structures": [],
                }} for seat in range(5)
            }},
            "legal_actions": {"state_version": self.version, "actions": entries},
        }

    def get_state(self):
        self.reads += 1
        # In realtime the terminal observation is delivered after the agent
        # has set all five orders and yielded at its chosen decision cadence.
        return GameState.from_mcp_state(self.raw(terminal=self.rounds >= 1))

    def get_game_config(self, game_type):
        assert game_type == GAME
        self.config_reads += 1
        return {"max_steps": 3000}

    def play_action(self, *, action_id, action, state_version):
        assert state_version == self.version
        if self.error:
            error, self.error = self.error, None
            self.version += 1
            raise MCPToolError("state changed", error_code=error, status_code=None)
        if action is None:
            entry = next(a for a in self.raw()["legal_actions"]["actions"]
                         if a["action_id"] == action_id)
            action = entry["input"]["action"]
        assert action["seat"] in self.pending
        assert action["macro"] == "macro_advance"
        self.actions.append((state_version, deepcopy(action)))
        self.pending.remove(action["seat"])
        self.orders[str(action["seat"])] = action["macro"]
        if not self.pending:
            self.rounds += 1
            self.version += 1
            self.pending = list(range(5))
        terminal = self.mode == "lockstep" and self.rounds == 2
        return {"accepted": True, "state": self.raw(terminal=terminal)}

    def wait_for_update(self, **kwargs):
        self.waits.append(kwargs)
        assert self.queued or self.rounds >= 1
        self.queued = False
        return GameState.from_mcp_state(self.raw(terminal=self.rounds >= 1))

    def get_result(self):
        return {"is_terminal": True, "termination_reason": "step_limit",
                "outcome": {"winner_camp": 1}, "returns": {"team-one": 1}}


class ContractPolicy:
    """A protocol-only policy, deliberately separate from our game strategy."""

    def __init__(self):
        self.results = []

    def choose_action(self, state, context):
        assert state.phase == "moving"
        standing = state.raw["simultaneous"]["standing_orders"]
        for legal in state.legal_actions:
            action = legal.input["action"]
            if (state.raw["pacing"]["mode"] == "lockstep"
                    or standing.get(str(action["seat"])) != action["macro"]):
                return legal
        return WAIT

    def on_action_result(self, result, context):
        self.results.append(result)


def test_realtime_sets_all_five_orders_before_pacing_wait():
    server, policy, sleeps = TeamServer(), ContractPolicy(), []
    policy.realtime_wait_seconds = 1.0
    final = run_game(server, context(), policy, sleep=sleeps.append)
    assert [a["seat"] for _, a in server.actions] == list(range(5))
    assert sleeps == [1.0]
    assert not server.waits
    assert len(policy.results) == 5
    assert server.config_reads == 1
    assert final.final_result["outcome"]["winner_camp"] == 1


def test_lockstep_resends_all_pending_heroes_even_when_orders_match():
    server, sleeps = TeamServer("lockstep"), []
    policy = ContractPolicy()
    policy.realtime_wait_seconds = 1.0
    run_game(server, context(), policy, sleep=sleeps.append)
    assert server.actions == [
        (version, {"seat": seat, "macro": "macro_advance"})
        for version in (40, 41) for seat in range(5)
    ]
    assert not sleeps
    assert not server.waits


@pytest.mark.parametrize("mode,error", [
    ("lockstep", "STALE_STATE"), ("realtime", "INVALID_ACTION"),
])
def test_race_is_reported_and_fresh_state_version_is_used(mode, error):
    server, policy = TeamServer(mode, error=error), ContractPolicy()
    run_game(server, context(), policy, sleep=lambda _: None)
    assert policy.results[0]["error"] == error
    assert server.actions[0][0] == 41
    assert {a["seat"] for _, a in server.actions} == set(range(5))


def test_queued_game_long_polls_before_any_decision():
    server = TeamServer(queued=True)
    run_game(server, context(), ContractPolicy(), sleep=lambda _: None)
    assert server.waits[0]["since_phase"] == "queued"
    assert server.waits[0]["timeout_seconds"] == 20
    assert len(server.actions) == 5


def test_policy_without_wait_hint_preserves_sdk_long_poll():
    server, sleeps = TeamServer(), []
    run_game(server, context(), ContractPolicy(), sleep=sleeps.append)
    assert not sleeps
    assert len(server.waits) == 1


@pytest.mark.parametrize("hint", [-1, 5.1, float("inf"), float("nan"), True, "1"])
def test_invalid_wait_hint_fails_before_sleep(hint):
    policy, sleeps = ContractPolicy(), []
    policy.realtime_wait_seconds = hint
    with pytest.raises(DecisionError, match="finite number"):
        run_game(TeamServer(), context(), policy, sleep=sleeps.append)
    assert not sleeps


def test_router_and_real_hok_policy_submit_all_five_orders():
    server, sleeps = TeamServer(), []
    final = run_game(server, context(), create_agent(), sleep=sleeps.append)
    assert [a["seat"] for _, a in server.actions] == list(range(5))
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 5
    assert final.is_terminal


def test_real_hok_policy_keeps_lockstep_alive():
    server = TeamServer("lockstep")
    run_game(server, context(), create_agent(), sleep=lambda _: None)
    assert len(server.actions) == 10
    assert {a["seat"] for _, a in server.actions[:5]} == set(range(5))
    assert {a["seat"] for _, a in server.actions[5:]} == set(range(5))


def test_worker_probe_imports_four_game_factories():
    import launcher
    seen = []
    queue = SimpleNamespace(put=seen.append)
    with patch("hok_platform.agent.create_agent", wraps=__import__(
            "hok_platform.agent", fromlist=["create_agent"]).create_agent) as factory:
        launcher._probe_worker(queue)
    factory.assert_called_once_with()
    assert seen == [{"worker": True, "mcp": True, "entry": True, "tls": True}]
    build = (Path(__file__).resolve().parents[1] / "build.sh").read_text()
    assert "--collect-submodules hok_platform" in build


@pytest.mark.parametrize("value,expected", [(1, "won"), (-1, "lost"), (0, "drew")])
def test_worker_hok_uses_signed_mcp_returns(value, expected):
    from altruagent.worker import game_outcome
    final = GameState.from_mcp_state(TeamServer().raw(terminal=True), result={
        "is_terminal": True, "termination_reason": "step_limit", "returns": {"team-one": value},
    })
    assert game_outcome(final, "team-one") == expected


@pytest.mark.parametrize("result,expected", [
    ({"winner_agent_ids": ["team-one"]}, "won"),
    ({"winner_agent_ids": ["team-two"]}, "lost"),
    ({"outcome": {"winner_camp": 1}}, "won"),
    ({"outcome": {"winner_camp": 2}}, "lost"),
    ({"your_return": 0}, "drew"),
    ({}, None),
])
def test_worker_hok_team_winner_fields(result, expected):
    from altruagent.worker import game_outcome
    final = GameState.from_mcp_state(TeamServer().raw(terminal=True), result=result)
    assert game_outcome(final, "team-one") == expected


@pytest.mark.parametrize("reason", ["start_failed", "engine_failed", "match_stalled", "cancelled"])
def test_worker_hok_failed_start_is_not_a_draw(reason):
    from altruagent.worker import game_outcome
    final = GameState.from_mcp_state(TeamServer().raw(terminal=True), result={
        "termination_reason": reason, "your_return": 0, "winner_agent_ids": ["team-one"],
    })
    assert game_outcome(final, "team-one") == "no result"


@pytest.mark.parametrize("game", ["red_alert", "pokemon_vgc_doubles_draft"])
@pytest.mark.parametrize("value,expected", [(1, "won"), (0, "lost"), (.5, "drew")])
def test_worker_existing_games_keep_zero_one_result_scale(game, value, expected):
    from altruagent.worker import game_outcome
    raw = TeamServer().raw(terminal=True)
    raw["game_type"] = game
    final = GameState.from_mcp_state(raw, result={"your_return": value})
    assert game_outcome(final, "team-one") == expected


def test_hok_selftest_checks_both_teams_without_network(capsys):
    from hok_platform.selftest import run
    with patch("socket.create_connection", side_effect=AssertionError("network not allowed")):
        assert run() == 0
    assert capsys.readouterr().out == "Honor of Kings 5v5 offline protocol checks passed.\n"


def test_launcher_selftest_runs_hok_and_propagates_its_failure():
    import launcher
    with patch("pokemon_bot.selftest.run", return_value=0), \
         patch("redalert_bot.selftest.run", return_value=0), \
         patch("werewolf_bot.selftest.run", return_value=0), \
         patch("hok_platform.selftest.run", return_value=1) as hok, \
         patch.object(launcher, "runtime_self_test", return_value={"worker": True}), \
         patch.object(launcher, "load_configuration") as auth:
        assert launcher.main(["--self-test"]) == 1
    hok.assert_called_once_with()
    auth.assert_not_called()
