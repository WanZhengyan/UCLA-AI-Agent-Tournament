"""Defend a nonnegative trade score; counterattack only through safety gates."""
import pytest

from redalert_bot.agent import validate
from redalert_bot.maps import adapt, route_safe
from redalert_bot.strategy import blockers
from test_redalert_balance import actor, combat, view
from test_redalert_maps import mapped


def armored_view(*, balance=0, remaining=600, x=35, y=20, forts=None, enemies=None):
    army = [actor(i, x=x, y=y) for i in range(1, 7)]
    army += [actor(100+i, '3tnk', x, y) for i in range(3)]
    v = view(units=army, forts=forts if forts is not None else [actor(500, 'proc', 40, 20)],
             enemies=enemies, remaining=remaining,
             military={'kills_cost': max(0, balance), 'deaths_cost': max(0, -balance)})
    v.profile = 'eco_guard'
    return v


def movements(orders):
    return [o for o in orders if o['cmd'] in {'move', 'attack_move', 'attack', 'stop'}]


@pytest.mark.parametrize('balance', [0, 1, 1000])
@pytest.mark.parametrize('remaining', [600, 20])
def test_tie_or_lead_does_not_take_exposed_economic_bait(balance, remaining):
    v = armored_view(balance=balance, remaining=remaining)
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert memory['combat']['wave_ids'] == []
    assert movements(orders) and all(o['cmd'] == 'move' for o in movements(orders))
    assert not any(o.get('to') == [40, 20] for o in orders)
    assert all(validate(o, v) for o in orders)


@pytest.mark.parametrize('new_balance', [0, 1])
def test_new_nonnegative_score_immediately_recalls_an_active_counterattack(new_balance):
    v = armored_view(balance=-100)
    first, memory = combat(v)
    assert any(o.get('target') == 500 for o in first)
    assert memory['combat']['wave_ids']
    v.now += .2
    v.military.update(kills_cost=100+new_balance, deaths_cost=100)
    for unit in v.units:
        unit['idle'] = False
    orders, memory = combat(v, memory)
    assert memory['combat']['wave_ids'] == []
    assert memory['combat']['mode'] == 'guard economy'
    assert {i for o in movements(orders) for i in o['units']} == {u['id'] for u in v.units}
    assert all(o['cmd'] == 'move' for o in movements(orders))
    assert all(o.get('to') != [40, 20] for o in movements(orders))


def test_positive_score_recalls_wave_without_crossing_a_known_tower_line():
    v = armored_view(balance=1, x=45, y=10, forts=[actor(501, 'tsla', 30, 10)])
    memory = {'combat': {'scouted': True, 'wave_ids': [u['id'] for u in v.units],
                        'unit_orders': {str(u['id']): {'at': v.now-.2, 'mode': 'attack',
                                                      'goal': [80, 80]} for u in v.units}}}
    for unit in v.units:
        unit['idle'] = False
    orders, memory = combat(v, memory)
    assert memory['combat']['wave_ids'] == []
    assert movements(orders)
    assert all(o['cmd'] == 'move' and not blockers(v, (45, 10), o['to'])
               for o in movements(orders))


def test_old_recovery_timers_cannot_override_a_new_safe_guard_posture():
    v = armored_view(balance=1)
    v.strategy = {'recover_until': v.now+30}
    memory = {'combat': {'retreat_until': v.now+30, 'retreat_goal': [80, 80],
                        'wave_ids': [u['id'] for u in v.units]}}
    orders, memory = combat(v, memory)
    assert memory['combat']['mode'] == 'guard economy'
    assert not memory['combat'].get('retreat_until')
    assert all(o.get('to') != [80, 80] for o in movements(orders))


def test_ahead_army_still_defends_home_and_cancels_the_unneeded_attack_wave():
    v = armored_view(balance=-100)
    _, memory = combat(v)
    v.now += .2
    v.military.update(kills_cost=101, deaths_cost=100)
    v.enemies = [actor(600, 'ftrk', 20, 10)]
    for unit in v.units:
        unit['idle'] = False
    orders, memory = combat(v, memory)
    defending = {i for o in movements(orders) if o.get('to') == [20, 10] for i in o['units']}
    recalling = {i for o in movements(orders) if o['cmd'] == 'move' for i in o['units']}
    assert memory['combat']['mode'] == 'defend economy'
    assert defending and recalling and not defending & recalling
    assert defending | recalling == {u['id'] for u in v.units}
    assert memory['combat']['wave_ids'] == []


def test_negative_score_can_still_take_a_favorable_armored_counterattack():
    v = armored_view(balance=-100)
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'pressure enemy'
    assert any(o.get('target') == 500 for o in orders)


def test_negative_score_near_deadline_does_not_override_bad_trade_gate():
    enemies = [actor(600+i, '3tnk', 62, 62) for i in range(6)]
    v = armored_view(balance=-100, remaining=20, x=55, y=55, forts=[], enemies=enemies)
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'retreat from bad trade'
    assert all(o['cmd'] == 'move' for o in movements(orders))


def test_negative_score_near_deadline_does_not_override_tower_gate():
    v = armored_view(balance=-100, remaining=20, x=45, y=45,
                     forts=[actor(501, 'tsla', 65, 65)])
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'contain fortifications'
    assert all(o['cmd'] == 'move' and not blockers(v, (45, 45), o['to'])
               for o in movements(orders))


def test_balanced_profile_keeps_its_existing_offensive_policy():
    v = armored_view(balance=100)
    v.profile = 'balanced'
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'pressure enemy'
    assert any(o.get('target') == 500 for o in orders)


def test_even_a_small_positive_lead_does_not_launch_an_optional_warning_scout():
    v = mapped()
    v.military = {'kills_cost': 1}
    orders, memory = combat(v)
    assert 'warning_scout_id' not in memory['combat']
    assert not memory['combat'].get('warning_scout_attempts')
    assert all(o.get('to') != v.map_plan['scout_cell'] for o in movements(orders))


def test_existing_warning_scout_is_recalled_when_a_positive_lead_appears():
    v = mapped()
    _, memory = combat(v)
    ident = memory['combat']['warning_scout_id']
    scout = next(u for u in v.units if u['id'] == ident)
    scout.update(x=v.map_plan['scout_cell'][0], y=v.map_plan['scout_cell'][1], idle=False)
    v.now += .2
    v.military = {'kills_cost': 1}
    orders, memory = combat(v, memory)
    assert 'warning_scout_id' not in memory['combat']
    recall = [o for o in movements(orders) if ident in o['units']]
    assert len(recall) == 1 and recall[0]['cmd'] == 'move'
    assert recall[0]['to'] == v.map_plan['guard_cell']


def covered_crossing(*, start=(30, 10), goal=(10, 10)):
    v = mapped()
    rows = [list(row) for row in v.map_info['layout']['rows']]
    for y in range(45):
        rows[y][15] = '~'
    v.map_info['layout']['rows'] = [''.join(row) for row in rows]
    v.base = goal
    adapt(v, {})
    v.map_plan['guard_cell'] = list(goal)
    v.units = [actor(i, '3tnk', *start) for i in range(1, 10)]
    v.enemy_buildings = [actor(501, 'tsla', 15, 45)]
    v.military = {'kills_cost': 1}
    return v


def test_guard_recall_does_not_take_a_covered_detour_despite_clear_straight_line():
    v = covered_crossing()
    assert not blockers(v, (30, 10), (10, 10))
    assert not route_safe(v, (10, 10), start=(30, 10))
    orders, _ = combat(v)
    assert movements(orders)
    assert all(o['cmd'] == 'stop' and 'to' not in o for o in movements(orders))
    assert all(validate(o, v) for o in orders)


def test_unsafe_short_hold_is_cancelled_even_inside_normal_goal_change_threshold():
    v = covered_crossing(start=(16, 10), goal=(14, 10))
    memory = {'combat': {'unit_orders': {str(u['id']): {'at': v.now-.2,
        'mode': 'hold', 'goal': [14, 10]} for u in v.units}}}
    for unit in v.units:
        unit['idle'] = False
    orders, memory = combat(v, memory)
    assert movements(orders)
    assert {i for o in movements(orders) for i in o['units']} == {u['id'] for u in v.units}
    assert all(o['cmd'] == 'stop' and 'to' not in o for o in movements(orders))


def test_guard_already_inside_a_tower_zone_uses_a_short_escape_segment():
    v = covered_crossing(start=(16, 44))
    orders, _ = combat(v)
    assert movements(orders)
    for order in movements(orders):
        x, y = order['to']
        assert order['cmd'] == 'move'
        assert 0 < abs(x-16)+abs(y-44) <= 6
        assert x == 16 or y == 44
        assert (x-15)**2+(y-45)**2 > 2


def test_unmapped_tower_hold_also_cancels_a_nearby_unsafe_old_goal():
    v = armored_view(balance=1, x=28, y=10, forts=[actor(501, 'tsla', 15, 10)])
    memory = {'combat': {'unit_orders': {str(u['id']): {'at': v.now-.2,
        'mode': 'hold', 'goal': [22, 10]} for u in v.units}}}
    for unit in v.units:
        unit['idle'] = False
    orders, _ = combat(v, memory)
    assert movements(orders)
    assert all(o['cmd'] == 'move' and not blockers(v, (28, 10), o['to'])
               for o in movements(orders))


def test_disconnected_guard_is_stopped_without_projecting_a_move_across_water():
    v = covered_crossing()
    rows = [list(row) for row in v.map_info['layout']['rows']]
    for row in rows:
        row[15] = '~'
    v.map_info['layout']['rows'] = [''.join(row) for row in rows]
    adapt(v, {})
    v.map_plan['guard_cell'] = [10, 10]
    v.enemy_buildings = []
    assert (30, 10) not in v.navigation['parents']
    orders, _ = combat(v)
    assert movements(orders)
    assert all(o['cmd'] == 'stop' and 'to' not in o for o in movements(orders))
    assert all(validate(o, v) for o in orders)
