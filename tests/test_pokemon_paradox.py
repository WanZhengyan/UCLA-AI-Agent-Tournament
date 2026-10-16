"""Regression checks for public Paradox activations in damage estimates."""
import copy
import json
import os
import subprocess

import pytest

from pokemon_bot.battle import choose_battle, damage, speed
from pokemon_bot.state import normalize_mon

FACTOR = 5325 / 4096


def mon(ability='', stat=None, **kwargs):
    effects = {ability.lower().replace(' ', '') + stat: True} if stat else {}
    return normalize_mon(dict(species='Mew', ability=ability, effects=effects,
                              current_hp_fraction=1., **kwargs), {})


@pytest.mark.parametrize('ability', ['Protosynthesis', 'Quark Drive'])
@pytest.mark.parametrize('stat,move', [('atk', 'Tackle'), ('spa', 'Psychic')])
def test_consumed_booster_offensive_activation_matches_stat_modifier(ability, stat, move):
    p, q = mon(ability, stat, item=''), mon()
    expected = copy.deepcopy(p)
    expected['ability'] = ''
    expected['stats'][stat] *= FACTOR
    assert damage(p, q, move, {}, 0) == pytest.approx(damage(expected, q, move, {}, 0))


@pytest.mark.parametrize('ability', ['Protosynthesis', 'Quark Drive'])
@pytest.mark.parametrize('stat,move', [('def', 'Tackle'), ('spd', 'Psychic')])
def test_defensive_activation_matches_stat_modifier(ability, stat, move):
    p, q = mon('Mold Breaker'), mon(ability, stat, item='')
    expected = copy.deepcopy(q)
    expected['ability'] = ''
    expected['stats'][stat] *= FACTOR
    assert damage(p, q, move, {}, 0) == pytest.approx(damage(p, expected, move, {}, 0))


@pytest.mark.parametrize('ability', ['Protosynthesis', 'Quark Drive'])
def test_later_stage_changes_do_not_reselect_offensive_activation(ability):
    p, q = mon(ability, 'spa', item='', boosts={'atk': 6}), mon()
    expected = copy.deepcopy(p)
    expected['ability'] = ''
    expected['stats']['spa'] *= FACTOR
    field = {'weather': 'sunnyday', 'terrain': 'electricterrain'}
    assert damage(p, q, 'Psychic', field, 0) == pytest.approx(damage(expected, q, 'Psychic', field, 0))


@pytest.mark.parametrize('ability', ['Protosynthesis', 'Quark Drive'])
@pytest.mark.parametrize('stat,enhanced', [('atk', True), ('def', False)])
def test_body_press_offensive_modifier_uses_category_not_borrowed_stat(ability, stat, enhanced):
    p, q = mon(ability, stat), mon()
    plain = copy.deepcopy(p)
    plain['ability'] = ''
    actual, baseline = damage(p, q, 'Body Press', {}, 0), damage(plain, q, 'Body Press', {}, 0)
    assert actual > baseline if enhanced else actual == baseline


@pytest.mark.parametrize('ability', ['Protosynthesis', 'Quark Drive'])
@pytest.mark.parametrize('stat,reduced', [('def', True), ('spd', False)])
def test_psyshock_uses_defense_modifier_despite_special_category(ability, stat, reduced):
    p, q = mon(), mon(ability, stat)
    plain = copy.deepcopy(q)
    plain['ability'] = ''
    actual, baseline = damage(p, q, 'Psyshock', {}, 0), damage(p, plain, 'Psyshock', {}, 0)
    assert actual < baseline if reduced else actual == baseline


def test_known_speed_activation_does_not_become_special_attack_in_sun():
    p, q = mon('Protosynthesis', 'spe', boosts={'spa': 6}), mon()
    plain = copy.deepcopy(p)
    plain['ability'] = ''
    assert damage(p, q, 'Psychic', {'weather': 'sunnyday'}, 0) == damage(plain, q, 'Psychic', {'weather': 'sunnyday'}, 0)
    assert speed(p, 0, {}) > speed(plain, 0, {})


def test_policy_does_not_assume_survival_after_public_special_attack_boost():
    own = dict(species='Gholdengo', moves=['makeitrain', 'protect'], current_hp_fraction=.4)
    foe = dict(species='Flutter Mane', ability='Protosynthesis', effects={'protosynthesisspa': True},
               item='', moves=['moonblast'], current_hp_fraction=.4, stats={'spa': 205, 'spe': 170})
    obs = dict(turn=3, active_pokemon=[own, None], opponent_active_pokemon=[foe, None],
               team={'Gholdengo': own}, opponent_team={'Flutter Mane': foe})
    template = {'type': 'doubles_turn', 'slots': [
        {'slot': 0, 'options': [{'type': 'move', 'move_id': 'makeitrain', 'targets': [0]},
                                {'type': 'move', 'move_id': 'protect', 'targets': [0]}]},
        {'slot': 1, 'options': [{'type': 'pass'}]},
    ]}
    assert choose_battle(obs, template, {}, budget=1.)['slot_0']['move_id'] == 'protect'


@pytest.mark.skipif(not os.environ.get('SHOWDOWN_NODE'), reason='Enable pinned Showdown checks')
def test_independent_engine_paradox_modifier_events():
    script = r'''
const assert=require('assert');
const {Battle,toID}=require('pokemon-showdown');
let checks=0;
function compare(ab,stat,move,defensive=false) {
 const mk=ability=>({species:'Mew',ability,moves:['Splash'],level:50});
 const b=new Battle({formatid:'gen9customgame',seed:[1,2,3,4],p1:{name:'A',team:[mk(defensive?'Mold Breaker':ab)]},p2:{name:'B',team:[mk(defensive?ab:'Synchronize')]}});
 b.makeChoices('team 1','team 1');
 const p=defensive?b.p2.active[0]:b.p1.active[0];p.storedStats[stat]=200;
 b.field[ab==='Protosynthesis'?'setWeather':'setTerrain'](ab==='Protosynthesis'?'sunnyday':'electricterrain',p);
 const key=toID(ab);assert.equal(p.volatiles[key].bestStat,stat);
 const seed=b.prng.getSeed();
 const boosted=b.actions.getDamage(b.p1.active[0],b.p2.active[0],move);
 delete p.volatiles[key];b.resetRNG(seed);
 const plain=b.actions.getDamage(b.p1.active[0],b.p2.active[0],move);
 b.destroy();return [boosted,plain];
}
for(const ab of ['Protosynthesis','Quark Drive']) {
 for(const [stat,move] of [['atk','Tackle'],['spa','Psychic'],['atk','Body Press']]) {
  const [a,b]=compare(ab,stat,move);assert(a>b);checks++;
 }
 {const [a,b]=compare(ab,'def','Body Press');assert.equal(a,b);checks++;}
 for(const [stat,move] of [['def','Tackle'],['spd','Psychic'],['def','Psyshock']]) {
  const [a,b]=compare(ab,stat,move,true);assert(a<b);checks++;
 }
 {const [a,b]=compare(ab,'spd','Psyshock',true);assert.equal(a,b);checks++;}
 // A real consumed Booster Energy keeps its original stat after later boosts.
 const b=new Battle({formatid:'gen9customgame',seed:[5,6,7,8],p1:{name:'A',team:[
  {species:'Mew',ability:ab,item:'Booster Energy',nature:'Modest',evs:{spa:252},moves:['Psychic'],level:50}]},
  p2:{name:'B',team:[{species:'Mew',ability:'Synchronize',moves:['Splash'],level:50}]}});
 b.makeChoices('team 1','team 1');const p=b.p1.active[0],key=toID(ab);
 assert.equal(p.item,'');assert.equal(p.volatiles[key].bestStat,'spa');p.boosts.atk=6;
 const seed=b.prng.getSeed(),boosted=b.actions.getDamage(p,b.p2.active[0],'Psychic');
 delete p.volatiles[key];b.resetRNG(seed);
 assert(boosted>b.actions.getDamage(p,b.p2.active[0],'Psychic'));checks++;b.destroy();
}
{
 const mk=(species,ability,moves,item='',nature='Serious',evs={})=>({species,ability,moves,item,nature,evs,level:50});
 const b=new Battle({formatid:'gen9doublescustomgame',seed:[1,2,3,4],p1:{name:'A',team:[
  mk('Gholdengo','Good as Gold',['Make It Rain']),mk('Magikarp','Swift Swim',['Splash'])]},p2:{name:'B',team:[
  mk('Flutter Mane','Protosynthesis',['Moonblast'],'Booster Energy','Modest',{spa:252}),mk('Magikarp','Swift Swim',['Splash'])]}});
 b.makeChoices('team 12','team 12');const p=b.p1.active[0];p.hp=Math.floor(p.maxhp*.4);
 b.makeChoices('move makeitrain,move splash','move moonblast 1,move splash');
 assert.equal(p.hp,0);assert(!b.log.some(x=>x.includes('|move|p1a:')&&x.includes('Make It Rain')));
 checks++;b.destroy();
}
console.log(JSON.stringify({checks,version:require('pokemon-showdown/package.json').version}));
'''
    result = subprocess.run([os.environ['SHOWDOWN_NODE'], '-e', script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'checks': 19, 'version': '0.11.11'}
