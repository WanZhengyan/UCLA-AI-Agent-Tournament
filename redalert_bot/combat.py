"""Ground army controller: grouped pressure, local defence, and survival.

This deliberately uses the engine's attack-move targeting. Replacing its orders
on every observation interrupts movement/combat, so orders persist until units
idle or a meaningful tactical change occurs.
"""
from __future__ import annotations

from .common import NONCOMBAT, alive, cell, distance
from .strategy import STATIC, SIEGE, TANKS, observe, fortifications, blockers, safe_cell, radius, weapon_range

AIR = {'mig', 'yak', 'heli', 'hind', 'tran', 'badr', 'u2'}
PASSIVE = NONCOMBAT | AIR | {'dtruck', 'ant', 'ant1', 'ant2', 'ant3'}
WALLS = {'sbag', 'fenc', 'brik', 'cycl', 'wood'}
ECONOMIC = {'harv', 'proc', 'weap', 'fact', 'mcv', 'powr', 'apwr', 'barr', 'tent'}


def _combat(a):
    return alive(a) and a.get('type', '') not in PASSIVE


def _centre(actors):
    return (sum(cell(a)[0] for a in actors) / len(actors),
            sum(cell(a)[1] for a in actors) / len(actors))


def _value(v, actors, *, structures=False):
    total = 0.0
    for a in actors:
        hp = max(0.2, float(a.get('hp', 100)) / 100)
        typ = a.get('type', '')
        # Price is only a coarse local strength estimate, not a damage model.
        multiplier = 2.0 if structures and typ in STATIC else 1.0
        total += v.cost(typ) * (0.45 + 0.55 * hp) * multiplier
    return total


def _walkable(v, destination):
    """Keep goals on land when a public terrain layout is available."""
    if getattr(v, 'map_plan', {}).get('active'):
        from .maps import nearest_reachable
        reachable = nearest_reachable(v, destination)
        if reachable is not None:
            return reachable
    target = tuple(v.clamp(destination))
    layout = v.map_info.get('layout') or {}
    rows = layout.get('rows') or []
    if not rows:
        return target
    ox, oy = layout.get('origin') or v.bounds[:2]

    def free(p):
        x, y = p[0] - ox, p[1] - oy
        return 0 <= y < len(rows) and 0 <= x < len(rows[y]) and rows[y][x] not in '~^T#'

    if free(target):
        return target
    for radius in range(1, 9):
        candidates = [(target[0] + x, target[1] + y)
                      for x in range(-radius, radius + 1)
                      for y in range(-radius, radius + 1)
                      if max(abs(x), abs(y)) == radius]
        for p in sorted(candidates, key=lambda x: distance(x, target)):
            if tuple(v.clamp(p)) == p and free(p):
                return p
    return target


def _matchup_value(v, actors, opponents, *, structures=False):
    """Conservative type-aware gate, NOT a damage simulator or win predictor.

    Rifles/anti-infantry support cannot substitute for a tank/rocket screen
    merely because enough of them add up to the same purchase price.
    """
    if getattr(v, 'profile', 'balanced') != 'eco_guard':
        return _value(v, actors, structures=structures)
    total = sum(v.cost(a.get('type')) for a in opponents)
    armor = sum(v.cost(a.get('type')) for a in opponents if a.get('type') in TANKS)
    armor_share = armor / total if total else 0.
    result = 0.
    for actor in actors:
        typ = actor.get('type')
        penalty = .85 if typ in {'e1', 'dog', 'jeep', 'apc', 'pbox', 'hbox'} else .65 if typ in {'e2', 'e4', 'ftur', 'arty'} else 0.
        result += _value(v, [actor], structures=structures) * (1 - penalty * armor_share)
    return result


def _rear(v):
    dx, dy = v.enemy_base[0] - v.base[0], v.enemy_base[1] - v.base[1]
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    return _walkable(v, (v.base[0] - 5 * dx / length, v.base[1] - 5 * dy / length))


def _stage(v):
    if getattr(v, 'map_plan', {}).get('guard_cell'):
        return _walkable(v, v.map_plan['guard_cell'])
    dx, dy = v.enemy_base[0] - v.base[0], v.enemy_base[1] - v.base[1]
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    return _walkable(v, (v.base[0] + 7 * dx / length, v.base[1] + 7 * dy / length))


def _issue(v, state, emit, actors, destination, mode, urgent=False, command='attack_move', target=None):
    """Return IDs actually submitted. Never assume a refused emit succeeded."""
    if not actors:
        return set()
    destination = _walkable(v, destination)
    history = state.setdefault('unit_orders', {})
    eligible = []
    for actor in actors:
        ident = actor['id']
        previous = history.get(str(ident))
        age = v.now - previous['at'] if previous else 10_000
        changed = previous is None or previous['mode'] != mode or distance(previous['goal'], destination) > 8
        # Active orders normally continue without interference. The 40 s rescue
        # handles a unit stuck in a stale engine activity or an old objective.
        safety_change = changed and mode in {'contain', 'retreat', 'regroup', 'defend', 'hold', 'siege-screen'}
        if previous is None or safety_change or (urgent and age >= 3) or (actor.get('idle', False) and age >= 6) or (changed and age >= 12) or age >= 40:
            # Do not repeatedly rally units already at the gathering point.
            if mode in {'gather', 'hold', 'reserve', 'contain', 'siege-screen'} and distance(cell(actor), destination) <= 2 and not changed:
                continue
            eligible.append(actor)
    submitted = set()
    group_size = min(40, max(1, int((v.raw.get('limits') or {}).get('max_units_per_order', 50))))
    for offset in range(0, len(eligible), group_size):
        group = eligible[offset:offset + group_size]
        ids = [a['id'] for a in group]
        key = 'combat:' + mode + ':' + ','.join(str(x) for x in ids)
        order = {'cmd': command, 'units': ids}
        if command == 'attack' and target is not None:
            order['target'] = target
        else:
            order['to'] = list(destination)
        if not emit(order, key=key, cooldown=3.0):
            break
        for actor in group:
            history[str(actor['id'])] = {'at': v.now, 'goal': list(destination), 'mode': mode}
            submitted.add(actor['id'])
    return submitted


def _remember_buildings(v, state, army):
    known = state.setdefault('enemy_sites', {})
    visible = {str(a['id']) for a in v.enemy_buildings if a.get('type') not in WALLS}
    for a in v.enemy_buildings:
        if a.get('type') not in WALLS:
            known[str(a['id'])] = {'cell': list(cell(a)), 'type': a.get('type'), 'seen': v.now}
    # Only erase an old contact when a friendly unit can inspect its cell.
    for ident, contact in list(known.items()):
        if ident not in visible and any(distance(cell(a), contact['cell']) <= 4 for a in army):
            del known[ident]
    if any(distance(cell(a), v.enemy_base) < 7 for a in army) and not any(distance(cell(a), v.enemy_base) < 12 for a in v.enemy_buildings):
        state['spawn_checked'] = True


def _objective(v, state, army):
    centre = _centre(army)
    enemy_defences = [a for a in v.enemy_buildings if a.get('type') in STATIC]
    targets = [a for a in v.enemy_buildings if a.get('type') not in WALLS]
    targets += [a for a in v.enemies if a.get('type') in {'harv', 'mcv'} and distance(cell(a), centre) < 24]
    if targets:
        exposed = [a for a in targets if not blockers(v, centre, cell(a))]
        if exposed:
            targets = exposed
        def priority(a):
            typ = a.get('type', '')
            near_defences = sum(1 for d in enemy_defences if d['id'] != a['id'] and distance(cell(a), cell(d)) < 8)
            bonus = {'mcv': 14, 'harv': 12, 'proc': 9, 'weap': 8, 'fact': 7, 'barr': 5, 'tent': 5, 'powr': 4, 'apwr': 4}.get(typ, 0)
            return distance(cell(a), centre) + 6 * near_defences - bonus - (100 - a.get('hp', 100)) / 20
        return _walkable(v, cell(min(targets, key=priority)))
    contacts = list(state.get('enemy_sites', {}).values())
    if contacts:
        return _walkable(v, min(contacts, key=lambda x: distance(x['cell'], centre))['cell'])
    if not state.get('spawn_checked'):
        return v.enemy_base
    # Enemy may have expanded or moved its MCV. Sweep land sectors instead of
    # standing forever at the empty original spawn.
    visited = state.setdefault('sweep_visited', [])
    x, y, w, h = v.bounds
    points = [_walkable(v, (x + w * fx, y + h * fy))
              for fx, fy in ((.15, .15), (.5, .15), (.85, .15), (.85, .5),
                             (.85, .85), (.5, .85), (.15, .85), (.15, .5), (.5, .5))]
    for p in points:
        if distance(p, centre) < 7 and list(p) not in visited:
            visited.append(list(p))
    candidates = [p for p in points if list(p) not in visited and distance(p, v.base) > 13]
    if not candidates:
        state['sweep_visited'] = []
        candidates = [p for p in points if distance(p, v.base) > 13] or [v.enemy_base]
    return min(candidates, key=lambda p: distance(p, centre))


def _safe_hold(v, reference, nearest, margin=4):
    """Find a nearby goal outside ALL remembered tower firing zones."""
    from math import cos, sin, pi
    bx, by = cell(nearest)
    dx, dy = reference[0]-bx, reference[1]-by
    length = max(1., (dx*dx+dy*dy)**.5)
    r = radius(v, nearest)+margin
    preferred = (bx+r*dx/length, by+r*dy/length)
    candidates = [preferred, _stage(v), _rear(v)]
    candidates += [(bx+(r+extra)*cos(i*pi/8), by+(r+extra)*sin(i*pi/8))
                   for extra in (0, 5, 10) for i in range(16)]
    candidates = {_walkable(v, p) for p in candidates}
    candidates = [p for p in candidates if safe_cell(v, p)]
    return min(candidates, key=lambda p: distance(p, preferred)+.15*distance(p, v.base)) if candidates else _rear(v)


def _contain(v, state, emit, active, blocked):
    """Do not send a mixed blob through a tower line; screen ranged siege."""
    centre = _centre(active)
    nearest = min(blocked, key=lambda b: distance(cell(b), centre))
    goal = _safe_hold(v, centre, nearest)
    artillery = [a for a in active if a.get('type') in SIEGE]
    screens = [a for a in active if a.get('type') not in SIEGE]
    visible = {b['id'] for b in v.enemy_buildings}
    state.update(mode='contain fortifications', target=list(cell(nearest)))
    mobile = [a for a in v.enemies if _combat(a) and
              min(distance(cell(a),centre),distance(cell(a),goal))<18]
    if _matchup_value(v,mobile,active) > max(800,_matchup_value(v,active,mobile)*1.15):
        state.update(mode='retreat from bad trade',retreat_until=v.now+30,
                     retreat_goal=list(_stage(v)),wave_ids=[])
        _issue(v,state,emit,active,_stage(v),'retreat',command='move')
        return
    # Infantry/tanks stop outside the firing zone instead of escorting siege
    # into it. Defend stance prevents an automatic pursuit into the towers.
    if screens:
        _issue(v,state,emit,screens,goal,'siege-screen',command='move')
        cap = min(40,max(1,int((v.raw.get('limits') or {}).get('max_units_per_order',50))))
        for offset in range(0,len(screens),cap):
            ids = [a['id'] for a in screens[offset:offset+cap]]
            emit({'cmd':'set_stance','units':ids,'stance':'defend'},
                 key='contain-stance:'+','.join(map(str,ids)),cooldown=20)
    for gun in artillery:
        reach = weapon_range(v,gun.get('type'),12. if gun.get('type')=='arty' else 10.)
        targets = [b for b in blocked if b['id'] in visible and radius(v,b)+.5 < reach]
        target = min(targets,key=lambda b:distance(cell(gun),cell(b))) if targets else None
        if target:
            d = distance(cell(gun),cell(target))
            # Explicit attacks only while already at a safe firing distance:
            # an out-of-range attack would make the artillery walk forward.
            if 4.5 <= d <= reach-.25 and safe_cell(v,cell(gun)):
                _issue(v,state,emit,[gun],cell(target),'siege:'+str(target['id']),
                       command='attack',target=target['id'])
                state['mode'] = 'ranged siege'
                continue
            tx,ty = cell(target)
            dx,dy = centre[0]-tx,centre[1]-ty
            length = max(1.,(dx*dx+dy*dy)**.5)
            firing = _walkable(v,(tx+(reach-.7)*dx/length,ty+(reach-.7)*dy/length))
            if safe_cell(v,firing) and 4.5 <= distance(firing,cell(target)) <= reach-.25:
                _issue(v,state,emit,[gun],firing,'contain',command='move')
                continue
        _issue(v,state,emit,[gun],goal,'contain',command='move')
    state['last_mode'] = 'contain'


def _warning_scout(v, state, emit, army, threats):
    """One cheap forward lookout; the defensive policy must not remain blind."""
    goal = getattr(v, 'map_plan', {}).get('scout_cell')
    if not goal or v.now < 40 or len(army) < 8 or v.enemy_buildings:
        state.pop('warning_scout_id', None)
        return set()
    scout = next((a for a in army if a['id'] == state.get('warning_scout_id')), None)
    if (scout is None and v.now >= state.get('next_warning_scout_at', 0)
            and state.get('warning_scout_attempts', 0) < 2):
        rifles = [a for a in army if a.get('type') == 'e1' and a.get('idle', True)]
        scout = min(rifles, key=lambda a: distance(cell(a), goal)) if rifles else None
        if scout:
            state.update(warning_scout_id=scout['id'], next_warning_scout_at=v.now+90)
            state['warning_scout_attempts'] = state.get('warning_scout_attempts', 0)+1
    if scout is None:
        return set()
    from .maps import route_safe
    if (not route_safe(v, goal) or blockers(v, cell(scout), goal)
            or any(min(distance(cell(scout), cell(e)), distance(goal, cell(e))) < 9 for e in threats)):
        state.pop('warning_scout_id', None)
        state['next_warning_scout_at'] = v.now+60
        return set()  # The normal guard orders recall it with the rest of the army.
    _issue(v, state, emit, [scout], goal, 'scout-warning', command='move')
    return {scout['id']}


def plan(v, memory: dict, emit) -> None:
    state = memory.setdefault('combat', {})
    if not getattr(v,'strategy',None):
        observe(v,state.setdefault('intel',{}))
    army = [a for a in v.units if _combat(a)]
    if not army:
        state['wave_ids'] = []
        state['mode'] = 'build army'
        return
    own_ids = {a['id'] for a in army}
    state['unit_orders'] = {k: val for k, val in state.get('unit_orders', {}).items() if int(k) in own_ids}
    wave_ids = set(state.get('wave_ids', [])) & own_ids
    _remember_buildings(v, state, army)
    threats = [a for a in v.enemies if _combat(a)]
    important_assets = [a for a in v.buildings if a.get('type') in {'fact', 'proc', 'weap', 'tent', 'barr'}]
    important_assets += [a for a in v.units if a.get('type') == 'harv']
    home_threats = [a for a in threats if distance(cell(a), v.base) <= 21 or any(distance(cell(a), cell(b)) <= 12 for b in important_assets)]
    # Enemy aircraft should attract rocket troops rather than rifles/tanks.
    home_air = [a for a in v.enemies if a.get('type') in {'mig', 'yak', 'heli', 'hind'} and distance(cell(a), v.base) < 20]
    if home_air:
        rockets = [a for a in army if a.get('type') in {'e3', 'ftrk'} and min(distance(cell(a), cell(e)) for e in home_air) < 9]
        if rockets:
            target = min(home_air, key=lambda e: distance(cell(e), v.base))
            _issue(v, state, emit, rockets, cell(target), 'anti-air', urgent=True)
            # Keep both newly submitted and still-active AA orders separate
            # from ground groups. The shared emitter rejects an entire group
            # if even one actor already received movement in this batch.
            # Retain the assignment on following frames too, until the
            # aircraft leaves, so an unchanged AA order is not recalled home.
            aa_ids = {a['id'] for a in rockets
                      if state.get('unit_orders', {}).get(str(a['id']), {}).get('mode') == 'anti-air'}
            army = [a for a in army if a['id'] not in aa_ids]
            wave_ids -= aa_ids
            state['wave_ids'] = list(wave_ids)
            if not army:
                state.update(mode='defend against aircraft', last_mode='anti-air')
                return
    balance = float(v.military.get('kills_cost', 0)) - float(v.military.get('deaths_cost', 0))
    if (0 < v.remaining <= 75 and balance > 0 and not home_threats
            and getattr(v, 'profile', 'balanced') != 'eco_guard'):
        state['mode'] = 'protect lead'
        # First disengage instead of stopping to trade on the journey home.
        # Once idle at home the engine's normal defensive stance still fires.
        _issue(v, state, emit, army, _rear(v), 'hold', urgent=state.get('last_mode') != 'hold', command='move')
        state['last_mode'] = 'hold'
        return
    if home_threats:
        target = min(home_threats, key=lambda a: distance(cell(a), v.base))
        nearby_enemies = [a for a in home_threats if distance(cell(a), cell(target)) <= 13]
        local = [a for a in army if distance(cell(a), cell(target)) <= 26 or a['id'] not in wave_ids]
        # Commit the distant army only for a substantial incursion, not a scout.
        if _matchup_value(v, local, nearby_enemies) < _matchup_value(v, nearby_enemies, local) * 1.15:
            local = army
        defenders = [a for a in v.buildings if a.get('type') in STATIC and distance(cell(a), cell(target)) < 12]
        friendly = _matchup_value(v, local, nearby_enemies) + _matchup_value(v, defenders, nearby_enemies, structures=True)
        can_engage = friendly >= _matchup_value(v, nearby_enemies, local) * (.95 if getattr(v, 'profile', 'balanced') == 'eco_guard' else .85)
        goal = cell(target) if can_engage else _rear(v)
        command = 'move' if not can_engage and getattr(v, 'profile', 'balanced') == 'eco_guard' else 'attack_move'
        _issue(v, state, emit, local, goal, 'defend', urgent=True, command=command)
        used = {a['id'] for a in local}
        wave_ids -= used
        state['wave_ids'] = list(wave_ids)
        state['mode'] = 'defend economy'
        state['last_mode'] = 'defend'
        # Preserve the rest of an already advancing army's current orders.
        return
    if (getattr(v,'strategy',{}) or {}).get('recover_until',0) > v.now and v.remaining > 45:
        state.update(mode='recover after bad exchange',wave_ids=[])
        _issue(v,state,emit,army,_stage(v),'regroup',command='move')
        return
    if state.get('retreat_until', -1) > v.now:
        state['mode'] = 'regroup'
        _issue(v, state, emit, army, state.get('retreat_goal', _stage(v)), 'regroup', command='move')
        return

    if getattr(v, 'profile', 'balanced') == 'eco_guard':
        # An experimental defensive-economic profile. It knows ONLY this
        # seat's own observation, never the other self-play worker's trace.
        # A positive own trade balance is a heuristic, not an omniscient lead.
        desperate = balance < 0 and v.remaining <= min(180, (v.now + v.remaining) * .25)
        armor_ready = sum(a.get('type') in TANKS and a.get('hp', 100) >= 50 for a in army) >= 3
        economic_targets = [a for a in v.enemy_buildings + v.enemies
                            if a.get('type') in ECONOMIC
                            and distance(cell(a), v.base) < 35
                            and not blockers(v, _centre(army), cell(a))]
        nearby_hostiles = [a for a in threats if distance(cell(a), _centre(army)) < 18]
        opportunity = bool(economic_targets) and armor_ready and _matchup_value(v, army, nearby_hostiles) > max(1800, _matchup_value(v, nearby_hostiles, army) * 1.8)
        if not (desperate and armor_ready) and not opportunity:
            # Cover separate refineries with nearby defenders; keep the bulk
            # behind a single front instead of scattering across every miner.
            state.update(mode='guard economy', wave_ids=[], last_mode='hold')
            scouting = _warning_scout(v, state, emit, army, threats)
            remaining_army = [a for a in army if a['id'] not in scouting]
            outposts = [b for b in v.buildings if b.get('type') == 'proc'
                        and 15 < distance(cell(b), v.base) < 50]
            for outpost in outposts[:2]:
                guards = sorted(remaining_army, key=lambda a: distance(cell(a), cell(outpost)))[:max(0, min(4, len(remaining_army)//4))]
                goal = _walkable(v, cell(outpost))
                if guards and safe_cell(v, goal):
                    _issue(v, state, emit, guards, goal, 'hold', command='move')
                    used = {a['id'] for a in guards}
                    remaining_army = [a for a in remaining_army if a['id'] not in used]
            goal = _stage(v)
            if not safe_cell(v, goal):
                goal = _safe_hold(v, v.base, min(fortifications(v), key=lambda b: distance(cell(b), v.base)))
            _issue(v, state, emit, remaining_army, goal, 'hold', command='move')
            group_size = min(40, max(1, int((v.raw.get('limits') or {}).get('max_units_per_order', 50))))
            for offset in range(0, len(army), group_size):
                ids = [a['id'] for a in army[offset:offset+group_size] if a.get('stance') != 'defend']
                if ids:
                    emit({'cmd':'set_stance','units':ids,'stance':'defend'},
                         key='eco-stance:'+','.join(map(str,ids)), cooldown=15)
            return

    # Scout once with a cheap rifle, but never send harvesters or a lone tank.
    scout_id = state.get('scout_id')
    scout = next((a for a in army if a['id'] == scout_id), None)
    if scout and (v.enemy_buildings or v.now > state.get('scout_until', 0)):
        scout_id = None
        state.pop('scout_id', None)
    if scout and scout_id is not None:
        if any(distance(cell(scout), cell(e)) < 7 for e in threats):
            _issue(v, state, emit, [scout], _stage(v), 'scout-retreat', urgent=True, command='move')
        else:
            scout_goal = (v.base[0] + .82 * (v.enemy_base[0] - v.base[0]), v.base[1] + .82 * (v.enemy_base[1] - v.base[1]))
            _issue(v, state, emit, [scout], scout_goal, 'scout')
    elif not state.get('scouted') and not v.enemy_buildings and v.now >= 40 and len(army) >= 5:
        rifles = [a for a in army if a.get('type') == 'e1' and a.get('idle', True)]
        if rifles:
            scout = min(rifles, key=lambda a: distance(cell(a), v.enemy_base))
            scout_id = scout['id']
            state.update(scout_id=scout_id, scouted=True, scout_until=v.now + 45)
            scout_goal = (v.base[0] + .82 * (v.enemy_base[0] - v.base[0]), v.base[1] + .82 * (v.enemy_base[1] - v.base[1]))
            _issue(v, state, emit, [scout], scout_goal, 'scout')
    # Keep a small, stable reserve near the economy. Do not recall a distant
    # winning army just to meet a numerical quota; new reinforcements fill it.
    home = [a for a in army if a.get('type') not in SIEGE and a['id'] != scout_id
            and distance(cell(a),v.base) <= 24]
    quota = min(6,max(2,len(army)//5)) if len(army)>=12 and v.remaining>90 else 0
    previous_reserve = set(state.get('reserve_ids',[]))
    reserve = sorted(home,key=lambda a:(getattr(v,'profile','balanced') == 'eco_guard' and a.get('type') in TANKS,
                                        a['id'] not in previous_reserve,distance(cell(a),v.base),a['id']))[:quota]
    reserve_ids = {a['id'] for a in reserve}
    state['reserve_ids'] = sorted(reserve_ids)
    wave_ids -= reserve_ids
    reserve_goal = _stage(v)
    if reserve and not safe_cell(v,reserve_goal):
        nearest = min(fortifications(v),key=lambda b:distance(cell(b),reserve_goal))
        reserve_goal = _safe_hold(v,v.base,nearest)
    _issue(v,state,emit,reserve,reserve_goal,'reserve')
    recruits = [a for a in army if a['id'] not in wave_ids|reserve_ids and a['id'] != scout_id]
    active = [a for a in army if a['id'] in wave_ids]
    ready = (len(recruits) >= 12 or (len(recruits) >= 8 and _value(v, recruits) >= 2000)
             or (v.now >= 130 and len(recruits) >= 9) or (v.remaining <= 90 and balance <= 0 and len(recruits) >= 4)
             or (v.remaining <= 45 and balance < 0 and len(recruits) >= 1))
    if active and len(recruits) >= 6:
        ready = True
    if ready:
        wave_ids.update(a['id'] for a in recruits)
        active.extend(recruits)
        recruits = []
        state['wave_ids'] = list(wave_ids)
    if not active:
        state['mode'] = 'gather wave'
        _issue(v, state, emit, recruits, _stage(v), 'gather')
        return

    if (getattr(v, 'profile', 'balanced') == 'eco_guard'
            and sum(a.get('type') in TANKS and a.get('hp', 100) >= 50 for a in active) < 3):
        state.update(mode='gather armored wave', wave_ids=[])
        _issue(v, state, emit, active + recruits, _stage(v), 'gather', command='move')
        return

    goal = _objective(v, state, active)
    blocked = blockers(v,_centre(active),goal)
    if blocked:
        _contain(v,state,emit,active,blocked)
        _issue(v,state,emit,recruits,_stage(v),'gather')
        return
    front = min(active, key=lambda a: distance(cell(a), goal))
    cluster = [a for a in active if distance(cell(a), cell(front)) <= 15]
    close_enemies = [a for a in threats if distance(cell(a), cell(front)) <= 12]
    close_defences = [a for a in v.enemy_buildings if a.get('type') in STATIC and distance(cell(a), cell(front)) <= 12]
    hostile = _matchup_value(v, close_enemies, cluster) + _matchup_value(v, close_defences, cluster, structures=True)
    friendly = _matchup_value(v, cluster, close_enemies + close_defences)
    armor_focus = getattr(v, 'profile', 'balanced') == 'eco_guard'
    unsafe = (hostile >= 400 and friendly < hostile * 1.25) if armor_focus else (hostile >= 1000 and hostile > friendly * 1.5)
    if unsafe and (armor_focus or v.remaining > 45):
        # Disengage toward the base. A short retreat hold prevents oscillation
        # between attack and retreat on every new observation.
        centre = _centre(cluster)
        dx, dy = v.base[0] - centre[0], v.base[1] - centre[1]
        length = max(1.0, (dx * dx + dy * dy) ** .5)
        retreat = _walkable(v, (centre[0] + min(15, length) * dx / length, centre[1] + min(15, length) * dy / length))
        _issue(v, state, emit, active, retreat, 'retreat', urgent=True, command='move')
        state.update(mode='retreat from bad trade', retreat_until=v.now + 12,
                     retreat_goal=list(retreat), wave_ids=[])
        _issue(v, state, emit, recruits, _stage(v), 'gather')
        return
    state['mode'] = 'pressure enemy'
    state['target'] = list(goal)
    # Attack-move is useful against mobile threats, but it must not be relied
    # on to destroy passive structures. Finish a visible nearby objective with
    # an explicit target order once the local fight is favourable.
    visible_targets = [a for a in v.enemy_buildings if a.get('type') not in WALLS]
    visible_targets += [a for a in v.enemies if a.get('type') in {'harv', 'mcv'}]
    focus = [a for a in visible_targets if distance(cell(a), goal) <= 3
             and min(distance(cell(u), cell(a)) for u in active) <= 8]
    firing_ids = set()
    if focus and (hostile <= friendly / 1.15 or (hostile <= friendly and min(a.get('hp', 100) for a in focus) <= 20)):
        target = min(focus, key=lambda a: distance(cell(a), goal))
        firing = [a for a in active if distance(cell(a), cell(target)) <= 10]
        _issue(v, state, emit, firing, cell(target), 'finish:' + str(target['id']),
               command='attack', target=target['id'])
        firing_ids = {a['id'] for a in firing}
    _issue(v, state, emit, [a for a in active if a['id'] not in firing_ids], goal, 'attack')
    _issue(v, state, emit, recruits, _stage(v), 'gather')
    state['last_mode'] = 'attack'
