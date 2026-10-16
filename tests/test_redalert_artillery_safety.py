"""Rear artillery cancels stale attacks instead of chasing moving bait."""
from redalert_bot.agent import validate
from redalert_bot.combat import _rear_artillery
from test_redalert_balance import actor, view


class Recorder:
    """Apply the production emitter's per-key cooldown and acceptance rule."""
    def __init__(self, v):
        self.v, self.orders, self.cooldowns = v, [], {}
        self.reject_target = None
        self.reject_moves = False

    def __call__(self, order, *, key, cooldown):
        if self.cooldowns.get(key, -1) > self.v.now:
            return False
        if order.get('target') == self.reject_target and order['cmd'] == 'attack':
            return False
        if self.reject_moves and order['cmd'] in {'move', 'stop'}:
            return False
        self.orders.append(order)
        self.cooldowns[key] = self.v.now+cooldown
        return True


def artillery():
    gun = actor(90, 'arty', 14, 10)
    gun['idle'] = False
    tanks = [actor(1, '3tnk', 19, 10), actor(2, '3tnk', 19, 11)]
    target = actor(901, '3tnk', 23, 10)
    v = view(units=[gun]+tanks, enemies=[target])
    v.profile = 'eco_guard'
    return v, gun, tanks, {}, Recorder(v)


def frame(v, gun, tanks, memory, emit):
    emit.orders = []
    _rear_artillery(v, memory, emit, [gun], tanks, (18, 10), v.enemies)
    assert all(validate(o, v) for o in emit.orders)
    return [o for o in emit.orders if o['cmd'] in {'attack', 'move', 'attack_move', 'stop'}]


def move_old_target_out_of_range(v):
    v.now += .2
    v.enemies[0]['x'] = 28
    v.enemies.append(actor(902, '3tnk', 24, 10))


def test_artillery_immediately_retargets_when_old_target_moves_out_of_range():
    v, gun, tanks, memory, emit = artillery()
    assert frame(v, gun, tanks, memory, emit) == [{'cmd': 'attack', 'units': [90], 'target': 901}]
    move_old_target_out_of_range(v)
    orders = frame(v, gun, tanks, memory, emit)
    assert orders == [{'cmd': 'attack', 'units': [90], 'target': 902}]
    assert memory['unit_orders']['90']['target'] == 902


def test_refused_retarget_cancels_unsafe_old_attack_with_a_local_hold():
    v, gun, tanks, memory, emit = artillery()
    frame(v, gun, tanks, memory, emit)
    move_old_target_out_of_range(v)
    emit.reject_target = 902
    orders = frame(v, gun, tanks, memory, emit)
    assert orders == [{'cmd': 'stop', 'units': [90]}]
    assert memory['unit_orders']['90']['command'] == 'stop'
    assert memory['unit_orders']['90']['target'] is None


def test_refused_retarget_and_hold_do_not_falsely_update_order_history():
    v, gun, tanks, memory, emit = artillery()
    frame(v, gun, tanks, memory, emit)
    original = dict(memory['unit_orders']['90'])
    move_old_target_out_of_range(v)
    emit.reject_target, emit.reject_moves = 902, True
    assert frame(v, gun, tanks, memory, emit) == []
    assert memory['unit_orders']['90'] == original
    v.now += .2
    emit.reject_target, emit.reject_moves = None, False
    assert frame(v, gun, tanks, memory, emit) == [{'cmd': 'attack', 'units': [90], 'target': 902}]


def test_unchanged_in_range_target_keeps_its_attack_without_order_churn():
    v, gun, tanks, memory, emit = artillery()
    frame(v, gun, tanks, memory, emit)
    original = dict(memory['unit_orders']['90'])
    v.now += .2
    assert frame(v, gun, tanks, memory, emit) == []
    assert memory['unit_orders']['90'] == original


def test_no_replacement_target_cancels_out_of_range_attack():
    v, gun, tanks, memory, emit = artillery()
    frame(v, gun, tanks, memory, emit)
    v.now += .2
    v.enemies[0]['x'] = 28
    orders = frame(v, gun, tanks, memory, emit)
    assert orders and all(o['cmd'] == 'move' for o in orders)
    assert memory['unit_orders']['90']['target'] is None


def test_retired_target_cooldown_cannot_leave_another_stale_attack_running():
    v, gun, tanks, memory, emit = artillery()
    v.enemies.append(actor(902, '3tnk', 24, 10))
    v.enemies[1]['hp'] = 10
    assert frame(v, gun, tanks, memory, emit)[0]['target'] == 902
    v.now += .2
    v.enemies[0]['hp'], v.enemies[1]['hp'] = 5, 100
    assert frame(v, gun, tanks, memory, emit)[0]['target'] == 901
    v.now += .2
    v.enemies[0]['x'] = 28
    orders = frame(v, gun, tanks, memory, emit)
    assert orders == [{'cmd': 'stop', 'units': [90]}]
    assert memory['unit_orders']['90']['command'] == 'stop'


def test_refused_artillery_retarget_stops_by_id_even_outside_navigation_component():
    v, gun, tanks, memory, emit = artillery()
    frame(v, gun, tanks, memory, emit)
    move_old_target_out_of_range(v)
    v.navigation = {'parents': {(5, 10): None}, 'distances': {(5, 10): 0}}
    v.map_plan = {'active': True}
    emit.reject_target = 902
    orders = frame(v, gun, tanks, memory, emit)
    assert orders == [{'cmd': 'stop', 'units': [90]}]
