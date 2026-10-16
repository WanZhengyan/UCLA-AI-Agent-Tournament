"""Counterplay regressions against conditional priority and protected allies."""
import copy
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from pokemon_bot.battle import choose_battle, evaluate, simulate
from pokemon_bot.state import normalize_mon


PASS = {"type": "pass"}


def mon(name, moves=(), **kwargs):
    return normalize_mon(dict(species=name, moves=list(moves), current_hp_fraction=1., **kwargs), {})


def move(name, target=1):
    return {"type": "move", "move_id": name, "target": target}


def resolve(base, actions):
    snapshots = []

    def capture(board, benches, field, horizon=True):
        snapshots.append(copy.deepcopy((board, benches, field)))
        return evaluate(board, benches, field, horizon)

    with patch("pokemon_bot.battle.evaluate", side_effect=capture):
        simulate(base, actions, horizon=False)
    return snapshots[-1]


def state(ours, theirs, **kwargs):
    return dict(own=[ours, None], foe=[theirs, None], own_bench=[], foe_bench=[], field={}, **kwargs)


@pytest.mark.parametrize("response", ["splash", "nastyplot", "extremespeed"])
def test_thunderclap_does_not_hit_a_status_or_already_moved_target(response):
    base = state(mon("Raging Bolt"), mon("Dragonite"))
    board, _, _ = resolve(base, ((move("thunderclap"), PASS), (move(response), PASS)))
    assert board[1][0]["hp"] == 1


def test_thunderclap_does_not_hit_an_incoming_switch():
    base = state(mon("Raging Bolt"), mon("Dragonite"))
    base["foe_bench"] = [mon("Blissey")]
    board, _, _ = resolve(base, ((move("thunderclap"), PASS), ({"type": "switch", "species": "blissey"}, PASS)))
    assert board[1][0]["species"] == "blissey"
    assert board[1][0]["hp"] == 1


@pytest.mark.parametrize("attack", ["thunderclap", "suckerpunch"])
def test_conditional_priority_hits_a_pending_attack(attack):
    base = state(mon("Raging Bolt"), mon("Dragonite"))
    board, _, _ = resolve(base, ((move(attack), PASS), (move("dragonclaw"), PASS)))
    assert board[1][0]["hp"] < 1


@pytest.mark.parametrize("attack", ["thunderclap", "suckerpunch"])
def test_conditional_priority_fails_against_recharge(attack):
    base = state(mon("Raging Bolt"), mon("Dragonite", effects={"mustrecharge": True}))
    board, _, _ = resolve(base, ((move(attack), PASS), (move("recharge"), PASS)))
    assert board[1][0]["hp"] == 1


@pytest.mark.parametrize("blocking_ability", ["Armor Tail", "Queenly Majesty", "Dazzling"])
@pytest.mark.parametrize("attacker_ability,shield,blocked", [
    ("Mold Breaker", "", False),
    ("Mold Breaker", "Ability Shield", True),
    ("Defiant", "", True),
])
def test_priority_ability_denial_respects_mold_breaker_and_ability_shield(blocking_ability, attacker_ability, shield, blocked):
    base = state(mon("Ogerpon-Hearthflame", ability=attacker_ability), mon("Blissey"))
    base["foe"][1] = mon("Farigiraf", ability=blocking_ability, item=shield)
    board, _, _ = resolve(base, ((move("quickattack"), PASS), (PASS, PASS)))
    assert (board[1][0]["hp"] == 1) is blocked


@pytest.mark.parametrize("field,response", [({"terrain": "psychicterrain"}, PASS), ({}, move("quickguard", 0))])
def test_mold_breaker_does_not_bypass_priority_terrain_or_quick_guard(field, response):
    base = state(mon("Ogerpon-Hearthflame", ability="Mold Breaker"), mon("Farigiraf", ability="Armor Tail"))
    base["field"] = field
    board, _, _ = resolve(base, ((move("quickattack"), PASS), (response, PASS)))
    assert board[1][0]["hp"] == 1


def test_policy_does_not_credit_thunderclap_against_public_status_only_set():
    # Thunderclap looks like a KO and outranks Dragon Pulse before simulation.
    # The public target only has Roost, so the conditional attack always fails.
    own = dict(species="Raging Bolt", moves=["thunderclap", "dragonpulse"], current_hp_fraction=1.)
    foe = dict(species="Pelipper", moves=["roost"], current_hp_fraction=.4)
    obs = dict(turn=2, active_pokemon=[own, None], opponent_active_pokemon=[foe, None],
               team={"ragingbolt": own}, opponent_team={"pelipper": foe})
    template = {"type": "doubles_turn", "slots": [
        {"slot": 0, "options": [dict(type="move", move_id=x, targets=[1]) for x in own["moves"]]},
        {"slot": 1, "options": [PASS]},
    ]}
    chosen = choose_battle(obs, template, {}, budget=1.)
    assert chosen["slot_0"]["move_id"] == "dragonpulse"


@pytest.mark.skipif(not os.environ.get("SHOWDOWN_NODE"), reason="Set SHOWDOWN_NODE with the pinned Pokemon Showdown dependency")
def test_independent_showdown_confirms_conditional_priority_and_ability_bypass():
    script = r'''
const assert=require('node:assert/strict');
const {Battle}=require('pokemon-showdown');
const mk=(species,moves,ability,item='')=>({species,moves,ability,item,level:50});
const splash=()=>mk('Magikarp',['Splash'],'Swift Swim');
let checks=0;
function make(p,q,ally=splash(),reserve=null) {
 const team=[q,ally];if(reserve)team.push(reserve);
 const b=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[p,splash()]},p2:{name:'p2',team}});
 b.makeChoices('team 12',reserve?'team 123':'team 12');return b;
}
for(const response of ['Splash','Nasty Plot','Extreme Speed','Dragon Claw']) {
 const b=make(mk('Raging Bolt',['Thunderclap'],'Protosynthesis'),mk('Dragonite',[response],'Inner Focus'));
 b.makeChoices('move thunderclap 1, move splash','move '+response.replace(/ /g,'').toLowerCase()+(response==='Extreme Speed'||response==='Dragon Claw'?' 1':'')+', move splash');
 assert.equal(b.p2.active[0].hp<b.p2.active[0].maxhp,response==='Dragon Claw');b.destroy();checks++;
}
let b=make(mk('Raging Bolt',['Thunderclap'],'Protosynthesis'),mk('Dragonite',['Dragon Claw'],'Inner Focus'),splash(),mk('Blissey',['Splash'],'Natural Cure'));
b.makeChoices('move thunderclap 1, move splash','switch 3, move splash');assert.equal(b.p2.active[0].hp,b.p2.active[0].maxhp);b.destroy();checks++;
for(const shield of ['', 'Ability Shield']) {
 b=make(mk('Ogerpon-Hearthflame',['Quick Attack'],'Mold Breaker','Hearthflame Mask'),mk('Blissey',['Splash'],'Natural Cure'),mk('Farigiraf',['Splash'],'Armor Tail',shield));
 b.makeChoices('move quickattack 1, move splash','move splash, move splash');assert.equal(b.p2.active[0].hp<b.p2.active[0].maxhp,!shield);b.destroy();checks++;
}
b=make(mk('Ogerpon-Hearthflame',['Quick Attack'],'Mold Breaker','Hearthflame Mask'),mk('Farigiraf',['Splash'],'Armor Tail'));
b.field.setTerrain('psychicterrain',b.p2.active[0]);b.makeChoices('move quickattack 1, move splash','move splash, move splash');assert.equal(b.p2.active[0].hp,b.p2.active[0].maxhp);b.destroy();checks++;
b=make(mk('Ogerpon-Hearthflame',['Quick Attack'],'Mold Breaker','Hearthflame Mask'),mk('Farigiraf',['Quick Guard'],'Armor Tail'));
b.makeChoices('move quickattack 1, move splash','move quickguard, move splash');assert.equal(b.p2.active[0].hp,b.p2.active[0].maxhp);b.destroy();checks++;
console.log(JSON.stringify({checks,engine:require('pokemon-showdown/package.json').version}));
'''
    result = subprocess.run([os.environ["SHOWDOWN_NODE"], "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"checks": 9, "engine": "0.11.11"}
