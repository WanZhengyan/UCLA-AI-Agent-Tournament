"""Deterministic, objective-first policy for Tencent's official HoK1v1 SDK.

Contract verified against tencent-ailab/hok_env at c6e0029: env1v1.py,
actor/agent_demo.py, and the CPython 3.8 interface's exposed actor properties.
Only the supplied player's state dictionary is read. No engine queries, custom
game protocol, learned weights, or privileged replay data are used at play time.
"""

from dataclasses import dataclass
from math import hypot, isfinite

ACTION_SHAPE = (12, 16, 16, 16, 16, 8)
LEGAL_SIZE = 172
NONE, NOOP, MOVE, ATTACK = 0, 1, 2, 3
HEAL, RECALL = 7, 9


class ProtocolError(ValueError):
    """The supplied state is not the supported official HoK1v1 contract."""


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _number(obj, name, default=0.0):
    try:
        value = float(_get(obj, name, default))
        return value if isfinite(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _position(actor):
    loc = _get(actor, "location")
    return _number(loc, "x"), _number(loc, "z")


def _distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _hp(actor):
    return max(0.0, min(1.0, _number(actor, "hp") / max(1.0, _number(actor, "max_hp", 1))))


def _visible(actor, camp):
    # The pinned SDK's ModifyInvisibleInfo indexes this vector by camp - 1.
    # Missing visibility metadata requires an actionable target as fallback.
    flags = _get(actor, "camp_visible", ())
    try:
        return bool(flags[camp - 1]) if len(flags) >= camp else None
    except (TypeError, IndexError):
        return None


class LegalActions:
    """Button-conditioned target masks; all six output dimensions are checked."""

    def __init__(self, state):
        try:
            raw = list(state["legal_action"])
        except (KeyError, TypeError) as exc:
            raise ProtocolError("Missing legal_action vector") from exc
        if len(raw) != LEGAL_SIZE:
            raise ProtocolError("Expected 172 HoK1v1 legal-action entries, got %d" % len(raw))
        try:
            raw = [float(v) for v in raw]
        except (ValueError, TypeError) as exc:
            raise ProtocolError("legal_action must contain numbers") from exc
        if any(not isfinite(v) or v not in (0.0, 1.0) for v in raw):
            raise ProtocolError("legal_action must contain finite binary masks")
        self.parts = [raw[:12], raw[12:28], raw[28:44], raw[44:60], raw[60:76]]
        self.targets = [raw[76 + b * 8:84 + b * 8] for b in range(12)]

    def allowed(self, button, target=None):
        return bool(self.parts[0][button]) and (target is None or bool(self.targets[button][target]))

    def actionable(self, target):
        return any(self.allowed(b, target) for b in (ATTACK, 4, 5, 6, 10))

    @staticmethod
    def _nearest(mask, value):
        choices = [i for i, legal in enumerate(mask) if legal]
        if not choices:
            raise ProtocolError("A legal-action dimension has no available value")
        return min(choices, key=lambda i: (abs(i - value), i))

    def build(self, button, target=0, direction=(8, 8)):
        if not self.allowed(button):
            raise ProtocolError("Requested button is not legal")
        masks = self.parts + [self.targets[button]]
        wanted = (button, direction[0], direction[1], direction[0], direction[1], target)
        return tuple(self._nearest(mask, value) for mask, value in zip(masks, wanted))

    def safe(self):
        # Don't accidentally cast a summoner skill just because it has a low
        # index. Prefer no-op/movement, then an actually available action.
        for b in (NOOP, NONE, MOVE, ATTACK, HEAL, RECALL, 4, 5, 6, 10, 11, 8):
            if self.allowed(b) and any(self.targets[b]):
                return self.build(b)
        raise ProtocolError("No legal HoK1v1 action is available")

    def validates(self, action):
        if len(action) != 6 or any(not isinstance(v, int) for v in action):
            return False
        if not 0 <= action[0] < 12:
            return False
        masks = self.parts + [self.targets[action[0]]]
        return all(0 <= v < len(mask) and mask[v] for mask, v in zip(masks, action))


@dataclass(frozen=True)
class Target:
    actor: object
    slot: int
    kind: str


class HonorOfKingsAgent:
    """Rule baseline: survive, collect farm, push protected objectives.

    This is a transparent starting policy, not a pretrained competitive model.
    It uses tower aggro, wave cover, legal masks, and camp-relative steering;
    hero-specific skill combos remain an explicit limitation.
    """

    version = "hok_objective_v1"

    def __init__(self):
        self.game_id = None
        self.recovering = False
        self.recall_until = -1
        self.last_frame = -1
        self.last_hp = None
        self.last_reason = "initial"

    def _direction(self, source, destination, camp):
        # Tencent's demo canonicalizes camp 2 before emitting movement offsets.
        sign = -1 if camp == 2 else 1
        dx = (destination[0] - source[0]) * sign
        dz = (destination[1] - source[1]) * sign
        scale = max(abs(dx), abs(dz))
        if scale < 1:
            return 8, 8
        return tuple(max(0, min(15, int(round(8 + 7 * v / scale)))) for v in (dx, dz))

    def _move(self, legal, source, destination, camp, reason):
        self.recall_until = -1  # Any movement interrupts the recall channel.
        self.last_reason = reason
        if _distance(source, destination) < 250:
            return self._idle(legal)
        if legal.allowed(MOVE):
            return legal.build(MOVE, direction=self._direction(source, destination, camp))
        return legal.safe()

    @staticmethod
    def _idle(legal):
        for b in (NOOP, NONE):
            if legal.allowed(b):
                return legal.build(b)
        return legal.safe()

    def _attack(self, legal, ego, target, camp, skills=False):
        # Never re-map an unavailable requested target onto a different actor.
        # Unknown heroes use basic attacks; known marksmen can use ranged skills.
        hero = int(_number(ego, "config_id"))
        buttons = [ATTACK]
        if skills and target.kind != "organ":
            if hero == 133:  # Di Renjie: preserve skill 2 as a defensive cleanse.
                buttons = ([6] if target.kind == "hero" else []) + [4, ATTACK]
            elif hero == 112:  # Lu Ban No.7: ranged damage, no random melee dash.
                buttons = ([6] if target.kind == "hero" else []) + [4, 5, ATTACK]
        for b in buttons:
            if legal.allowed(b, target.slot):
                # The official demo uses centered skill offsets (8, 8) to aim
                # at the selected actor. Movement direction is a separate input.
                return legal.build(b, target.slot)
        return None

    def act(self, state):
        legal = LegalActions(state)
        pb = state.get("req_pb")
        if pb is None or "player_id" not in state:
            raise ProtocolError("Expected official state_dict with req_pb and player_id")
        heroes = list(_get(pb, "hero_list", ()))
        ego = next((h for h in heroes if int(_number(h, "runtime_id", -1)) == int(state["player_id"])), None)
        if ego is None:
            raise ProtocolError("player_id was not found in req_pb.hero_list")
        camp = int(_number(ego, "camp"))
        if camp not in (1, 2):
            raise ProtocolError("Only official camps 1 and 2 are supported")
        game_id = state.get("sgame_id", state.get("game_id"))
        frame = int(_number(pb, "frame_no", state.get("frame_no", 0)))
        if game_id != self.game_id or frame < self.last_frame:
            self.game_id, self.recovering, self.recall_until = game_id, False, -1
            self.last_hp = None
        self.last_frame = frame
        pos = _position(ego)
        health = _hp(ego)
        current_hp = _number(ego, "hp")
        damaged = self.last_hp is not None and current_hp < self.last_hp
        self.last_hp = current_hp
        if _number(ego, "hp") <= 0:
            self.recovering, self.recall_until = False, -1
            self.last_reason = "dead_wait"
            return self._idle(legal)

        home_sign = -1 if camp == 1 else 1
        home = (home_sign * 29820, home_sign * 29820)
        soldiers = [s for s in _get(pb, "soldier_list", ()) if _number(s, "hp") > 0]
        friendly = [s for s in soldiers if int(_number(s, "camp")) == camp]
        enemy_soldiers = sorted((s for s in soldiers if int(_number(s, "camp")) == 3 - camp),
                                key=lambda s: int(_number(s, "runtime_id")))[:4]
        enemies = sorted((h for h in heroes if int(_number(h, "camp")) == 3 - camp),
                         key=lambda h: int(_number(h, "config_id")))
        targets = [Target(h, 1 + i, "hero") for i, h in enumerate(enemies[:1]) if _number(h, "hp") > 0]
        targets += [Target(s, 3 + i, "soldier") for i, s in enumerate(enemy_soldiers)]
        targets = [t for t in targets if _visible(t.actor, camp) is not False and
                   (_visible(t.actor, camp) is True or legal.actionable(t.slot))]
        organs = [o for o in _get(pb, "organ_list", ()) if _number(o, "hp") > 0 and
                  int(_number(o, "camp")) == 3 - camp]
        organ = min(organs, key=lambda o: _distance(pos, _position(o))) if organs else None
        target_organ = Target(organ, 7, "organ") if organ is not None else None
        attack_range = max(1800.0, _number(ego, "atk_range", 6000))
        nearby_foes = [t for t in targets if t.kind == "hero" and _distance(pos, _position(t.actor)) < 11000]
        nearby_soldiers = any(t.kind == "soldier" and _distance(pos, _position(t.actor)) < 6500 for t in targets)
        tower_radius = max(8000.0, _number(organ, "attack_range", 8800)) if organ else 0
        tower_distance = _distance(pos, _position(organ)) if organ else float("inf")
        cover = [s for s in friendly if organ and _distance(_position(s), _position(organ)) < tower_radius - 500
                 and _hp(s) > .22]
        tower_aggro = organ is not None and int(_number(organ, "attack_target", -1)) == int(state["player_id"])
        tower_danger = tower_aggro or (tower_distance < tower_radius + 400 and not cover)
        if health < .30 or (health < .44 and nearby_foes):
            self.recovering = True
        if health >= .78:
            self.recovering = False
            self.recall_until = -1

        # Preserve recall channel until it completes; every attack/move cancels it.
        if frame < self.recall_until:
            if not nearby_foes and not nearby_soldiers and not tower_danger and not damaged:
                self.last_reason = "recall_channel"
                return self._idle(legal)
            self.recall_until = -1
        if tower_danger and tower_distance < tower_radius + 900:
            self.recall_until = -1
            return self._move(legal, pos, home, camp, "leave_tower_aggro" if tower_aggro else "wait_for_wave")
        if health < .62 and legal.allowed(HEAL):
            self.last_reason = "heal"
            return legal.build(HEAL, 2)
        if self.recovering:
            if _distance(pos, home) < 2500:
                self.last_reason = "recover_at_base"
                return self._idle(legal)
            if not nearby_foes and not nearby_soldiers and not damaged and legal.allowed(RECALL):
                self.recall_until = frame + 135  # ~9 seconds at the official 15 fps.
                self.last_reason = "safe_recall"
                return legal.build(RECALL)
            return self._move(legal, pos, home, camp, "retreat_low_health")

        # Structure damage wins games. Prefer a safe final structure hit to chase.
        if target_organ and cover and health > .48 and tower_distance <= attack_range + 600:
            if _hp(organ) < .18 or not nearby_foes:
                action = self._attack(legal, ego, target_organ, camp)
                if action is not None:
                    self.last_reason = "finish_objective" if _hp(organ) < .18 else "push_with_wave"
                    return action

        attack = max(60.0, _number(ego, "phy_atk", 150))
        last_hits = [t for t in targets if t.kind == "soldier" and _number(t.actor, "hp") <= attack * .85
                     and _distance(pos, _position(t.actor)) <= attack_range + 500]
        for target in sorted(last_hits, key=lambda t: (_number(t.actor, "hp"), t.slot)):
            action = self._attack(legal, ego, target, camp)
            if action is not None:
                self.last_reason = "last_hit"
                return action

        # Take favorable trades away from tower range, and avoid healthy chases.
        for target in nearby_foes:
            enemy_health = _hp(target.actor)
            in_tower = organ and _distance(_position(target.actor), _position(organ)) < tower_radius + 800
            if not in_tower and health > .52 and (health >= enemy_health + .12 or enemy_health < .25):
                if _distance(pos, _position(target.actor)) < attack_range + 700:
                    action = self._attack(legal, ego, target, camp, skills=True)
                    if action is not None:
                        self.last_reason = "favorable_trade"
                        return action

        farm = sorted((t for t in targets if t.kind == "soldier"),
                      key=lambda t: (_distance(pos, _position(t.actor)), _number(t.actor, "hp")))
        for target in farm:
            if _distance(pos, _position(target.actor)) <= attack_range + 500:
                action = self._attack(legal, ego, target, camp, skills=len(farm) >= 3)
                if action is not None:
                    self.last_reason = "clear_wave"
                    return action
        if target_organ and cover and health > .48 and tower_distance <= attack_range + 500:
            action = self._attack(legal, ego, target_organ, camp)
            if action is not None:
                self.last_reason = "push_with_wave"
                return action

        # Stay outside the opponent's attack range if no favorable trade exists.
        threat = next((t for t in nearby_foes if _distance(pos, _position(t.actor)) <
                       max(2500, _number(t.actor, "atk_range", 6000)) + 300), None)
        if threat and health < _hp(threat.actor) + .08 and not friendly:
            return self._move(legal, pos, home, camp, "kite_unfavorable_trade")

        destination = _position(farm[0].actor) if farm else (_position(organ) if organ else (-home[0], -home[1]))
        # Approach only to attack range, and stop outside unsupported tower fire.
        stop_range = attack_range * .85 if farm else attack_range * .88
        if organ and not cover and _distance(destination, _position(organ)) < tower_radius:
            destination = _position(organ)
            stop_range = tower_radius + 1000
        d = _distance(pos, destination)
        if d <= stop_range:
            self.last_reason = "hold_safe_range"
            return self._idle(legal)
        destination = (destination[0] + (pos[0] - destination[0]) * stop_range / d,
                       destination[1] + (pos[1] - destination[1]) * stop_range / d)
        return self._move(legal, pos, destination, camp, "approach_wave" if farm else "advance_lane")
