"""Role-aware Werewolf policy with bounded, untrusted discussion evidence.

Only server observations establish roles. Chat is parsed as game claims, never
executed or interpreted as instructions. Private role information lives only in
the current decision; no raw state, chat, credential or reasoning is persisted.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from itertools import combinations
import math
import re
import secrets
from time import perf_counter

from altruagent import SendMessage, TERMINATE_MESSAGING, WAIT


SEATS = frozenset(range(7))
ROLES = frozenset({"wolf", "seer", "villager"})
MAX_SESSIONS = 64
MAX_MESSAGES = 256
_ROLE = re.compile(r"Your role: (WOLF|SEER|VILLAGER)")
_CHECK = re.compile(r"Player([0-6]) is (wolf|villager)")
_CLAIM = re.compile(r"I (?:am|'m) (?:the |a )?seer", re.I)
_REPORT = re.compile(
    r"(?:I (?:checked|investigated|inspected) )?Player([0-6]) (?:is|was|as|:) "
    r"(?:a |the )?(wolf|werewolf|villager|innocent|good)", re.I)
_VOTE = re.compile(r"(?:I (?:will vote|vote|recommend)|My vote is|Vote(?: to eliminate)?) "
                   r"(?:for )?Player([0-6])", re.I)
_NIGHT = re.compile(r"Night target: Player([0-6])\.?", re.I)


def _seat(value):
    return value if type(value) is int and value in SEATS else None


def _list(value, limit=64):
    return value[:limit] if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


@dataclass(repr=False)
class View:
    session: str
    me: int | None
    day: int
    phase: str
    role: str | None = None
    allies: set = field(default_factory=set)
    checks: dict = field(default_factory=dict)
    alive: set = field(default_factory=set)
    dead: dict = field(default_factory=dict)
    votes: list = field(default_factory=list)

    @classmethod
    def read(cls, state, context=None):
        raw = _dict(getattr(state, "raw", None))
        session = getattr(state, "session_id", "")
        expected_session = getattr(context, "session_id", None)
        if expected_session and session and expected_session != session:
            raise ValueError("Assignment and observation session mismatch")
        declared = getattr(context, "game_type", None)
        if declared not in (None, "werewolf") or raw.get("game_type") not in (None, "werewolf"):
            raise ValueError("Werewolf policy received another game")
        me = _seat(raw.get("your_position"))
        expected_seat = _seat(getattr(context, "seat_position", None))
        if me is not None and expected_seat is not None and me != expected_seat:
            raise ValueError("Assignment and observation seat mismatch")
        me = me if me is not None else expected_seat
        public = _dict(raw.get("game_state"))
        day = public.get("day")
        day = day if type(day) is int and 1 <= day <= 1000 else 0
        phase = public.get("phase")
        phase = phase if phase in ("night_wolf", "night_seer", "day_vote") else "unknown"
        view = cls(str(session or expected_session or "offline"), me, day, phase)

        # Exact server header only: never scan chat, display names, or later
        # observation lines for a replacement role or investigation result.
        observation = raw.get("observation", getattr(state, "observation", ""))
        lines = observation.splitlines()[:4] if isinstance(observation, str) and len(observation) <= 65536 else []
        if len(lines) >= 2 and lines[0] == "=== Werewolf ===":
            role = _ROLE.fullmatch(lines[1])
            if role:
                view.role = role[1].lower()
                detail = lines[2] if len(lines) > 2 else ""
                if view.role == "wolf" and detail.startswith("Your fellow wolves: "):
                    allies = detail[len("Your fellow wolves: "):].split(", ")
                    if len(allies) == 1 and all(re.fullmatch(r"Player[0-6]", value) for value in allies):
                        view.allies = {int(value[-1]) for value in allies} - {me}
                if view.role == "seer" and detail.startswith("Your investigations: "):
                    entries = detail[len("Your investigations: "):].split(", ")
                    matches = [_CHECK.fullmatch(value) for value in entries]
                    if all(matches) and len(matches) <= 6:
                        for match in matches:
                            target, result = int(match[1]), match[2]
                            if target not in view.checks or view.checks[target] == result:
                                view.checks[target] = result
                            else:
                                view.checks = {}
                                break

        # Names are opaque identifiers. A deceptive name containing Player6,
        # a role, or an instruction never changes the seat map.
        mapping, ambiguous = {}, set()
        for player in _list(raw.get("players"), 7):
            player = _dict(player)
            position, name = _seat(player.get("position")), player.get("name")
            if position is not None and isinstance(name, str) and len(name) <= 512:
                if name in mapping and mapping[name] != position:
                    ambiguous.add(name)
                mapping[name] = position
        for name in ambiguous:
            mapping.pop(name, None)
        view.alive = {mapping[name] for name in _list(public.get("alive"), 7)
                      if isinstance(name, str) and name in mapping}
        for entry in _list(public.get("dead"), 7):
            entry = _dict(entry)
            name, role = entry.get("player"), entry.get("role")
            if isinstance(name, str) and name in mapping and isinstance(role, str) and role in ROLES:
                view.dead[mapping[name]] = role
        view.alive -= view.dead.keys()
        for entry in _list(public.get("vote_history"), 30):
            entry = _dict(entry)
            votes = {}
            for sender, target in list(_dict(entry.get("votes")).items())[:7]:
                if sender in mapping and isinstance(target, str):
                    if target in mapping:
                        votes[mapping[sender]] = mapping[target]
                    elif target == "abstain":
                        votes[mapping[sender]] = 7
            view.votes.append(votes)
        return view

    def truth(self):
        known = {seat: role == "wolf" for seat, role in self.dead.items()}
        if self.me is not None and self.role in ROLES:
            known[self.me] = self.role == "wolf"
        if self.role == "wolf":
            known.update({seat: True for seat in self.allies})
            if len(self.allies) == 1 and self.me is not None:
                known.update({seat: False for seat in SEATS - self.allies - {self.me}})
        if self.role == "seer":
            known.update({seat: role == "wolf" for seat, role in self.checks.items()})
        return known


@dataclass(repr=False)
class Memory:
    tie_seed: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    seen: OrderedDict = field(default_factory=OrderedDict)
    claims: dict = field(default_factory=dict)
    reports: dict = field(default_factory=dict)
    contradictions: set = field(default_factory=set)
    announced: dict = field(default_factory=dict)
    coordinated: dict = field(default_factory=dict)
    sent: dict = field(default_factory=dict)


class WerewolfAgent:
    strategy_version = "evidence_v1"

    def __init__(self):
        self._memories = OrderedDict()
        self.last_diagnostics = {}

    def _memory(self, view, context):
        key = (view.session, view.me, getattr(context, "agent_id", ""))
        if key not in self._memories:
            self._memories[key] = Memory()
            if len(self._memories) > MAX_SESSIONS:
                self._memories.popitem(last=False)
        self._memories.move_to_end(key)
        return self._memories[key]

    def _read_messages(self, state, view, memory):
        # The server limits a day to 35 messages. Bound malformed envelopes
        # anyway, and cap each speaker's evidence so repetition is not voting.
        for message in _list(getattr(state, "new_messages", []), 64):
            sender = _seat(getattr(message, "sender", None))
            sequence = getattr(message, "index", None)
            content = getattr(message, "content", None)
            recipients = getattr(message, "recipients", None)
            if (sender is None or type(sequence) is not int or sequence < 0
                    or not isinstance(content, str) or len(content) > 1024
                    or len(content.split()) > 50 or getattr(message, "type", None) != "chat"
                    or not isinstance(recipients, list) or len(recipients) > 1
                    or any(_seat(value) is None for value in recipients)
                    or (recipients and view.me not in recipients)):
                continue
            if sequence in memory.seen:
                continue
            memory.seen[sequence] = None
            if len(memory.seen) > MAX_MESSAGES:
                memory.seen.popitem(last=False)
            if sender == view.me:
                continue
            night = _NIGHT.fullmatch(content.strip())
            if (night and recipients == [view.me] and view.role == "wolf"
                    and sender in view.allies and sender < view.me):
                memory.coordinated[view.day] = int(night[1])
            # Direct claims cannot build a public coalition. They remain
            # untrusted evidence, but receive half of the broadcast weight.
            public = not recipients
            parts = re.split(r"[.!?;\n]+", content)[:12]
            claim = any(_CLAIM.fullmatch(part.strip()) for part in parts)
            if claim:
                memory.claims.setdefault(sender, (view.day, public))
            for part in parts:
                part = part.strip()
                report = _REPORT.fullmatch(part)
                if report and (claim or sender in memory.claims):
                    target = int(report[1])
                    is_wolf = report[2].lower() in ("wolf", "werewolf")
                    prior = memory.reports.get((sender, target))
                    if prior is not None and prior[0] != is_wolf:
                        memory.contradictions.add(sender)
                    elif prior is None:
                        # The timestamp distinguishes predictions from claims
                        # opportunistically made after a target's death.
                        memory.reports[(sender, target)] = (is_wolf, view.day, public, target not in view.dead)
                    # At most one investigation is possible per night, and
                    # the seer can never investigate their own seat.
                    count = sum(speaker == sender for speaker, _ in memory.reports)
                    if target == sender or (view.day > 0 and count > view.day):
                        memory.contradictions.add(sender)
                vote = _VOTE.fullmatch(part)
                if vote and public and sender not in view.dead:
                    memory.announced[(view.day, sender)] = int(vote[1])
        # A game cannot run indefinitely (three empty days lose), but keep
        # bounded state even if a malformed source invents arbitrary days.
        memory.announced = {key: value for key, value in memory.announced.items() if key[0] >= view.day - 2}
        memory.coordinated = {day: target for day, target in memory.coordinated.items() if day >= view.day - 1}
        memory.sent = {day: value for day, value in memory.sent.items() if day >= view.day - 1}

    @staticmethod
    def _rank(view, memory, target):
        # One private random seed per seat prevents source-reading opponents
        # from predicting otherwise equal targets. Repeated decisions stay
        # stable. Wolf agreement uses authenticated direct messages instead.
        value = memory.tie_seed + f"werewolf-tie-v1:{view.session}:{target}".encode()
        return int.from_bytes(hashlib.sha256(value).digest()[:8], "big")

    def _probabilities(self, view, memory):
        truth = view.truth()
        worlds = [frozenset(pair) for pair in combinations(range(7), 2)
                  if all((seat in pair) == wolf for seat, wolf in truth.items())]
        if not worlds:
            # Conflicting/malformed authoritative fields must not promote a
            # chat claim to truth. Preserve each usable explicit check.
            return {seat: float(truth[seat]) if seat in truth else 2 / 7 for seat in SEATS}
        evidence = {seat: 0.0 for seat in SEATS}
        for votes in view.votes:
            for voter, target in votes.items():
                if target in view.dead:
                    evidence[voter] += -0.85 if view.dead[target] == "wolf" else 0.16
                if view.dead.get(voter) == "wolf" and target in SEATS:
                    evidence[target] -= 0.35
        for sender in memory.contradictions:
            evidence[sender] += 1.1
        if view.role == "seer" or "seer" in view.dead.values():
            for sender in memory.claims:
                if sender != view.me and view.dead.get(sender) != "seer":
                    evidence[sender] += 0.6
        for (sender, target), (wolf, day, public, before_death) in memory.reports.items():
            if target in truth and truth[target] != wolf:
                evidence[sender] += 0.9 if before_death else 0.3
        # A revealed seer's earlier report is much stronger than a live
        # player's unverifiable claim, but never overrides a private check.
        for (sender, target), (wolf, day, public, before_death) in memory.reports.items():
            if view.dead.get(sender) == "seer" and before_death:
                evidence[target] += 4.0 if wolf else -4.0
        weighted = []
        for world in worlds:
            score = sum(max(-2.0, min(2.0, evidence[seat])) for seat in world)
            for sender, (claim_day, claim_public) in memory.claims.items():
                if sender in view.dead or sender in memory.contradictions or view.role == "seer":
                    continue
                reports = [(target, value) for (speaker, target), value in memory.reports.items() if speaker == sender]
                # A claimed seer is one hypothesis, not a cleared player.
                # At most one bounded contribution per speaker and world.
                if sender not in world and reports:
                    agreement = sum(1 if (target in world) == value[0] else -1 for target, value in reports)
                    score += max(-0.7, min(0.7, agreement * 0.35)) * (1 if claim_public else 0.5)
            weighted.append((world, score))
        peak = max(score for _, score in weighted)
        weights = [(world, math.exp(score - peak)) for world, score in weighted]
        total = sum(weight for _, weight in weights)
        return {seat: sum(weight for world, weight in weights if seat in world) / total for seat in SEATS}

    def _vote_target(self, view, memory, targets):
        probabilities = self._probabilities(view, memory)
        truth = view.truth()
        if view.role == "wolf":
            preferred = [target for target in targets if not truth.get(target, False)]
        else:
            confirmed = [target for target in targets if truth.get(target) is True]
            preferred = confirmed or [target for target in targets if truth.get(target) is not False]
        preferred = preferred or list(targets)
        support = {target: 0.0 for target in preferred}
        for (day, sender), target in memory.announced.items():
            if day == view.day and sender in view.alive and sender != view.me and target in support:
                # Announced votes can be lies; never count them as resolved
                # votes, and never allow them to override hard role knowledge.
                support[target] += 1.0 - probabilities[sender]
        def utility(target):
            if view.role == "wolf":
                return 0.3 * support[target] + 0.15 * (1 - probabilities[target])
            return probabilities[target] + min(0.18, 0.06 * support[target])
        return max(preferred, key=lambda target: (utility(target), self._rank(view, memory, target)))

    def _night_target(self, view, memory, targets):
        proposal = memory.coordinated.get(view.day - 1)
        if proposal in targets:
            return proposal
        def danger(target):
            score = 0.0
            if target in memory.claims:
                score += 3.0
            for (sender, checked), (wolf, day, public, before_death) in memory.reports.items():
                if sender == target and wolf and checked in view.allies | {view.me}:
                    score += 2.0
                if checked == target and not wolf and view.dead.get(sender) == "seer":
                    score += 1.5
            for votes in view.votes:
                if votes.get(target) in view.allies | {view.me}:
                    score += 0.5
            return score
        return max(targets, key=lambda target: (danger(target), self._rank(view, memory, target)))

    def choose_action(self, state, context=None):
        start = perf_counter()
        raw = _dict(getattr(state, "raw", None))
        if (getattr(state, "is_terminal", False) or raw.get("eliminated") is True
                or getattr(state, "phase", None) != "moving"
                or getattr(state, "is_current_actor", None) is False):
            return WAIT
        view = View.read(state, context)
        memory = self._memory(view, context)
        self._read_messages(state, view, memory)
        # Only IDs matter. Never echo an input template, display label, or a
        # field injected into an action envelope back to the server.
        legal = {action.action_id for action in _list(getattr(state, "legal_actions", []), 8)
                 if isinstance(getattr(action, "action_id", None), str)
                 and re.fullmatch(r"[0-7]", action.action_id)}
        if not legal:
            raise ValueError("No valid pending Werewolf action")
        targets = {int(value) for value in legal if value != "7"}
        targets.discard(view.me)
        targets -= view.dead.keys()
        if view.phase == "night_wolf":
            targets -= view.allies
        if targets:
            if view.phase == "night_seer":
                unchecked = targets - view.checks.keys()
                candidates = unchecked or targets
                probabilities = self._probabilities(view, memory)
                target = max(candidates, key=lambda seat: (
                    probabilities[seat] * (1 - probabilities[seat])
                    + (0.05 if seat in memory.claims else 0), self._rank(view, memory, seat)))
            elif view.phase == "night_wolf":
                target = self._night_target(view, memory, targets)
            else:
                target = self._vote_target(view, memory, targets)
            answer = str(target)
        elif "7" in legal and view.phase in ("day_vote", "unknown"):
            answer = "7"
        else:
            raise ValueError("Werewolf legal list conflicts with public seat state")
        self.last_diagnostics = {"phase": view.phase, "strategy_version": self.strategy_version,
                                 "seconds": round(perf_counter() - start, 6)}
        return answer

    def choose_message(self, state, context=None):
        raw = _dict(getattr(state, "raw", None))
        if (getattr(state, "is_terminal", False) or raw.get("eliminated") is True
                or getattr(state, "phase", None) != "messaging"):
            return TERMINATE_MESSAGING
        view = View.read(state, context)
        memory = self._memory(view, context)
        self._read_messages(state, view, memory)
        remaining = raw.get("messaging_seconds_left")
        if (view.me is None or view.day == 0 or view.me in getattr(state, "terminated_messaging", [])
                or (isinstance(remaining, (int, float)) and remaining <= 2)):
            return TERMINATE_MESSAGING
        sent = memory.sent.setdefault(view.day, set())
        if len(sent) >= 3:
            return TERMINATE_MESSAGING
        candidates = view.alive - {view.me}
        if not candidates:
            return TERMINATE_MESSAGING
        # Only the lower-seat wolf proposes a shared target. The partner
        # accepts it solely from the authoritative ally's direct envelope.
        living_allies = view.allies & view.alive
        if (view.role == "wolf" and living_allies and view.me < min(living_allies)
                and "coordination" not in sent):
            targets = candidates - view.allies
            if targets:
                target = self._night_target(view, memory, targets)
                memory.coordinated[view.day] = target
                sent.add("coordination")
                return SendMessage(f"Night target: Player{target}.", [min(living_allies)])
        reveal = (view.role == "seer" and view.checks and (
            any(role == "wolf" and seat in view.alive for seat, role in view.checks.items())
            or view.day >= 2 or len(view.alive) <= 5 or bool(memory.claims)))
        if reveal and "report" not in sent:
            sent.add("report")
            reports = "; ".join(f"Player{seat} is {role}" for seat, role in sorted(view.checks.items()))
            return SendMessage(f"I am the seer. {reports}. These are my investigation results.")
        target = self._vote_target(view, memory, candidates)
        tag = ("vote", target)
        earlier_votes = {item for item in sent if isinstance(item, tuple)}
        if tag not in sent and len(earlier_votes) < 2:
            sent.add(tag)
            if earlier_votes:
                return SendMessage(f"I revise my earlier recommendation. I recommend Player{target}. New evidence changed my assessment; vote suggestions alone are not proof of role.")
            return SendMessage(f"I recommend Player{target}. This is my current vote preference. Compare independent claims and the revealed vote history; we need a coordinated vote. Vote suggestions alone are not proof of role.")
        return TERMINATE_MESSAGING

    def on_game_end(self, state, context=None):
        session = getattr(context, "session_id", None) or getattr(state, "session_id", None)
        agent = getattr(context, "agent_id", "")
        for key in list(self._memories):
            if key[0] == session and key[2] == agent:
                del self._memories[key]
        self.last_diagnostics = {}


def create_agent():
    return WerewolfAgent()
