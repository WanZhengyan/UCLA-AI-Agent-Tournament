"""Current owned-team visibility regressions; not a combat or win-rate model."""
from copy import deepcopy

import pytest

from hok_platform.agent import create_agent
from test_hok_platform import action, choose, hero, mine, sample, tick


def shared_scene(*, camp=1, enemies=(), structures=(), macros=None, size=2):
    seats = list(range((camp - 1) * 5, (camp - 1) * 5 + size))
    raw = sample(camp=camp, seats=seats, structures=structures,
                 macros=macros or ['macro_advance', 'macro_retreat', 'macro_attack'],
                 pending=[seats[0]])
    for seat in seats[1:]:
        mine(raw, seat)['x'] = 40000
    raw['observation']['seats'][str(seats[-1])]['summary']['other_heroes'] = deepcopy(list(enemies))
    return raw


def views(raw):
    return [raw['observation']['seats'][str(seat)]['summary'] for seat in raw['seats']]


@pytest.mark.parametrize('camp', [1, 2])
def test_team_only_visible_outnumbering_prevents_feeding_at_our_tower(camp):
    enemies = [hero(200 + i, 3 - camp, x=1000 + 1000 * i, visible=True) for i in range(3)]
    raw = shared_scene(camp=camp, enemies=enemies,
                       structures=[hero(300, camp, type='ACTOR_TOWER')])
    bot = create_agent()
    assert choose(bot, raw) == {'seat': raw['seats'][0], 'macro': 'macro_retreat'}
    assert bot.last_diagnostics['reason'] == 'local_disadvantage'


@pytest.mark.parametrize('camp', [1, 2])
def test_team_only_visible_defender_prevents_unsupported_siege(camp):
    raw = shared_scene(camp=camp, enemies=[hero(200, 3 - camp, x=9500, visible=True)],
                       structures=[hero(300, 3 - camp, x=9000, type='ACTOR_TOWER')])
    for offered in raw['legal_actions']['actions']:
        if offered['action_id'].endswith(':macro_attack'):
            offered['label'] = 'Attack nearest enemy tower (9000 away)'
    bot = create_agent()
    assert choose(bot, raw)['macro'] == 'macro_retreat'
    assert bot.last_diagnostics['reason'] == 'siege_regroup'


def test_team_only_visible_lane_blocker_is_fought_not_walked_through():
    raw = shared_scene(enemies=[hero(200, 2, x=6500, visible=True)],
                       structures=[hero(300, 2, x=20000, type='ACTOR_TOWER')])
    raw['legal_actions']['actions'].append(action(0, 'macro_skill1', 'Cast toward enemy hero (6500 away)'))
    bot = create_agent()
    assert choose(bot, raw)['macro'] == 'macro_skill1'
    assert bot.last_diagnostics['reason'] == 'combat_skill'


def test_low_health_bait_does_not_hide_team_visible_backup():
    bait = hero(200, 2, hp=100, x=1000, visible=True)
    raw = shared_scene(enemies=[bait, hero(201, 2, x=2000, visible=True),
                                hero(202, 2, x=3000, visible=True)])
    views(raw)[0]['other_heroes'] = [bait]
    assert choose(create_agent(), raw)['macro'] == 'macro_retreat'


@pytest.mark.parametrize('identity', ['runtime', 'hero', 'mixed'])
def test_one_enemy_reported_by_five_heroes_is_not_five_opponents(identity):
    raw = shared_scene(size=5)
    for index, view in enumerate(views(raw)):
        enemy = hero(200, 2, x=1000 + index * 100, hero_id=27, visible=True)
        if identity == 'hero' or (identity == 'mixed' and index > 0):
            del enemy['runtime_id']
        view['other_heroes'] = [enemy]
    assert choose(create_agent(), raw)['macro'] == 'macro_attack'


def test_supported_team_can_still_fight_shared_visible_enemies():
    raw = shared_scene(enemies=[hero(200 + i, 2, x=1000 + i * 500, visible=True) for i in range(3)], size=5)
    for seat in raw['seats'][1:]:
        mine(raw, seat)['x'] = 1000
    assert choose(create_agent(), raw)['macro'] == 'macro_attack'


@pytest.mark.parametrize('changes', [
    {'visible': False}, {'visible': 1}, {'hp': 0}, {'hp': True}, {'hp': float('nan')},
    {'hp': '1000'}, {'max_hp': 0}, {'max_hp': float('inf')}, {'revive_time': 1},
    {'revive_time': '0'}, {'revive_time': -1}, {'x': float('nan')}, {'z': None},
    {'x': True}, {'camp': 1}, {'camp': 2.0}, {'camp': '2'}, {'level': float('inf')},
    {'level': '5'}, {'runtime_id': True}, {'runtime_id': -1}, {'runtime_id': '200'},
    {'hero_id': []}, {'runtime_id': None},
])
def test_hidden_dead_malformed_or_unidentified_shared_records_do_not_create_threats(changes):
    enemies = []
    for index in range(3):
        enemy = hero(200 + index, 2, x=1000 + index * 500, visible=True)
        enemy.update(changes)
        enemies.append(enemy)
    raw = shared_scene(enemies=enemies, macros=['macro_advance', 'macro_retreat'])
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_boolean_camp_cannot_impersonate_camp_one():
    raw = shared_scene(camp=2, enemies=[hero(200 + i, True, x=1000 + i, visible=True) for i in range(3)],
                       macros=['macro_advance', 'macro_retreat'])
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_unowned_seat_view_is_never_team_intelligence():
    raw = shared_scene(macros=['macro_advance', 'macro_retreat'])
    raw['seats'].append(5)  # Contradicts our camp: this is not an owned seat.
    raw['observation']['seats']['5'] = {'summary': {'other_heroes': [
        hero(200 + i, 2, x=1000 + i, visible=True) for i in range(3)]}}
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_hidden_duplicate_cannot_override_a_visible_team_contact():
    enemies = [hero(200 + i, 2, x=1000 + i, visible=True) for i in range(3)]
    raw = shared_scene(enemies=enemies)
    views(raw)[0]['other_heroes'] = [dict(enemy, visible=False, x=None, z=None) for enemy in enemies]
    assert choose(create_agent(), raw)['macro'] == 'macro_retreat'


def test_removed_contacts_are_not_kept_as_enemy_position_history():
    raw = shared_scene(enemies=[hero(200 + i, 2, x=1000 + i, visible=True) for i in range(3)],
                       macros=['macro_advance', 'macro_retreat'])
    bot = create_agent()
    assert choose(bot, raw)['macro'] == 'macro_retreat'
    for view in views(raw):
        view['other_heroes'] = []
    tick(raw, steps=15)  # The existing two-second regroup hysteresis has expired.
    assert choose(bot, raw)['macro'] == 'macro_advance'


def test_far_team_visible_contacts_do_not_count_as_local_opponents():
    raw = shared_scene(enemies=[hero(200 + i, 2, x=30000 + i, visible=True) for i in range(3)],
                       macros=['macro_advance', 'macro_retreat'])
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_contradictory_runtime_and_hero_identities_are_not_trusted():
    raw = shared_scene(macros=['macro_advance', 'macro_retreat'])
    for index, view in enumerate(views(raw)):
        view['other_heroes'] = [hero(200 + i, 2, x=1000 + i, hero_id=20 + i + index * 10,
                                    visible=True) for i in range(3)]
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_contact_scan_is_bounded_even_with_oversized_server_records():
    raw = shared_scene(enemies=[hero(200, 2, x=30000, visible=False)] * 10 + [
        hero(300 + i, 2, x=1000, visible=True) for i in range(1000)],
        macros=['macro_advance', 'macro_retreat'])
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


def test_collecting_shared_contacts_never_mutates_server_observations():
    raw = shared_scene(enemies=[hero(200, 2, x=1000, visible=True)], size=5)
    before = deepcopy(raw)
    choose(create_agent(), raw)
    assert raw == before


def test_tower_defense_keeps_legal_minion_clear_before_optional_hero_skill():
    raw = shared_scene(enemies=[hero(200, 2, x=1000, visible=True)],
                       structures=[hero(300, 1, type='ACTOR_TOWER')])
    for offered in raw['legal_actions']['actions']:
        if offered['action_id'].endswith(':macro_attack'):
            offered['label'] = 'Attack nearest enemy minion (1000 away)'
    raw['legal_actions']['actions'].append(action(0, 'macro_skill1', 'Cast toward enemy hero (1000 away)'))
    bot = create_agent()
    assert choose(bot, raw)['macro'] == 'macro_attack'
    assert bot.last_diagnostics['reason'] == 'tower_defense'
