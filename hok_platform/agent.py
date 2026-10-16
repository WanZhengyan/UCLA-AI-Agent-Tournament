"""Fast, observation-only team control for AltruAgent Honor of Kings 5v5.

Only server-listed macros are used for combat. Their nearest-target semantics
do not permit arbitrary focus fire or lane assignment. All thresholds are
development heuristics, not calibrated damage/range models or win guarantees.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import re

from altruagent import WAIT

GAME_TYPE = 'honor_of_kings_5v5'
MACROS = ('macro_advance', 'macro_retreat', 'macro_attack',
          'macro_skill1', 'macro_skill2', 'macro_skill3')
SEAT_ACTION = re.compile(r'^s([0-9]):(.+)$')
DISTANCE = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s+away\s*\)', re.I)


def number(value, default=None):
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return default


def hp_fraction(hero):
    hp, maximum = number(hero.get('hp')), number(hero.get('max_hp'))
    if hp is None or maximum is None or maximum <= 0:
        return None
    return max(0., min(1., hp / maximum))


def distance(a, b):
    values = [number(o.get(k)) for o in (a, b) for k in ('x', 'z')]
    if None in values:
        return math.inf
    return math.hypot(values[0] - values[2], values[1] - values[3])


def alive(hero):
    return number(hero.get('hp'), 0) > 0 and number(hero.get('revive_time'), 0) <= 0


def records(value, cap=32):
    return [x for x in value[:cap] if isinstance(x, dict)] if isinstance(value, list) else []


def strength(hero):
    # A local health/level proxy, never a prediction of exact matchup damage.
    return (hp_fraction(hero) or 0) * (1 + .10 * max(0, number(hero.get('level'), 1) - 1))


def summary(raw, seat):
    obs = raw.get('observation')
    entries = obs.get('seats') if isinstance(obs, dict) else None
    entry = entries.get(str(seat), {}) if isinstance(entries, dict) else {}
    result = entry.get('summary') if isinstance(entry, dict) else None
    return result if isinstance(result, dict) else {}


def label_distance(label):
    match = DISTANCE.search(label or '')
    return float(match[1]) if match else math.inf


@dataclass
class HeroMemory:
    samples: list = field(default_factory=list)
    recovering: bool = False
    danger_until: float = -1.
    last_served: int = -1
    deaths: float | None = None
    was_dead: bool = False
    combat_since: float | None = None
    push_until: float = -1.


class HokPlatformAgent:
    strategy_version = 'hok_objectives_v2'
    profile = 'structure_first'
    realtime_wait_seconds = .6

    def __init__(self):
        self._identity = None
        self._memory = {}
        self._sequence = 0
        self._last_order = None
        self._last_version = -1
        self._rejected = set()
        self.last_diagnostics = {}
        self.counts = Counter()

    def _owned(self, raw):
        camp = raw.get('camp')
        seats = raw.get('seats')
        if not isinstance(seats, list) or type(camp) is not int or camp not in (1, 2):
            return []
        return sorted({s for s in seats if type(s) is int and 0 <= s < 10 and s // 5 + 1 == camp})

    def _offers(self, state, owned):
        out = {seat: {'macros': {}, 'raw': []} for seat in owned}
        for action in state.legal_actions:
            match = SEAT_ACTION.fullmatch(action.action_id)
            if not match or int(match[1]) not in out:
                continue
            seat, name = int(match[1]), match[2]
            payload = action.input.get('action', {})
            if not isinstance(payload, dict):
                continue
            if 'seat' in payload and (type(payload['seat']) is not int or payload['seat'] != seat):
                continue
            if name in MACROS:
                if 'macro' in payload and payload['macro'] != name:
                    continue
                # A listed macro is a complete server-computed action, even
                # when its raw description includes legal_* metadata.
                out[seat]['macros'][name] = action.label or ''
            elif name.startswith('button_'):
                # Tolerate template metadata beside input.action, but never
                # discard a required domain or resolve contradictory domains.
                resolved = dict(payload)
                conflict = False
                for container in (action.raw, action.input):
                    for key, value in container.items():
                        if key.startswith('legal_'):
                            if key in resolved and resolved[key] != value:
                                conflict = True
                            resolved[key] = value
                if not conflict:
                    out[seat]['raw'].append(resolved)
        return out

    @staticmethod
    def _raw_fallback(offers, seat):
        # A neutral action only when explicitly offered; never invent button 0.
        for payload in sorted(offers['raw'], key=lambda p: p.get('which_button') != 0):
            if type(payload.get('which_button')) is not int:
                continue
            output = {'seat': seat}
            valid = True
            for key, value in payload.items():
                if key == 'seat':
                    continue
                if key.startswith('legal_'):
                    if not isinstance(value, list) or not value:
                        valid = False
                        break
                    name = key[6:]
                    selected = payload.get(name, value[0])
                    if selected not in value:
                        valid = False
                        break
                    output[name] = selected
                elif not isinstance(value, (dict, list)):
                    output[key] = value
            if valid:
                return output
        return None

    def _observe_hero(self, seat, hero, now):
        memory = self._memory.setdefault(seat, HeroMemory())
        dead = not alive(hero)
        deaths = number(hero.get('deaths'))
        if dead or memory.was_dead or (deaths is not None and memory.deaths is not None and deaths != memory.deaths):
            memory.samples.clear()
            memory.recovering = False
            memory.danger_until = -1.
            memory.combat_since = None
            memory.push_until = -1.
        memory.was_dead = dead
        memory.deaths = deaths
        hp = hp_fraction(hero)
        maximum = number(hero.get('max_hp'))
        if dead or hp is None:
            return memory, 0.
        memory.samples[:] = [(t, h, m) for t, h, m in memory.samples if 0 <= now - t <= 2.]
        loss = max((h - hp for t, h, m in memory.samples if t < now and m == maximum), default=0.)
        if not memory.samples or memory.samples[-1][0] < now:
            memory.samples.append((now, hp, maximum))
        if (loss >= .25 and hp < .65) or (loss >= .18 and hp < .48):
            memory.danger_until = now + 1.2
        if hp <= .28:
            memory.recovering = True
        if hp >= .55:
            memory.recovering = False
        return memory, loss

    def _plan_hero(self, seat, raw, offers, own, now):
        view = summary(raw, seat)
        me = view.get('my_hero')
        macros = offers['macros']
        if not isinstance(me, dict) or hp_fraction(me) is None:
            return None, 'missing_observation', False
        memory, loss = self._observe_hero(seat, me, now)
        if not alive(me):
            return None, 'dead', False
        hp = hp_fraction(me)
        camp = raw['camp']
        visible = [e for e in records(view.get('other_heroes'), 10)
                   if e.get('visible') is True and e.get('camp') in (1, 2)
                   and e.get('camp') != camp and alive(e)]
        enemies = [e for e in visible if distance(me, e) <= 10000]
        allies = [a for a in own.values() if alive(a) and distance(me, a) <= 10000]
        friendly = sum(strength(a) for a in allies) or strength(me)
        hostile = sum(strength(e) for e in enemies)
        disadvantaged = hostile > friendly * 1.55 and len(enemies) >= 2 and hp < .70
        structures = [s for s in records(view.get('structures'))
                      if alive(s) and s.get('visible') is not False]
        objectives = [s for s in structures if s.get('camp') == 3 - camp
                      and str(s.get('type', '')).upper() in
                      {'ACTOR_TOWER', 'ACTOR_CRYSTAL', 'TOWER', 'CRYSTAL', 'TURRET'}]
        objective = min(objectives, key=lambda s: distance(me, s), default=None)
        attack_label = macros.get('macro_attack', '').lower()
        structure_attack = ('macro_attack' in macros and 'spring' not in attack_label
                            and any(w in attack_label for w in ('tower', 'crystal', 'turret')))
        # Do not abandon a legal crystal finish to chase a hero or heal.
        finish = (structure_attack and 'crystal' in attack_label and hp > .15
                  and objective is not None and 'CRYSTAL' in str(objective.get('type', '')).upper()
                  and (hp_fraction(objective) or 1) <= .15)
        if finish:
            return 'macro_attack', 'structure_pressure', True
        critical_home = any(s.get('camp') == camp and 'CRYSTAL' in str(s.get('type', '')).upper()
                            and (hp_fraction(s) or 1) < .55 and distance(me, s) < 24000
                            and any(distance(e, s) < 10000 for e in visible) for s in structures)
        emergency_defense = critical_home and hp >= .23
        if emergency_defense:
            if 'macro_attack' in macros:
                return 'macro_attack', 'home_defense', True
            if 'macro_advance' in macros:
                # From the fountain, rejoin the lane through our crystal.
                # No invented target IDs or raw movement fields.
                return 'macro_advance', 'home_defense', True
        at_home = any(s.get('camp') == camp and 'SPRING' in str(s.get('type', '')).upper()
                      and distance(me, s) < 5000 for s in structures)
        if at_home and hp >= .42:
            memory.recovering = False
        # Listed structure attacks are precious. Ordinary chip damage should
        # not send a healthy siege group all the way back to the fountain.
        if structure_attack and hp >= .40 and loss < .25 and not disadvantaged:
            memory.combat_since = None
            return 'macro_attack', 'structure_pressure', False
        if 'macro_retreat' in macros:
            if memory.recovering and not emergency_defense:
                return 'macro_retreat', 'recover', hp <= .28
            if now < memory.danger_until:
                return 'macro_retreat', 'damage_spike', True
            if disadvantaged:
                return 'macro_retreat', 'local_disadvantage', True

        # A legal attack already has an in-range target. Do not apply the
        # heuristic skill range to it, and do not assume missing minion data
        # means that there is no supporting wave.
        if structure_attack:
            return 'macro_attack', 'structure_pressure', False
        # Fighting is a way to reach a building, not the objective. A distant
        # or rearward hero must not lure all five units away from the lane.
        hero_target = 'enemy hero' in attack_label or any(
            re.search(r'enemy\s+hero', macros.get(m, ''), re.I)
            for m in ('macro_skill1', 'macro_skill2', 'macro_skill3'))
        if objective is not None and math.isfinite(distance(me, objective)) and hero_target:
            blockers = [e for e in enemies if distance(me, e) <= 4500
                        and distance(e, objective) <= distance(me, objective) + 1000]
            safe_push = hp >= .60 and not disadvantaged and loss < .12 and friendly >= hostile * .85
            if not blockers:
                memory.combat_since = None
            elif memory.combat_since is None:
                memory.combat_since = now
            elif safe_push and now - memory.combat_since >= 2.4 and now >= memory.push_until:
                memory.push_until = now + 3.
                memory.combat_since = now
            if 'macro_advance' in macros and (not blockers or (safe_push and now < memory.push_until)):
                return 'macro_advance', 'objective_commit', False
        else:
            memory.combat_since = None
            memory.push_until = -1.
        skills = []
        if enemies:
            for name in ('macro_skill1', 'macro_skill2', 'macro_skill3'):
                label = macros.get(name, '')
                if name not in macros or label_distance(label) > 9000:
                    continue
                # Avoid spending combat skills on far structures or guessing
                # their damage to buildings. Labels are data, never commands.
                if not re.search(r'enemy\s+hero', label, re.I):
                    continue
                if name == 'macro_skill3' and not (len(enemies) >= 2 or hp < .60
                                                  or any((hp_fraction(e) or 1) <= .40 for e in enemies)):
                    continue
                skills.append(name)
        if skills:
            # Only choose among currently listed skills; a skill no longer
            # offered is replaced by attack/advance, never kept on cooldown.
            choice = 'macro_skill3' if 'macro_skill3' in skills else skills[0]
            return choice, 'combat_skill', False
        if 'macro_attack' in macros:
            return 'macro_attack', 'attack_available', False
        if 'macro_advance' in macros:
            return 'macro_advance', 'objective_advance', False
        return None, 'no_useful_macro', False

    def choose_action(self, state, context=None):
        raw = state.raw or {}
        if state.is_terminal or state.phase != 'moving' or state.is_current_actor is False:
            return WAIT
        owned = self._owned(raw)
        version = number(state.state_version, 0)
        identity = (getattr(context, 'session_id', None) or state.session_id,
                    getattr(context, 'agent_id', None), raw.get('camp'), tuple(owned))
        if identity != self._identity or version < self._last_version:
            self._memory.clear()
            self._rejected.clear()
            self._last_order = None
            self._sequence = 0
            self._identity = identity
        self._last_version = version
        if not owned:
            raise ValueError('HOK observation lacks explicit owned team seats/camp')
        realtime = (raw.get('pacing') or {}).get('mode') == 'realtime'
        now = version * .2  # documented simulation step, independent of wall time
        offers = self._offers(state, owned)
        simultaneous = raw.get('simultaneous') or {}
        pending = simultaneous.get('your_pending_seats', owned)
        if not isinstance(pending, list):
            pending = owned
        pending = [s for s in pending if type(s) is int and s in owned]
        standing = simultaneous.get('standing_orders') or {}
        own = {s: summary(raw, s).get('my_hero', {}) for s in owned}
        own = {s: h for s, h in own.items() if isinstance(h, dict)}
        self._rejected = {r for r in self._rejected if r[0] == version}
        for seat in owned:
            offers[seat]['macros'] = {m: label for m, label in offers[seat]['macros'].items()
                                     if (version, seat, m) not in self._rejected}
        choices = []
        for seat in owned:
            want, reason, urgent = self._plan_hero(seat, raw, offers[seat], own, now)
            if seat not in pending:
                continue
            memory = self._memory.setdefault(seat, HeroMemory())
            if want and not (realtime and standing.get(str(seat)) == want):
                choices.append((not urgent, memory.last_served, seat,
                                {'seat': seat, 'macro': want}, reason))
            elif want is None:
                fallback = self._raw_fallback(offers[seat], seat)
                # For live heroes this also cancels a stale unsafe standing
                # order when no useful macro is offered. Dead heroes only need
                # a neutral action in lockstep.
                if (fallback and (version, seat, None) not in self._rejected
                        and (not realtime or (alive(own.get(seat, {})) and standing.get(str(seat))))):
                    choices.append((True, memory.last_served, seat, fallback, reason))
        if not choices:
            self.last_diagnostics = {'reason': 'standing_orders_current', 'pending': len(pending)}
            if realtime or not pending:
                return WAIT
            raise ValueError('HOK pending lockstep seat has no complete listed action')
        _, _, seat, order, reason = min(choices, key=lambda x: x[:3])
        self._sequence += 1
        self._memory[seat].last_served = self._sequence
        self._last_order = (version, seat, order.get('macro'))
        self.last_diagnostics = {'seat': seat, 'reason': reason, 'macro': order.get('macro'),
                                 'pending': len(pending)}
        self.counts[reason] += 1
        return order

    def on_action_result(self, result, context=None):
        if isinstance(result, dict) and result.get('error') and self._last_order:
            self._rejected.add(self._last_order)
            self.counts['rejected'] += 1
        self._last_order = None


def create_agent():
    return HokPlatformAgent()
