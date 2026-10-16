"""Owned-territory mining hints, not a live ore map or placement oracle.

The server may ignore a placement hint. Observe the resulting refinery before
counting it as a new drop-off, and back off when placement fell back to home.
"""
from .common import cell, distance
from .harvesters import _patches, _hostiles, _safe_route, _idle
from .maps import nearest_reachable, route_safe
from .strategy import STATIC, TANKS, fortifications, radius


def observe(v, memory):
    pending = memory.get('placement')
    if not pending:
        return
    new = [b for b in v.buildings if b.get('type') == 'proc'
           and b['id'] not in pending['before']]
    if new:
        # An accepted place order is not evidence that the hint was honored.
        if min(distance(cell(b), pending['at']) for b in new) > 6:
            memory.setdefault('blocked_until', {})[pending['patch']] = v.now + 180
        memory.pop('placement', None)
        memory.pop('cached', None)
    elif v.now - pending['sent_at'] > 90:
        memory.pop('placement', None)


def _safe(v, point):
    return (all(distance(point, cell(e)) >= 18 for e in _hostiles(v))
            and all(distance(point, cell(b)) > radius(v, b) + 5
                    for b in fortifications(v)))


def _working_near(v, miners, points, memory, patch):
    """Activity evidence, never a measurement of remaining resource quantity."""
    seen = memory.setdefault('activity', {}).setdefault(patch, {})
    nearby, working = set(), []
    for unit in miners:
        if unit.get('idle') is True or min(distance(cell(unit), p) for p in points) > 4:
            continue
        activity = str(unit.get('act', '')).lower()
        direct = ('harvest' in activity and not any(s in activity for s in
                  ('find', 'search', 'wait', 'move', 'return', 'deliver')))
        # Some engine views expose the parent activity, not HarvestResource.
        # Require repeated near-patch activity instead of treating a single
        # travelling/searching observation as proof of productive ore.
        parent = activity == 'findanddeliverresources'
        if not (direct or parent):
            continue
        ident = str(unit['id'])
        nearby.add(ident)
        first, last = seen.get(ident, (v.now, v.now))
        if v.now - last > 15:
            first = v.now
        seen[ident] = (first, v.now)
        if direct or v.now - first >= 12:
            working.append(unit)
    for ident in set(seen) - nearby:
        del seen[ident]
    return working


def refinery_site(v, memory, harvest_memory):
    """Prefer a shorter delivery trip inside an existing construction area.

    Initial resources are only hypotheses. Ignore patches that idle-miner
    recovery suspects, and after midgame require a current harvesting activity
    near the patch. Unknown/depleted patches do not justify endless factories.
    """
    if not getattr(v, 'map_plan', {}).get('active'):
        return None
    refs = [b for b in v.buildings if b.get('type') == 'proc']
    facts = [b for b in v.buildings if b.get('type') == 'fact']
    if not facts or len(refs) >= 6:
        return None
    suspects = harvest_memory.get('suspect_until', {})
    blocked = memory.get('blocked_until', {})
    signature = (tuple((b['id'], cell(b)) for b in v.buildings),
                 tuple(sorted(suspects.items())), tuple(sorted(blocked.items())))
    cached = memory.get('cached')
    if (cached is None and memory.get('signature') == signature
            and v.now - memory.get('checked_at', -100) < 6):
        return None
    if (cached and memory.get('signature') == signature
            and v.now - memory.get('checked_at', -100) < 6
            and _safe(v, cached['at']) and _safe(v, cached['ore'])
            and route_safe(v, cached['at']) and route_safe(v, cached['ore'])):
        return cached
    memory.update(checked_at=v.now, signature=signature, cached=None)
    ground = v.navigation.get('parents', {})
    layout = v.map_info.get('layout') or {}
    rows = layout.get('rows') or []
    ox, oy = layout.get('origin') or v.bounds[:2]
    miners = [u for u in v.units if u.get('type') == 'harv']
    choices = []
    for patch in _patches(v, harvest_memory):
        ident, points = patch['id'], patch['cells']
        if len(points) < 6 or max(suspects.get(ident, 0), blocked.get(ident, 0)) > v.now:
            continue
        # Sustained activity isn't a reserve measurement, but a harvesting
        # activity is better evidence than a remembered initial ore tile.
        working = _working_near(v, miners, points, memory, ident)
        if v.now > 300 and not working:
            continue
        ore = min(points, key=lambda p: (min(distance(p, cell(f)) for f in facts), p))
        if min(distance(ore, cell(f)) for f in facts) > 18 or not _safe(v, ore):
            continue
        if not route_safe(v, ore):
            continue
        delivery = min((distance(ore, cell(r)) for r in refs), default=100)
        if refs and delivery < 10:
            continue  # Already has a nearby drop-off; do not tile the base.
        for dx, dy in ((4, 0), (-4, 0), (0, 4), (0, -4), (4, 4), (-4, -4), (4, -4), (-4, 4)):
            at = (ore[0] + dx - 1, ore[1] + dy - 1)
            if at not in ground or not _safe(v, at):
                continue
            # A conservative clear 3x3 hint, never a claim of engine legality.
            if not all((at[0]+x, at[1]+y) in ground
                       and rows[at[1]+y-oy][at[0]+x-ox] in '.S'
                       for x in range(3) for y in range(3)):
                continue
            if (min(distance(at, cell(f)) for f in facts) > 18
                    or min(distance(at, cell(b)) for b in v.buildings) > 8
                    or any(distance(at, cell(b)) < 4 for b in v.buildings)
                    or any(distance(at, cell(r)) < 8 for r in refs)):
                continue
            if distance(at, v.enemy_base) < distance(at, v.base) + 10:
                continue
            # Check the delivery route too, not just the construction cell.
            path = _safe_route(v, ore, at, _hostiles(v))
            if path is None or len(path) > 13 or not route_safe(v, at):
                continue
            improvement = delivery - (len(path) - 1)
            if refs and improvement < 4:
                continue
            score = improvement + min(12, len(points) / 3) + 6 * len(working)
            choices.append((score, at, ident, ore))
    if choices:
        _, at, patch, ore = max(choices)
        memory['cached'] = {'at': list(at), 'patch': patch, 'ore': list(ore)}
    return memory['cached']


def record_placement(v, memory, site):
    if not memory.get('placement'):
        memory['placement'] = dict(site, sent_at=v.now,
                                   before=[b['id'] for b in v.buildings if b.get('type') == 'proc'])


def defense_anchor(v):
    """One ground-defense position per separated mining area, at most three."""
    refs = sorted((b for b in v.buildings if b.get('type') == 'proc'),
                  key=lambda b: (distance(cell(b), v.base), b['id']))
    groups = []
    for refinery in refs:
        if all(distance(cell(refinery), cell(b)) > 12 for b in groups):
            groups.append(refinery)
    if not groups:
        return None
    towers = [b for b in v.buildings if b.get('type') in STATIC
              and b.get('powered') is not False and not b.get('powered_down')]
    gaps = [b for b in groups if not any(distance(cell(b), cell(t)) <= 10 for t in towers)]
    if not gaps:
        return None
    hostiles = _hostiles(v)
    target = min(gaps, key=lambda b: (
        min((distance(cell(b), cell(e)) for e in hostiles), default=100),
        distance(cell(b), v.base), b['id']))
    return target


def defense_hint(v, anchor):
    hostiles = _hostiles(v)
    target = cell(min(hostiles, key=lambda e: distance(cell(e), cell(anchor)))) if hostiles else v.enemy_base
    start = cell(anchor)
    length = max(1, distance(start, target))
    point = v.clamp((start[0] + 4*(target[0]-start[0])/length,
                     start[1] + 4*(target[1]-start[1])/length))
    if getattr(v, 'map_plan', {}).get('active'):
        point = nearest_reachable(v, point)
        if point is None or not route_safe(v, point):
            return None
    if any(distance(point, cell(b)) <= radius(v, b) + 2 for b in fortifications(v)):
        return None
    return list(point)


def miner_target(v, refs, memory=None, harvest_memory=None):
    """Raise the old eight-miner ceiling only with observable working income."""
    original = min(8, max(4, refs * 2))
    miners = [u for u in v.units if u.get('type') == 'harv']
    if (refs <= 4 or not getattr(v, 'map_plan', {}).get('active')
            or v.remaining < 180 or any(_idle(u) for u in miners)):
        return original
    memory = memory if memory is not None else {}
    harvest_memory = harvest_memory if harvest_memory is not None else {}
    working = {u['id'] for patch in _patches(v, harvest_memory)
               if harvest_memory.get('suspect_until', {}).get(patch['id'], 0) <= v.now
               for u in _working_near(v, miners, patch['cells'], memory, patch['id'])}
    healthy_tanks = sum(u.get('type') in TANKS and u.get('hp', 100) >= 50 for u in v.units)
    return min(12, refs * 2) if len(working) >= 2 and healthy_tanks >= 6 else original
