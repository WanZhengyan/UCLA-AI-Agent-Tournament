"""Owned mining / tank screens / rear artillery, not simulated win rates."""
from copy import deepcopy

import pytest

from redalert_bot import mining
from redalert_bot.agent import create_agent, validate
from redalert_bot.common import View, cell, distance
from redalert_bot.combat import _rear_artillery
from redalert_bot.economy import plan
from redalert_bot.maps import adapt
from redalert_bot.strategy import TANKS, weapon_range
from test_redalert_armor import economy, trained
from test_redalert_balance import actor, combat, view as combat_view
from test_redalert_economy import view, orders
from test_redalert_policy import decide


def mining_view(now=350, cash=5000, tanks=6):
    rows = ['.' * 64 for _ in range(64)]
    for y in range(10, 14):
        rows[y] = rows[y][:25] + '$$$$' + rows[y][29:]
    cfg = {'rules': {'maps': {'test': {'layout': {'rows': rows, 'origin': [0, 0]}}}}}
    buildings = [actor(1, 'fact', 10, 10), actor(2, 'powr', 16, 14),
                 actor(3, 'barr', 10, 5), actor(4, 'proc', 5, 8),
                 actor(5, 'proc', 8, 5), actor(6, 'weap', 10, 15),
                 actor(7, 'fix', 5, 15)]
    units = [dict(actor(100+i, 'harv', 25+i % 3, 11), idle=False, act='HarvestResource')
             for i in range(4)]
    units += [actor(200+i, '3tnk', 16, 16) for i in range(tanks)]
    v = view(buildings, units, available=['proc', '3tnk', 'harv', 'mcv', 'gun', 'arty'],
             cash=cash, power=500, drain=100, seconds=now, config=cfg)
    v.profile = 'eco_guard'
    adapt(v, {})
    return v


def test_new_version_is_selected():
    assert create_agent().strategy_version == 'mining_guard_v9'


def test_refinery_hint_shortens_delivery_inside_owned_construction_area():
    v = mining_view()
    site = mining.refinery_site(v, {}, {})
    assert site
    nearest_old = min(distance(site['ore'], cell(b)) for b in v.buildings if b['type'] == 'proc')
    assert distance(site['ore'], site['at']) + 4 < nearest_old
    assert min(distance(site['at'], cell(b)) for b in v.buildings) <= 8
    assert distance(site['at'], (10, 10)) <= 18
    assert tuple(site['at']) not in v.ore_cells


@pytest.mark.parametrize('cause', ['unknown_map', 'water', 'enemy', 'tower', 'depleted_hint', 'no_current_activity'])
def test_refinery_does_not_expand_on_unsafe_or_unsupported_hints(cause):
    v, memory, harvest = mining_view(), {}, {}
    if cause == 'unknown_map':
        v.map_plan['active'] = False
    elif cause == 'water':
        rows = v.map_info['layout']['rows']
        rows[:] = [r[:20] + '~' + r[21:] for r in rows]
        adapt(v, {})
    elif cause == 'enemy':
        v.enemies = [actor(900, '3tnk', 30, 12)]
    elif cause == 'tower':
        v.enemy_buildings = [actor(900, 'tsla', 32, 12)]
    elif cause == 'depleted_hint':
        harvest['suspect_until'] = {'25,10': v.now + 120}
    else:
        for u in v.units:
            if u['type'] == 'harv':
                u.update(act='FindAndDeliverResources')
    assert mining.refinery_site(v, memory, harvest) is None


def test_cached_site_is_invalidated_immediately_by_new_enemy():
    v, memory = mining_view(), {}
    assert mining.refinery_site(v, memory, {})
    v.now += .2
    v.enemies = [actor(900, '3tnk', 30, 12)]
    assert mining.refinery_site(v, memory, {}) is None


def test_parent_mining_activity_needs_repeated_near_patch_observations():
    v, memory = mining_view(), {}
    for u in v.units:
        if u['type'] == 'harv':
            u['act'] = 'FindAndDeliverResources'
    assert mining.refinery_site(v, memory, {}) is None
    v.now += 6
    assert mining.refinery_site(v, memory, {}) is None
    v.now += 6
    assert mining.refinery_site(v, memory, {})


def test_long_observation_gap_does_not_prove_parent_activity_worked():
    v, memory = mining_view(), {}
    for u in v.units:
        if u['type'] == 'harv':
            u['act'] = 'FindAndDeliverResources'
    assert mining.refinery_site(v, memory, {}) is None
    v.now += 60
    assert mining.refinery_site(v, memory, {}) is None


@pytest.mark.parametrize('transform', ['reflect_x', 'transpose'])
def test_mining_geometry_is_not_tied_to_one_spawn_or_map_orientation(transform):
    v = mining_view()
    raw, cfg = deepcopy(v.raw), deepcopy(v.config)
    change = (lambda p: [63-p[0], p[1]]) if transform == 'reflect_x' else (lambda p: [p[1], p[0]])
    for a in raw['observation']['units'] + raw['observation']['buildings']:
        a['x'], a['y'] = change((a['x'], a['y']))
    raw['observation']['base_center'] = change(raw['observation']['base_center'])
    raw['legal_actions']['enemy_base'] = change(raw['legal_actions']['enemy_base'])
    layout = cfg['rules']['maps']['test']['layout']
    rows = layout['rows']
    layout['rows'] = [r[::-1] for r in rows] if transform == 'reflect_x' else [''.join(r) for r in zip(*rows)]
    v = View(raw, cfg)
    v.profile = 'eco_guard'
    adapt(v, {})
    assert mining.refinery_site(v, {}, {})
    assert {'cmd': 'build', 'item': 'proc'} in orders(v)


def test_known_nearby_refinery_prevents_redundant_growth():
    v = mining_view()
    v.buildings.append(actor(8, 'proc', 24, 17))
    assert mining.refinery_site(v, {}, {}) is None


def test_refinery_precedes_mcv_and_keeps_tank_budget():
    v = mining_view(cash=800)
    out = orders(v)
    assert {'cmd': 'build', 'item': 'proc'} in out
    assert '3tnk' in trained(out)
    assert 'mcv' not in trained(out)


@pytest.mark.parametrize('cause', ['late', 'tank_shortage', 'under_attack', 'cash_shortage'])
def test_growth_has_time_defense_and_cash_gates(cause):
    v = mining_view()
    if cause == 'late':
        v.remaining = 180
    elif cause == 'tank_shortage':
        v.units = [u for u in v.units if u['type'] != '3tnk']
    elif cause == 'under_attack':
        v.enemies = v.obs['visible_enemies'] = [actor(900, '3tnk', 11, 11)]
    else:
        v.econ['cash'] = 700
    assert {'cmd': 'build', 'item': 'proc'} not in orders(v)


def test_finished_growth_refinery_uses_selected_mine_hint():
    v = mining_view()
    site = mining.refinery_site(v, {}, {})
    v.production = [{'item': 'proc', 'queue': 'Building', 'ready': True}]
    memory, out = {}, []
    plan(v, memory, lambda o, **kw: out.append(o) or True)
    assert {'cmd': 'place', 'item': 'proc', 'at': site['at']} in out
    assert memory['mining']['placement']['before'] == [4, 5]


def test_pending_placement_is_not_counted_as_new_refinery():
    v, memory = mining_view(), {}
    site = mining.refinery_site(v, memory, {})
    mining.record_placement(v, memory, site)
    mining.observe(v, memory)
    assert 'placement' in memory
    assert not memory.get('blocked_until')


def test_engine_fallback_to_home_backs_off_same_patch():
    v, memory = mining_view(), {}
    site = mining.refinery_site(v, memory, {})
    mining.record_placement(v, memory, site)
    v.buildings.append(actor(9, 'proc', 7, 18))
    mining.observe(v, memory)
    assert memory['blocked_until'][site['patch']] > v.now
    assert mining.refinery_site(v, memory, {}) is None


def test_successful_placement_uses_observed_building_not_hint_only():
    v, memory = mining_view(), {}
    site = mining.refinery_site(v, memory, {})
    mining.record_placement(v, memory, site)
    v.buildings.append(actor(9, 'proc', *site['at']))
    mining.observe(v, memory)
    assert 'placement' not in memory
    assert not memory.get('blocked_until')
    assert mining.refinery_site(v, memory, {}) is None


def test_unsafe_completed_refinery_is_placed_at_home_instead_of_stale_hint():
    v = mining_view()
    v.production = [{'item': 'proc', 'queue': 'Building', 'ready': True}]
    v.enemies = [actor(900, '3tnk', 30, 12)]
    assert {'cmd': 'place', 'item': 'proc'} in orders(v)


def test_separate_mine_gets_defense_instead_of_another_home_tower():
    v = mining_view()
    v.buildings += [actor(8, 'gun', 8, 10), actor(9, 'proc', 30, 20), actor(10, 'fact', 28, 24)]
    assert mining.defense_anchor(v)['id'] == 9
    assert {'cmd': 'build', 'item': 'gun'} in orders(v)
    v.production = [{'item': 'gun', 'queue': 'Defense', 'ready': True}]
    placed = next(o for o in orders(v) if o['cmd'] == 'place')
    assert distance(placed['at'], (30, 20)) <= 5
    assert distance(placed['at'], v.base) > 15


def test_no_extra_ground_tower_for_already_covered_mines():
    v = mining_view()
    v.buildings += [actor(8, 'gun', 8, 10), actor(9, 'proc', 30, 20), actor(10, 'gun', 32, 20)]
    assert mining.defense_anchor(v) is None
    assert not any(o['cmd'] == 'build' and o['item'] == 'gun' for o in orders(v))


def test_expanded_working_economy_can_grow_past_eight_miners():
    v = mining_view()
    assert mining.miner_target(v, 5) == 10
    assert mining.miner_target(v, 6) == 12
    assert mining.miner_target(v, 20) == 12


def test_miner_cap_uses_repeated_parent_activity_not_a_single_search_view():
    v, memory = mining_view(), {}
    for u in v.units:
        if u['type'] == 'harv':
            u['act'] = 'FindAndDeliverResources'
    assert mining.miner_target(v, 6, memory) == 8
    v.now += 6
    assert mining.miner_target(v, 6, memory) == 8
    v.now += 6
    assert mining.miner_target(v, 6, memory) == 12


@pytest.mark.parametrize('cause', ['idle', 'late', 'no_activity', 'weak_screen'])
def test_extra_miners_require_working_income_time_and_screen(cause):
    v = mining_view()
    if cause == 'idle':
        v.units[0].update(idle=True, act=None)
    elif cause == 'late':
        v.remaining = 100
    elif cause == 'no_activity':
        for u in v.units:
            u.pop('act', None)
    else:
        v.units = [u for u in v.units if u['type'] != '3tnk']
    assert mining.miner_target(v, 6) == 8


@pytest.mark.parametrize('item', ['arty', 'v2rl'])
def test_limited_defensive_artillery_is_available_without_enemy_towers(item):
    v = economy(tanks=5, cash=1800, available=['3tnk', item])
    assert trained(orders(v)) == [item]
    v.units.append(actor(800, item, 12, 12))
    assert trained(orders(v)) == ['3tnk']


def test_artillery_cannot_take_a_small_tank_budget_or_replace_emergency_armor():
    v = economy(tanks=5, cash=800, available=['3tnk', 'arty'])
    # An unaffordable discretionary artillery order must not idle the factory.
    assert trained(orders(v)) == ['3tnk']
    v.econ['cash'] = 1800
    v.enemies = v.obs['visible_enemies'] = [actor(900, '3tnk', 15, 15)]
    assert trained(orders(v)) == ['3tnk']


def garrison_view(tanks=7):
    army = [actor(i, '3tnk', 15, 15) for i in range(1, tanks+1)]
    army += [actor(90, 'arty', 13, 13)]
    v = combat_view(units=army)
    v.profile = 'eco_guard'
    v.buildings += [actor(800, 'proc', 30, 10)]
    return v


def movements(out):
    return [o for o in out if o['cmd'] in {'move', 'attack_move', 'attack'}]


def test_mine_uses_tanks_and_retains_home_screen_with_artillery_behind():
    v = garrison_view()
    out, memory = combat(v)
    commands = movements(out)
    mine_tanks = {i for o in commands if o.get('to', [0])[0] > 25 and 90 not in o['units'] for i in o['units']}
    assert len(mine_tanks) == 2
    assert all(next(u for u in v.units if u['id'] == i)['type'] in TANKS for i in mine_tanks)
    gun = next(o for o in commands if 90 in o['units'])
    tank = next(o for o in commands if mine_tanks.intersection(o['units']))
    assert distance(gun['to'], v.enemy_base) > distance(tank['to'], v.enemy_base)
    home = {i for o in commands if o.get('to', [100])[0] < 25 for i in o['units']}
    assert len(home - {90}) >= 3
    assert all(validate(o, v) for o in out)


def test_small_army_does_not_split_into_unprotected_outposts():
    v = garrison_view(tanks=4)
    out, _ = combat(v)
    assert all(o.get('to', [0])[0] < 25 for o in movements(out))


def test_expansion_mcv_gets_a_tank_escort():
    v = garrison_view()
    v.buildings = [b for b in v.buildings if b['type'] != 'proc']
    v.units.append(actor(800, 'mcv', 30, 10))
    out, _ = combat(v)
    escort = {i for o in movements(out) if o.get('to', [0])[0] > 30 for i in o['units']}
    assert len(escort) == 2
    assert 800 not in {i for o in movements(out) for i in o['units']}


def test_outpost_orders_do_not_cross_known_enemy_towers():
    v = garrison_view()
    v.enemy_buildings = [actor(900, 'tsla', 23, 10)]
    out, _ = combat(v)
    assert not any(o.get('to', [0])[0] > 25 for o in movements(out))


@pytest.mark.parametrize('enemy_x,screened,expected_attack', [(23, True, True), (40, True, False), (23, False, False), (17, True, False)])
def test_artillery_fires_only_in_range_behind_tanks(enemy_x, screened, expected_attack):
    gun = actor(90, 'arty', 14, 10)
    tanks = [actor(1, '3tnk', 19, 10), actor(2, '3tnk', 19, 11)] if screened else []
    enemy = actor(900, '3tnk', enemy_x, 10)
    v = combat_view(units=[gun] + tanks, enemies=[enemy])
    v.profile = 'eco_guard'
    out = []
    _rear_artillery(v, {}, lambda o, **kw: out.append(o) or True, [gun], tanks, (18, 10), [enemy])
    shots = [o for o in out if o['cmd'] == 'attack']
    assert bool(shots) == expected_attack
    assert not any(o['cmd'] == 'attack_move' for o in out)
    if shots:
        assert shots[0]['target'] == 900
        assert distance(cell(gun), cell(enemy)) < weapon_range(v, 'arty', 12)
    elif enemy_x == 17:
        retreat = next(o for o in out if o['cmd'] == 'move')
        assert distance(retreat['to'], cell(enemy)) > distance(cell(gun), cell(enemy))
    assert all(validate(o, v) for o in out)


def test_live_raid_controller_never_orders_artillery_to_chase():
    v = garrison_view()
    v.enemies = [actor(900+i, '3tnk', 23, 10) for i in range(5)]
    out, _ = combat(v)
    gun = [o for o in movements(out) if 90 in o['units']]
    assert gun
    assert all(o['cmd'] != 'attack_move' for o in gun)


def test_positive_trade_balance_at_cutoff_does_not_start_optional_attack():
    v = garrison_view()
    v.remaining = 60
    v.military['kills_cost'] = 1200
    v.enemy_buildings = [actor(900, 'proc', 40, 20)]
    out, memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert not any(o['cmd'] in {'attack', 'attack_move'} for o in out)


def test_real_agent_combines_growth_and_guards_with_protocol_limits():
    v = mining_view()
    raw = deepcopy(v.raw)
    raw.update(session_id='mining-contract', game_type='red_alert', phase='playing',
               state_version=8750, is_current_actor=True, is_terminal=False,
               limits={'max_orders_per_batch': 20, 'max_units_per_order': 50,
                       'max_train_count': 10})
    raw['legal_actions']['place'] = []
    raw['observation']['visible_enemy_buildings'] = []
    out = decide(create_agent(), raw, v.config)
    assert {'cmd': 'build', 'item': 'proc'} in out
    assert any(o.get('item') in {'3tnk', 'arty'} for o in out)
