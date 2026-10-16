"""Bounded harvester recovery and observed-damage escape.

The protocol exposes ``idle``/``act`` and ``harvest`` with optional ``to``.
It does not expose live resource-cell reserves or cargo. Initial-map patches
are search hints only; persistent idle at a destination temporarily lowers our
confidence in that patch, never establishes that it is actually exhausted.
"""
from collections import Counter, deque
from math import isfinite

from .common import cell, distance
from .maps import _route_from, route_safe
from .strategy import STATIC, fortifications, radius, weapon_range


RETRY_SECONDS = 12
PATCH_RECHECK_SECONDS = 120
MAX_TARGET_ORDERS = 4
DAMAGE_SAMPLE_SECONDS = 8
DAMAGE_RETRY_SECONDS = 4
ARMED_UNITS = frozenset({
    'e1', 'e2', 'e3', 'e4', 'e7', 'shok', '1tnk', '2tnk', '3tnk', '4tnk',
    'ttnk', 'stnk', 'ctnk', 'qtnk', 'jeep', 'apc', 'ftrk', 'arty', 'v2rl',
    'mig', 'yak', 'heli', 'hind', 'dd', 'ca', 'pt',
})


def _idle(unit):
    # A contradictory non-idle activity wins over idle=True. Unknown activity
    # names are left alone instead of interrupting a possibly productive trip.
    activity = unit.get('act')
    return unit.get('idle') is True and (activity is None or
           isinstance(activity, str) and activity.strip().lower() in {'', 'idle'})


def _patches(v, memory):
    navigation = getattr(v, 'navigation', {})
    ground = navigation.get('parents', {})
    key = (v.map_id, id(ground), id(v.map_info.get('layout')))
    if memory.get('map_key') == key:
        return memory['patches']
    # M denotes an ore-mine actor, not a resource cell to stand on. The ground
    # graph accepts only known traversable characters, which excludes M.
    remaining = set(tuple(p) for p in v.ore_cells if tuple(p) in ground)
    patches = []
    while remaining:
        first = min(remaining)
        todo, points = deque([first]), []
        remaining.remove(first)
        while todo:
            x, y = todo.popleft()
            points.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nxt = (x+dx, y+dy)
                    if nxt in remaining:
                        remaining.remove(nxt)
                        todo.append(nxt)
        patches.append({'id': f'{first[0]},{first[1]}', 'cells': tuple(points)})
    memory.update(map_key=key, patches=patches)
    return patches


def _hostiles(v):
    # Naval combat units still threaten shore miners even though they are
    # excluded from our own ground-army controller.
    harmless = {'harv', 'mcv', 'e6', 'medi', 'mech', 'spy', 'thf',
                'tran', 'badr', 'u2', 'lst', 'dog'}
    return [u for u in v.enemies if u.get('type') not in harmless]


def _safe_route(v, start, destination, hostiles):
    if not route_safe(v, destination, start=start):
        return None
    route = _route_from(v, start, destination)
    # This is a conservative local proximity gate, not a weapon simulation.
    if not route or any(distance(point, cell(enemy)) < 12
                        for point in route for enemy in hostiles):
        return None
    return route


def _danger_zones(v, hostiles):
    return [(cell(b), radius(v, b)) for b in fortifications(v)] + [(cell(u), 12.) for u in hostiles]


def _observe_health(v, unit, record):
    """Only distinct, recent public snapshots can establish fresh damage."""
    hp = unit.get('hp')
    if (isinstance(hp, bool) or not isinstance(hp, (int, float))
            or not isfinite(hp) or not 0 < hp <= 100 or not isfinite(v.now)):
        for key in ('last_hp', 'last_hp_at', 'damage_until'):
            record.pop(key, None)
        return
    previous, at = record.get('last_hp'), record.get('last_hp_at')
    if (previous is not None and at is not None
            and 0 < v.now-at <= DAMAGE_SAMPLE_SECONDS and hp < previous):
        record['damage_until'] = v.now+DAMAGE_RETRY_SECONDS
    elif at is not None and (v.now < at or v.now-at > DAMAGE_SAMPLE_SECONDS):
        record.pop('damage_until', None)
    if record.get('damage_until', -1) < v.now:
        record.pop('damage_until', None)
    record.update(last_hp=hp, last_hp_at=v.now)


def _active_threat_zones(v, hostiles):
    # Remembered towers still constrain the escape route, but only a CURRENTLY
    # visible armed contact can justify interrupting productive work. Live
    # range data wins; missing data uses the existing conservative 12-cell
    # mobile threat estimate. The one-cell margin covers actor footprints.
    armed = [u for u in hostiles if u.get('type') in ARMED_UNITS
             or v.item_rule(u.get('type')).get('weapon')]
    return ([(cell(b), radius(v, b)) for b in v.enemy_buildings
             if b.get('type') in STATIC]
            + [(cell(u), weapon_range(v, u.get('type'), 12.)+1.) for u in armed])


def _escape(v, current, zones, preferred):
    """Find nearby safe land without stepping deeper into any known threat."""
    ground = getattr(v, 'navigation', {}).get('parents', {})
    if current not in ground:
        return None
    def exposure(point):
        return tuple(max(0., r-distance(point, centre)+.01) for centre, r in zones)
    todo, seen = deque([(current, exposure(current), 0)]), {current}
    parents = {current: None}
    goals, first_distance = [], None
    while todo and len(seen) <= 4096:
        point, risk, steps = todo.popleft()
        if first_distance is not None and steps > first_distance:
            break
        if not any(risk):
            goals.append(point)
            first_distance = steps
            continue
        x, y = point
        for nxt in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if nxt not in ground or nxt in seen:
                continue
            after = exposure(nxt)
            if any(a > b+1e-9 for a, b in zip(after, risk)):
                continue
            seen.add(nxt)
            parents[nxt] = point
            todo.append((nxt, after, steps+1))
    if not goals:
        return None
    target = min(goals, key=lambda p: (distance(p, preferred), p))
    path = []
    while target is not None:
        path.append(target)
        target = parents[target]
    path.reverse()
    # Submit only the first straight, short segment. An engine may choose a
    # different route to a distant goal; reobserve before turning a corner.
    direction = (path[1][0]-current[0], path[1][1]-current[1])
    waypoint = path[1]
    for previous, point in zip(path[1:6], path[2:7]):
        if (point[0]-previous[0], point[1]-previous[1]) != direction:
            break
        waypoint = point
    return waypoint


def _choose(v, unit, record, refs, patches, memory, loads, hostiles):
    candidates = []
    current = cell(unit)
    suspects = memory.get('suspect_until', {})
    for patch in patches:
        ident = patch['id']
        if suspects.get(ident, 0) > v.now or record.get('avoid', {}).get(ident, 0) > v.now:
            continue
        for refinery in refs:
            home = cell(refinery)
            target = min(patch['cells'], key=lambda p: (distance(p, home), distance(p, current), p))
            # Do not assign a speculative cross-map trip with no nearby
            # working drop-off. A newly placed refinery enables new patches.
            if distance(home, target) > 24:
                continue
            score = (distance(current, target) + 2*distance(home, target)
                     + 12*loads['patch'][ident] + 6*loads['ref'][refinery['id']])
            candidates.append((score, ident, refinery['id'], target, home))
    choices = []
    for _, ident, ref_id, target, home in sorted(candidates)[:12]:
        outbound = _safe_route(v, current, target, hostiles)
        delivery = _safe_route(v, target, home, hostiles)
        if outbound is None or delivery is None:
            continue
        score = (len(outbound)-1 + 2*(len(delivery)-1)
                 + 12*loads['patch'][ident] + 6*loads['ref'][ref_id])
        choices.append((score, ident, ref_id, target))
    return min(choices) if choices else None


def plan(v, memory, emit):
    """Resume idle miners and rescue active miners with fresh visible risk.

    Call with a dedicated per-match memory dictionary. ``emit`` returning true
    records only a submitted order; actual progress is inferred later from
    observation, never from the transport's pending acknowledgement.
    Healthy productive work and old wounds never trigger a safety move.
    """
    miners = [u for u in v.units if u.get('type') == 'harv']
    live_ids = {str(u['id']) for u in miners}
    records = memory.setdefault('units', {})
    for ident in list(records):
        if ident not in live_ids:
            del records[ident]
    refs = [b for b in v.buildings if b.get('type') == 'proc'
            and b.get('powered') is not False and not b.get('powered_down')]
    patches = _patches(v, memory)
    hostiles = _hostiles(v)
    danger_zones = _danger_zones(v, hostiles)
    active_threats = _active_threat_zones(v, hostiles)
    loads = {'patch': Counter(), 'ref': Counter()}
    for unit in miners:
        record = records.setdefault(str(unit['id']), {})
        _observe_health(v, unit, record)
        if not _idle(unit):
            record['idle_since'] = None
            if record.get('active_since') is None:
                record['active_since'] = v.now
            # Sustained activity is enough to reset retry throttling, but does
            # not prove that resources were delivered or replenish a patch.
            if v.now-record['active_since'] >= 20:
                record['attempts'] = 0
            if record.get('patch'):
                loads['patch'][record['patch']] += 1
            elif patches:
                near = min(patches, key=lambda p: min(distance(cell(unit), c) for c in p['cells']))
                if min(distance(cell(unit), c) for c in near['cells']) <= 12:
                    loads['patch'][near['id']] += 1
            if refs:
                loads['ref'][min(refs, key=lambda b: distance(cell(unit), cell(b)))['id']] += 1
        else:
            record['active_since'] = None
            if record.get('idle_since') is None:
                record['idle_since'] = v.now
    generic, targeted, escape_checks = [], 0, 0
    for unit in sorted(miners, key=lambda u: u['id']):
        record = records[str(unit['id'])]
        current = cell(unit)
        idle = _idle(unit)
        damaged_active = (not idle and record.get('damage_until', -1) >= v.now
                          and any(distance(current, centre) <= r
                                  for centre, r in active_threats))
        if not idle and not damaged_active:
            continue
        zones = danger_zones + active_threats if damaged_active else danger_zones
        if any(distance(current, centre) <= r for centre, r in zones):
            # A normal safe-route gate rejects its starting cell when the
            # miner is already under attack. Escape must run first. Active
            # work is interrupted only after observed damage and a current
            # visible threat; failed searches are throttled as well.
            if v.now >= record.get('escape_retry', -1) and escape_checks < 4 and targeted < MAX_TARGET_ORDERS:
                escape_checks += 1
                preferred = cell(min(refs, key=lambda b: distance(current, cell(b)))) if refs else v.base
                target = _escape(v, current, zones, preferred)
                if target is None:
                    record['escape_retry'] = v.now+12
                elif emit({'cmd': 'move', 'units': [unit['id']], 'to': list(target)},
                          key=f'harvester-safety-{unit["id"]}', cooldown=2):
                    record.update(escape_retry=v.now+2, next_retry=v.now+2)
                    record.pop('damage_until', None)
                    targeted += 1
                    for key in ('target', 'patch', 'refinery'):
                        record.pop(key, None)
                elif damaged_active:
                    # A refused batch does not consume the observed-damage
                    # window, but retrying route search every frame is wasteful.
                    record['escape_retry'] = v.now+2
            continue
        if not refs:
            continue
        if v.now < record.get('next_retry', -1):
            continue
        previous = record.get('target')
        if previous is not None:
            if v.now-max(record.get('sent_at', v.now), record['idle_since']) < RETRY_SECONDS:
                continue
            patch = record['patch']
            # A stalled journey and idle at a resource destination are
            # different evidence. Only the latter affects other harvesters.
            arrived = distance(cell(unit), previous) <= 4
            record.setdefault('avoid', {})[patch] = v.now + (PATCH_RECHECK_SECONDS if arrived else 45)
            if arrived:
                failures = memory.setdefault('destination_failures', {})
                failures[patch] = failures.get(patch, 0)+1
                if failures[patch] >= 2:
                    memory.setdefault('suspect_until', {})[patch] = v.now+PATCH_RECHECK_SECONDS
            for key in ('target', 'patch', 'refinery'):
                record.pop(key, None)

        # First try the engine's native resume when there is no known enemy
        # risk. Subsequent recovery uses explicit, screened map hints.
        first_resume = (not record.get('attempts', 0) and not record.get('avoid')
                        and not memory.get('suspect_until') and not fortifications(v) and not hostiles)
        if first_resume:
            generic.append(unit)
            continue
        choice = _choose(v, unit, record, refs, patches, memory, loads, hostiles)
        if choice is not None and targeted < MAX_TARGET_ORDERS:
            _, patch, ref_id, target = choice
            if emit({'cmd': 'harvest', 'units': [unit['id']], 'to': list(target)},
                    key=f'harvester-{unit["id"]}', cooldown=RETRY_SECONDS):
                attempts = record.get('attempts', 0)+1
                record.update(target=target, patch=patch, refinery=ref_id, sent_at=v.now,
                              attempts=attempts, next_retry=v.now+RETRY_SECONDS)
                loads['patch'][patch] += 1
                loads['ref'][ref_id] += 1
                targeted += 1
        elif not patches and not fortifications(v) and not hostiles:
            # Missing topology/resource hints: bounded native-search retries,
            # never invent a target or reuse an initial ore cell indefinitely.
            generic.append(unit)
        else:
            record['next_retry'] = v.now+RETRY_SECONDS

    if generic:
        limit = min(50, max(1, int((v.raw.get('limits') or {}).get('max_units_per_order', 50))))
        selected = generic[:limit]
        if emit({'cmd': 'harvest', 'units': [u['id'] for u in selected]},
                key='idle-miners', cooldown=8):
            for unit in selected:
                record = records[str(unit['id'])]
                attempts = record.get('attempts', 0)+1
                # The native fallback reaches at most one retry per minute;
                # an idle miner can recover after an unseen resource change.
                delay = min(60, RETRY_SECONDS * 2**min(attempts-1, 3))
                record.update(attempts=attempts, sent_at=v.now, next_retry=v.now+delay)
