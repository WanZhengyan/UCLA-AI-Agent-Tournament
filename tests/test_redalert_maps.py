"""Synthetic topology checks, not measurements on the three live maps."""
from copy import deepcopy

import pytest

from altruagent.models import DecisionContext, GameState
from redalert_bot.agent import RedAlertAgent, validate
from redalert_bot.common import View
from redalert_bot.maps import adapt, route_safe, nearest_reachable
from redalert_bot.economy import plan as economy, _expansion_window, _expansion_site, _mcv_orders
from redalert_bot.strategy import blockers, safe_cell
from redalert_bot.combat import plan as combat
from test_redalert_balance import actor


def mapped(map_id='sidestep', separation=52, minutes=20, swapped=False, now=150):
    rows = [list('.'*120) for _ in range(120)]
    spawns = [(10,10), (10+separation,10)]
    for x,y in spawns:
        rows[y][x] = 'S'
        for dx in range(-2,3):
            for dy in range(4,8):
                rows[y+dy][x+dx] = '$'
    base, enemy = spawns[::-1] if swapped else spawns
    config = {'rules': {'maps': {map_id: {'bounds': [0,0,120,120], 'spawns': spawns,
                                        'layout': {'origin': [0,0], 'rows': [''.join(r) for r in rows]}}}}}
    raw = {'session_id':'maps', 'phase':'playing', 'is_current_actor':True,
           'state_version': int(now*25), 'map': {'id':map_id, 'bounds':[0,0,120,120]},
           'time': {'game_seconds':now, 'remaining_seconds':minutes*60-now, 'max_minutes':minutes},
           'observation': {'base_center':base, 'units':[actor(i,x=base[0],y=base[1]) for i in range(1,31)],
                           'buildings':[actor(999,'fact',*base)], 'production':[],
                           'available_production':[], 'economy':{'cash':1000,'power_provided':100},
                           'visible_enemies':[], 'visible_enemy_buildings':[]}}
    v = View(raw, config)
    v.profile = 'eco_guard'
    adapt(v, {})
    return v


@pytest.mark.parametrize('map_id,separation,style', [
    ('sidestep',52,'guarded-economy'), ('trapped',57,'guarded-economy'),
    ('shadowfiend-ii',88,'long-route-economy'), ('shadowfiend-ii',98,'long-route-economy')])
@pytest.mark.parametrize('minutes', [10,15,20])
@pytest.mark.parametrize('swapped', [False,True])
def test_public_geometry_selects_parameters_in_both_seats(map_id,separation,style,minutes,swapped):
    v = mapped(map_id,separation,minutes,swapped)
    assert v.map_plan['map_id'] == map_id
    assert v.map_plan['style'] == style
    assert v.map_plan['route_cells'] == separation
    assert v.map_plan['initial_home_resource_cells'] == 20
    assert v.remaining == minutes*60-v.now
    assert tuple(v.map_plan['guard_cell']) in v.navigation['distances']
    assert tuple(v.map_plan['scout_cell']) in v.navigation['distances']


def test_map_name_is_not_a_hardcoded_strategy_and_resources_matter():
    v = mapped('sidestep',98)
    assert v.map_plan['style'] == 'long-route-economy'
    v.ore_cells = []
    adapt(v,{})
    assert v.map_plan['style'] == 'guarded-economy'


def test_missing_public_spawns_does_not_turn_a_mirrored_guess_into_a_macro_opening():
    v = mapped(separation=98)
    del v.map_info['spawns']
    adapt(v,{})
    assert v.map_plan['route_cells'] is None
    assert 'scout_cell' not in v.map_plan
    assert v.map_plan['style'] == 'guarded-economy'


def test_missing_map_falls_back_without_an_exception_or_speculative_route():
    v = mapped()
    v.map_info = {}
    plan = adapt(v,{})
    assert not plan['active'] and plan['style'] == 'fallback'
    assert plan['expansion_margin'] == 7 and plan['expansion_radius'] == 42
    assert nearest_reachable(v,(30,10)) is None
    assert not route_safe(v,(30,10))


@pytest.mark.parametrize('layout', [{'rows':[]}, {'rows':[None]}, {'rows':['...'],'origin':['x',0]}])
def test_partial_layout_disables_adaptation(layout):
    v = mapped()
    v.map_info = {'layout':layout}
    assert not adapt(v,{})['active']


def test_static_topology_is_cached_between_decisions(monkeypatch):
    v, memory = mapped(), {}
    adapt(v,memory)
    import redalert_bot.maps as maps
    monkeypatch.setattr(maps,'_terrain',lambda v: (_ for _ in ()).throw(AssertionError('not cached')))
    later = View(v.raw,v.config)
    assert adapt(later,memory) == v.map_plan


def test_disconnected_terrain_does_not_invent_a_route_or_send_units_to_an_island():
    v = mapped(separation=98)
    layout = v.map_info['layout']
    layout['rows'] = [row[:50]+'~'+row[51:] for row in layout['rows']]
    adapt(v,{})
    assert v.map_plan['route_cells'] is None
    assert v.map_plan['style'] == 'guarded-economy'
    assert nearest_reachable(v,(90,10))[0] < 50
    assert not route_safe(v,(90,10))
    v.ore_cells = [(60,10)]
    assert _expansion_site(v,{}) is None


def test_expansion_time_accounts_for_a_detour_and_live_build_times():
    v = mapped(now=220)
    layout = v.map_info['layout']
    layout['rows'] = [row[:20]+('~' if y < 45 else '.')+row[21:] for y,row in enumerate(layout['rows'])]
    adapt(v,{})
    site = (30,10)
    assert v.navigation['distances'][site] > 20
    memory = {'site_checked_at':v.now, 'expansion_site':site}
    assert _expansion_window(v,memory)
    expected = 60+33.6+7.2+v.navigation['distances'][site]/.5+v.map_plan['productive_window']
    assert memory['expansion_required_seconds'] == pytest.approx(round(expected,1))
    v.remaining = expected-1
    assert not _expansion_window(v,memory)


def test_cached_expansion_is_rechecked_when_a_tower_is_seen():
    v = mapped()
    memory = {'site_checked_at':v.now, 'expansion_site':(30,10)}
    assert _expansion_site(v,memory) == (30,10)
    v.enemy_buildings = [actor(200,'tsla',25,10)]
    v.ore_cells = []
    assert not route_safe(v,(30,10))
    assert _expansion_site(v,memory) is None


def collect(planner,v,memory=None):
    orders, memory = [], memory if memory is not None else {}
    def emit(order, **kwargs):
        orders.append(order)
        return True
    planner(v,memory,emit)
    return orders, memory


def test_rally_projects_water_destination_to_reachable_land():
    v = mapped()
    layout = v.map_info['layout']
    rows = list(layout['rows'])
    # The old direct six-cell rally point is water, but land surrounds it.
    rows[10] = rows[10][:16] + '~' + rows[10][17:]
    layout['rows'] = rows
    adapt(v, {})
    v.buildings.append(actor(800, 'barr', 10, 12))
    orders, _ = collect(economy, v)
    rally = next(o for o in orders if o['cmd'] == 'rally')
    assert rally['to'] != [16, 10]
    assert tuple(rally['to']) in v.navigation['distances']


def test_assigned_mcv_rechecks_new_tower_on_terrain_detour():
    v = mapped()
    layout = v.map_info['layout']
    layout['rows'] = [row[:15] + ('~' if y < 45 else '.') + row[16:]
                      for y, row in enumerate(layout['rows'])]
    adapt(v, {})
    v.units = [dict(actor(400, 'mcv', 10, 10), idle=False)]
    site = (30, 10)
    memory = {'mcv-site-400': site, 'mcv-moving-400': True,
              'expansion_site': site, 'site_checked_at': v.now}
    assert route_safe(v, site)
    # A tower discovered after assignment covers the only land crossing,
    # while the naive straight line from MCV to destination looks safe.
    v.enemy_buildings = [actor(200, 'tsla', 15, 45)]
    assert not blockers(v, (10, 10), site)
    assert not route_safe(v, site)
    orders, memory = collect(_mcv_orders, v, memory)
    assert orders == [{'cmd': 'move', 'units': [400], 'to': [10, 10]}]
    assert 'mcv-site-400' not in memory and 'mcv-moving-400' not in memory
    assert memory['expansion_site'] is None
    assert memory['site_checked_at'] == -1000


def test_assigned_mcv_rechecks_enemy_at_destination_before_arrival():
    v = mapped()
    v.units = [dict(actor(400, 'mcv', 10, 10), idle=False)]
    site = (40, 10)
    memory = {'mcv-site-400': site, 'mcv-moving-400': True}
    v.obs['visible_enemies'] = [actor(200, '3tnk', *site)]
    orders, memory = collect(_mcv_orders, v, memory)
    assert orders == [{'cmd': 'move', 'units': [400], 'to': [10, 10]}]
    assert 'mcv-site-400' not in memory


def test_safe_assigned_mcv_keeps_existing_movement():
    v = mapped()
    v.units = [dict(actor(400, 'mcv', 10, 10), idle=False)]
    memory = {'mcv-site-400': (30, 10), 'mcv-moving-400': True}
    orders, memory = collect(_mcv_orders, v, memory)
    assert not orders
    assert memory['mcv-site-400'] == (30, 10)


def test_mcv_past_new_tower_keeps_safe_remaining_route():
    v = mapped()
    v.units = [dict(actor(400, 'mcv', 35, 10), idle=False)]
    v.enemy_buildings = [actor(200, 'tsla', 20, 10)]
    memory = {'mcv-site-400': (40, 10), 'mcv-moving-400': True}
    assert not route_safe(v, (40, 10))
    assert route_safe(v, (40, 10), start=(35, 10))
    orders, memory = collect(_mcv_orders, v, memory)
    assert not orders
    assert memory['mcv-site-400'] == (40, 10)


def test_mcv_does_not_recall_through_tower_when_destination_is_lost():
    v = mapped()
    v.units = [dict(actor(400, 'mcv', 35, 10), idle=False)]
    v.enemy_buildings = [actor(200, 'tsla', 20, 10)]
    v.obs['visible_enemies'] = [actor(201, '3tnk', 45, 10)]
    memory = {'mcv-site-400': (45, 10), 'mcv-moving-400': True}
    orders, memory = collect(_mcv_orders, v, memory)
    assert orders == [{'cmd': 'stop', 'units': [400]}]
    assert 'mcv-site-400' not in memory


def test_mcv_inside_tower_range_escapes_away_from_blocked_home_route():
    v = mapped()
    v.units = [dict(actor(400, 'mcv', 27, 10), idle=False)]
    v.enemy_buildings = [actor(200, 'tsla', 20, 10)]
    memory = {'mcv-site-400': (40, 10), 'mcv-moving-400': True}
    orders, _ = collect(_mcv_orders, v, memory)
    assert len(orders) == 1 and orders[0]['cmd'] == 'move'
    destination = tuple(orders[0]['to'])
    assert orders[0]['units'] == [400] and destination[0] > 27
    assert destination in v.navigation['distances'] and safe_cell(v, destination)


def opening(separation):
    v = mapped(separation=separation)
    v.buildings = [actor(900+i,t,10,10) for i,t in enumerate(['fact','powr','barr','proc'])]
    v.units = [actor(i,x=10,y=10) for i in range(1,7)] + [actor(100,'harv',10,10)]
    v.available = {'e1'}
    return v


def test_long_safe_route_saves_early_infantry_budget_but_responds_to_live_attack():
    close, far = opening(52), opening(98)
    assert any(o['cmd']=='train' for o in collect(economy,close)[0])
    assert not any(o['cmd']=='train' for o in collect(economy,far)[0])
    far.obs['visible_enemies'] = [actor(200+i,x=13,y=10) for i in range(6)]
    assert any(o['cmd']=='train' for o in collect(economy,far)[0])


def test_close_route_can_cover_one_refinery_earlier_without_tower_spam():
    close, far = opening(52), opening(98)
    for v in (close,far):
        v.available = {'pbox'}
        v.production = [{'item':'proc','queue':'Building'}]
    assert {'cmd':'build','item':'pbox'} in collect(economy,close)[0]
    assert {'cmd':'build','item':'pbox'} not in collect(economy,far)[0]
    close.buildings.append(actor(700,'pbox',12,10))
    assert not any(o.get('item')=='pbox' for o in collect(economy,close)[0])


def test_guard_scout_is_one_rifle_and_never_receives_a_second_movement_order():
    v = mapped()
    orders,memory = collect(combat,v)
    assert memory['combat']['mode'] == 'guard economy'
    scouting = [o for o in orders if o.get('to') == v.map_plan['scout_cell']]
    assert len(scouting) == 1 and len(scouting[0]['units']) == 1
    ident = scouting[0]['units'][0]
    assert sum(ident in o.get('units',[]) for o in orders if o['cmd'] in {'move','attack_move'}) == 1
    assert not any(o['cmd'] in {'attack','attack_move'} for o in orders)


def test_warning_scout_returns_when_a_visible_threat_approaches():
    v = mapped()
    _,memory = collect(combat,v)
    ident = memory['combat']['warning_scout_id']
    v.enemies = [actor(200,'1tnk',v.map_plan['scout_cell'][0]+8,10)]
    v.now += 5
    orders,memory = collect(combat,v,memory)
    assert 'warning_scout_id' not in memory['combat']
    assert any(ident in o.get('units',[]) and o.get('to') == v.map_plan['guard_cell'] for o in orders)


def test_scouting_does_not_repeatedly_sacrifice_new_rifles():
    v = mapped()
    memory = {}
    for _ in range(2):
        _,memory = collect(combat,v,memory)
        ident = memory['combat']['warning_scout_id']
        v.units = [a for a in v.units if a['id'] != ident]
        v.now += 100
    orders,_ = collect(combat,v,memory)
    assert not any(o.get('to') == v.map_plan['scout_cell'] for o in orders)


def test_time_fallback_obeys_selected_duration_not_always_twenty_minutes():
    v = mapped(minutes=10,now=500)
    del v.raw['time']['remaining_seconds']
    assert View(v.raw,v.config).remaining == 100


def test_candidate_integration_records_choice_and_preserves_action_limits_and_baseline():
    v = mapped(separation=98)
    before = deepcopy(v.raw)
    context = DecisionContext('maps',None,'red_alert','a',0,v.config)
    candidate, baseline = RedAlertAgent('eco_guard'), RedAlertAgent()
    result = candidate.choose_action(GameState.from_mcp_state(v.raw),context)
    assert candidate._memory(context)['map_adaptation']['plan']['style'] == 'long-route-economy'
    assert len(result['orders']) <= 20
    assert sum(len(o.get('units',[])) or o.get('count',1) for o in result['orders']) <= 200
    assert all(validate(o,v) for o in result['orders'])
    baseline.choose_action(GameState.from_mcp_state(v.raw),context)
    assert 'map_adaptation' not in baseline._memory(context)
    assert v.raw == before
