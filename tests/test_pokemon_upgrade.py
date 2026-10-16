"""Mechanics regressions motivated by public VGC play, with optional engine checks."""
import copy
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from pokemon_bot.battle import damage, evaluate, simulate
from pokemon_bot.state import normalize_mon

PASS = {"type": "pass"}


def mon(name, moves=(), **kwargs):
    return normalize_mon(dict(species=name, moves=list(moves), current_hp_fraction=1., **kwargs), {})


def action(name, target=1):
    return {"type": "move", "move_id": name, "target": target}


def resolve(p, q, attack, response=None, field=None):
    base = dict(own=[p, None], foe=[q, None], own_bench=[], foe_bench=[], field=field or {})
    snapshots = []
    def capture(board, benches, field, horizon=True):
        snapshots.append(copy.deepcopy((board, benches, field)))
        return evaluate(board, benches, field, horizon)
    with patch("pokemon_bot.battle.evaluate", side_effect=capture):
        simulate(base, ((action(attack), PASS), (action(response) if response else PASS, PASS)), horizon=False)
    return snapshots[-1][0]


def test_surging_strikes_pays_helmet_cost_for_each_hit():
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist")
    q = mon("Amoonguss", item="Rocky Helmet")
    board = resolve(p, q, "surgingstrikes")
    assert board[0][0]["hp"] == pytest.approx(.5)
    assert board[1][0]["hp"] > 0


def test_contact_knockout_stops_remaining_hits():
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist")
    q = mon("Amoonguss", item="Rocky Helmet")
    first = damage(p, q, "surgingstrikes") / 3
    p["hp"] = .3
    board = resolve(p, q, "surgingstrikes")
    assert board[0][0]["hp"] == 0
    assert board[1][0]["hp"] == pytest.approx(1 - 2 * first)


@pytest.mark.parametrize("ability,item", [("Magic Guard", ""), ("Long Reach", ""), ("Unseen Fist", "Protective Pads"), ("Unseen Fist", "Punching Glove")])
def test_contact_prevention_avoids_helmet_and_rough_skin(ability, item):
    p = mon("Urshifu-Rapid-Strike", ability=ability, item=item)
    q = mon("Garchomp", ability="Rough Skin", item="Rocky Helmet")
    assert resolve(p, q, "surgingstrikes")[0][0]["hp"] == 1


def test_stamina_triggers_per_hit_and_powers_up_body_press():
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist")
    q = mon("Archaludon", ability="Stamina")
    board = resolve(p, q, "surgingstrikes", "bodypress")
    assert board[1][0]["boosts"]["def"] == 3
    no_stamina = resolve(p, dict(q, ability=""), "surgingstrikes", "bodypress")
    assert board[0][0]["hp"] < no_stamina[0][0]["hp"]


def test_stamina_reduces_later_noncritical_hits_without_mutating_input():
    p = mon("Dragonite")
    q = mon("Archaludon", ability="Stamina")
    original = copy.deepcopy(q)
    assert damage(p, q, "doublehit") < damage(p, dict(q, ability=""), "doublehit")
    assert q == original


def test_multiscale_reduces_only_first_surging_strike():
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist")
    q = mon("Dragonite", ability="Multiscale")
    full = damage(p, dict(q, ability=""), "surgingstrikes")
    assert damage(p, q, "surgingstrikes") == pytest.approx(full * 2.5 / 3)


def test_sash_stops_first_hit_even_when_attacker_dies_before_hit_two():
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist")
    p["hp"] = .1
    p["stats"]["atk"] = 9999
    q = mon("Garchomp", ability="Rough Skin", item="Focus Sash")
    board = resolve(p, q, "surgingstrikes")
    assert board[0][0]["hp"] == 0
    assert board[1][0]["hp"] == pytest.approx(.006)
    assert board[1][0]["item"] == ""


def test_unaware_ignores_attack_boosts_but_mold_breaker_bypasses_it():
    p = mon("Dragonite")
    q = mon("Dondozo", ability="Unaware")
    normal = damage(p, q, "dragonclaw")
    p["boosts"]["atk"] = 6
    assert damage(p, q, "dragonclaw") == normal
    assert damage(dict(p, ability="moldbreaker"), q, "dragonclaw") > normal * 3


def test_unaware_attacker_ignores_both_positive_and_negative_defense_stages():
    p = mon("Dondozo", ability="Unaware")
    q = mon("Dragonite")
    normal = damage(p, q, "waterfall")
    for stage in (-6, 6):
        q["boosts"]["def"] = stage
        assert damage(p, q, "waterfall") == normal


@pytest.mark.parametrize("item,weather,damages,remaining", [
    ("", "raindance", True, ""),
    ("Power Herb", "", True, ""),
    ("Power Herb", "raindance", True, "powerherb"),
    ("Utility Umbrella", "raindance", False, "utilityumbrella"),
    ("", "", False, ""),
])
def test_electro_shot_boosts_before_charge_or_immediate_attack(item, weather, damages, remaining):
    p = mon("Archaludon", item=item)
    q = mon("Snorlax")
    board = resolve(p, q, "electroshot", field={"weather": weather})
    assert board[0][0]["boosts"]["spa"] == 1
    assert (board[1][0]["hp"] < 1) is damages
    assert board[0][0]["item"] == remaining


def test_second_charge_turn_does_not_boost_again():
    p = mon("Archaludon", effects={"electroshot": True}, boosts={"spa": 1})
    q = mon("Snorlax")
    board = resolve(p, q, "electroshot")
    assert board[0][0]["boosts"]["spa"] == 1
    assert board[1][0]["hp"] < 1


@pytest.mark.parametrize("berry", ["Lum Berry", "Chesto Berry"])
def test_sleep_cure_allows_a_slower_target_to_attack_same_turn(berry):
    p = mon("Amoonguss", stats={"spe": 100})
    q = mon("Calyrex-Ice", item=berry, stats={"spe": 30})
    board = resolve(p, q, "spore", "glaciallance")
    assert board[1][0]["status"] == ""
    assert board[1][0]["item"] == ""
    assert board[0][0]["hp"] < 1


def test_unnerve_blocks_sleep_cure_berry():
    p = mon("Amoonguss", ability="Unnerve", stats={"spe": 100})
    q = mon("Calyrex-Ice", item="Lum Berry", stats={"spe": 30})
    board = resolve(p, q, "spore", "glaciallance")
    assert board[1][0]["status"] == "slp"
    assert board[1][0]["item"] == "lumberry"
    assert board[0][0]["hp"] == 1


def test_mental_herb_restores_trick_room_on_the_same_turn():
    p = mon("Tornadus", ability="Prankster")
    q = mon("Cresselia", item="Mental Herb")
    base = dict(own=[p,None], foe=[q,None], own_bench=[], foe_bench=[], field={})
    fields = []
    with patch("pokemon_bot.battle.evaluate", side_effect=lambda b, r, f, horizon: fields.append(f.copy()) or 0):
        simulate(base, ((action("taunt"), PASS), (action("trickroom"), PASS)), False)
    assert fields[-1]["trickroom"] is True


def test_drain_punch_heals_before_rocky_helmet_damage():
    p = mon("Iron Hands")
    p["hp"] = .05
    q = mon("Blissey", item="Rocky Helmet")
    board = resolve(p, q, "drainpunch")
    healed = (1 - board[1][0]["hp"]) * q["stats"]["hp"] / p["stats"]["hp"] / 2
    assert board[0][0]["hp"] == pytest.approx(min(1., .05 + healed) - 1/6)
    assert board[0][0]["hp"] > 0


def test_unnerve_prevents_sitrus_recovery_after_damage():
    p = mon("Tyranitar", ability="Unnerve")
    q = mon("Dondozo", ability="Unaware", item="Sitrus Berry")
    q["hp"] = .55
    board = resolve(p, q, "crunch")
    assert 0 < board[1][0]["hp"] < .5
    assert board[1][0]["item"] == "sitrusberry"
    normal = resolve(dict(p, ability=""), q, "crunch")
    assert normal[1][0]["hp"] == pytest.approx(board[1][0]["hp"] + .25)



@pytest.mark.parametrize("held,blocked", [("Punching Glove", True), ("Protective Pads", False)])
def test_glove_removes_unseen_fist_contact_but_pads_do_not(held, blocked):
    p = mon("Urshifu-Rapid-Strike", ability="Unseen Fist", item=held)
    q = mon("Amoonguss", item="Rocky Helmet")
    board = resolve(p, q, "surgingstrikes", "protect")
    assert (board[1][0]["hp"] == 1) is blocked
    assert board[0][0]["hp"] == 1



def test_koraidon_switch_removes_electro_shots_immediate_rain_attack():
    p = mon("Archaludon", ability="Stamina")
    q = mon("Calyrex-Ice")
    reserve = mon("Koraidon", ability="Orichalcum Pulse")
    base = dict(own=[p,None], foe=[q,None], own_bench=[], foe_bench=[reserve], field={"weather":"raindance"})
    snapshots=[]
    with patch("pokemon_bot.battle.evaluate", side_effect=lambda b,r,f,horizon: snapshots.append(copy.deepcopy((b,f))) or 0):
        simulate(base, ((action("electroshot"),PASS), ({"type":"switch","species":"koraidon"},PASS)), False)
    board,field = snapshots[-1]
    assert field["weather"] == "sunnyday"
    assert board[1][0]["hp"] == 1
    assert board[0][0]["_charging"] == "electroshot"
    assert board[0][0]["boosts"]["spa"] == 1


def test_miraidon_switch_sets_terrain_before_priority_attack():
    p = mon("Dragonite")
    q = mon("Indeedee-F")
    reserve = mon("Miraidon", ability="Hadron Engine")
    base = dict(own=[p,None], foe=[q,None], own_bench=[], foe_bench=[reserve], field={"terrain":"psychicterrain"})
    snapshots=[]
    with patch("pokemon_bot.battle.evaluate", side_effect=lambda b,r,f,horizon: snapshots.append(copy.deepcopy((b,f))) or 0):
        simulate(base, ((action("extremespeed"),PASS), ({"type":"switch","species":"miraidon"},PASS)), False)
    board,field = snapshots[-1]
    assert field["terrain"] == "electricterrain"
    assert board[1][0]["hp"] < 1


def test_orichalcum_pulse_boosts_attack_only_in_effective_sun():
    p=mon("Koraidon", ability="Orichalcum Pulse")
    q=mon("Snorlax")
    plain=damage(dict(p,ability=""),q,"dragonclaw",{"weather":"sunnyday"})
    boosted=damage(p,q,"dragonclaw",{"weather":"sunnyday"})
    assert boosted > plain * 1.3
    assert damage(p,q,"dragonclaw",{}) == plain
    assert damage(dict(p,item="utilityumbrella"),q,"dragonclaw",{"weather":"sunnyday"}) == plain
    assert damage(p,q,"bodypress",{"weather":"sunnyday"}) > 1.3 * damage(dict(p,ability=""),q,"bodypress",{"weather":"sunnyday"})


def test_hadron_engine_special_attack_boost_does_not_require_grounding():
    p=mon("Miraidon", ability="Hadron Engine", item="Air Balloon")
    q=mon("Snorlax")
    plain=damage(dict(p,ability=""),q,"dragonpulse",{"terrain":"electricterrain"})
    assert damage(p,q,"dragonpulse",{"terrain":"electricterrain"}) > plain * 1.3
    assert damage(p,q,"dragonpulse",{}) == plain
    assert damage(p,q,"dragonclaw",{"terrain":"electricterrain"}) == damage(dict(p,ability=""),q,"dragonclaw",{"terrain":"electricterrain"})



@pytest.mark.skipif(not os.environ.get("SHOWDOWN_NODE"), reason="Set SHOWDOWN_NODE and install the pinned Pokemon Showdown dependency")
def test_independent_showdown_confirms_new_mechanics():
    script = r'''
const assert=require('node:assert/strict');
const {Battle}=require('pokemon-showdown');
const mk=(species,moves,ability,item='')=>({species,moves,ability,item,level:50});
const splash=()=>mk('Magikarp',['Splash'],'Swift Swim');
function turn(p,q,a,z='splash',setup=()=>{}) {
 const b=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[p,splash()]},p2:{name:'p2',team:[q,splash()]}});
 b.makeChoices('team 12','team 12');setup(b);b.makeChoices('move '+a+', move splash','move '+z+', move splash');return b;
}
let b=turn(mk('Urshifu-Rapid-Strike',['Surging Strikes'],'Unseen Fist'),mk('Amoonguss',['Splash'],'Regenerator','Rocky Helmet'),'surgingstrikes 1');
assert.equal(b.p1.active[0].maxhp-b.p1.active[0].hp,Math.floor(b.p1.active[0].maxhp/6)*3);b.destroy();
b=turn(mk('Urshifu-Rapid-Strike',['Surging Strikes'],'Unseen Fist'),mk('Archaludon',['Splash'],'Stamina'),'surgingstrikes 1');
assert.equal(b.p2.active[0].boosts.def,3);b.destroy();
b=turn(mk('Archaludon',['Electro Shot'],'Stamina'),mk('Snorlax',['Splash'],'Immunity'),'electroshot 1','splash',b=>b.field.setWeather('raindance',b.p1.active[0]));
assert.equal(b.p1.active[0].boosts.spa,1);assert.ok(b.p2.active[0].hp<b.p2.active[0].maxhp);b.destroy();
b=turn(mk('Amoonguss',['Spore'],'Regenerator'),mk('Calyrex-Ice',['Glacial Lance'],'As One (Glastrier)','Lum Berry'),'spore 1','glaciallance',b=>{b.p1.active[0].storedStats.spe=150;b.p2.active[0].storedStats.spe=10;});
assert.equal(b.p2.active[0].status,'');assert.equal(b.p2.active[0].item,'');assert.ok(b.p1.active[0].hp<b.p1.active[0].maxhp);b.destroy();
b=turn(mk('Iron Hands',['Drain Punch'],'Quark Drive'),mk('Blissey',['Splash'],'Natural Cure','Rocky Helmet'),'drainpunch 1','splash',b=>{b.p1.active[0].hp=10;});
assert.ok(b.p1.active[0].hp>10);b.destroy();
b=turn(mk('Tyranitar',['Crunch'],'Unnerve'),mk('Dondozo',['Splash'],'Unaware','Sitrus Berry'),'crunch 1','splash',b=>{b.p2.active[0].hp=Math.floor(b.p2.active[0].maxhp*.55);});
assert.ok(b.p2.active[0].hp<b.p2.active[0].maxhp*.5);assert.equal(b.p2.active[0].item,'sitrusberry');b.destroy();
b=turn(mk('Urshifu-Rapid-Strike',['Surging Strikes'],'Unseen Fist','Punching Glove'),mk('Amoonguss',['Protect'],'Regenerator','Rocky Helmet'),'surgingstrikes 1','protect');
assert.equal(b.p2.active[0].hp,b.p2.active[0].maxhp);b.destroy();
const c=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[mk('Archaludon',['Electro Shot'],'Stamina'),splash()]},p2:{name:'p2',team:[mk('Kyogre',['Splash'],'Drizzle'),splash(),mk('Koraidon',['Splash'],'Orichalcum Pulse')]}});
c.makeChoices('team 12','team 123');c.makeChoices('move electroshot 1, move splash','switch 3, move splash');
assert.equal(c.field.weather,'sunnyday');assert.equal(c.p2.active[0].hp,c.p2.active[0].maxhp);assert.ok(c.p1.active[0].volatiles.twoturnmove);c.destroy();
const d=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[mk('Dragonite',['Extreme Speed'],'Inner Focus'),splash()]},p2:{name:'p2',team:[mk('Indeedee-F',['Splash'],'Psychic Surge'),splash(),mk('Miraidon',['Splash'],'Hadron Engine')]}});
d.makeChoices('team 12','team 123');d.makeChoices('move extremespeed 1, move splash','switch 3, move splash');
assert.equal(d.field.terrain,'electricterrain');assert.ok(d.p2.active[0].hp<d.p2.active[0].maxhp);d.destroy();
console.log(JSON.stringify({checks:9,engine:require('pokemon-showdown/package.json').version}));
'''
    result = subprocess.run([os.environ["SHOWDOWN_NODE"], "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"checks": 9, "engine": "0.11.11"}
