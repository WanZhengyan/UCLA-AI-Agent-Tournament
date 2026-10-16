"""Team-visible tower defense scenarios, not a combat engine or win-rate test."""
from copy import deepcopy

import pytest

from altruagent import WAIT
from hok_platform.agent import create_agent
from test_hok_platform import action, choose, hero, mine, sample, tick


def scene(*, camp=1, positions=(12000,), enemies=(3000,), hp=1000, attack=False, neutral=False):
    sign = 1 if camp == 1 else -1
    seats = list(range((camp-1)*5, (camp-1)*5+len(positions)))
    structures = [hero(300,camp,hp=hp,x=0,type='ACTOR_TOWER'),
                  hero(301,camp,x=-20000*sign,type='ACTOR_CRYSTAL'),
                  hero(302,camp,x=-30000*sign,type='ACTOR_TOWER_SPRING'),
                  hero(303,3-camp,x=30000*sign,type='ACTOR_TOWER')]
    raw = sample(camp=camp,seats=seats,structures=structures,
                 enemies=[hero(200+i,3-camp,x=x*sign,visible=True) for i,x in enumerate(enemies)],
                 macros=['macro_advance','macro_retreat']+(['macro_attack'] if attack else []))
    for seat,x in zip(seats,positions):
        mine(raw,seat)['x']=x*sign
        if neutral:
            raw['legal_actions']['actions'].append({
                'action_id':f's{seat}:button_0','label':'No action',
                'input':{'action':{'seat':seat,'which_button':0}}})
    return raw


def change_building(raw, index=0, **changes):
    for entry in raw['observation']['seats'].values():
        entry['summary']['structures'][index].update(changes)


def clear_enemies(raw):
    for entry in raw['observation']['seats'].values():
        entry['summary']['other_heroes']=[]


@pytest.mark.parametrize('camp',[1,2])
@pytest.mark.parametrize('position,expected',[(12000,'macro_retreat'),(-15000,'macro_advance')])
def test_reinforcement_direction_matches_actual_side_of_tower(camp,position,expected):
    raw,bot=scene(camp=camp,positions=(position,)),create_agent()
    assert choose(bot,raw)=={'seat':raw['seats'][0],'macro':expected}
    assert bot.last_diagnostics['reason']=='tower_reinforce'


@pytest.mark.parametrize('camp',[1,2])
def test_fresh_tower_damage_without_visible_hero_still_calls_defense(camp):
    raw,bot=scene(camp=camp,enemies=()),create_agent()
    assert choose(bot,raw)['macro']=='macro_advance'
    change_building(raw,hp=900)
    tick(raw,steps=5)
    assert choose(bot,raw)['macro']=='macro_retreat'
    assert bot.last_diagnostics['reason']=='tower_reinforce'


def test_old_low_tower_hp_without_current_threat_does_not_stop_push():
    raw,bot=scene(enemies=(),hp=100),create_agent()
    assert choose(bot,raw)['macro']=='macro_advance'
    assert not bot._defense


def test_defense_expires_when_hp_stabilizes_and_attackers_leave():
    raw,bot=scene(enemies=()),create_agent()
    choose(bot,raw)
    change_building(raw,hp=900)
    tick(raw,steps=5)
    assert choose(bot,raw)['macro']=='macro_retreat'
    tick(raw,steps=10)
    assert choose(bot,raw)['macro']=='macro_retreat'
    tick(raw,steps=15)
    assert choose(bot,raw)['macro']=='macro_advance'
    assert not bot._defense


def test_old_damage_across_long_observation_gap_is_not_a_fresh_hit():
    raw,bot=scene(enemies=()),create_agent()
    choose(bot,raw)
    change_building(raw,hp=500)
    tick(raw,steps=100)
    assert choose(bot,raw)['macro']=='macro_advance'


def test_max_hp_change_does_not_create_a_fictional_damage_event():
    raw,bot=scene(enemies=()),create_agent()
    choose(bot,raw)
    change_building(raw,hp=900,max_hp=2000)
    tick(raw)
    assert choose(bot,raw)['macro']=='macro_advance'


@pytest.mark.parametrize('mode',['hidden','dead'])
def test_hidden_or_dead_attacker_does_not_trigger_defense(mode):
    raw,bot=scene(),create_agent()
    enemy=raw['observation']['seats']['0']['summary']['other_heroes'][0]
    enemy.update(visible=mode!='hidden',hp=0 if mode=='dead' else 1000)
    assert choose(bot,raw)['macro']=='macro_advance'
    assert not bot._defense


def test_missing_building_coordinates_do_not_create_a_route():
    raw,bot=scene(enemies=()),create_agent()
    change_building(raw,x=None)
    choose(bot,raw)
    change_building(raw,hp=900)
    tick(raw)
    assert choose(bot,raw)['macro']=='macro_advance'
    assert not bot._defense


def test_only_nearest_two_defend_one_attacker_others_keep_pushing():
    raw,bot=scene(positions=(12000,18000,26000,34000,42000)),create_agent()
    orders={}
    for _ in range(5):
        selected=choose(bot,raw)
        orders[selected['seat']]=selected['macro']
        raw['simultaneous']['standing_orders'][str(selected['seat'])]=selected['macro']
    assert set(bot._defense)=={0,1}
    assert orders=={0:'macro_retreat',1:'macro_retreat',2:'macro_advance',3:'macro_advance',4:'macro_advance'}
    assert choose(bot,raw) is WAIT


def test_duplicate_enemy_views_are_not_five_different_attackers():
    raw,bot=scene(positions=(12000,18000,26000,34000,42000)),create_agent()
    choose(bot,raw)
    assert len(bot._defense)==2
    assert all(len(t['attackers'])==1 for t in bot._defense.values())


def test_busy_routine_defender_does_not_starve_offensive_hero_orders():
    raw,bot=scene(positions=(12000,18000,26000,34000,42000)),create_agent()
    served=[]
    for _ in range(5):
        raw['simultaneous']['standing_orders']['0']='macro_advance'
        selected=choose(bot,raw)
        served.append(selected['seat'])
        raw['simultaneous']['standing_orders'][str(selected['seat'])]=selected['macro']
        tick(raw)
    assert set(served)==set(range(5))


def test_tower_damage_without_hero_threat_allocates_only_one_defender():
    raw,bot=scene(enemies=(),positions=(12000,18000,26000,34000,42000)),create_agent()
    choose(bot,raw)
    change_building(raw,hp=900)
    tick(raw)
    choose(bot,raw)
    assert set(bot._defense)=={0}


def test_dead_and_low_health_heroes_are_not_sent_to_rescue_a_tower():
    raw,bot=scene(positions=(3000,5000,12000,20000,30000)),create_agent()
    mine(raw,0)['hp']=0
    mine(raw,1)['hp']=200
    choose(bot,raw)
    assert set(bot._defense)=={2,3}


def test_remote_tower_does_not_recall_hero_from_other_end_of_map():
    raw,bot=scene(positions=(60000,)),create_agent()
    choose(bot,raw)
    assert not bot._defense


def test_full_health_crystal_threat_is_not_ignored_until_it_is_half_dead():
    raw,bot=scene(positions=(-10000,),enemies=(-18000,)),create_agent()
    assert choose(bot,raw)['macro']=='macro_retreat'
    assert next(iter(bot._defense.values()))['building']['type']=='ACTOR_CRYSTAL'


def test_critical_crystal_can_escalate_to_all_available_heroes():
    raw,bot=scene(positions=(-10000,-7000,-4000,1000,5000),enemies=(-18000,)),create_agent()
    change_building(raw,index=1,hp=200)
    choose(bot,raw)
    assert set(bot._defense)==set(range(5))
    assert all(t['building']['type']=='ACTOR_CRYSTAL' for t in bot._defense.values())


def test_multiple_tower_threats_share_a_bounded_defense_budget():
    raw,bot=scene(positions=(5000,8000,10000,15000,18000),enemies=(3000,-10000)),create_agent()
    for entry in raw['observation']['seats'].values():
        entry['summary']['structures'].append(hero(304,1,hp=700,x=-12000,type='ACTOR_TOWER'))
    choose(bot,raw)
    assert len(bot._defense)==3
    assert len({t['key'] for t in bot._defense.values()})==2


def test_nearby_defender_clears_legal_minion_target_instead_of_advancing():
    raw,bot=scene(positions=(2000,),attack=True),create_agent()
    raw['legal_actions']['actions'][-1]['label']='Attack nearest enemy minion (1000 away)'
    assert choose(bot,raw)['macro']=='macro_attack'
    assert bot.last_diagnostics['reason']=='tower_defense'


def test_enemy_structure_attack_does_not_masquerade_as_tower_defense():
    raw,bot=scene(attack=True),create_agent()
    raw['legal_actions']['actions'][-1]['label']='Attack nearest enemy tower (2000 away)'
    assert choose(bot,raw)['macro']=='macro_retreat'


def test_a_defender_can_use_a_listed_hero_skill_when_basic_attack_is_unavailable():
    raw,bot=scene(positions=(2000,)),create_agent()
    raw['legal_actions']['actions'].append(action(0,'macro_skill1','Cast skill toward enemy hero (1000 away)'))
    assert choose(bot,raw)['macro']=='macro_skill1'
    assert bot.last_diagnostics['reason']=='tower_defense'


def test_unsafe_rescue_does_not_override_outnumbered_escape():
    raw,bot=scene(positions=(2000,),enemies=(1000,2000,3000),attack=True),create_agent()
    assert choose(bot,raw)['macro']=='macro_retreat'
    assert bot.last_diagnostics['reason']=='local_disadvantage'


def test_fresh_burst_damage_overrides_ordinary_tower_rescue():
    raw,bot=scene(positions=(2000,),attack=True),create_agent()
    assert choose(bot,raw)['macro']=='macro_attack'
    tick(raw,steps=5,hp=600)
    assert choose(bot,raw)['macro']=='macro_retreat'


@pytest.mark.parametrize('mode',['realtime','lockstep'])
def test_listed_neutral_cancels_advance_to_hold_near_threatened_tower(mode):
    raw,bot=scene(positions=(2000,),neutral=True),create_agent()
    raw['pacing']['mode']=mode
    raw['simultaneous']['standing_orders']={'0':'macro_advance'}
    selected=choose(bot,raw)
    assert selected=={'seat':0,'which_button':0}
    assert bot.last_diagnostics['reason']=='tower_hold'
    raw['simultaneous']['standing_orders']={}
    if mode=='realtime':
        assert choose(bot,raw) is WAIT
    else:
        assert choose(bot,raw)==selected


def test_rejected_neutral_guard_does_not_loop_at_same_version():
    raw,bot=scene(positions=(2000,),neutral=True),create_agent()
    raw['simultaneous']['standing_orders']={'0':'macro_advance'}
    assert choose(bot,raw)=={'seat':0,'which_button':0}
    bot.on_action_result({'error':'INVALID_ACTION'})
    assert choose(bot,raw) is WAIT
    tick(raw)
    assert choose(bot,raw)=={'seat':0,'which_button':0}


def test_neutral_guard_action_is_never_invented_when_not_offered():
    raw,bot=scene(positions=(2000,)),create_agent()
    raw['simultaneous']['standing_orders']={'0':'macro_advance'}
    result=choose(bot,raw)
    assert result is WAIT or 'which_button' not in result


@pytest.mark.parametrize('change',['session','rewind','account'])
def test_building_damage_memory_does_not_leak_into_new_games(change):
    raw,bot=scene(enemies=()),create_agent()
    choose(bot,raw)
    change_building(raw,hp=900)
    tick(raw)
    assert choose(bot,raw)['macro']=='macro_retreat'
    current=scene(enemies=(),hp=800)
    current['state_version']=raw['state_version']+1
    if change=='session': current['session_id']='new-session'
    if change=='rewind': current['state_version']=1
    assert choose(bot,current,account='different' if change=='account' else 'owner')['macro']=='macro_advance'
    assert not bot._defense


def test_destroyed_tower_is_not_defended_after_it_is_gone():
    raw,bot=scene(),create_agent()
    assert choose(bot,raw)['macro']=='macro_retreat'
    change_building(raw,hp=0)
    clear_enemies(raw)
    tick(raw)
    assert choose(bot,raw)['macro']=='macro_advance'
    assert not bot._defense


def test_building_tracking_and_assignments_do_not_mutate_server_state():
    raw,bot=scene(positions=(12000,18000,26000)),create_agent()
    before=deepcopy(raw)
    choose(bot,raw)
    assert raw==before


def test_same_version_observation_does_not_extend_damage_alarm_forever():
    raw,bot=scene(enemies=()),create_agent()
    choose(bot,raw)
    change_building(raw,hp=900)
    tick(raw)
    choose(bot,raw)
    for _ in range(20): choose(bot,raw)
    tick(raw,steps=30)
    assert choose(bot,raw)['macro']=='macro_advance'
