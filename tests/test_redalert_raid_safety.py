"""Public miner-raiding pattern regressions, not an engine outcome estimate."""
from copy import deepcopy

import pytest

from redalert_bot.agent import validate
from redalert_bot.common import distance
from test_redalert_harvesters import actor, collect, view


def raided_view(activity='HarvestResource', *, idle=False, mapped=True):
    miner = actor(100)
    miner.update(idle=idle, act=activity)
    v = view([miner], mapped=mapped)
    v.enemies = [actor(200, '3tnk', 15, 10)]
    return v


def damaged(v, memory, *, hp=70, elapsed=2, accepted=True):
    v.now += elapsed
    v.units[0]['hp'] = hp
    return collect(v, memory, accepted=accepted)


@pytest.mark.parametrize('activity', ['HarvestResource', 'DeliverResources', 'Unload', 'Move'])
@pytest.mark.parametrize('idle', [False, True])
def test_active_miner_taking_fresh_visible_damage_escapes(activity, idle):
    v = raided_view(activity, idle=idle)
    first, memory = collect(v)
    assert first == []
    orders, memory = damaged(v, memory)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'
    order = orders[0]
    assert order['units'] == [100]
    assert validate(order, v) == order
    assert tuple(order['to']) in v.navigation['parents']
    assert 0 < distance((18, 10), order['to']) <= 6
    assert order['to'][0] == 18 or order['to'][1] == 10
    assert distance(order['to'], (15, 10)) > 3


def test_active_escape_does_not_interrupt_again_without_new_damage():
    v = raided_view()
    _, memory = collect(v)
    record = memory['units']['100']
    record.update(target=(26, 14), patch='26,14', refinery=2)
    orders, _ = damaged(v, memory)
    assert orders and not any(k in record for k in ('target', 'patch', 'refinery'))
    v.units[0].update(x=orders[0]['to'][0], y=orders[0]['to'][1], act='Move')
    for elapsed in (.2, 2, 4):
        v.now += elapsed
        assert not collect(v, memory)[0]


def test_only_the_damaged_miner_is_interrupted_and_input_is_unchanged():
    v = raided_view()
    healthy = actor(101)
    healthy.update(idle=False, act='HarvestResource')
    v.units.append(healthy)
    _, memory = collect(v)
    v.now += 2
    v.units[0]['hp'] = 70
    before = deepcopy(v.raw)
    orders, _ = collect(v, memory)
    assert [o['units'] for o in orders] == [[100]]
    assert v.raw == before


def test_enemy_proximity_old_wounds_and_healing_do_not_interrupt_work():
    v = raided_view()
    v.units[0]['hp'] = 60
    first, memory = collect(v)
    assert first == []
    assert not damaged(v, memory, hp=60)[0]
    assert not damaged(v, memory, hp=75)[0]


@pytest.mark.parametrize('elapsed', [0, -1, 8.01, 60])
def test_duplicate_reversed_or_stale_health_sample_does_not_trigger_escape(elapsed):
    v = raided_view()
    _, memory = collect(v)
    assert not damaged(v, memory, elapsed=elapsed)[0]


@pytest.mark.parametrize('bad_hp', [None, '70', True, float('nan'), float('inf'), -1, 101])
def test_malformed_health_breaks_the_damage_comparison_chain(bad_hp):
    v = raided_view()
    _, memory = collect(v)
    assert not damaged(v, memory, hp=bad_hp)[0]
    assert not damaged(v, memory, hp=60)[0]


def test_missing_health_is_not_a_default_full_health_observation():
    v = raided_view()
    del v.units[0]['hp']
    _, memory = collect(v)
    assert not damaged(v, memory, hp=70)[0]


@pytest.mark.parametrize('contact', ['hidden', 'far', 'unarmed', 'remembered_tower'])
def test_damage_without_a_current_visible_armed_threat_does_not_interrupt(contact):
    v = raided_view()
    if contact == 'hidden':
        v.enemies = []
    elif contact == 'far':
        v.enemies[0].update(x=50, y=40)
    elif contact == 'unarmed':
        v.enemies[0]['type'] = 'harv'
    else:
        v.enemies = []
        v.strategy = {'enemy_static': {'200': actor(200, 'tsla', 15, 10)}}
    _, memory = collect(v)
    assert not damaged(v, memory)[0]


@pytest.mark.parametrize('weapon', [{'range_cells': 4}, {'range': '4c0'}, 'short_cannon'])
def test_live_weapon_range_prevents_a_distant_enemy_from_triggering_escape(weapon):
    v = raided_view()
    v.enemies[0].update(x=10, y=10)
    v.rules = {'units': {'3tnk': {'weapon': weapon}},
               'weapons': {'short_cannon': {'range': 4}}}
    _, memory = collect(v)
    assert not damaged(v, memory)[0]


def test_live_long_range_threat_has_a_compatible_escape_danger_zone():
    v = raided_view()
    v.enemies[0].update(type='v2rl', x=2, y=10)
    v.rules = {'units': {'v2rl': {'weapon': {'range': 18}}}}
    _, memory = collect(v)
    orders, _ = damaged(v, memory)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'
    assert distance(orders[0]['to'], (2, 10)) > 16


def test_current_visible_tower_can_trigger_active_miner_escape():
    v = raided_view()
    v.enemy_buildings, v.enemies = [actor(200, 'tsla', 15, 10)], []
    _, memory = collect(v)
    orders, _ = damaged(v, memory)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'


def test_refused_escape_retains_short_retry_window_without_per_frame_retries():
    v = raided_view()
    _, memory = collect(v)
    assert not damaged(v, memory, accepted=False)[0]
    record = memory['units']['100']
    assert record['damage_until'] > v.now
    v.now += .2
    assert not collect(v, memory)[0]
    v.now += 1.8
    orders, _ = collect(v, memory)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'
    assert 'damage_until' not in record


def test_refused_escape_cannot_reuse_expired_damage():
    v = raided_view()
    _, memory = collect(v)
    damaged(v, memory, accepted=False)
    v.now += 4.1
    assert not collect(v, memory)[0]


def test_repeated_damage_respects_escape_cooldown():
    v = raided_view()
    _, memory = collect(v)
    first, _ = damaged(v, memory)
    assert first
    assert not damaged(v, memory, hp=65, elapsed=.2)[0]
    v.now += 1.8
    assert collect(v, memory)[0]


@pytest.mark.parametrize('mapped', [False, True])
def test_no_proven_safe_route_never_creates_a_fallback_harvest_or_move(mapped):
    v = raided_view(mapped=mapped)
    if mapped:
        v.navigation = {'parents': {(18, 10): None, (19, 10): (18, 10)}}
    _, memory = collect(v)
    assert not damaged(v, memory)[0]
    assert memory['units']['100']['escape_retry'] > v.now


def test_emergency_escape_obeys_the_shared_four_order_budget():
    v = raided_view()
    v.units = [dict(v.units[0], id=100+i) for i in range(10)]
    _, memory = collect(v)
    v.now += 2
    for unit in v.units:
        unit['hp'] = 70
    orders, _ = collect(v, memory)
    assert len(orders) == 4
    assert all(o['cmd'] == 'move' and validate(o, v) for o in orders)


def test_escape_never_steps_toward_a_second_visible_attacker():
    v = raided_view()
    v.enemies.append(actor(201, '3tnk', 24, 10))
    _, memory = collect(v)
    orders, _ = damaged(v, memory)
    assert len(orders) == 1
    point = orders[0]['to']
    for enemy in v.enemies:
        origin = (enemy['x'], enemy['y'])
        assert distance(point, origin) >= distance((18, 10), origin)
