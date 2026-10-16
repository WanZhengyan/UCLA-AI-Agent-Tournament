"""Short-queue OpenRA economy: two refineries, infantry and screened armor.

Policy inspiration: OpenRA's official multiplayer fundamentals. Runtime
availability and prices always take precedence over the upstream build order.
"""
from __future__ import annotations

from collections import Counter, deque
from math import hypot
from .strategy import TANKS, fortifications, blockers, radius, safe_cell


SUPPORT = {"harv", "mcv", "e6", "medi", "mech", "dog"}
DEFENSE = {"pbox", "hbox", "ftur", "gun", "tsla", "sam", "agun"}


def _dist(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _type(actor):
    return str(actor.get("type", "")).lower()


def _enemies(v):
    return [x for x in v.obs.get("visible_enemies", []) if isinstance(x, dict)
            and not x.get("wreck") and not _type(x).endswith("husk")]


def _queued(v, item):
    return sum(int(p.get("count", 1) or 1) for p in v.production
               if str(p.get("item", "")).lower() == item)


def _near_base(v):
    positions = [v.cell(b) for b in v.buildings if _type(b) in {"fact", "proc", "weap", "barr", "tent"}]
    positions = positions or [v.base]
    return [e for e in _enemies(v) if _type(e) not in SUPPORT
            and min(_dist(v.cell(e), p) for p in positions) < 17]


def _layout(v):
    raw = v.map_info.get("layout", {}) if isinstance(v.map_info, dict) else {}
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list):
        return None
    rows = raw["rows"]
    origin = raw.get("origin", list(v.bounds[:2]))
    if not rows or not all(isinstance(r, str) for r in rows):
        return None
    return rows, origin


def _reachable_land(v):
    """Conservative static connectivity; no expansion when map data is absent."""
    layout = _layout(v)
    if not layout:
        return set()
    rows, origin = layout
    ox, oy = int(origin[0]), int(origin[1])
    # Only known ground is accepted. Unknown map symbols are not guessed.
    ground = {(ox + x, oy + y) for y, row in enumerate(rows)
              for x, char in enumerate(row) if char in ".S$*"}
    if not ground:
        return set()
    start = min(ground, key=lambda c: _dist(c, v.base))
    seen, todo = {start}, deque([start])
    while todo:
        x, y = todo.popleft()
        for nxt in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nxt in ground and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _expansion_site(v, memory):
    # Compute a few times, rather than walking the whole map each 200 ms.
    map_plan = getattr(v, 'map_plan', {})
    if v.now - memory.get("site_checked_at", -1000) < 25:
        cached = memory.get("expansion_site")
        if not map_plan.get('active') or not cached:
            return cached
        from .maps import route_safe
        if route_safe(v, cached) and not any(_dist(cached, v.cell(e)) < 20 for e in _enemies(v)):
            return cached
    memory["site_checked_at"] = v.now
    facts = [v.cell(b) for b in v.buildings if _type(b) == "fact"]
    refs = [v.cell(b) for b in v.buildings if _type(b) == "proc"]
    candidates = []
    for ore in v.ore_cells:
        if any(_dist(ore,v.cell(b)) <= radius(v,b)+8 for b in fortifications(v)):
            continue
        home = min((_dist(ore, p) for p in facts), default=_dist(ore, v.base))
        if not 17 <= home <= map_plan.get('expansion_radius', 42) or _dist(ore, v.enemy_base) < home + map_plan.get('expansion_margin', 7):
            continue
        if refs and min(_dist(ore, p) for p in refs) < 13:
            continue
        candidates.append(ore)
    if not candidates:
        memory["expansion_site"] = None
        return None
    land = _reachable_land(v)
    layout = _layout(v)
    if not land or not layout:
        memory["expansion_site"] = None
        return None
    rows, (ox, oy) = layout
    choices = []
    for ore in sorted(candidates, key=lambda c: _dist(c, v.base))[:100]:
        for dx, dy in ((4, 0), (-4, 0), (0, 4), (0, -4), (4, 4), (-4, -4), (4, -4), (-4, 4)):
            cell = (int(ore[0] + dx), int(ore[1] + dy))
            if cell not in land:
                continue
            if map_plan.get('active'):
                from .maps import route_safe
                if not route_safe(v, cell):
                    continue
            elif blockers(v,v.base,cell):
                continue
            # Clear 3x3 footprint gives an MCV a realistic place to unfold.
            if not all((cell[0]+a, cell[1]+b) in land and
                       rows[cell[1]+b-oy][cell[0]+a-ox] in ".S"
                       for a in (-1, 0, 1) for b in (-1, 0, 1)):
                continue
            if any(_dist(cell, v.cell(e)) < 20 for e in _enemies(v)):
                continue
            travel = getattr(v, 'navigation', {}).get('distances', {}).get(cell, _dist(cell, v.base))
            choices.append((travel, cell))
    site = min(choices)[1] if choices else None
    memory["expansion_site"] = site
    return site


def _place_at(v, item):
    facts = [v.cell(b) for b in v.buildings if _type(b) == "fact"] or [v.base]
    if item == "proc" and v.ore_cells:
        refs = [v.cell(b) for b in v.buildings if _type(b) == "proc"]
        candidates = [c for c in v.ore_cells if min(_dist(c, f) for f in facts) < 18
                      and _dist(c, v.enemy_base) > 16]
        if candidates:
            def score(c):
                crowd = sum(max(0, 13 - _dist(c, r)) for r in refs)
                return min(_dist(c, f) for f in facts) + crowd * 1.8
            ore = min(candidates, key=score)
            anchor = min(facts, key=lambda f: _dist(f, ore))
            length = max(1, _dist(anchor, ore))
            # Place on the near side of the ore, without covering the patch.
            return v.clamp((round(ore[0] + 4*(anchor[0]-ore[0])/length) - 1,
                            round(ore[1] + 4*(anchor[1]-ore[1])/length) - 1))
    if item in DEFENSE:
        threats = _near_base(v)
        target = min(threats, key=lambda e: _dist(v.cell(e), v.base)) if threats else None
        direction = v.cell(target) if target else v.enemy_base
        length = max(1, _dist(v.base, direction))
        return v.clamp((round(v.base[0]+7*(direction[0]-v.base[0])/length),
                        round(v.base[1]+7*(direction[1]-v.base[1])/length)))
    return None


def _guarded_third_refinery(v, power_margin):
    """A narrow financing exception, not a guarantee of safety or payback.

    Existing six-tank financing remains unchanged. Before that point, only
    invest behind healthy home armor with a long remaining working window.
    Missing terrain retains the native-placement fallback; supplied terrain
    must not contradict a reachable, screened site and nearby resource hint.
    Initial resource cells do not establish that any ore remains there.
    """
    facts = [b for b in v.buildings if _type(b) == 'fact']
    refs = [b for b in v.buildings if _type(b) == 'proc']
    if (getattr(v, 'profile', 'balanced') != 'eco_guard'
            or len(facts) != 1 or len(refs) != 2 or v.remaining < 360
            or sum(_type(u) == 'harv' and u.get('idle') is False for u in v.units) < 4
            or (getattr(v, 'strategy', {}) or {}).get('recover_until', 0) > v.now):
        return False
    # Explicit activity avoids financing growth while the current ore line
    # is idle. Activity alone still does not prove successful ore deliveries.
    anchor = v.cell(facts[0])
    cover = [u for u in v.units if _type(u) in TANKS
             and u.get('hp', 0) >= 70 and _dist(v.cell(u), anchor) <= 22]
    if len(cover) < 5:
        return False
    raw_power = v.item_rule('proc').get('power')
    drain = max(0, -float(raw_power)) if isinstance(raw_power, (int, float)) else 30
    if not power_margin >= drain + 10:
        return False
    site = _place_at(v, 'proc')
    protected = [anchor] + [v.cell(b) for b in refs]
    if site is not None:
        protected.append(tuple(site))
    # Engineers can capture and MCVs can establish forward production. They
    # are support elsewhere, but still deny this discounted growth window.
    growth_support = SUPPORT - {'e6', 'mcv'}
    if any(_type(e) not in growth_support and any(_dist(v.cell(e), p) <= 30 for p in protected)
           for e in v.enemies):
        return False
    if any(not safe_cell(v, p) or blockers(v, anchor, p) for p in protected):
        return False
    if v.map_info.get('layout') is not None:
        # Adaptation validates and bounds the supplied terrain. No new BFS is
        # needed on maps without known towers; at most eight resource routes
        # are inspected when remembered towers require detailed screening.
        from .maps import route_safe
        ground = getattr(v, 'navigation', {}).get('parents', {})
        if site is None or tuple(site) not in ground or not route_safe(v, site, start=anchor):
            return False
        ore = sorted((p for p in v.ore_cells if tuple(p) in ground and _dist(p, site) <= 12),
                     key=lambda p: (_dist(p, site), p))[:8]
        if not any(safe_cell(v, p) and route_safe(v, p, start=site) for p in ore):
            return False
    return True


def _expansion_window(v, memory):
    """Experimental feasibility margin, NOT a measured return-on-investment.

    Use live build times and remaining time. Travel speed and the 150-second
    productive window are conservative hypotheses to validate in self-play.
    The normal competition profile retains its existing timing unchanged.
    """
    if getattr(v, 'profile', 'balanced') != 'eco_guard':
        return v.now > 260 and v.remaining > 330
    site = _expansion_site(v, memory)
    if not site:
        return False
    screen = [u for u in v.units if _type(u) not in SUPPORT
              and _type(u) not in {'medi', 'mech', 'spy', 'thf', 'tran'}]
    map_plan = getattr(v, 'map_plan', {})
    if sum(v.cost(_type(u)) * max(0, float(u.get('hp', 100))) / 100 for u in screen) < map_plan.get('expansion_screen', 1800):
        return False
    seconds = 0.
    for item, fallback in (('mcv', 60.), ('proc', 33.6), ('powr', 7.2)):
        value = v.item_rule(item).get('build_time_s', fallback)
        seconds += float(value) if isinstance(value, (int, float)) and value > 0 else fallback
    travel = _dist(v.base, site)
    if map_plan.get('active'):
        travel = getattr(v, 'navigation', {}).get('distances', {}).get(tuple(site))
        if travel is None:
            return False
    seconds += travel / .5 + map_plan.get('productive_window', 150.)
    memory['expansion_required_seconds'] = round(seconds, 1)
    return v.remaining > seconds


def _mcv_withdraw(v, mcv, emit):
    """Do not turn an unsafe destination into an unsafe retreat order."""
    ident, current = mcv['id'], v.cell(mcv)
    destination = None
    if getattr(v, 'map_plan', {}).get('active'):
        from .maps import route_safe, escape_cell
        if route_safe(v, v.base, start=current):
            destination = v.base
        elif not safe_cell(v, current):
            destination = escape_cell(v, current, v.base)
    elif not blockers(v, current, v.base):
        destination = v.base
    order = ({'cmd': 'move', 'units': [ident], 'to': v.clamp(destination)}
             if destination is not None else {'cmd': 'stop', 'units': [ident]})
    emit(order, key=f'mcv-safety-{ident}', cooldown=8)


def _mcv_orders(v, memory, emit):
    mcvs = [u for u in v.units if _type(u) == "mcv"]
    for mcv in mcvs[:2]:
        ident = mcv["id"]
        if not v.count("fact"):
            # If the start cell is blocked, a later observation will let us
            # shift one clear cell and retry instead of spamming deployment.
            attempts = memory.get("deploy_attempts", {}).get(ident, 0)
            if attempts >= 2 and mcv.get("idle"):
                offsets = ((3, 0), (0, 3), (-3, 0), (0, -3))
                dx, dy = offsets[(attempts // 2 - 1) % len(offsets)]
                x, y = v.cell(mcv)
                if emit({"cmd": "move", "units": [ident], "to": v.clamp((x+dx, y+dy))},
                        key=f"mcv-unblock-{ident}", cooldown=12):
                    memory.setdefault("deploy_attempts", {})[ident] = attempts + 1
                    continue
            if emit({"cmd": "deploy", "units": [ident]}, key=f"deploy-{ident}", cooldown=6):
                memory.setdefault("deploy_attempts", {})[ident] = attempts + 1
            continue
        site = memory.get(f"mcv-site-{ident}") or _expansion_site(v, memory)
        if not site:
            # A purchased MCV must not sit helplessly if its chosen mine is lost.
            if mcv.get("idle"):
                emit({"cmd": "deploy", "units": [ident]}, key=f"deploy-{ident}", cooldown=8)
            continue
        memory[f"mcv-site-{ident}"] = site
        # A per-MCV destination persists longer than the shared 25-second site
        # cache. Recheck it against new contacts as well: a straight segment
        # can miss a tower on the only traversable route around a river.
        unsafe_route = False
        if getattr(v, 'map_plan', {}).get('active'):
            from .maps import route_safe
            unsafe_route = not route_safe(v, site, start=v.cell(mcv))
        unsafe_site = any(_dist(site, v.cell(e)) < 20 for e in _enemies(v))
        if unsafe_route or unsafe_site or blockers(v,v.cell(mcv),site):
            memory.pop(f"mcv-site-{ident}",None)
            memory.pop(f"mcv-moving-{ident}",None)
            memory["expansion_site"] = None
            memory["site_checked_at"] = -1000
            _mcv_withdraw(v, mcv, emit)
            continue
        if any(_dist(v.cell(mcv), v.cell(e)) < 12 for e in _enemies(v) if _type(e) not in SUPPORT):
            memory.pop(f"mcv-moving-{ident}", None)
            _mcv_withdraw(v, mcv, emit)
            continue
        if _dist(v.cell(mcv), site) <= 3:
            emit({"cmd": "deploy", "units": [ident]}, key=f"deploy-{ident}", cooldown=6)
        elif mcv.get("idle") or not memory.get(f"mcv-moving-{ident}"):
            if emit({"cmd": "move", "units": [ident], "to": v.clamp(site)},
                    key=f"mcv-expand-{ident}", cooldown=10):
                memory[f"mcv-moving-{ident}"] = True


def plan(v, memory: dict, emit) -> None:
    """Add economic orders; shared core owns validation, limits, and retry state."""
    _mcv_orders(v, memory, emit)
    available = v.available
    cash = max(0, float(v.econ.get("cash", 0) or 0) + float(v.econ.get("ore", 0) or 0))
    threats = _near_base(v)
    threat_value = sum(v.cost(_type(e)) for e in threats)
    urgent = threat_value >= 400
    buildings = Counter(_type(b) for b in v.buildings)
    units = Counter(_type(u) for u in v.units)
    fortified = bool(fortifications(v))
    map_plan = getattr(v, 'map_plan', {})
    armor_focus = getattr(v, 'profile', 'balanced') == 'eco_guard'
    tanks = sum(units[t] for t in TANKS)
    tank_types = ('3tnk', '2tnk', '1tnk', '4tnk', 'ttnk') if armor_focus else ('3tnk', '2tnk', '1tnk')
    tank_item = next((t for t in tank_types if t in available), None)
    enemy_tanks = sum(v.cost(_type(e)) for e in _enemies(v) if _type(e) in TANKS)

    # Placement always outranks more production. Leaving a finished structure
    # in its queue blocks the entire category.
    ready = {str(p.get("item", "")).lower() for p in v.production if p.get("ready")
             and p.get('queue', v.queue(str(p.get('item', '')).lower())) in {'Building', 'Defense'}}
    for hint in v.hints.get("place", []):
        if isinstance(hint, str):
            ready.add(hint.lower())
        elif isinstance(hint, dict) and hint.get("item"):
            ready.add(str(hint["item"]).lower())
    for item in sorted(ready):
        if not item or v.queue(item) not in {'Building', 'Defense'}:
            continue
        order = {"cmd": "place", "item": item}
        at = _place_at(v, item)
        if at is not None:
            order["at"] = at
        emit(order, key=f"place-{item}", cooldown=2)

    if armor_focus:
        from .harvesters import plan as recover_harvesters
        recover_harvesters(v, memory.setdefault('harvesters', {}), emit)
    else:
        # Preserve the experimental baseline's original native resume policy.
        idle_harv = [u["id"] for u in v.units if _type(u) == "harv" and u.get("idle")]
        if idle_harv and buildings["proc"]:
            emit({"cmd": "harvest", "units": idle_harv[:50]}, key="idle-miners", cooldown=8)
    for b in sorted(v.buildings, key=lambda x: x.get("hp", 100))[:3]:
        hp = b.get("hp", 100)
        if hp < 80 and not b.get("repairing") and (cash > 250 or _type(b) in {"fact", "proc"}):
            emit({"cmd": "repair", "building": b["id"], "on": True},
                 key=f"repair-{b['id']}", cooldown=6)

    if not buildings["fact"]:
        return

    barracks = "tent" if "tent" in available or buildings["tent"] else "barr"
    rax_count = buildings["tent"] + buildings["barr"]
    refs = buildings["proc"]
    harvesters = max(units["harv"], int(v.econ.get("harvesters", 0) or 0))
    power_provided = float(v.econ.get("power_provided", 0) or 0)
    power_drained = float(v.econ.get("power_drained", 0) or 0)
    power_margin = power_provided - power_drained
    tank_start = (max(250, min(500, v.cost(tank_item) * .45)) if harvesters >= 2 else v.cost(tank_item)) if tank_item else 0
    tank_budget = tank_start + 100 if armor_focus and tank_item else 0
    construction = None

    # Stable two-refinery opening. Avoid researching everything before making
    # a sustainable army. Power reserve covers the next production building.
    if not buildings["powr"] and not buildings["apwr"]:
        construction = "powr"
    elif power_margin < (0 if not rax_count else 30):
        construction = "apwr" if "apwr" in available and cash > 650 else "powr"
    elif rax_count == 0:
        construction = barracks
    elif refs < 2:
        construction = "proc"
    elif not buildings["weap"]:
        construction = "weap"
    elif armor_focus and not buildings['fix'] and 'fix' in available and harvesters >= 2:
        # Medium/heavy tanks require the service depot. Do not spend all income
        # on additional barracks or support vehicles while it is missing.
        construction = 'fix'
    elif fortified and not buildings["dome"] and "dome" in available and harvesters >= 3 and cash >= 700 and not urgent and (not armor_focus or tanks >= 3):
        # Ranged siege answers fortifications; more barracks do not.
        construction = "dome"
    elif not buildings["fix"] and refs >= 2 and (cash >= 850 or harvesters >= 4):
        construction = "fix"
    elif refs < 3 and (cash >= 800 or harvesters >= 4) and not urgent and (not armor_focus or tanks >= 3):
        construction = "proc"
    elif buildings["fact"] >= 2 and refs < 4 and cash >= 600:
        construction = "proc"
    elif armor_focus and buildings['weap'] < 2 and harvesters >= 5 and tanks >= 4 and cash > 1600 and not urgent:
        construction = 'weap'
    elif rax_count < (2 if armor_focus else 3) and harvesters >= 3 and cash >= (2000 if armor_focus else 500) and (not armor_focus or tanks >= 6):
        construction = barracks
    elif not buildings["dome"] and buildings["fix"] and harvesters >= 4 and cash >= 1100:
        construction = "dome"
    elif not armor_focus and rax_count < 5 and refs >= 3 and harvesters >= 5 and cash > 1800:
        construction = barracks
    elif buildings["weap"] < 2 and harvesters >= 5 and cash > 2800:
        construction = "weap"
    elif not armor_focus and rax_count < 7 and harvesters >= 6 and cash > 3000:
        construction = barracks
    elif power_margin < 60 and cash > 1500:
        construction = "apwr" if "apwr" in available else "powr"

    if (getattr(v, 'profile', 'balanced') == 'eco_guard' and v.remaining < 150
            and construction not in {'powr', 'apwr'} and refs >= 2 and buildings['weap']):
        # Do not start late economic/production infrastructure whose useful
        # operating window is tiny; replacement infrastructure stays allowed.
        construction = None
    if construction not in available:
        construction = None
    optional_construction = ((construction == 'proc' and refs >= 2)
                             or (construction == 'dome' and not fortified)
                             or (construction in {'tent', 'barr'} and rax_count > 0))
    optional_budget = v.cost(construction) + tank_budget
    if construction == 'proc' and (tanks >= 6 or _guarded_third_refinery(v, power_margin)):
        # After establishing the tank core, let a refinery use progressive
        # payment again. Otherwise a low-income base could postpone growth
        # forever while every deposit funds its next tank. A screened third
        # refinery may start one tank earlier; all other growth keeps the
        # original full-cost reserve until the six-tank core is established.
        optional_budget = tank_budget
    if (armor_focus and tank_item and optional_construction
            and cash < optional_budget):
        # Do not let another expansion/tech/support queue consume the next
        # tank's operating cash. Power, the first factory, tank tech and a
        # second factory retain their infrastructure priority.
        construction = None
    if construction and construction not in {"powr","apwr"} and "powr" in available:
        raw_power = v.item_rule(construction).get("power")
        next_drain = max(0,-float(raw_power)) if isinstance(raw_power,(int,float)) else (
            40 if construction=="dome" else 20 if construction in {"tent","barr"} else 30)
        if power_margin < next_drain+10:
            construction = "apwr" if "apwr" in available and cash>650 else "powr"
    recovering = refs > 0 and harvesters == 0 and "harv" in available
    if recovering and power_margin >= 0:
        # An existing factory can replace the miner much more cheaply than
        # buying another refinery. Do not spend its recovery budget elsewhere.
        construction = None
    build_budget = 0
    building_reserve = 0
    if construction and not v.queue_count("Building"):
        price = v.cost(construction)
        # Production is paid progressively. Start essential infrastructure
        # below full price when harvesters can pay the remaining cost.
        minimum = min(price, 200 if construction in {"powr", "apwr"} else 400)
        building_reserve = minimum
        if cash >= minimum or (harvesters and construction in {"proc", "powr", "apwr"}):
            if emit({"cmd": "build", "item": construction}, key=f"build-{construction}", cooldown=4):
                build_budget = min(price, max(0, cash-300))
                building_reserve = 0

    # One affordable home defense can cover the economy while the army
    # contains a fortified opponent. Do not turn this into tower spam.
    defenses = sum(buildings[t] for t in DEFENSE)
    cover_economy = (fortified or getattr(v, 'profile', 'balanced') == 'eco_guard') and refs >= map_plan.get('defense_refs', 2) and harvesters >= map_plan.get('defense_miners', 3) and cash-build_budget >= map_plan.get('defense_cash', 900) and power_margin >= 30
    if (urgent or cover_economy) and defenses < (2 if threat_value > 2000 else 1) and not v.queue_count("Defense"):
        defense_types = ('gun', 'tsla') if armor_focus and enemy_tanks else ('pbox', 'ftur', 'hbox', 'gun', 'tsla')
        candidate = next((t for t in defense_types if t in available), None)
        if armor_focus and candidate:
            live_power = v.item_rule(candidate).get('power')
            drain = max(0, -live_power) if isinstance(live_power, (int, float)) else {'tsla': 150, 'gun': 40, 'ftur': 40}.get(candidate, 0)
            if power_margin < drain + 10:
                candidate = None
        defense_budget = min(350, v.cost(candidate)) if candidate else 0
        if armor_focus and tank_item and not urgent and candidate:
            defense_budget = v.cost(candidate) + tank_budget + build_budget
        if candidate and cash >= defense_budget:
            emit({"cmd": "build", "item": candidate}, key=f"build-{candidate}", cooldown=5)

    # Queue a few units at a time, preserving the ability to respond to armor
    # or aircraft. The default 2:1 infantry mix follows the official guide.
    infantry_queued = v.queue_count("Infantry")
    target_harvesters = min(8, max(4, refs * 2))
    future_harvesters = harvesters + _queued(v, "harv") + _queued(v, "proc")
    miner_reserve = (300 if buildings["weap"] and "harv" in available
                     and future_harvesters < target_harvesters
                     and not v.queue_count("Vehicle") and not urgent else 0)
    infantry_reserved = 0
    infantry_spent = 0
    # Production is paid progressively: protect the start/operating budget of
    # a tank instead of letting another cheap rifle consume every small deposit.
    armor_reserve = tank_budget if armor_focus and tank_item and not v.queue_count('Vehicle') else 0
    if armor_focus and any(p.get('item') in TANKS for p in v.production):
        armor_reserve = max(200, tank_start)
    # Leave an operating buffer during containment. This is not a spending
    # ceiling: surplus income still funds infantry, vehicles and expansion.
    operating_reserve = 350 if fortified and not urgent and harvesters >= 2 else 0
    if rax_count and infantry_queued < 2 and "e1" in available and not recovering:
        early_cap = map_plan.get('early_infantry_cap', 6) if refs == 0 else map_plan.get('second_ref_infantry_cap', 10) if refs < 2 else min(24, 10 + 2*tanks) if armor_focus else 10000
        economical_opening = (not map_plan.get('active')
                              or map_plan.get('style') == 'long-route-economy')
        if armor_focus and refs == 1 and not urgent and economical_opening:
            # Preserve an initial screen while financing the second refinery
            # and factory before adding another group of rifles. Keep the
            # larger screen explicitly selected for a guarded/close map.
            early_cap = min(early_cap, 6)
        current_inf = sum(units[t] for t in ("e1", "e3", "e2", "e4", "shok"))
        air_threat = any(_type(e) in {'heli', 'hind', 'mig', 'yak'} for e in threats)
        emergency_rockets = armor_focus and urgent and (enemy_tanks or air_threat) and units['e3'] + _queued(v, 'e3') < 4
        opening_emergency = armor_focus and urgent and not buildings['weap'] and current_inf + infantry_queued < 12
        support_shortage = armor_focus and refs >= 2 and units['e3'] + _queued(v, 'e3') < 2
        if current_inf + infantry_queued < early_cap or (urgent and not armor_focus) or emergency_rockets or opening_emergency or support_shortage:
            enemy_armor = sum(v.cost(_type(e)) for e in _enemies(v)
                              if _type(e) in {"1tnk", "2tnk", "3tnk", "4tnk", "ttnk", "heli", "hind", "mig", "yak"})
            rocket_ratio = 1.4 if enemy_armor > 1500 else 2.0
            want_rocket = (refs >= 2 or enemy_armor > 0) and (units["e3"] + _queued(v, "e3")) * rocket_ratio < units["e1"]
            item = "e3" if want_rocket and "e3" in available else "e1"
            if (support_shortage or (armor_focus and enemy_armor and units['e3'] + _queued(v, 'e3') < 4)) and 'e3' in available:
                item = 'e3'
            rifle_cap = min(6, 4 + tanks//4) if armor_focus and refs >= 2 else early_cap
            if opening_emergency:
                rifle_cap = max(rifle_cap, 12)
            if armor_focus and item == 'e1' and units['e1'] + _queued(v, 'e1') >= rifle_cap:
                item = None
            reserve = max(building_reserve, miner_reserve, operating_reserve, armor_reserve, 100 if refs >= 2 or urgent else 700)
            spendable = cash - reserve - (build_budget * 0.2)
            # Units are paid during production, not at queue insertion. A
            # rocket must not wait for $450 while cheap vehicles consume each
            # incoming $300. With two working miners, a small initial buffer
            # is enough to finance a single rocket over the following seconds.
            required = min(v.cost(item), 100) if harvesters >= 2 else v.cost(item)
            if armor_focus and tank_item:
                # Support is discretionary once tanks are available. Reserve
                # its full cost, not merely its first production installment,
                # so a rocket order cannot preempt the next tank's start.
                required = v.cost(item)
            infantry_reserved = reserve + required
            if item and (spendable >= required or (urgent and cash >= 100 and (not armor_focus or emergency_rockets or opening_emergency))):
                batch = 1 if armor_focus or item == "e3" or cash < 1000 else min(3, max(1, int(spendable // max(1, v.cost(item)))))
                batch = min(batch, max(1, int((v.raw.get("limits") or {}).get("max_train_count", 10))))
                if emit({"cmd": "train", "item": item, "count": batch}, key="train-Infantry", cooldown=3):
                    infantry_reserved = min(v.cost(item) * batch, cash)
                    infantry_spent = infantry_reserved

    if buildings["weap"] and v.queue_count("Vehicle") == 0:
        vehicle = None
        # Replacement miners outrank armor; never turn a lost economy into
        # permanent military spam. A refinery under construction brings one.
        if "harv" in available and future_harvesters < target_harvesters and (not urgent or harvesters < 2):
            vehicle = "harv"
        elif (buildings["fact"] < 2 and not units["mcv"] and "mcv" in available
              and harvesters >= 4 and cash >= 2000 and _expansion_window(v, memory)
              and (not armor_focus or (tanks >= 6 and cash >= v.cost('mcv') + tank_budget))
              and not urgent and _expansion_site(v, memory)):
            vehicle = "mcv"
        else:
            artillery = units["arty"] + units["v2rl"]
            screen = sum(units[t] for t in ("e1","e3","e2","e4","shok"))
            want_siege = fortified and (tanks >= 3 if armor_focus else screen >= 8 or tanks >= 2) and artillery < 2
            if want_siege or (not armor_focus and tanks >= 2 and artillery < min(4, 1 + tanks // 3)):
                vehicle = next((t for t in ("arty", "v2rl") if t in available), None)
            if vehicle is None:
                vehicle = tank_item
                if vehicle is None and (not armor_focus or 'fix' not in available):
                    vehicle = next((t for t in ('apc', 'ftrk', 'jeep') if t in available), None)
        if vehicle:
            if vehicle == "harv":
                required = v.cost(vehicle) if recovering else 300
            elif armor_focus and vehicle in TANKS:
                required = tank_start + max(building_reserve, operating_reserve, infantry_spent, 100)
                if urgent and harvesters >= 2:
                    required = tank_start
            else:
                # Recurring low-tier armor must not preempt the service depot
                # or every rocket purchase. Reserve the pending building and
                # infantry buffer; spend a full vehicle budget in peacetime.
                required = v.cost(vehicle) + max(building_reserve, infantry_reserved, operating_reserve, 150)
                if urgent:
                    required = max(200, v.cost(vehicle) * 0.45)
            if cash >= required:
                emit({"cmd": "train", "item": vehicle, "count": 1}, key="train-Vehicle", cooldown=4)

    # Reinforcements assemble safely instead of walking alone to the enemy.
    for b in v.buildings:
        if _type(b) not in {"barr", "tent", "weap"} or b.get("rally"):
            continue
        x, y = v.base
        direction = v.enemy_base
        length = max(1, _dist((x, y), direction))
        point = v.clamp((round(x + 6*(direction[0]-x)/length), round(y + 6*(direction[1]-y)/length)))
        if map_plan.get('active'):
            from .maps import nearest_reachable
            point = list(nearest_reachable(v, point) or point)
        emit({"cmd": "rally", "building": b["id"], "to": point}, key=f"rally-{b['id']}", cooldown=20)
