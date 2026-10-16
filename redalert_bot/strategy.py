"""Public defensive contacts and conservative engagement geometry.

These are risk gates, not an OpenRA damage/pathfinding simulator. Remembered
positions never authorize targeting an enemy ID that is no longer visible.
"""
import math
import re

from .common import cell, distance

STATIC = {"pbox", "hbox", "gun", "ftur", "tsla"}
SIEGE = {"arty", "v2rl"}
TANKS = {"1tnk", "2tnk", "3tnk", "4tnk", "ttnk"}


def weapon_range(v, item, default):
    weapon = v.item_rule(item).get("weapon") or {}
    if isinstance(weapon, str):
        weapon = (v.rules.get("weapons") or {}).get(weapon, {})
    value = weapon.get("range_cells", weapon.get("range")) if isinstance(weapon, dict) else None
    try:
        if isinstance(value, str) and "c" in value:
            match = re.fullmatch(r"(\d+)c(\d*)", value)
            value = float(match[1]) + float(match[2] or 0) / 1024 if match else None
        value = float(value)
        return value if math.isfinite(value) and 0 < value <= 64 else default
    except (TypeError, ValueError):
        return default


def radius(v, building):
    # Unknown tower ranges receive a conservative planning radius. Live
    # game_config overrides this, rather than assuming upstream balance.
    return weapon_range(v, building.get("type"), 9.) + 1.


def observe(v, memory):
    contacts = memory.setdefault("enemy_static", {})
    visible = {str(b["id"]): b for b in v.enemy_buildings}
    for ident, b in visible.items():
        if b.get("type") in STATIC:
            contacts[ident] = {k: b[k] for k in ("id", "type", "x", "y", "hp") if k in b}
    for ident, b in list(contacts.items()):
        if ident not in visible and any(distance(cell(u), cell(b)) <= 3 for u in v.units):
            del contacts[ident]
    kills = float(v.military.get("kills_cost", 0))
    deaths = float(v.military.get("deaths_cost", 0))
    history = memory.setdefault("trades", [])
    history[:] = [row for row in history if v.now-row[0] <= 45]
    if history:
        _, old_kills, old_deaths = history[0]
        if deaths > memory.get("last_deaths", deaths) and deaths-old_deaths-(kills-old_kills) >= 500:
            memory["recover_until"] = v.now+45
    if not history or v.now-history[-1][0] >= 2:
        history.append((v.now, kills, deaths))
    memory["last_deaths"] = deaths
    v.strategy = memory


def fortifications(v):
    known = dict((getattr(v, "strategy", {}) or {}).get("enemy_static", {}))
    known.update({str(b["id"]): b for b in v.enemy_buildings if b.get("type") in STATIC})
    return list(known.values())


def segment_distance(point, start, finish):
    dx, dy = finish[0]-start[0], finish[1]-start[1]
    denominator = dx*dx+dy*dy
    t = max(0., min(1., ((point[0]-start[0])*dx+(point[1]-start[1])*dy)/denominator)) if denominator else 0.
    return distance(point, (start[0]+t*dx, start[1]+t*dy))


def blockers(v, start, finish):
    return [b for b in fortifications(v) if segment_distance(cell(b), start, finish) <= radius(v, b)+2]


def safe_cell(v, position):
    return all(distance(position, cell(b)) > radius(v, b) for b in fortifications(v))
