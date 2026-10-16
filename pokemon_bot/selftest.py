"""Small deterministic release smoke test (no network or credentials)."""
import time
from .dex import stats,effectiveness,move
from .legal import enumerate_actions,validate_action


def fixture():
    def mon(species,moves,**kw):
        return dict(species=species,moves=moves,current_hp_fraction=1.,status=None,boosts={},**kw)
    own=[mon('Incineroar',['fakeout','flareblitz','knockoff','protect'],ability='Intimidate',item='Sitrus Berry'),
         mon('Flutter Mane',['moonblast','shadowball','dazzlinggleam','protect'],ability='Protosynthesis',item='Booster Energy')]
    foe=[mon('Rillaboom',['grassyglide','woodhammer','fakeout','protect'],ability='Grassy Surge'),
         mon('Urshifu-Rapid-Strike',['surgingstrikes','closecombat','aquajet','protect'],ability='Unseen Fist')]
    slots=[]
    for i,m in enumerate(own):
        options=[]
        for mid in m['moves']:
            targets=[0] if move(mid).get('target') in ('self','allAdjacentFoes','allAdjacent','all') else [1,2,-2 if i==0 else -1]
            options.append({'type':'move','move_id':mid,'targets':targets})
        slots.append({'slot':i,'active':m['species'],'force_switch':False,'options':options})
    template={'type':'doubles_turn','slots':slots}
    return {'session_id':'selftest','game_type':'pokemon_vgc_doubles_draft','phase':'moving','status':'in_progress','state_version':1,'is_current_actor':True,'is_terminal':False,
            'observation':{'phase':'moving','is_doubles':True,'turn':1,'active_pokemon':own,'opponent_active_pokemon':foe,'team':{m['species']:m for m in own},'opponent_team':{m['species']:m for m in foe},'weather':None,'fields':{},'side_conditions':{},'opponent_side_conditions':{},'clock':{'decision_seconds_left':50,'bank_seconds_left':420}},
            'legal_actions':{'actions':[{'action_id':'doubles_turn','input':{'action':template}}]}}


def run():
    from .agent import PokemonAgent
    assert effectiveness('Electric',['Ground'])==0
    assert effectiveness('Fire',['Grass','Steel'])==4
    assert stats({'species':'Urshifu-Rapid-Strike','nature':'Adamant','evs':{'atk':252,'hp':4},'level':50})['atk']==200
    template={'type':'doubles_turn','slots':[{'slot':0,'options':[{'type':'switch','species':'x'},{'type':'pass'}]}, {'slot':1,'options':[{'type':'switch','species':'x'},{'type':'pass'}]}]}
    choices=enumerate_actions(template)
    assert len(choices)==2 and all(validate_action(a,template) for a in choices)
    agent=PokemonAgent();raw=fixture();start=time.monotonic();a=agent.decide(raw)
    assert validate_action(a,raw['legal_actions']['actions'][0]['input']['action'])
    assert not agent.last_diagnostics['fallback'],agent.last_diagnostics
    assert agent.decide(raw)==a
    print('Offline strategy self-test passed; decision %.3fs'%(time.monotonic()-start))
    return 0
