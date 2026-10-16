"""Tank-budget regressions and synthetic production checks, not win-rate tests."""
from unittest.mock import patch

import pytest

from redalert_bot.strategy import TANKS
from test_redalert_armor import economy, trained
from test_redalert_balance import actor
from test_redalert_economy import orders
from test_redalert_policy import mock_production_progression


def test_support_rocket_does_not_consume_the_next_tank_budget():
    v = economy(cash=700, rifles=6, rockets=0)
    assert trained(orders(v)) == ['3tnk']


def test_tank_already_in_production_keeps_its_operating_cash():
    v = economy(cash=400, rifles=6, rockets=0,
                production=[{'item': '3tnk', 'queue': 'Vehicle', 'progress': .2}])
    assert not trained(orders(v))


def test_nonurgent_defense_must_leave_the_next_tank_budget():
    v = economy(cash=900, available=['3tnk', 'pbox'])
    out = orders(v)
    assert trained(out) == ['3tnk']
    assert not any(o.get('item') == 'pbox' for o in out)


def test_actual_infantry_attack_can_still_trigger_emergency_defense():
    v = economy(cash=900, available=['3tnk', 'pbox'],
                enemies=[actor(500+i, 'e1', 15, 15) for i in range(6)])
    out = orders(v)
    assert {'cmd': 'build', 'item': 'pbox'} in out
    assert '3tnk' in trained(out)


def test_visible_air_attack_can_still_get_emergency_rockets():
    v = economy(cash=200, rifles=6, rockets=0,
                enemies=[actor(500, 'mig', 15, 15)])
    assert trained(orders(v)) == ['e3']


def test_third_refinery_waits_for_tank_core_on_a_small_budget():
    out = orders(economy(cash=700, tanks=3, available=['proc', '3tnk']))
    assert trained(out) == ['3tnk']
    assert not any(o.get('item') == 'proc' for o in out)


def test_refinery_growth_resumes_after_tank_core_without_full_price_cash():
    out = orders(economy(cash=700, tanks=6, available=['proc', '3tnk']))
    assert {'cmd': 'build', 'item': 'proc'} in out


def test_optional_radar_does_not_take_tank_budget():
    out = orders(economy(cash=1200, tanks=3, available=['dome', '3tnk']))
    assert trained(out) == ['3tnk']
    assert not any(o.get('item') == 'dome' for o in out)


@pytest.mark.parametrize('tanks,cash,expected', [(3, 5000, '3tnk'),
                                               (6, 3000, '3tnk'),
                                               (6, 3500, 'mcv')])
def test_expansion_mcv_requires_tank_core_and_keeps_operating_budget(tanks, cash, expected):
    v = economy(cash=cash, tanks=tanks, available=['mcv', '3tnk'])
    with patch('redalert_bot.economy._expansion_window', return_value=True), \
            patch('redalert_bot.economy._expansion_site', return_value=(40, 10)):
        assert trained(orders(v)) == [expected]


# Before this change, the same 600-second progressive-payment fixture made
# 4/3 tanks at income 8 and 14/11 at income 16 (Allies/Soviets). These floors
# detect renewed infantry/budget starvation; the fixture does not simulate
# fighting, map income, real build speeds, or match outcomes.
@pytest.mark.parametrize('faction,income,tank_floor', [
    ('allies', 8, 6), ('soviets', 8, 5),
    ('allies', 16, 16), ('soviets', 16, 11),
])
def test_ten_minute_tank_throughput_with_lower_support_spending(faction, income, tank_floor):
    result = mock_production_progression(faction, 600, income)
    assert sum(t in TANKS for t in result['trained']) >= tank_floor
    assert sum(t in {'e1', 'e3'} for t in result['trained']) <= 9
    assert result['units'].count('harv') >= 4
    assert {'weap', 'fix'} <= set(result['buildings'])
