"""Offline installation checks. These are not live match or win-rate tests."""
from copy import deepcopy
from time import perf_counter
from altruagent import WAIT
from altruagent.models import GameState, DecisionContext
from .agent import create_agent, validate
from .common import View

def sample():
    return {
        'session_id':'offline','game_type':'red_alert','status':'in_progress',
        'phase':'playing','pacing':{'mode':'realtime'},'is_current_actor':True,
        'state_version':25,'is_terminal':False,'map':{'bounds':[8,8,96,96]},
        'time':{'game_seconds':1,'remaining_seconds':1199},
        'legal_actions':{'deploy':[1],'enemy_base':[80,80]},
        'observation':{'tick':25,'base_center':[20,20],'faction':'russia',
            'economy':{'cash':5000,'ore':0,'power_provided':0,'power_drained':0,'harvesters':0},
            'units':[{'id':1,'type':'mcv','x':20,'y':20,'hp':100,'idle':True}],
            'buildings':[],'production':[],'available_production':[],
            'visible_enemies':[],'visible_enemy_buildings':[]}}

def run():
    ctx = DecisionContext('offline',None,'red_alert','offline',0)
    bot = create_agent()
    raw = sample()
    out = bot.choose_action(GameState.from_mcp_state(raw),ctx)
    assert {'cmd':'deploy','units':[1]} in out['orders'], 'MCV deployment'
    raw['state_version'] += 5
    raw['time']['game_seconds'] += .2
    assert bot.choose_action(GameState.from_mcp_state(raw),ctx) is WAIT, 'Repeated deployment guard'
    raw['state_version'] = 100
    raw['time']['game_seconds'] = 4
    raw['observation']['units'] = []
    raw['observation']['buildings'] = [{'id':2,'type':'fact','x':20,'y':20,'hp':100}]
    raw['observation']['available_production'] = ['powr']
    out = bot.choose_action(GameState.from_mcp_state(raw),ctx)
    assert {'cmd':'build','item':'powr'} in out['orders'], 'Opening power'
    raw['time']['game_seconds'] = 4.2
    raw['state_version'] = 105
    out = bot.choose_action(GameState.from_mcp_state(raw),ctx)
    assert out is WAIT or not any(o['cmd']=='build' for o in out['orders']), 'Pending production guard'
    raw['time']['game_seconds'] = 14
    raw['state_version'] = 350
    raw['observation']['production'] = [{'queue':'Building','item':'powr','ready':True,'progress':1}]
    out = bot.choose_action(GameState.from_mcp_state(raw),ctx)
    assert any(o['cmd']=='place' and o['item']=='powr' for o in out['orders']), 'Ready placement'
    assert validate({'cmd':'move','units':[99],'to':[20,20]},View(raw)) is None
    assert validate({'cmd':'attack','units':[2],'target':999},View(raw)) is None
    halted = deepcopy(raw)
    halted['phase'] = 'waiting_for_agents'
    assert bot.choose_action(GameState.from_mcp_state(halted),ctx) is WAIT
    started = perf_counter()
    for _ in range(100): bot.choose_action(GameState.from_mcp_state(raw),ctx)
    elapsed = (perf_counter()-started)*10
    print(f'Offline policy checks passed; sample decisions averaged {elapsed:.2f} ms on this machine. This is not a live win-rate test.')
    return 0
