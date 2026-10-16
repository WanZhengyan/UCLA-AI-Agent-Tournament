"""Public raid/ambush pattern regressions, not head-to-head win estimates."""
from redalert_bot.agent import validate
from redalert_bot.strategy import blockers, safe_cell
from test_redalert_balance import actor, view, combat


def armored_defenders():
    return [actor(i, '3tnk', 15, 15) for i in range(1, 9)]


def defensive_view(units=None, enemies=None, forts=None, now=150):
    v = view(units=units or armored_defenders(), enemies=enemies,
             forts=forts, now=now)
    v.profile = 'eco_guard'
    return v


def movements(orders):
    return [o for o in orders if o['cmd'] in {'move', 'attack_move', 'attack'}]


def test_small_flank_raid_does_not_pull_every_economic_defender():
    v = defensive_view(enemies=[actor(501, 'ftrk', 23, 10),
                               actor(502, 'ftrk', 24, 10)])
    orders, memory = combat(v)
    response = {i for o in movements(orders) if o.get('to') == [23, 10]
                for i in o['units']}
    assert response and len(response) < len(v.units)
    assert memory['combat']['mode'] == 'defend economy'
    assert all(validate(o, v) for o in orders)


def test_raider_cannot_bait_home_defenders_into_known_tower_fire():
    v = defensive_view(enemies=[actor(501, 'jeep', 27, 10)],
                       forts=[actor(601, 'tsla', 30, 10)])
    orders, memory = combat(v)
    assert movements(orders)
    assert not any(o.get('to') == [27, 10] for o in movements(orders))
    assert all(o['cmd'] == 'move' and safe_cell(v, o['to'])
               for o in movements(orders))
    held = {i for o in movements(orders) for i in o['units']}
    restrained = {i for o in orders if o['cmd'] == 'set_stance' and o['stance'] == 'defend'
                  for i in o['units']}
    assert held <= restrained
    assert all(validate(o, v) for o in orders)


def test_remembered_tower_still_blocks_a_home_defense_pursuit():
    _, memory = combat(defensive_view(forts=[actor(601, 'tsla', 30, 10)]))
    later = defensive_view(enemies=[actor(501, 'jeep', 27, 10)], now=151)
    orders, _ = combat(later, memory)
    assert not any(o.get('to') == [27, 10] for o in movements(orders))
    assert all(o['cmd'] != 'attack' for o in orders)


def test_full_incursion_can_still_mobilize_all_ground_defenders():
    v = defensive_view(enemies=[actor(501+i, '3tnk', 23, 10)
                               for i in range(7)])
    orders, _ = combat(v)
    response = {i for o in movements(orders) if o.get('to') == [23, 10]
                for i in o['units']}
    assert response == {u['id'] for u in v.units}


def test_existing_raid_response_is_stable_when_other_units_become_closer():
    units = armored_defenders()
    enemy = actor(501, 'ftrk', 23, 10)
    first, memory = combat(defensive_view(units=units, enemies=[enemy]))
    response = {i for o in movements(first) if o.get('to') == [23, 10]
                for i in o['units']}
    assert response and len(response) < len(units)
    for unit in units:
        unit['idle'] = False
        if unit['id'] not in response:
            unit.update(x=22, y=10)
    _, memory = combat(defensive_view(units=units, enemies=[enemy], now=150.2), memory)
    assigned = {int(i) for i, row in memory['combat']['unit_orders'].items()
                if row['mode'] == 'defend'}
    assert assigned == response


def test_fleeing_raid_is_released_when_it_leaves_the_economy():
    units = armored_defenders()
    _, memory = combat(defensive_view(units=units,
                                      enemies=[actor(501, 'ftrk', 23, 10)]))
    for unit in units:
        unit['idle'] = False
    later = defensive_view(units=units, enemies=[actor(501, 'ftrk', 45, 10)], now=151)
    orders, memory = combat(later, memory)
    assert memory['combat']['mode'] == 'guard economy'
    assert all(o.get('to') != [45, 10] for o in movements(orders))
    assert any(o['cmd'] == 'move' for o in orders)


def test_enemy_tower_on_defense_path_blocks_even_if_target_cell_is_safe():
    v = defensive_view(units=[actor(i, '3tnk', 28, 10) for i in range(1, 9)],
                       enemies=[actor(501, 'jeep', 8, 10)],
                       forts=[actor(601, 'tsla', 18, 10)])
    # The live range makes the destination safe but the direct approach unsafe.
    v.rules = {'buildings': {'tsla': {'weapon': {'range': 6}}}}
    orders, _ = combat(v)
    assert safe_cell(v, (8, 10))
    assert not any(o.get('to') == [8, 10] for o in movements(orders))
    assert all(o['cmd'] == 'move' for o in movements(orders))


def test_unassigned_reserve_does_not_cross_a_tower_to_return_home():
    v = defensive_view(units=[actor(i, '3tnk', 45, 10) for i in range(1, 9)],
                       enemies=[actor(501, 'jeep', 27, 10)],
                       forts=[actor(601, 'tsla', 30, 10)])
    orders, _ = combat(v)
    assert movements(orders)
    assert all(not blockers(v, (45, 10), o['to']) for o in movements(orders))


def test_weak_reserve_keeps_local_cover_without_global_retreat():
    units = [actor(i, '3tnk', 45, 10) for i in (1, 2)]
    units += [actor(i, 'e1', 45, 10) for i in (3, 4)]
    v = defensive_view(units=units,
                       enemies=[actor(501, 'ftrk', 27, 10), actor(502, 'ftrk', 27, 11)],
                       forts=[actor(601, 'tsla', 30, 10)])
    orders, memory = combat(v)
    assert movements(orders)
    assert all(not blockers(v, (45, 10), o['to']) for o in movements(orders))
    assert 'retreat_until' not in memory['combat']
    for unit in units:
        unit['idle'] = False
    v.now += .2
    following, memory = combat(v, memory)
    assert 'retreat_until' not in memory['combat']
    assert not any(o.get('to') == [15, 15] for o in movements(following))


def test_enemy_force_behind_bait_cannot_trigger_tower_crossing_retreat():
    enemies = [actor(501, 'ftrk', 27, 10), actor(502, 'ftrk', 27, 11)]
    enemies += [actor(510+i, '3tnk', 33, 10) for i in range(8)]
    v = defensive_view(units=[actor(i, '3tnk', 45, 10) for i in range(1, 9)],
                       enemies=enemies, forts=[actor(601, 'tsla', 30, 10)])
    orders, memory = combat(v)
    assert movements(orders)
    assert all(not blockers(v, (45, 10), o['to']) for o in movements(orders))
    assert 'retreat_until' not in memory['combat']
