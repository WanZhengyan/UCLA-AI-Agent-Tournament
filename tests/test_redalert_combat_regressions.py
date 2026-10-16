"""Multi-observation regressions for disengagement and shared command ownership."""
import pytest

from redalert_bot.agent import RedAlertAgent
from test_redalert_balance import actor, view, combat
from test_redalert_policy import fixture, decide


def test_retreat_remains_a_move_on_the_following_observation():
    army = [actor(i, x=55, y=55) for i in range(1, 9)]
    army += [actor(100+i, '3tnk', 55, 55) for i in range(3)]
    enemies = [actor(500+i, '3tnk', 62, 62) for i in range(6)]
    v = view(units=army, enemies=enemies, remaining=20,
             military={'deaths_cost': 5000})
    v.profile = 'eco_guard'
    first, memory = combat(v)
    assert memory['combat']['mode'] == 'retreat from bad trade'
    goal = memory['combat']['retreat_goal']
    assert all(o['cmd'] == 'move' for o in first)

    for unit in army:
        unit['idle'] = False
    later = view(units=army, now=150.2, remaining=19.8,
                 military={'deaths_cost': 5000})
    later.profile = 'eco_guard'
    following, memory = combat(later, memory)
    assert memory['combat']['mode'] == 'regroup'
    assert following
    assert all(o['cmd'] == 'move' and o['to'] == goal for o in following)


def air_attack_fixture(rifles=10, ground_attack=False):
    raw = fixture(seconds=150, session='air-defense')
    obs = raw['observation']
    obs.update(base_center=[10, 10],
               buildings=[actor(999, 'fact', 10, 10)],
               units=[actor(1, 'e3', 15, 15)]
                     + [actor(i, x=15, y=15) for i in range(2, rifles+2)],
               visible_enemies=[actor(500, 'mig', 17, 17)])
    if ground_attack:
        obs['visible_enemies'].append(actor(501, x=18, y=15))
    return raw


@pytest.mark.parametrize('ground_attack', [False, True])
def test_aa_assignment_does_not_block_the_rest_of_the_army(ground_attack):
    raw = air_attack_fixture(ground_attack=ground_attack)
    out = decide(RedAlertAgent('eco_guard'), raw)
    movements = [o for o in out if o['cmd'] in {'move', 'attack_move', 'attack'}]
    assert any(o['units'] == [1] and o.get('to') == [17, 17] for o in movements)
    ground_ids = {i for o in movements if 1 not in o['units'] for i in o['units']}
    assert ground_ids == set(range(2, 12))
    all_ids = [i for o in movements for i in o['units']]
    assert len(all_ids) == len(set(all_ids))


def test_aa_assignment_survives_next_frame_then_rejoins_when_aircraft_leaves():
    raw = air_attack_fixture()
    bot = RedAlertAgent('eco_guard')
    decide(bot, raw)
    for unit in raw['observation']['units']:
        unit['idle'] = False
    raw['state_version'] += 5
    raw['time']['game_seconds'] += .2
    following = decide(bot, raw)
    assert not any(1 in o.get('units', []) for o in following
                   if o['cmd'] in {'move', 'attack_move', 'attack'})
    history = bot.sessions['air-defense']['combat']['combat']['unit_orders']
    assert history['1']['mode'] == 'anti-air'

    raw['state_version'] += 5
    raw['time']['game_seconds'] += .2
    raw['observation']['visible_enemies'] = []
    released = decide(bot, raw)
    assert any(o['cmd'] == 'move' and 1 in o['units'] for o in released)
    assert bot.sessions['air-defense']['combat']['combat']['unit_orders']['1']['mode'] == 'hold'


def test_rocket_only_army_can_remain_on_air_defense():
    out = decide(RedAlertAgent('eco_guard'), air_attack_fixture(rifles=0))
    assert any(o['cmd'] == 'attack_move' and o['units'] == [1] for o in out)
