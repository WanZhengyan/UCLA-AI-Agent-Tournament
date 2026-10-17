"""Projected power regressions; these fixtures do not simulate matches."""

import pytest

from redalert_bot.common import View
from redalert_bot.economy import plan


def power_view(*, production=(), margin=60, available=('gun',), rules=None,
               threatened=True, profile='eco_guard', extra_buildings=(),
               enemy_kind='3tnk'):
    def actor(ident, kind, x=12, y=12):
        return dict(id=ident, type=kind, x=x, y=y, hp=100, idle=False)

    kinds = ['fact', 'powr', 'powr', 'barr', 'proc', 'proc', 'weap', 'fix']
    buildings = [actor(i, kind) for i, kind in enumerate(kinds, 1)]
    buildings += [actor(50+i, kind) for i, kind in enumerate(extra_buildings)]
    units = [actor(100+i, 'harv') for i in range(4)]
    units += [actor(200+i, '2tnk') for i in range(5)]
    raw = {
        'map': {'bounds': [0, 0, 100, 100]},
        'time': {'game_seconds': 400, 'remaining_seconds': 800},
        'legal_actions': {'enemy_base': [80, 80]},
        'observation': {
            'base_center': [10, 10], 'buildings': buildings, 'units': units,
            'production': list(production), 'available_production': list(available),
            'economy': {'cash': 3000, 'power_provided': 200,
                        'power_drained': 200-margin},
            'visible_enemies': [actor(400+i, enemy_kind, 17, 10)
                                for i in range(6 if enemy_kind == 'e1' else 1)]
                               if threatened else [],
        },
    }
    v = View(raw, {'rules': {'buildings': rules or {}}})
    v.profile = profile
    return v


def build_orders(v, *, reject=()):
    out = []

    def emit(order, **kwargs):
        if order.get('item') in reject and order['cmd'] == 'build':
            return False
        out.append(order)
        return True

    plan(v, {}, emit)
    return [order['item'] for order in out if order['cmd'] == 'build']


@pytest.mark.parametrize('ready', [False, True])
def test_refinery_commitment_prevents_powered_defense_brownout(ready):
    v = power_view(production=[{'item': 'proc', 'queue': 'Building',
                               'progress': 1 if ready else .5, 'ready': ready}])
    assert 'gun' not in build_orders(v)


def test_same_batch_refinery_and_defense_share_power_headroom():
    v = power_view(available=['proc', 'gun'], threatened=False)
    assert build_orders(v) == ['proc']


def test_queued_defense_is_reserved_before_new_refinery():
    v = power_view(production=[{'item': 'gun', 'queue': 'Defense'}],
                   available=['powr', 'proc'], threatened=False)
    assert build_orders(v) == ['powr']


def test_all_queued_copies_count_toward_future_power():
    v = power_view(margin=80, production=[{'item': 'proc', 'count': 2}])
    assert 'gun' not in build_orders(v)


def test_sufficient_power_still_allows_defense_with_pending_refinery():
    v = power_view(margin=80, production=[{'item': 'proc'}])
    assert 'gun' in build_orders(v)


def test_zero_drain_emergency_defense_survives_low_projected_power():
    v = power_view(margin=20, available=['pbox'],
                   production=[{'item': 'proc'}], enemy_kind='e1')
    # A small early screen still selects a pillbox. Three or more tanks
    # intentionally select anti-tank defenses in the mining policy.
    v.units = [u for u in v.units if u['type'] != '2tnk' or u['id'] < 202]
    assert 'pbox' in build_orders(v)


def test_unplaced_generator_does_not_supply_power_early():
    v = power_view(margin=30, production=[{'item': 'powr', 'ready': True}],
                   rules={'powr': {'power': 100}, 'gun': {'power': -40}})
    assert 'gun' not in build_orders(v)


def test_placed_building_load_is_not_counted_twice():
    v = power_view(margin=50, extra_buildings=['proc'])
    assert 'gun' in build_orders(v)


@pytest.mark.parametrize('rules,expected', [
    ({'proc': {'power': -35}, 'gun': {'power': -25}}, False),
    ({'proc': {'power': -5}, 'gun': {'power': -5}}, True),
])
def test_runtime_power_rules_override_fallbacks(rules, expected):
    v = power_view(production=[{'item': 'proc'}], rules=rules)
    assert ('gun' in build_orders(v)) is expected


def test_rejected_build_does_not_reserve_phantom_power():
    v = power_view(available=['proc', 'gun'], threatened=False)
    assert build_orders(v, reject={'proc'}) == ['gun']


def test_balanced_baseline_keeps_existing_behavior():
    v = power_view(production=[{'item': 'proc'}], profile='balanced')
    assert 'gun' in build_orders(v)
