"""Idle recovery uses only documented public fields, never live ore guesses."""
from copy import deepcopy

import pytest

from redalert_bot.agent import validate
from redalert_bot.common import View
from redalert_bot.harvesters import plan
from redalert_bot.maps import adapt


def actor(ident, typ='harv', x=18, y=10, **extra):
    return dict(id=ident, type=typ, x=x, y=y, hp=100, idle=True, act=None, **extra)


def view(units=None, *, mapped=True, wall=False):
    rows = [list('.'*64) for _ in range(48)]
    for x in (10, 26):
        for dx in (0, 1):
            for y in (14, 15):
                rows[y][x+dx] = '$'
    if wall:
        for row in rows:
            row[20] = '~'
    cfg = {'rules': {'maps': {'test': {'bounds': [0, 0, 64, 48],
            'spawns': [[8, 8], [55, 40]],
            'layout': {'origin': [0, 0], 'rows': [''.join(r) for r in rows]}}}}} if mapped else {}
    raw = {'map': {'id': 'test', 'bounds': [0, 0, 64, 48]},
           'time': {'game_seconds': 900, 'remaining_seconds': 300},
           'observation': {'base_center': [8, 8],
               'units': units if units is not None else [actor(100)],
               'buildings': [actor(1, 'proc', 8, 8), actor(2, 'proc', 28, 8)],
               'visible_enemies': [], 'visible_enemy_buildings': []}}
    v = View(raw, cfg)
    if mapped:
        adapt(v, {})
    return v


def collect(v, memory=None, accepted=True):
    memory = {} if memory is None else memory
    orders = []
    def emit(order, **kwargs):
        if accepted:
            orders.append(order)
        return accepted
    plan(v, memory, emit)
    return orders, memory


def after_native_resume(v):
    orders, memory = collect(v)
    assert orders == [{'cmd': 'harvest', 'units': [u['id'] for u in v.units]}]
    v.now += 12
    return memory


def wider_search_view(points):
    original = view([actor(100, x=8, y=8)])
    raw, config = deepcopy(original.raw), deepcopy(original.config)
    raw['observation']['buildings'] = [actor(1, 'proc', 8, 8)]
    rows = [list('.'*64) for _ in range(48)]
    for x, y in points:
        rows[y][x] = '$'
    config['rules']['maps']['test']['layout']['rows'] = [''.join(r) for r in rows]
    v = View(raw, config)
    adapt(v, {})
    return v


@pytest.mark.parametrize('radius', [24, 25, 28, 32])
def test_idle_miner_can_search_up_to_32_cells_from_working_refinery(radius):
    v = wider_search_view([(8, 8+radius)])
    memory = after_native_resume(v)
    out, _ = collect(v, memory)
    assert out == [{'cmd': 'harvest', 'units': [100], 'to': [8, 8+radius]}]
    assert validate(out[0], v)


def test_search_does_not_expand_past_32_cells():
    v = wider_search_view([(8, 41)])
    assert collect(v, after_native_resume(v))[0] == []


def test_nearby_safe_patch_still_precedes_extended_search():
    v = wider_search_view([(12, 8), (8, 36)])
    assert collect(v, after_native_resume(v))[0][0]['to'] == [12, 8]


def test_suspect_near_patch_allows_wider_safe_fallback():
    v = wider_search_view([(12, 8), (8, 36)])
    memory = after_native_resume(v)
    memory['suspect_until'] = {'12,8': v.now+120}
    assert collect(v, memory)[0][0]['to'] == [8, 36]


@pytest.mark.parametrize('threat', ['3tnk', 'tsla'])
def test_extended_patch_keeps_existing_enemy_and_tower_checks(threat):
    v = wider_search_view([(8, 36)])
    memory = after_native_resume(v)
    enemy = actor(500, threat, 8, 32)
    if threat == 'tsla':
        v.enemy_buildings = [enemy]
    else:
        v.enemies = [enemy]
    assert not collect(v, memory)[0]


def test_extended_search_does_not_head_toward_enemy_home():
    v = wider_search_view([(35, 24)])
    assert not collect(v, after_native_resume(v))[0]


def test_extended_search_rejects_long_detour_to_nearby_ore():
    v = wider_search_view([(8, 36)])
    rows = v.map_info['layout']['rows']
    rows[25] = '~'*50 + '.'*14
    adapt(v, {})
    assert not collect(v, after_native_resume(v))[0]


def test_extended_search_does_not_interrupt_a_working_miner():
    v = wider_search_view([(8, 36)])
    memory = after_native_resume(v)
    v.units[0].update(idle=False, act='HarvestResource')
    assert not collect(v, memory)[0]


@pytest.mark.parametrize('activity', ['Move', 'HarvestResource', 'DeliverResources',
                                    'Unload', 'FindAndDeliverResources', 'UnknownActivity'])
@pytest.mark.parametrize('idle_flag', [False, True])
def test_active_or_contradictory_activity_is_never_interrupted(activity, idle_flag):
    unit = actor(100)
    unit.update(idle=idle_flag, act=activity)
    assert collect(view([unit]))[0] == []


def test_initial_native_resume_waits_before_targeting_and_preserves_input():
    v = view()
    original = deepcopy(v.raw)
    orders, memory = collect(v)
    assert orders == [{'cmd': 'harvest', 'units': [100]}]
    for elapsed in (0.2, 2, 8, 11.9):
        v.now = 900+elapsed
        assert not collect(v, memory)[0]
    v.now = 912
    targeted, _ = collect(v, memory)
    assert len(targeted) == 1 and 'to' in targeted[0]
    assert validate(targeted[0], v) == targeted[0]
    assert v.raw == original


def test_failed_emission_does_not_consume_retry_or_assignment():
    v = view()
    _, memory = collect(v, accepted=False)
    assert not memory['units']['100'].get('attempts')
    assert collect(v, memory)[0] == [{'cmd': 'harvest', 'units': [100]}]


def test_idle_at_initial_patch_switches_patch_instead_of_looping_on_same_ore():
    v = view()
    memory = after_native_resume(v)
    first, _ = collect(v, memory)
    target = first[0]['to']
    v.units[0].update(x=target[0], y=target[1])
    v.now += 12
    second, _ = collect(v, memory)
    assert len(second) == 1 and second[0]['to'] != target
    second_target = second[0]['to']
    v.units[0].update(x=second_target[0], y=second_target[1])
    v.now += 12
    assert not collect(v, memory)[0]
    # Both patches are merely under a temporary retry cooldown, not marked
    # as actual depleted resources. A later probe can recover regenerated ore.
    v.now += 24
    assert not collect(v, memory)[0]
    v.now += 120
    assert any('to' in order for order in collect(v, memory)[0])


def test_stalled_journey_does_not_label_destination_as_failed_for_other_miners():
    v = view()
    memory = after_native_resume(v)
    collect(v, memory)
    v.units[0].update(x=18, y=2)
    v.now += 12
    collect(v, memory)
    assert not memory.get('destination_failures')
    assert not memory.get('suspect_until')


def test_repeated_idle_destination_is_temporarily_avoided_across_miners():
    v = view()
    memory = after_native_resume(v)
    first, _ = collect(v, memory)
    target = first[0]['to']
    previous = deepcopy(memory['units']['100'])
    patch = previous['patch']
    v.units = [actor(100, x=target[0], y=target[1]), actor(101, x=target[0], y=target[1])]
    memory['units']['101'] = deepcopy(previous)
    v.now += 12
    orders, _ = collect(v, memory)
    assert memory['suspect_until'][patch] > v.now
    assert orders and all(order.get('to') != target for order in orders)


def test_multiple_idle_miners_distribute_between_equivalent_resource_zones():
    v = view([actor(100), actor(101)])
    memory = after_native_resume(v)
    orders, _ = collect(v, memory)
    assert len(orders) == 2
    assert len({tuple(order['to']) for order in orders}) == 2
    assert {memory['units'][str(i)]['refinery'] for i in (100, 101)} == {1, 2}


def test_unreachable_island_and_disabled_refinery_are_not_assigned():
    v = view(wall=True)
    memory = after_native_resume(v)
    orders, _ = collect(v, memory)
    assert orders and orders[0]['to'][0] < 20
    v.buildings[0]['powered_down'] = True
    v.now += 12
    assert not collect(v, memory)[0]


@pytest.mark.parametrize('threat', ['tsla', '3tnk'])
def test_known_threat_at_patch_and_dropoff_selects_other_safe_zone(threat):
    v = view()
    memory = after_native_resume(v)
    unit = actor(200, threat, 10, 14)
    if threat == 'tsla':
        v.enemy_buildings = [unit]
    else:
        v.enemies = [unit]
    v.units[0].update(x=28, y=10)
    orders, _ = collect(v, memory)
    assert orders and orders[0]['to'][0] >= 26


def test_missing_map_uses_backoff_and_never_invents_coordinates():
    v = view(mapped=False)
    memory, observed = {}, []
    for second in range(181):
        v.now = 900+second
        orders, _ = collect(v, memory)
        if orders:
            observed.append(second)
            assert orders == [{'cmd': 'harvest', 'units': [100]}]
    assert observed == [0, 12, 36, 84, 144]


def test_no_refinery_no_orders_and_dead_miners_leave_no_retry_records():
    v = view()
    _, memory = collect(v)
    v.buildings = []
    v.now += 60
    assert not collect(v, memory)[0]
    v.units = []
    collect(v, memory)
    assert not memory['units']


def test_targeting_budget_leaves_room_for_economy_and_combat_orders():
    v = view([actor(i) for i in range(100, 110)])
    memory = after_native_resume(v)
    orders, _ = collect(v, memory)
    assert len(orders) <= 4
    assert all(validate(order, v) for order in orders)


def test_generic_resume_obeys_smaller_runtime_unit_limit():
    v = view([actor(i) for i in range(100, 105)], mapped=False)
    v.raw['limits'] = {'max_units_per_order': 2}
    orders, memory = collect(v)
    assert orders == [{'cmd': 'harvest', 'units': [100, 101]}]
    assert not memory['units']['102'].get('attempts')
    assert validate(orders[0], v)


@pytest.mark.parametrize('threat, danger', [('tsla', 10), ('3tnk', 12)])
def test_idle_miner_inside_danger_escapes_by_short_waypoints_before_harvesting(threat, danger):
    v = view()
    enemy = actor(200, threat, 15, 10)
    if threat == 'tsla':
        v.enemy_buildings = [enemy]
    else:
        v.enemies = [enemy]
    memory = {'units': {'100': {'next_retry': v.now+60}}}
    # Emergency escape overrides the normal mining retry timer.
    for _ in range(8):
        current = (v.units[0]['x'], v.units[0]['y'])
        before = ((current[0]-15)**2+(current[1]-10)**2)**.5
        if before > danger:
            break
        orders, _ = collect(v, memory)
        assert len(orders) == 1 and orders[0]['cmd'] == 'move'
        point = tuple(orders[0]['to'])
        assert point in v.navigation['parents']
        assert abs(point[0]-current[0])+abs(point[1]-current[1]) <= 6
        assert point[0] == current[0] or point[1] == current[1]
        assert ((point[0]-15)**2+(point[1]-10)**2)**.5 >= before
        assert validate(orders[0], v)
        v.units[0].update(x=point[0], y=point[1], idle=False, act='Move')
        v.now += .2
        assert not collect(v, memory)[0]
        v.units[0].update(idle=True, act=None)
        v.now += 1.8
    assert ((v.units[0]['x']-15)**2+(v.units[0]['y']-10)**2)**.5 > danger


def test_idle_miner_with_no_safe_exit_does_not_receive_suicidal_harvest_or_move():
    v = view([actor(100, x=8, y=8)])
    # The entire reachable island is within the newly seen tower's range.
    v.navigation = {'parents': {(8, 8): None, (9, 8): (8, 8)},
                    'distances': {(8, 8): 0, (9, 8): 1}}
    v.enemy_buildings = [actor(200, 'tsla', 8, 10)]
    orders, memory = collect(v)
    assert not orders
    assert memory['units']['100']['escape_retry'] > v.now
    v.now += .2
    assert not collect(v, memory)[0]


def test_idle_miner_can_escape_after_all_refineries_are_lost():
    v = view()
    v.buildings = []
    v.enemies = [actor(200, '3tnk', 15, 10)]
    orders, _ = collect(v)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'


def test_escape_does_not_run_away_from_one_enemy_toward_another():
    v = view()
    v.enemies = [actor(200, '3tnk', 15, 10), actor(201, '3tnk', 24, 10)]
    orders, _ = collect(v)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'
    point = orders[0]['to']
    for enemy_x in (15, 24):
        assert (point[0]-enemy_x)**2+(point[1]-10)**2 >= (18-enemy_x)**2
