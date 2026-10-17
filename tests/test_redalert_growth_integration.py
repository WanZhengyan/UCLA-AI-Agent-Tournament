"""Combine guarded financing with observed, protected mining-site selection."""
from unittest.mock import patch

import pytest

from redalert_bot import mining
from redalert_bot.common import View, cell, distance
from redalert_bot.economy import plan
from redalert_bot.maps import adapt


def growth_view(*, cash=700, tanks=5):
    def actor(ident, kind, x, y):
        return dict(id=ident, type=kind, x=x, y=y, hp=100, idle=False)

    rows = [list('.' * 64) for _ in range(64)]
    for y in range(10, 14):
        rows[y][25:29] = '$' * 4
    buildings = [actor(1, 'fact', 10, 10), actor(2, 'powr', 16, 14),
                 actor(3, 'barr', 10, 5), actor(4, 'proc', 5, 8),
                 actor(5, 'proc', 8, 5), actor(6, 'weap', 10, 15),
                 actor(7, 'fix', 5, 15)]
    units = [dict(actor(100+i, 'harv', 25+i % 3, 11), act='HarvestResource')
             for i in range(4)]
    units += [actor(200+i, '3tnk', 16, 16) for i in range(tanks)]
    raw = {
        'map': {'id': 'test', 'bounds': [0, 0, 64, 64]},
        'time': {'game_seconds': 400, 'remaining_seconds': 800},
        'legal_actions': {'enemy_base': [54, 54]},
        'observation': {'base_center': [10, 10], 'buildings': buildings,
                        'units': units, 'production': [],
                        'available_production': ['proc', '3tnk', 'powr'],
                        'economy': {'cash': cash, 'power_provided': 500,
                                    'power_drained': 100},
                        'visible_enemies': []},
    }
    v = View(raw, {'rules': {'maps': {'test': {'layout': {
        'rows': [''.join(row) for row in rows], 'origin': [0, 0]}}}}})
    v.profile = 'eco_guard'
    adapt(v, {})
    return v


def orders(v, memory=None):
    out = []
    plan(v, memory if memory is not None else {}, lambda o, **kw: out.append(o) or True)
    return out


def builds_refinery(v, memory=None):
    return {'cmd': 'build', 'item': 'proc'} in orders(v, memory)


def test_five_tanks_can_finance_selected_working_mine_and_next_tank():
    v = growth_view()
    assert mining.refinery_site(v, {}, {})
    out = orders(v)
    assert {'cmd': 'build', 'item': 'proc'} in out
    assert {'cmd': 'train', 'item': '3tnk', 'count': 1} in out


@pytest.mark.parametrize('cash, expected', [(599, False), (600, True)])
def test_selected_mine_keeps_heavy_tank_operating_reserve(cash, expected):
    assert builds_refinery(growth_view(cash=cash)) is expected


def test_selected_site_is_checked_instead_of_unrelated_legacy_hint():
    v = growth_view()
    assert mining.refinery_site(v, {}, {})
    # This fallback is irrelevant to the actual selected placement and lacks
    # a nearby resource patch. Its presence must not disable valid financing.
    with patch('redalert_bot.economy._place_at', return_value=[3, 55]):
        assert builds_refinery(v)


def test_threat_near_actual_site_denies_discount_even_if_legacy_hint_is_safe():
    v, memory = growth_view(), {'mining': {}}
    site = mining.refinery_site(v, memory['mining'], {})
    # Both hints are reachable and near the patch, but only the selected
    # hint is close enough to this raider to deny discounted financing.
    fallback = [site['at'][0] - 2, site['at'][1]]
    protected = [cell(b) for b in v.buildings if b['type'] in {'fact', 'proc'}]
    candidates = [(x, y) for x in range(64) for y in range(64)
                  if 18 <= distance((x, y), site['at']) <= 30
                  and all(distance((x, y), p) > 30 for p in protected + [fallback])]
    assert candidates
    x, y = min(candidates, key=lambda p: distance(p, site['at']))
    v.enemies = v.obs['visible_enemies'] = [dict(id=900, type='e1', x=x, y=y, hp=100)]
    assert mining.refinery_site(v, memory['mining'], {}) == site
    with patch('redalert_bot.economy._place_at', return_value=fallback):
        assert not builds_refinery(v, memory)


@pytest.mark.parametrize('cause', ['inactive', 'depleted', 'damaged', 'away', 'late', 'bad_trade'])
def test_discount_keeps_mining_and_guarded_growth_requirements(cause):
    v, memory = growth_view(), {}
    if cause == 'inactive':
        for u in v.units:
            if u['type'] == 'harv':
                u['act'] = 'FindAndDeliverResources'
    elif cause == 'depleted':
        memory['harvesters'] = {'suspect_until': {'25,10': v.now + 120}}
    elif cause == 'damaged':
        v.units[-1]['hp'] = 69
    elif cause == 'away':
        v.units[-1].update(x=40, y=40)
    elif cause == 'late':
        v.remaining = 359
    else:
        v.strategy = {'recover_until': v.now + 45}
    assert not builds_refinery(v, memory)


def test_pending_defense_power_cannot_be_spent_on_discounted_growth():
    v = growth_view()
    v.econ.update(power_provided=200, power_drained=140)
    v.production = [{'item': 'gun', 'queue': 'Defense'}]
    out = orders(v)
    assert {'cmd': 'build', 'item': 'proc'} not in out
    assert {'cmd': 'build', 'item': 'powr'} in out


@pytest.mark.parametrize('cash, expected', [(799, False), (800, True)])
def test_existing_six_tank_mining_budget_is_preserved(cash, expected):
    assert builds_refinery(growth_view(cash=cash, tanks=6)) is expected
