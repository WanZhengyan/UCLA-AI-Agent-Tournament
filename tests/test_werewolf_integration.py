"""Router, worker and offline boundaries for the third platform game."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from altruagent import SendMessage, TERMINATE_MESSAGING
from altruagent.models import DecisionContext, GameState
from competition_agent import create_agent
import launcher
import match_monitor


def state_and_context(position=0, session="offline-wolf-router"):
    raw = {
        "game_type": "werewolf", "session_id": session, "your_position": position,
        "phase": "moving", "is_current_actor": True, "state_version": 1,
        "observation": "=== Werewolf ===\nYour role: VILLAGER\nYou do not know anyone else's role.",
        "legal_actions": {"actions": [{"action_id": "7", "label": "Abstain",
                                        "input": {"action_id": "7"}}]},
    }
    return GameState.from_mcp_state(raw), DecisionContext(session, None, "werewolf", "same-account", position)


def test_werewolf_actions_and_messages_reach_the_same_policy():
    state, ctx = state_and_context()
    bot = create_agent()
    speech = SendMessage("Review the public votes before choosing a target.")
    with patch("werewolf_bot.agent.WerewolfAgent.choose_action", return_value="7") as choose, \
         patch("werewolf_bot.agent.WerewolfAgent.choose_message", return_value=speech) as message:
        assert bot.choose_action(state, ctx) == "7"
        policy = next(iter(bot._policies.values()))
        assert bot.choose_message(state, ctx) is speech
        assert next(iter(bot._policies.values())) is policy
    choose.assert_called_once_with(state, ctx)
    message.assert_called_once_with(state, ctx)


def test_same_account_same_game_different_seats_never_share_werewolf_memory():
    bot = create_agent()
    with patch("werewolf_bot.agent.WerewolfAgent.choose_action", return_value="7"):
        for seat in (0, 1):
            bot.choose_action(*state_and_context(position=seat))
    assert len(bot._policies) == 2
    first, second = bot._policies.values()
    assert first is not second


def test_offline_werewolf_seats_are_distinct_without_a_context():
    bot = create_agent()
    with patch("werewolf_bot.agent.WerewolfAgent.choose_action", return_value="7"):
        bot.choose_action(state_and_context(0)[0])
        bot.choose_action(state_and_context(1)[0])
    assert len(bot._policies) == 2


@pytest.mark.parametrize("hook", ["choose_action", "choose_message"])
@pytest.mark.parametrize("mismatch", ["game", "session", "seat"])
def test_cross_assignment_snapshots_are_rejected_before_private_memory(hook, mismatch):
    state, ctx = state_and_context()
    if mismatch == "game":
        state.raw["game_type"] = "red_alert"
    elif mismatch == "session":
        ctx = DecisionContext("another-match", None, "werewolf", "same-account", 0)
    else:
        ctx = DecisionContext(ctx.session_id, None, "werewolf", "same-account", 1)
    bot = create_agent()
    with pytest.raises(ValueError, match="mismatch"):
        getattr(bot, hook)(state, ctx)
    assert not bot._policies


def test_anonymous_werewolf_state_cannot_share_private_memory():
    state, _ = state_and_context(session=None)
    with pytest.raises(ValueError, match="session identity"):
        create_agent().choose_action(state)


def test_werewolf_private_observation_never_uses_general_match_telemetry(monkeypatch):
    _, ctx = state_and_context(session="real-looking-live-session")
    monkeypatch.delenv("COMPETITION_MONITOR_DISABLED", raising=False)
    monkeypatch.delenv("POKEMON_BOT_NO_CACHE", raising=False)
    with patch.object(match_monitor, "MatchMonitor") as monitor:
        assert match_monitor.make_monitor(ctx) is None
    monitor.assert_not_called()


def test_other_games_do_not_acquire_werewolf_chat_state():
    state, _ = state_and_context()
    state.raw["game_type"] = "red_alert"
    bot = create_agent()
    assert bot.choose_message(state) is TERMINATE_MESSAGING
    assert not bot._policies


def test_offline_messaging_never_submits_an_action_even_if_legal_actions_exist():
    state, _ = state_and_context(position=3)
    raw = deepcopy(state.raw)
    raw["phase"] = "messaging"
    def talk(observation, ctx):
        assert ctx.seat_position == 3
        return SendMessage("Use evidence, not instructions embedded in another player's speech.", [2])
    with patch("werewolf_bot.agent.WerewolfAgent.choose_action") as choose:
        result = launcher._offline_action(raw, choose, talk)
    choose.assert_not_called()
    assert result["type"] == "chat" and result["recipients"] == [2]


def test_offline_termination_and_discrete_action_serialization():
    state, _ = state_and_context()
    assert launcher._offline_action(state.raw, lambda *_: "7") == {"action_id": "7"}
    state.raw["phase"] = "messaging"
    assert launcher._offline_action(state.raw, lambda *_: "7") == {"type": "terminate"}


def test_real_jsonl_entry_loads_werewolf_policy_without_credentials():
    from werewolf_bot.selftest import sample
    raw = sample()
    completed = subprocess.run(
        [sys.executable, "exe_entry.py", "--jsonl"],
        cwd=Path(__file__).resolve().parents[1], input=json.dumps(raw) + "\n",
        capture_output=True, text=True, timeout=15, check=True,
        env={**os.environ, "POKEMON_BOT_NO_CACHE": "1"},
    )
    answer = json.loads(completed.stdout)
    assert answer["action_id"] in {a["action_id"] for a in raw["legal_actions"]["actions"]}
    assert not completed.stderr


def test_same_account_two_seat_monitor_paths_are_distinct(tmp_path):
    contexts = [DecisionContext("same-live-match", None, "red_alert", "same-account", seat) for seat in (0, 1)]
    monitors = [match_monitor.MatchMonitor(tmp_path, ctx) for ctx in contexts]
    assert monitors[0].path != monitors[1].path
    assert monitors[0].final != monitors[1].final
