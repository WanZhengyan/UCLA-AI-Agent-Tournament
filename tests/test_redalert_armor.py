"""Armor-budget/engagement regressions; no real-engine win-rate claims."""
import pytest

from redalert_bot.economy import plan
from redalert_bot.combat import _matchup_value
from redalert_bot.strategy import TANKS
from test_redalert_economy import view as economy_view, orders
from test_redalert_balance import actor, view, combat
from test_redalert_policy import mock_production_progression


def economy(cash=800, tanks=0, rifles=10, rockets=4, miners=4, available=None, enemies=(), production=()):
    v = economy_view(['fact', 'powr', 'apwr', 'barr', 'proc', 'proc', 'weap', 'fix'],
                     units=['harv']*miners + ['e1']*rifles + ['e3']*rockets + ['3tnk']*tanks,
                     available=available if available is not None else ['e1', 'e3', 'harv', '3tnk'],
                     cash=cash, power=400, drain=140, enemies=enemies, production=production, seconds=300)
    v.profile = 'eco_guard'
    return v


def trained(out):
    return [o['item'] for o in out if o['cmd'] == 'train']


def test_rifle_heavy_army_stops_infantry_and_finances_tank_below_full_price():
    out = orders(economy(cash=700, rifles=100, rockets=40))
    assert trained(out) == ['3tnk']


def test_small_income_deposit_is_saved_for_tank_not_spent_on_rifles():
    out = orders(economy(cash=400, rifles=2, rockets=2))
    assert not trained(out)


def test_infantry_batches_remain_small_even_with_surplus_income():
    out = orders(economy(cash=5000, tanks=6, rifles=2, rockets=2))
    assert any(o.get('item') == '3tnk' for o in out)
    assert all(o['count'] == 1 for o in out if o['cmd'] == 'train')


def test_soviet_depot_outranks_more_barracks_and_support_car_spam():
    v = economy(cash=600, available=['fix', 'barr', 'e1', 'e3', 'apc'])
    v.buildings = [b for b in v.buildings if b['type'] != 'fix']
    out = orders(v)
    assert {'cmd': 'build', 'item': 'fix'} in out
    assert 'apc' not in trained(out)
    assert not any(o.get('item') == 'barr' for o in out)


def test_no_extra_barracks_before_tank_core():
    v = economy(cash=3000, available=['barr', '3tnk', 'e1', 'e3'])
    assert not any(o.get('item') == 'barr' for o in orders(v))


def test_second_factory_outranks_second_barracks_once_economy_supports_it():
    v = economy(cash=2500, tanks=5, miners=6, available=['weap', 'barr', '3tnk', 'e1', 'e3'])
    v.buildings.append(actor(800, 'proc', 13, 10))
    out = orders(v)
    assert {'cmd': 'build', 'item': 'weap'} in out
    assert not any(o.get('item') == 'barr' for o in out)


@pytest.mark.parametrize('miners,cash', [(0, 1200), (1, 400), (2, 400)])
def test_miner_replacement_still_precedes_tanks(miners, cash):
    assert trained(orders(economy(cash=cash, miners=miners))) == ['harv']


def test_zero_income_preserves_full_miner_recovery_budget():
    assert not trained(orders(economy(cash=900, miners=0)))


def test_ongoing_tank_production_does_not_create_duplicate_queue():
    v = economy(cash=1000, production=[{'queue': 'Vehicle', 'item': '3tnk', 'progress': .3}])
    assert '3tnk' not in trained(orders(v))


def test_visible_enemy_tanks_get_antitank_defense_not_pillbox():
    v = economy(cash=1500, available=['pbox', 'gun', '3tnk', 'e1', 'e3'],
                enemies=[actor(900, '3tnk', 15, 15)])
    out = orders(v)
    assert {'cmd': 'build', 'item': 'gun'} in out
    assert not any(o.get('item') == 'pbox' for o in out)


def test_tesla_is_not_queued_when_it_would_overload_power():
    v = economy(cash=1500, available=['tsla', '3tnk', 'e1', 'e3'],
                enemies=[actor(900, '3tnk', 15, 15)])
    v.econ['power_provided'] = 200
    assert not any(o.get('item') == 'tsla' for o in orders(v))


def test_artillery_does_not_replace_the_first_tanks():
    v = economy(cash=1800, available=['3tnk', 'arty'])
    v.enemy_buildings = [actor(950, 'tsla', 55, 55)]
    assert trained(orders(v)) == ['3tnk']


def test_siege_support_remains_available_after_armor_core():
    v = economy(cash=1800, tanks=3, available=['3tnk', 'arty'])
    v.enemy_buildings = [actor(950, 'tsla', 55, 55)]
    assert trained(orders(v)) == ['arty']


def test_live_tank_prices_control_budget():
    v = economy(cash=1300, available=['3tnk'], miners=1)
    v.rules = {'units': {'3tnk': {'cost': 1800}}}
    assert not trained(orders(v))


def test_rifle_price_is_not_treated_as_equal_antitank_strength():
    v = view()
    v.profile = 'eco_guard'
    rifle_blob = [actor(i) for i in range(40)]
    tanks = [actor(500+i, '3tnk') for i in range(3)]
    assert _matchup_value(v, rifle_blob, tanks) < _matchup_value(v, tanks, rifle_blob)


def test_rifle_only_defenders_do_not_charge_a_home_tank_attack():
    v = view(units=[actor(i, x=15, y=15) for i in range(40)],
             enemies=[actor(500+i, '3tnk', 19, 15) for i in range(3)])
    v.profile = 'eco_guard'
    out, memory = combat(v)
    assert memory['combat']['mode'] == 'defend economy'
    assert all(o['cmd'] == 'move' for o in out)
    assert not any(o.get('to') == [19, 15] for o in out)


def test_unarmored_late_deficit_does_not_force_attack():
    v = view(units=[actor(i) for i in range(40)], remaining=20, military={'deaths_cost': 5000})
    v.profile = 'eco_guard'
    out, memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert not any(o['cmd'] in {'attack', 'attack_move'} for o in out)


def test_armored_wave_can_attack_an_exposed_economic_target():
    army = [actor(i, x=35, y=20) for i in range(1, 7)] + [actor(100+i, '3tnk', 35, 20) for i in range(3)]
    v = view(units=army, forts=[actor(500, 'proc', 40, 20)], military={'deaths_cost': 100})
    v.profile = 'eco_guard'
    out, memory = combat(v)
    assert memory['combat']['mode'] == 'pressure enemy'
    assert any(o.get('target') == 500 or o.get('to') == [40, 20] for o in out)


def test_last_seconds_do_not_disable_unfavorable_engagement_gate():
    army = [actor(i, x=55, y=55) for i in range(1, 9)] + [actor(100+i, '3tnk', 55, 55) for i in range(3)]
    enemies = [actor(500+i, '3tnk', 62, 62) for i in range(6)]
    v = view(units=army, enemies=enemies, remaining=20, military={'deaths_cost': 5000})
    v.profile = 'eco_guard'
    out, memory = combat(v)
    assert memory['combat']['mode'] == 'retreat from bad trade'
    assert all(o['cmd'] == 'move' for o in out)


def test_reserve_does_not_take_all_tanks_away_from_attacking_wave():
    army = [actor(i, x=20, y=20) for i in range(1, 16)] + [actor(100+i, '3tnk', 11, 11) for i in range(3)]
    v = view(units=army, now=480, remaining=120, military={'deaths_cost': 5000})
    v.profile = 'eco_guard'
    out, memory = combat(v)
    assert not {100, 101, 102} & set(memory['combat']['reserve_ids'])
    assert any(set(o.get('units', [])) >= {100, 101, 102} for o in out if o['cmd'] == 'attack_move')


@pytest.mark.parametrize('faction', ['allies', 'soviets'])
@pytest.mark.parametrize('income', [8, 16])
def test_synthetic_ten_minute_economy_produces_tanks_without_infantry_flood(faction, income):
    result = mock_production_progression(faction, 600, income)
    assert sum(t in TANKS for t in result['trained']) >= 3
    assert sum(t in {'e1', 'e3'} for t in result['trained']) <= 24
    assert result['units'].count('harv') >= 4
