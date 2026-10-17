"""Screened third-refinery financing; fixtures do not establish match wins."""
from unittest.mock import patch

import pytest

from redalert_bot.economy import _place_at
from redalert_bot.maps import adapt
from test_redalert_armor import economy, trained
from test_redalert_balance import actor
from test_redalert_economy import orders


def growth_view(**kwargs):
    v = economy(cash=kwargs.pop('cash', 700), tanks=kwargs.pop('tanks', 5),
                available=kwargs.pop('available', ['proc', '3tnk']), **kwargs)
    v.base = (8, 8)
    homes = iter(((8, 8), (8, 14), (14, 8)))
    for building in v.buildings:
        if building['type'] in {'fact', 'proc'}:
            building['x'], building['y'] = next(homes)
    for unit in v.units:
        unit.update(x=10, y=10)
        if unit['type'] == 'harv':
            unit['idle'] = False
    return v


def mapped(v, *, wall=None, ore=True):
    rows = [list('.' * 64) for _ in range(64)]
    # The integrated mining planner requires a useful patch, current mining
    # evidence, and a drop-off that improves on the existing refineries.
    patches = [(x, y) for x in range(22, 26) for y in (8, 9)] if ore else []
    homes = iter(((6, 14), (12, 4)))
    for building in v.buildings:
        if building['type'] == 'proc':
            building['x'], building['y'] = next(homes)
        elif building['type'] == 'weap':
            building.update(x=16, y=14)
    for unit in v.units:
        if unit['type'] == 'harv':
            unit.update(x=22, y=8, act='HarvestResource')
    for x, y in patches:
        rows[y][x] = '$'
    if wall is not None:
        for row in rows:
            row[wall] = '~'
    v.map_info = {'layout': {'origin': [0, 0], 'rows': [''.join(r) for r in rows]}}
    v.ore_cells = patches
    adapt(v, {})
    return v


def builds_refinery(v):
    return {'cmd': 'build', 'item': 'proc'} in orders(v)


def test_screened_third_refinery_finances_growth_without_waiting_for_six_tanks():
    v = growth_view()
    out = orders(v)
    assert {'cmd': 'build', 'item': 'proc'} in out
    assert trained(out) == ['3tnk']


@pytest.mark.parametrize('cash, expected', [(599, False), (600, True)])
def test_growth_preserves_next_heavy_tank_operating_reserve(cash, expected):
    assert builds_refinery(growth_view(cash=cash)) is expected


def test_live_tank_price_still_sets_operating_reserve():
    v = growth_view(cash=549)
    v.rules = {'units': {'3tnk': {'cost': 1000}}}
    assert not builds_refinery(v)
    v.econ['cash'] = 550
    assert builds_refinery(v)


@pytest.mark.parametrize('tanks', [3, 4])
def test_earlier_tank_cores_keep_original_full_price_budget(tanks):
    assert not builds_refinery(growth_view(tanks=tanks))


@pytest.mark.parametrize('change', ['damaged', 'away', 'dispersed'])
def test_cover_requires_five_healthy_tanks_at_one_fact_anchor(change):
    v = growth_view()
    tanks = [u for u in v.units if u['type'] == '3tnk']
    if change == 'damaged':
        tanks[-1]['hp'] = 69
    elif change == 'away':
        tanks[-1].update(x=31, y=8)
    else:
        refs = [b for b in v.buildings if b['type'] == 'proc']
        refs[-1].update(x=40, y=8)
        for tank in tanks[-2:]:
            tank.update(x=40, y=8)
    assert not builds_refinery(v)


def test_healthy_cover_threshold_is_inclusive():
    v = growth_view()
    for tank in [u for u in v.units if u['type'] == '3tnk']:
        tank.update(hp=70, x=30, y=8)
    assert builds_refinery(v)


def test_reported_miner_total_cannot_replace_four_observed_miners():
    v = growth_view(miners=3)
    v.econ['harvesters'] = 8
    assert not builds_refinery(v)


@pytest.mark.parametrize('idle', [True, None, 'false'])
def test_idle_or_unknown_miner_activity_cannot_finance_growth(idle):
    v = growth_view()
    for unit in v.units:
        if unit['type'] == 'harv':
            if idle is None:
                unit.pop('idle', None)
            else:
                unit['idle'] = idle
    assert not builds_refinery(v)


def test_only_three_active_miners_deny_early_growth_even_with_extra_idle_miner():
    v = growth_view()
    next(u for u in v.units if u['type'] == 'harv')['idle'] = True
    assert not builds_refinery(v)


@pytest.mark.parametrize('remaining, expected', [(359.9, False), (360, True)])
def test_growth_requires_conservative_remaining_work_window(remaining, expected):
    v = growth_view()
    v.remaining = remaining
    assert builds_refinery(v) is expected


def test_recent_bad_trade_blocks_early_financing():
    v = growth_view()
    v.strategy = {'recover_until': v.now + 1}
    assert not builds_refinery(v)
    v.strategy['recover_until'] = v.now
    assert builds_refinery(v)


@pytest.mark.parametrize('threat', ['e1', '3tnk', 'mig', 'arty'])
def test_mobile_threat_outside_urgent_radius_blocks_early_financing(threat):
    # One rifle is below the old $400 urgency threshold. Its presence still
    # denies the new exception; the original full-budget rule is preserved.
    v = growth_view(enemies=[actor(900, threat, 34, 8)])
    assert not builds_refinery(v)


def test_small_raid_keeps_full_budget_path_instead_of_disabling_all_growth():
    v = growth_view(cash=1999, enemies=[actor(900, 'e1', 34, 8)])
    assert not builds_refinery(v)
    v.econ['cash'] = 2000
    assert builds_refinery(v)


@pytest.mark.parametrize('threat', ['e6', 'mcv'])
def test_capture_or_forward_base_risk_denies_early_growth(threat):
    # Exactly 24 cells from the construction yard. These types are excluded
    # from the legacy combat urgency score but can threaten economic assets.
    assert not builds_refinery(growth_view(enemies=[actor(900, threat, 32, 8)]))


def test_noncombat_enemy_does_not_trigger_a_fictitious_raid():
    assert builds_refinery(growth_view(enemies=[actor(900, 'harv', 34, 8)]))


@pytest.mark.parametrize('margin, expected', [(89, False), (90, True)])
def test_runtime_refinery_power_cost_and_margin_control_growth(margin, expected):
    v = growth_view()
    v.rules = {'buildings': {'proc': {'power': -80}}}
    v.econ.update(power_provided=140 + margin, power_drained=140)
    assert builds_refinery(v) is expected


def test_known_connected_resource_site_allows_growth():
    assert builds_refinery(mapped(growth_view()))


@pytest.mark.parametrize('wall', [16, 20])
def test_known_unreachable_placement_or_resource_denies_exception(wall):
    assert not builds_refinery(mapped(growth_view(), wall=wall))


def test_known_terrain_without_resource_hint_denies_exception():
    assert not builds_refinery(mapped(growth_view(), ore=False))


def test_supplied_but_unusable_terrain_does_not_fall_back_to_unknown_map():
    v = growth_view()
    v.map_info = {'layout': {'rows': []}}
    assert not builds_refinery(v)


def test_visible_threat_near_planned_site_is_screened_beyond_existing_assets():
    v = mapped(growth_view())
    site = _place_at(v, 'proc')
    v.enemies = [actor(900, 'e1', site[0] + 29, site[1])]
    assert all((b['x'] - v.enemies[0]['x'])**2 + (b['y'] - v.enemies[0]['y'])**2 > 30**2
               for b in v.buildings if b['type'] in {'fact', 'proc'})
    assert not builds_refinery(v)


@pytest.mark.parametrize('remembered', [False, True])
def test_known_tower_near_growth_site_denies_exception(remembered):
    v = mapped(growth_view())
    site = _place_at(v, 'proc')
    tower = actor(901, 'tsla', site[0] + 3, site[1])
    if remembered:
        v.strategy = {'enemy_static': {'901': tower}}
    else:
        v.enemy_buildings = [tower]
    assert not builds_refinery(v)


def test_growth_is_not_extended_to_remote_second_base():
    v = growth_view()
    v.buildings.append(actor(900, 'fact', 40, 40))
    assert not builds_refinery(v)


def test_growth_is_not_extended_to_fourth_refinery():
    v = growth_view()
    v.buildings.extend([actor(900, 'fact', 40, 40), actor(901, 'proc', 40, 44)])
    assert not builds_refinery(v)


def test_existing_building_and_vehicle_queues_are_not_duplicated():
    v = growth_view(production=[{'queue': 'Building', 'item': 'proc', 'progress': .5},
                               {'queue': 'Vehicle', 'item': '3tnk', 'progress': .5}])
    assert not any(o['cmd'] in {'build', 'train'} for o in orders(v))


def test_existing_six_tank_financing_and_late_guard_are_unchanged():
    v = growth_view(tanks=6)
    v.remaining = 200
    assert builds_refinery(v)
    v.remaining = 149
    assert not builds_refinery(v)


def test_balanced_profile_retains_existing_refinery_order():
    v = growth_view(tanks=3)
    v.profile = 'balanced'
    assert builds_refinery(v)


def test_mcv_still_needs_existing_six_tank_core():
    v = growth_view(cash=5000, available=['mcv', '3tnk'])
    with patch('redalert_bot.economy._expansion_window', return_value=True), \
            patch('redalert_bot.economy._expansion_site', return_value=(40, 10)):
        assert trained(orders(v)) == ['3tnk']
