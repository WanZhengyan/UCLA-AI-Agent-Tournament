"""Dispatch the two supported games without sharing seat-local policy state.

The official runtime still owns authentication, leases and one worker per seat.
This module only forwards decisions and real-time order verdicts.
"""
from collections import OrderedDict
from time import perf_counter

SUPPORTED_GAME_TYPES = frozenset({"pokemon_vgc_doubles_draft", "red_alert"})


class CompetitionAgent:
    def __init__(self):
        self._policies = OrderedDict()
        self._selfplay = {}
        self._monitors = OrderedDict()

    def _monitor(self, context, policy=None):
        key = self._key(getattr(context, 'game_type', None), context)
        if key not in self._monitors:
            from match_monitor import make_monitor
            self._monitors[key] = make_monitor(context, policy)
            if len(self._monitors) > 64:
                self._monitors.popitem(last=False)
        return self._monitors[key]

    def _record(self, method, context, policy, *args):
        # Recording must not change actions, callbacks or exception semantics.
        try:
            monitor = self._monitor(context, policy)
            if monitor is not None:
                getattr(monitor, method)(*args)
        except Exception:
            pass

    def on_match_start(self, metadata, context):
        if (getattr(context, 'game_type', None) == 'red_alert'
                and getattr(context, 'tournament_id', None) is None
                and metadata.get('verified_selfplay') is True):
            self._selfplay[self._key('red_alert', context)] = dict(metadata)

    @staticmethod
    def _key(game_type, context, state=None):
        session = getattr(context, "session_id", None) or getattr(state, "session_id", None) or "offline"
        seat = getattr(context, "agent_id", None) or ""
        return game_type, session, seat

    def _policy(self, game_type, context, state):
        if game_type not in SUPPORTED_GAME_TYPES:
            raise ValueError("Unsupported game; no policy will be selected implicitly")
        key = self._key(game_type, context, state)
        if key not in self._policies:
            if game_type == "red_alert":
                metadata = self._selfplay.get(key)
                if metadata:
                    from redalert_bot.selfplay import make_policy
                    policy = make_policy(metadata, context, state)
                else:
                    from redalert_bot.agent import create_agent as create_redalert
                    policy = create_redalert()
            else:
                from pokemon_bot.agent import PokemonAgent
                policy = PokemonAgent()
            self._policies[key] = policy
            if len(self._policies) > 64:
                self._policies.popitem(last=False)
        self._policies.move_to_end(key)
        return self._policies[key]

    def choose_action(self, state, context=None):
        declared = getattr(context, "game_type", None)
        observed = (state.raw or {}).get("game_type")
        if declared and observed and declared != observed:
            raise ValueError("Game type mismatch between assignment and state")
        policy = self._policy(declared or observed, context, state)
        started = perf_counter()
        action = policy.choose_action(state, context)
        elapsed = perf_counter() - started
        self._record('observe', context, policy, state, context, action, policy, elapsed)
        return action

    def on_action_result(self, result, context):
        # A pending/rejected/lost Red Alert order must reach the SAME policy
        # instance that proposed it. Never instantiate a policy on a callback.
        key = self._key(getattr(context, "game_type", None), context)
        policy = self._policies.get(key)
        handler = getattr(policy, "on_action_result", None)
        if callable(handler):
            handler(result, context)
        if policy is not None:
            self._record('action_result', context, policy, result)

    def on_game_end(self, state, context):
        policy = self._policies.get(self._key(getattr(context, 'game_type', None), context))
        handler = getattr(policy, 'on_game_end', None)
        try:
            if callable(handler):
                handler(state, context)
        finally:
            self._record('finish', context, policy, state, context, policy)


def create_agent():
    return CompetitionAgent()
