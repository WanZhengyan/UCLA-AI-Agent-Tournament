from redalert_bot.common import View
from redalert_bot.combat import plan


def actor(ident, typ='e1', x=15, y=15, **kw):
    return dict(id=ident, type=typ, x=x, y=y, hp=100, idle=True, **kw)


def view(units, enemies=(), enemy_buildings=(), now=150, remaining=600, military=None):
    return View({'state_version': int(now*25), 'phase': 'playing',
                 'time': {'game_seconds': now, 'remaining_seconds': remaining},
                 'map': {'bounds': [0, 0, 100, 100]},
                 'legal_actions': {'enemy_base': [80, 80]},
                 'observation': {'units': units, 'buildings': [actor(999, 'fact', 10, 10)],
                                 'base_center': [10, 10], 'visible_enemies': list(enemies),
                                 'visible_enemy_buildings': list(enemy_buildings),
                                 'military': military or {}}})


def run(v, memory=None):
    memory = memory if memory is not None else {'combat': {'scouted': True}}
    orders = []
    def emit(order, **kw):
        orders.append(order)
        return True
    plan(v, memory, emit)
    return orders, memory


def test_support_units_and_wrecks_never_join_army():
    units = [actor(1), actor(2, 'harv'), actor(3, 'mcv'), actor(4, 'medi'),
             actor(5, 'e6'), actor(6, 'ss'), actor(7, '1tnkhusk', wreck=True), actor(8, 'mig')]
    orders, _ = run(view(units))
    assert orders
    assert {i for o in orders for i in o['units']} == {1}


def test_grouped_wave_advances_and_does_not_spam_active_orders():
    units = [actor(i) for i in range(1, 14)]
    orders, memory = run(view(units))
    advancing = [o for o in orders if o.get('to') == [80,80]]
    assert advancing and advancing[0]['cmd'] == 'attack_move'
    assert len(memory['combat']['reserve_ids']) == 2
    assert not set(memory['combat']['reserve_ids']).intersection(advancing[0]['units'])
    for a in units:
        a['idle'] = False
    following, _ = run(view(units, now=150.2), memory)
    assert following == []


def test_threat_to_economy_recalls_defenders():
    units = [actor(i) for i in range(1, 14)]
    enemy = actor(50, 'e1', 18, 11)
    orders, memory = run(view(units, enemies=[enemy]))
    assert memory['combat']['mode'] == 'defend economy'
    assert orders[0]['to'] == [18, 11]


def test_positive_tiebreak_lead_keeps_army_safe_at_end():
    units = [actor(i, x=70, y=70) for i in range(1, 14)]
    orders, memory = run(view(units, remaining=50, military={'kills_cost': 3000, 'deaths_cost': 2000}))
    assert memory['combat']['mode'] == 'protect lead'
    assert orders[0]['to'][0] < 10
    assert orders[0]['to'][1] < 10


def test_outmatched_front_disengages_from_teslas():
    units = [actor(i, x=60, y=60) for i in range(1, 14)]
    defenses = [actor(80, 'tsla', 66, 64), actor(81, 'tsla', 65, 68)]
    orders, memory = run(view(units, enemy_buildings=defenses))
    assert memory['combat']['mode'] == 'contain fortifications'
    assert orders[0]['cmd'] == 'move'
    assert orders[0]['to'][0] < 60
    from redalert_bot.common import distance
    for order in orders:
        if 'to' in order:
            assert all(distance(order['to'],(d['x'],d['y']))>10 for d in defenses)


def test_cleared_spawn_triggers_map_sweep():
    units = [actor(i, x=80, y=80) for i in range(1, 14)]
    orders, memory = run(view(units))
    assert memory['combat']['spawn_checked'] is True
    assert orders[0]['to'] != [80, 80]


def test_failed_emit_does_not_consume_unit_command_history():
    v = view([actor(i) for i in range(1, 14)])
    memory = {'combat': {'scouted': True}}
    plan(v, memory, lambda *args, **kwargs: False)
    assert memory['combat']['unit_orders'] == {}
    orders, _ = run(v, memory)
    assert orders


def test_groups_obey_unit_limit():
    units = [actor(i) for i in range(1, 104)]
    orders, _ = run(view(units))
    assert all(0 < len(order['units']) <= 50 for order in orders)
    assert sum(len(order['units']) for order in orders) == 103


def test_nearby_visible_passive_building_gets_explicit_finish_attack():
    units = [actor(i, x=73, y=74) for i in range(1, 14)]
    building = actor(80, 'proc', 78, 78)
    orders, memory = run(view(units, enemy_buildings=[building]))
    shots = [o for o in orders if o['cmd'] == 'attack']
    assert shots and shots[0]['target'] == building['id']
    assert 'to' not in shots[0]
    for a in units:
        a['idle'] = False
    next_orders, _ = run(view(units, enemy_buildings=[building], now=151), memory)
    assert next_orders == []


def test_remembered_hidden_building_only_gets_movement_not_target_attack():
    units = [actor(i, x=73, y=74) for i in range(1, 14)]
    memory = {'combat': {'scouted': True, 'enemy_sites': {'80': {'cell': [78, 78], 'type': 'proc', 'seen': 100}}}}
    orders, _ = run(view(units), memory)
    assert orders
    assert all(o['cmd'] != 'attack' for o in orders)
    assert orders[0]['to'] == [78, 78]


def test_custom_lower_unit_limit_is_honoured():
    units = [actor(i) for i in range(1, 25)]
    v = view(units)
    v.raw['limits'] = {'max_units_per_order': 7}
    orders, _ = run(v)
    assert max(len(o['units']) for o in orders) <= 7


def test_final_seconds_behind_releases_last_surviving_unit():
    orders, memory = run(view([actor(1)], remaining=40,
                              military={'kills_cost': 100, 'deaths_cost': 500}))
    assert memory['combat']['mode'] == 'pressure enemy'
    assert orders[0]['cmd'] == 'attack_move'
    assert orders[0]['to'] == [80, 80]


def test_equal_kill_balance_does_not_force_lone_survivor_to_charge():
    orders, memory = run(view([actor(1)], remaining=40,
                              military={'kills_cost': 500, 'deaths_cost': 500}))
    assert memory['combat']['mode'] == 'gather wave'
    assert orders[0]['to'] != [80, 80]
