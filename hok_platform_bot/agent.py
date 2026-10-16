"""Legal-macro team policy for AltruAgent's honor_of_kings_5v5.

Contract: https://api.altruagent-game.com/skill/hok (2026-10-16), and
altruagent-starter 686e756/examples/llm/hok.py. No guessed 1v1/raw SDK actions.
Only the assigned team's summaries and server-listed actions are consulted.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
import re

from altruagent import WAIT

GAME_TYPE = "honor_of_kings_5v5"
MACROS = frozenset({"macro_advance", "macro_retreat", "macro_attack",
                    "macro_skill1", "macro_skill2", "macro_skill3"})
SEAT_ACTION = re.compile(r"^s(\d+):(.+)$")
DISTANCE = re.compile(r"(\d+(?:\.\d+)?) away\)")


def number(value, default=0.0):
    if isinstance(value, bool):
        return default
    try:
        value = float(value)
        return value if isfinite(value) else default
    except (TypeError, ValueError):
        return default


def health(hero):
    return max(0.0, min(1.0, number(hero.get("hp")) / max(1, number(hero.get("max_hp"), 1))))


def distance(a, b):
    coords = [number(h.get(k), float("inf")) for h in (a, b) for k in ("x", "z")]
    return hypot(coords[0] - coords[2], coords[1] - coords[3]) if all(map(isfinite, coords)) else float("inf")


def macro_distance(action):
    match = DISTANCE.search(action.label or "")
    return float(match.group(1)) if match else float("inf")


def summary(state, seat):
    obs = state.raw.get("observation")
    seats = obs.get("seats", {}) if isinstance(obs, dict) else {}
    entry = seats.get(str(seat), {}) if isinstance(seats, dict) else {}
    value = entry.get("summary", {}) if isinstance(entry, dict) else {}
    return value if isinstance(value, dict) else {}


def owned_seats(state):
    seats = state.raw.get("seats")
    camp = state.raw.get("camp")
    if not isinstance(seats, list) or camp not in (1, 2):
        raise ValueError("HoK 5v5 requires explicit team seats and camp")
    if any(type(s) is not int or not (0 <= s < 10) or s // 5 + 1 != camp for s in seats):
        raise ValueError("HoK team seats do not match its camp")
    return set(seats)


def offers_by_seat(state, owned):
    offers = {}
    for action in state.legal_actions:
        match = SEAT_ACTION.fullmatch(action.action_id)
        if not match or int(match[1]) not in owned:
            continue
        seat, name = int(match[1]), match[2]
        payload = action.input.get("action", {})
        if not isinstance(payload, dict) or type(payload.get("seat")) is not int or payload["seat"] != seat:
            continue
        offer = offers.setdefault(seat, {"macros": {}, "raw": []})
        if name in MACROS:
            # Upstream entries may contain a raw-button preview. The action_id
            # identifies the macro; sending that preview would clear its order.
            offer["macros"][name] = action
        elif name.startswith("button_"):
            offer["raw"].append(action)
    return offers


def complete_raw(entries, seat):
    """Lockstep fallback, including dead heroes, using only listed values."""
    for entry in sorted(entries, key=lambda a: a.input["action"].get("which_button") != 0):
        payload = entry.input["action"]
        if type(payload.get("which_button")) is not int:
            continue
        output = {k: v for k, v in payload.items() if not k.startswith("legal_")}
        valid = True
        for key, values in payload.items():
            if key.startswith("legal_"):
                if not isinstance(values, list) or not values:
                    valid = False
                    break
                output[key[6:]] = values[0]
        if valid:
            output["seat"] = seat
            return output
    raise ValueError("HoK lockstep has no complete listed action for a pending hero")


@dataclass
class HeroMemory:
    recovering: bool = False
    step: int = -1
    hp: float = 0
    loss_rate: float = 0
    last_skill: int = -1000
    last_sent: int = -1


class HokTeamAgent:
    strategy_version = "hok_team_v11"

    def __init__(self):
        self.heroes = {}
        self.identity = None
        self.version = -1
        self.sequence = 0
        self.pending = None
        self.last_reason = "initial"
        self.rejected = 0
        self.accepted_seats = set()
        self.accepted_count = 0

    def _macro(self, seat, state, macros, team):
        view = summary(state, seat)
        me = view.get("my_hero") or {}
        memory = self.heroes.setdefault(seat, HeroMemory())
        step, hp, ratio = state.state_version, number(me.get("hp")), health(me)
        if not me or "hp" not in me or "max_hp" not in me:
            return ("macro_retreat", 80, "missing_hero_summary") if "macro_retreat" in macros else (None, 0, "missing_summary")
        if hp <= 0 or number(me.get("revive_time")) > 0:
            memory.recovering, memory.loss_rate = False, 0
            memory.step, memory.hp = step, hp
            return None, 0, "dead_wait"
        if step > memory.step:
            elapsed = max(.2, (step - memory.step) * .2)
            memory.loss_rate = (max(0, memory.hp - hp) / max(1, number(me.get("max_hp"))) / elapsed
                                if memory.step >= 0 and elapsed <= 4 else 0)
            memory.step, memory.hp = step, hp
        enemies = [h for h in view.get("other_heroes", []) if isinstance(h, dict)
                   and h.get("visible") is True and h.get("camp") == 3 - state.raw["camp"]
                   and number(h.get("hp")) > 0 and distance(me, h) < 10000]
        friends = [h for h in team if number(h.get("hp")) > 0 and health(h) >= .35
                   and distance(me, h) < 12000]
        def strength(h):
            return number(h.get("hp")) * (1 + .08 * max(0, number(h.get("level"), 1) - 1))
        friendly_power = sum(strength(h) for h in friends)
        enemy_power = sum(strength(h) for h in enemies)
        outmatched = bool(enemies) and enemy_power > max(1, friendly_power) * 1.35
        structures = [o for o in view.get("structures", []) if isinstance(o, dict)
                      and o.get("camp") == 3 - state.raw["camp"] and number(o.get("hp")) > 0]
        near_structure = any(distance(me, o) < 9000 for o in structures)
        # No minion/aggro field is promised by the platform summary. Never claim
        # a wave protects us: use observed health loss as a conservative signal.
        danger = (ratio < .27 or (enemies and ratio < .40)
                  or (memory.loss_rate > .10 and near_structure and ratio < .78)
                  or (memory.loss_rate * 2.5 > ratio)
                  or (outmatched and ratio < .80))
        if danger:
            memory.recovering = True
        elif ratio >= .78:
            memory.recovering = False
        if memory.recovering and "macro_retreat" in macros:
            return "macro_retreat", 100 + (1 - ratio) * 10, "recover_or_disengage"

        attack = macros.get("macro_attack")
        # The SDK's official example documents the distance suffix. If it is
        # absent, legal macro availability is still preferable to standing idle.
        can_attack = attack is not None and (macro_distance(attack) <= 9000 or not DISTANCE.search(attack.label or ""))
        # Avoid parking on a skill during cooldown: follow a successful cast
        # with basic attacks. Skills are generic macros, not hero-specific combos.
        if enemies and not outmatched and ratio >= .48 and step - memory.last_skill >= 15:
            for macro in ("macro_skill3", "macro_skill1", "macro_skill2"):
                if macro in macros and macro_distance(macros[macro]) <= 9000:
                    return macro, 45, "supported_skill"
        if can_attack:
            return "macro_attack", 50 if near_structure else 40, "objective_or_wave_attack"
        if "macro_advance" in macros:
            return "macro_advance", 20, "advance_to_objective"
        if "macro_retreat" in macros:
            return "macro_retreat", 10, "safe_available_macro"
        return None, 0, "no_safe_macro"

    def choose_action(self, state, context=None):
        realtime = (state.raw.get("pacing") or {}).get("mode") == "realtime"
        if state.is_terminal or state.phase != "moving":
            return WAIT
        if state.raw.get("game_type") != GAME_TYPE:
            raise ValueError("HoK team policy requires honor_of_kings_5v5")
        owned = owned_seats(state)
        identity = (state.session_id, state.raw["camp"], tuple(sorted(owned)))
        if self.identity != identity or state.state_version < self.version:
            self.heroes, self.pending = {}, None
            self.accepted_seats, self.accepted_count = set(), 0
            self.identity = identity
        self.version = state.state_version
        offers = offers_by_seat(state, owned)
        simultaneous = state.raw.get("simultaneous") or {}
        pending = simultaneous.get("your_pending_seats")
        eligible = set(s for s in pending if type(s) is int) if isinstance(pending, list) else owned
        standing = simultaneous.get("standing_orders") or {}
        team = [summary(state, s).get("my_hero") or {} for s in owned]
        choices = []
        for seat in sorted(owned & eligible & offers.keys()):
            macro, priority, reason = self._macro(seat, state, offers[seat]["macros"], team)
            memory = self.heroes[seat]
            if macro is None:
                if realtime:
                    continue
                action = complete_raw(offers[seat]["raw"], seat)
            else:
                if realtime and standing.get(str(seat)) == macro:
                    continue
                action = {"macro": macro, "seat": seat}
            # Emergency retreat wins; otherwise serve the least recently sent
            # hero first, preventing a rapidly changing seat from starving four.
            choices.append((priority >= 100, -memory.last_sent, priority, -seat, action, reason))
        if not choices:
            if realtime:
                return WAIT
            raise ValueError("HoK lockstep requested a decision without a pending listed hero")
        _, _, _, _, action, self.last_reason = max(choices, key=lambda c: c[:4])
        self.sequence += 1
        self.heroes[action["seat"]].last_sent = self.sequence
        self.pending = (action, state.state_version)
        return action

    def on_action_result(self, result, context=None):
        if self.pending is None:
            return
        action, step = self.pending
        if result.get("error"):
            self.rejected += 1
        elif result.get("accepted") is True:
            self.accepted_count += 1
            seat = action["seat"]
            if seat not in self.accepted_seats:
                if context is not None and not str(context.session_id).startswith(("offline", "test", "selftest")):
                    print(f"[hok5v5] {self.strategy_version}: server accepted first order for hero seat {seat}.", flush=True)
                self.accepted_seats.add(seat)
            if action.get("macro", "").startswith("macro_skill"):
                self.heroes[seat].last_skill = step
        # Server-reported standing_orders, never a local send, acknowledge an
        # order. Rejections/lost replies cannot mark an unexecuted command done.
        self.pending = None

    def on_game_end(self, state, context=None):
        print(f"[hok5v5] {self.strategy_version}: accepted={self.accepted_count}, "
              f"refused={self.rejected}, controlled_heroes={sorted(self.accepted_seats)}.", flush=True)


def create_agent():
    return HokTeamAgent()
