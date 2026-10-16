"""Speed-control decisions checked against Gen 9 turn resolution."""
import copy
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from pokemon_bot.battle import choose_battle, evaluate, simulate, speed
from pokemon_bot.state import normalize_mon


PASS = {"type": "pass"}


def mon(name="Pikachu", **kwargs):
    return normalize_mon(dict(species=name, current_hp_fraction=1., **kwargs), {})


def action(name, target=1):
    return dict(type="move", move_id=name, target=target)


def state(ours=None, theirs=None, field=None):
    return dict(own=[ours or mon(), None], foe=[theirs or mon(), None],
                own_bench=[], foe_bench=[], field=field or {})


def resolve(base, actions=((PASS, PASS), (PASS, PASS))):
    snapshots = []

    def capture(board, benches, field, horizon=True):
        snapshots.append(copy.deepcopy((board, benches, field)))
        return evaluate(board, benches, field, horizon)

    with patch("pokemon_bot.battle.evaluate", side_effect=capture):
        simulate(base, actions, horizon=False)
    return snapshots[-1]


@pytest.mark.parametrize("raw,stage,item,status,tailwind,expected", [
    (91, 0, "choicescarf", "", False, 136),
    (101, -1, "choicescarf", "", False, 100),
    (101, -1, "choicescarf", "par", True, 100),
    (101, 0, "ironball", "par", False, 25),
    (101, 0, "poweranklet", "", False, 50),
    (101, 0, "", "par", False, 50),
])
def test_speed_uses_integer_stages_modifiers_and_final_paralysis(raw, stage, item, status, tailwind, expected):
    p = mon(ability="Static", item=item, status=status, boosts={"spe": stage})
    p["stats"]["spe"] = raw
    assert speed(p, 0, {"own_tailwind": tailwind}) == expected


def test_rounded_choice_scarf_speed_tie_does_not_guarantee_a_ko():
    p, q = mon(item="Choice Scarf", ability="Static"), mon(ability="Static")
    p["stats"]["spe"], q["stats"]["spe"] = 91, 136
    p["hp"] = q["hp"] = .01
    # Each side wins if it moves first; 91 * 1.5 is a real tie at 136.
    assert simulate(state(p, q), ((action("tackle"), PASS), (action("tackle"), PASS)), False) == pytest.approx(0.)


@pytest.mark.parametrize("ability,weather", [("Swift Swim", "raindance"), ("Chlorophyll", "sunnyday")])
def test_utility_umbrella_blocks_weather_speed(ability, weather):
    p = mon(ability=ability, item="Utility Umbrella")
    assert speed(p, 0, {"weather": weather}) == speed(p, 0, {})


def test_public_unburden_turns_a_losing_exchange_into_a_first_strike():
    p = mon("Sneasler", ability="Unburden", item="", effects={"unburden": True})
    q = mon("Flutter Mane", ability="Protosynthesis")
    p["stats"]["spe"], q["stats"]["spe"] = 172, 205
    p["hp"] = q["hp"] = .2
    board, _, _ = resolve(state(p, q), ((action("poisonjab"), PASS), (action("moonblast"), PASS)))
    assert board[0][0]["hp"] > 0
    assert board[1][0]["hp"] == 0


def test_policy_takes_a_neutral_stab_ko_enabled_by_public_unburden():
    own = dict(species="Sneasler", ability="Unburden", item="", effects={"unburden": True},
               moves=["poisonjab", "protect"], current_hp_fraction=.2, stats={"spe": 172})
    foe = dict(species="Flutter Mane", ability="Protosynthesis", moves=["moonblast"],
               current_hp_fraction=.2, stats={"spe": 205})
    obs = dict(turn=3, active_pokemon=[own, None], opponent_active_pokemon=[foe, None],
               team={"sneasler": own}, opponent_team={"fluttermane": foe})
    template = {"type": "doubles_turn", "slots": [
        {"slot": 0, "options": [dict(type="move", move_id="poisonjab", targets=[1]),
                                  dict(type="move", move_id="protect", targets=[0])]},
        {"slot": 1, "options": [PASS]},
    ]}
    chosen = choose_battle(obs, template, {}, budget=1.)
    assert chosen["slot_0"]["move_id"] == "poisonjab"


@pytest.mark.parametrize("item,ability,expected", [("", "Unburden", 200), ("Leftovers", "Unburden", 100), ("", "Pressure", 100)])
def test_unburden_needs_the_ability_and_no_replacement_item(item, ability, expected):
    p = mon("Sneasler", ability=ability, item=item, effects={"unburden": True})
    p["stats"]["spe"] = 100
    assert speed(p, 0, {}) == expected


def test_knock_off_activates_unburden_for_a_pending_move():
    p = mon("Weavile", ability="Pressure")
    q = mon("Sneasler", ability="Unburden", item="Leftovers")
    p["stats"]["spe"], q["stats"]["spe"] = 200, 100
    board, _, _ = resolve(state(p, q), ((action("knockoff"), PASS), (PASS, PASS)))
    assert board[1][0]["item"] == ""
    assert speed(board[1][0], 1, {}) == 200


def test_focus_sash_unburden_outruns_the_second_attacker_in_the_same_turn():
    p = mon("Sneasler", ability="Unburden", item="Focus Sash")
    q, r = mon("Weavile", ability="Pressure"), mon("Flutter Mane", ability="Protosynthesis")
    p["stats"]["spe"], q["stats"]["spe"], r["stats"]["spe"] = 100, 200, 150
    p["stats"]["def"] = 1  # Psycho Cut activates Sash before Moonblast acts.
    r["hp"] = .2
    base = state(p, q)
    base["foe"][1] = r
    board, _, _ = resolve(base, ((action("poisonjab", 2), PASS), (action("psychocut"), action("moonblast"))))
    assert board[0][0]["item"] == "" and board[0][0]["hp"] > 0
    assert board[1][1]["hp"] == 0


def test_unburden_is_lost_when_switching_out():
    p = mon("Sneasler", ability="Unburden", item="", effects={"unburden": True})
    p["_unburden"] = True
    p["stats"]["spe"] = 100
    base = state(p)
    base["own_bench"] = [mon("Amoonguss")]
    _, benches, _ = resolve(base, ((dict(type="switch", species="amoonguss"), PASS), (PASS, PASS)))
    assert speed(benches[0][0], 0, {}) == 100


@pytest.mark.parametrize("ability,effect,field", [
    ("Protosynthesis", "protosynthesisspa", {"weather": "sunnyday"}),
    ("Quark Drive", "quarkdrivespa", {"terrain": "electricterrain"}),
])
def test_public_paradox_stat_does_not_change_after_a_speed_boost(ability, effect, field):
    p = mon("Flutter Mane", ability=ability, effects={effect: True}, boosts={"spe": 1})
    p["stats"].update({"atk": 100, "def": 100, "spa": 180, "spd": 100, "spe": 170})
    assert speed(p, 0, field) == 255  # SpA was locked in at activation.


def test_known_speed_paradox_activation_is_applied_only_once():
    p = mon("Flutter Mane", ability="Protosynthesis", effects={"protosynthesisspe": True})
    p["stats"]["spe"] = 170
    p["_quark_speed"] = True
    assert speed(p, 0, {}) == 255


@pytest.mark.parametrize("condition", ["own_tailwind", "foe_tailwind", "trickroom"])
def test_last_turn_speed_control_expires_before_the_horizon(condition):
    base = state(field={condition: True, condition + "_turns": 1})
    _, _, field = resolve(base)
    assert field[condition] is False
    assert field[condition + "_turns"] == 0


def test_last_turn_tailwind_still_changes_this_turn_move_order():
    p, q = mon(), mon()
    p["stats"]["spe"], q["stats"]["spe"] = 100, 150
    p["hp"] = q["hp"] = .01
    base = state(p, q, {"own_tailwind": True, "own_tailwind_turns": 1})
    board, _, field = resolve(base, ((action("tackle"), PASS), (action("tackle"), PASS)))
    assert board[0][0]["hp"] > 0 and board[1][0]["hp"] == 0
    assert field["own_tailwind"] is False


def test_last_turn_trick_room_still_changes_this_turn_move_order():
    p, q = mon(), mon()
    p["stats"]["spe"], q["stats"]["spe"] = 100, 150
    p["hp"] = q["hp"] = .01
    base = state(p, q, {"trickroom": True, "trickroom_turns": 1})
    board, _, field = resolve(base, ((action("tackle"), PASS), (action("tackle"), PASS)))
    assert board[0][0]["hp"] > 0 and board[1][0]["hp"] == 0
    assert field["trickroom"] is False


@pytest.mark.parametrize("move,condition,remaining", [("tailwind", "own_tailwind", 3), ("trickroom", "trickroom", 4)])
def test_new_speed_control_has_the_correct_next_turn_duration(move, condition, remaining):
    _, _, field = resolve(state(), ((action(move, 0), PASS), (PASS, PASS)))
    assert field[condition] is True
    assert field[condition + "_turns"] == remaining


def test_tailwind_cannot_refresh_an_existing_last_turn():
    base = state(field={"own_tailwind": True, "own_tailwind_turns": 1})
    _, _, field = resolve(base, ((action("tailwind", 0), PASS), (PASS, PASS)))
    assert field["own_tailwind"] is False


def test_trick_room_removes_an_existing_room_instead_of_refreshing_it():
    base = state(field={"trickroom": True, "trickroom_turns": 3})
    _, _, field = resolve(base, ((action("trickroom", 0), PASS), (PASS, PASS)))
    assert field["trickroom"] is False and field["trickroom_turns"] == 0


def test_forced_replacement_does_not_spend_a_speed_control_turn():
    base = state(field={"own_tailwind": True, "own_tailwind_turns": 1, "trickroom": True, "trickroom_turns": 2})
    base["forced_switch"] = True
    _, _, field = resolve(base)
    assert field["own_tailwind_turns"] == 1 and field["trickroom_turns"] == 2


def test_unknown_speed_control_duration_is_not_invented():
    _, _, field = resolve(state(field={"own_tailwind": True, "trickroom": True}))
    assert field["own_tailwind"] is True and field["trickroom"] is True
    assert "own_tailwind_turns" not in field and "trickroom_turns" not in field


def test_tailwind_is_a_liability_while_it_reverses_matchups_under_trick_room():
    p, q = mon(), mon()
    p["stats"]["spe"], q["stats"]["spe"] = 100, 150
    plain = evaluate([[p, None], [q, None]], [[], []], {"trickroom": True}, False)
    boosted = evaluate([[p, None], [q, None]], [[], []], {"trickroom": True, "own_tailwind": True}, False)
    # The change loses the matchup (+0.16 -> -0.16) and must not also receive
    # the normal +0.29 Tailwind bonus, which nearly cancels that disadvantage.
    assert boosted < plain - .5


@pytest.mark.skipif(not os.environ.get("SHOWDOWN_NODE"), reason="Set SHOWDOWN_NODE with pinned Pokemon Showdown")
def test_independent_showdown_speed_rounding_abilities_and_duration():
    script = r'''
const assert=require('node:assert/strict');
const {Battle}=require('pokemon-showdown');
const mk=(species,ability,item='')=>({species,moves:['Splash','Tailwind','Trick Room','Tackle'],ability,item,level:50});
const make=(p=mk('Pikachu','Static'))=>{
 const b=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[p,mk('Magikarp','Swift Swim')]},p2:{name:'p2',team:[mk('Pikachu','Static'),mk('Magikarp','Swift Swim')]}});
 b.makeChoices('team 12','team 12');return b;
};
let checks=0;
for(const [raw,stage,item,status,tailwind,expected] of [
 [91,0,'Choice Scarf','',false,136], [101,-1,'Choice Scarf','',false,100],
 [101,-1,'Choice Scarf','par',true,100], [101,0,'Iron Ball','par',false,25],
 [101,0,'Power Anklet','',false,50], [101,0,'','par',false,50]]) {
 const b=make(mk('Pikachu','Static',item)),p=b.p1.active[0];
 p.storedStats.spe=raw;p.boosts.spe=stage;p.status=status;
 if(tailwind)p.side.addSideCondition('tailwind',p);
 assert.equal(p.getStat('spe'),expected);checks++;b.destroy();
}
for(const [ability,weather] of [['Swift Swim','raindance'],['Chlorophyll','sunnyday']]){
 const b=make(mk('Pikachu',ability,'Utility Umbrella')),p=b.p1.active[0];
 p.storedStats.spe=100;b.field.setWeather(weather,p);
 assert.equal(p.getStat('spe'),100);checks++;b.destroy();
}
{
 const b=make(mk('Sneasler','Unburden','Leftovers')),p=b.p1.active[0];p.storedStats.spe=100;
 p.takeItem();assert.equal(p.getStat('spe'),200);checks++;
 p.setItem('Leftovers');assert.equal(p.getStat('spe'),100);checks++;b.destroy();
}
for(const [ability,field] of [['Protosynthesis','sunnyday'],['Quark Drive','electricterrain']]) {
 const b=make(mk('Flutter Mane',ability)),p=b.p1.active[0];
 Object.assign(p.storedStats,{atk:100,def:100,spa:180,spd:100,spe:170});
 if(field==='sunnyday')b.field.setWeather(field,p);else b.field.setTerrain(field,p);
 p.boosts.spe=1;assert.equal(p.getStat('spe'),255);checks++;b.destroy();
}
{
 const p={species:'Sneasler',ability:'Unburden',item:'Focus Sash',moves:['Poison Jab'],level:50};
 const q={species:'Weavile',ability:'Pressure',moves:['Psycho Cut'],level:50};
 const r={species:'Flutter Mane',ability:'Protosynthesis',moves:['Moonblast'],level:50};
 const b=new Battle({formatid:'gen9doublescustomgame',strictChoices:true,seed:[10,20,30,40],p1:{name:'p1',team:[p,mk('Magikarp','Swift Swim')]},p2:{name:'p2',team:[q,r]}});
 b.makeChoices('team 12','team 12');
 b.p1.active[0].storedStats.spe=100;b.p1.active[0].storedStats.def=1;
 b.p2.active[0].storedStats.spe=200;b.p2.active[1].storedStats.spe=150;
 b.p2.active[1].hp=Math.floor(b.p2.active[1].maxhp*.2);
 b.makeChoices('move poisonjab 2, move splash','move psychocut 1, move moonblast 1');
 assert.equal(b.p1.active[0].hp,1);assert.equal(b.p2.active[1].hp,0);checks++;b.destroy();
}
{
 const b=make();b.makeChoices('move tailwind, move splash','move splash, move splash');
 assert.equal(b.p1.sideConditions.tailwind.duration,3);checks++;
 b.p1.sideConditions.tailwind.duration=1;
 b.makeChoices('move tailwind, move splash','move splash, move splash');
 assert.equal(b.p1.sideConditions.tailwind,undefined);checks++;b.destroy();
}
{
 const b=make();b.makeChoices('move trickroom, move splash','move splash, move splash');
 assert.equal(b.field.pseudoWeather.trickroom.duration,4);checks++;
 b.makeChoices('move trickroom, move splash','move splash, move splash');
 assert.equal(b.field.pseudoWeather.trickroom,undefined);checks++;b.destroy();
}
console.log(JSON.stringify({checks,engine:require('pokemon-showdown/package.json').version}));
'''
    result = subprocess.run([os.environ["SHOWDOWN_NODE"], "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"checks": 17, "engine": "0.11.11"}
