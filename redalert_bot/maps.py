"""Conservative map adaptation from this seat's public map configuration.

Grid distances are cardinal, static estimates, not OpenRA travel times. The
layout describes INITIAL resources, never current ore reserves or enemy state.
No map-name-specific winner or learned win rate is claimed here.
"""
from collections import deque
from math import hypot


def _terrain(v):
    layout = v.map_info.get('layout') or {}
    rows = layout.get('rows')
    origin = layout.get('origin') or v.bounds[:2]
    if (not isinstance(rows, list) or not rows or len(rows) > 256
            or not all(isinstance(row, str) and len(row) <= 256 for row in rows)
            or not isinstance(origin, (list, tuple)) or len(origin) != 2
            or any(type(n) is not int for n in origin)):
        return {}, [], 0
    ox, oy = origin
    bx, by, w, h = v.bounds
    ground = {(ox+x, oy+y) for y, row in enumerate(rows) for x, c in enumerate(row)
              if c in '.S$*' and bx <= ox+x < bx+w and by <= oy+y < by+h}
    if not ground:
        return {}, [], 0
    start = min(ground, key=lambda p: (hypot(p[0]-v.base[0], p[1]-v.base[1]), p))
    if hypot(start[0]-v.base[0], start[1]-v.base[1]) > 3:
        return {}, [], 0
    parents, distances, todo = {start: None}, {start: 0}, deque([start])
    while todo:
        x, y = todo.popleft()
        for p in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if p in ground and p not in parents:
                parents[p] = (x,y)
                distances[p] = distances[(x,y)] + 1
                todo.append(p)
    target = min(ground, key=lambda p: (hypot(p[0]-v.enemy_base[0], p[1]-v.enemy_base[1]), p))
    route = []
    known_spawn = bool(v.hints.get('enemy_base')) or len(v.map_info.get('spawns') or []) == 2
    if known_spawn and target in parents and hypot(target[0]-v.enemy_base[0], target[1]-v.enemy_base[1]) <= 3:
        p = target
        while p is not None:
            route.append(p)
            p = parents[p]
        route.reverse()
    home_ore = sum(1 for p in set(v.ore_cells) if distances.get(p, 10**9) <= 24)
    return {'parents': parents, 'distances': distances}, route, home_ore


def adapt(v, memory):
    """Attach cached topology and a small, traceable policy parameter set."""
    layout = v.map_info.get('layout') or {}
    key = (v.map_id, tuple(v.bounds), tuple(v.base), tuple(v.enemy_base), id(layout))
    if memory.get('key') != key:
        nav, route, home_ore = _terrain(v)
        # A long approach alone is not enough: require a local resource patch.
        direct = hypot(v.enemy_base[0]-v.base[0], v.enemy_base[1]-v.base[1])
        macro = bool(route) and (direct >= 70 or len(route)-1 >= 90) and home_ore >= 8
        active = bool(nav)
        plan = dict(map_id=v.map_id, active=active,
                    style=('long-route-economy' if macro else 'guarded-economy') if active else 'fallback',
                    route_cells=len(route)-1 if route else None,
                    spawn_distance=round(direct, 1),
                    initial_home_resource_cells=home_ore,
                    early_infantry_cap=4 if macro else 6,
                    second_ref_infantry_cap=6 if macro else 10,
                    defense_cash=1300 if macro else 900,
                    defense_refs=2 if macro or not active else 1,
                    defense_miners=3 if macro or not active else 1,
                    expansion_radius=42 if macro or not active else 32,
                    expansion_screen=1800 if macro or not active else 2400,
                    expansion_margin=(10 if macro else 12) if active else 7,
                    productive_window=150 if macro or not active else 180)
        if route:
            plan['guard_cell'] = list(route[min(len(route)-1, 8 if macro else 6)])
            plan['scout_cell'] = list(route[min(len(route)-1, max(12, min(22, (len(route)-1)//3)))])
        memory.update(key=key, navigation=nav, plan=plan)
    v.navigation = memory['navigation']
    v.map_plan = memory['plan']
    return v.map_plan


def nearest_reachable(v, destination):
    distances = getattr(v, 'navigation', {}).get('distances', {})
    if not distances:
        return None
    p = tuple(v.clamp(destination))
    if p in distances:
        return p
    return min(distances, key=lambda c: (hypot(c[0]-p[0], c[1]-p[1]), distances[c], c))


def route_safe(v, destination):
    """Reject a static route crossing known towers; fog is NOT proof of safety."""
    from .strategy import fortifications, radius
    parents = getattr(v, 'navigation', {}).get('parents', {})
    p = tuple(destination)
    if p not in parents:
        return False
    towers = tuple(sorted((b['x'], b['y'], radius(v,b)) for b in fortifications(v)))
    if not towers:
        return True
    signature = (id(parents), towers)
    if getattr(v, '_route_safety_key', None) != signature:
        v._route_safety_key, v._route_safety = signature, {None: True}
    cache, pending = v._route_safety, []
    while p not in cache:
        pending.append(p)
        if any(hypot(p[0]-x,p[1]-y) <= r for x,y,r in towers):
            cache[p] = False
            break
        p = parents[p]
    safe = cache[p]
    for point in pending:
        cache[point] = safe
    return safe
