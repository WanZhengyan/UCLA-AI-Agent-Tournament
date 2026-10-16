"""Behavioral safety/production checks, not combat-win-rate estimates."""
from copy import deepcopy

import pytest

from altruagent.models import GameState, DecisionContext
from redalert_bot.agent import create_agent
from redalert_bot.common import View, distance
from redalert_bot.combat import plan
from redalert_bot.economy import plan as economy, _expansion_site
from redalert_bot.strategy import observe, fortifications, radius, weapon_range
from redalert_bot.selftest import sample


def actor(i, typ="e1", x=40, y=40):
    return dict(id=i,type=typ,x=x,y=y,hp=100,idle=True)


def view(units=None, forts=None, enemies=None, now=150, remaining=600, config=None, military=None):
    raw=sample()
    raw.update(state_version=int(now*25),map={"id":"test","bounds":[0,0,100,100]},
               time={"game_seconds":now,"remaining_seconds":remaining})
    raw["legal_actions"]={"enemy_base":[80,80]}
    raw["observation"].update(
        base_center=[10,10],units=units or [actor(i) for i in range(1,16)],
        buildings=[actor(999,"fact",10,10)],visible_enemy_buildings=forts or [],
        visible_enemies=enemies or [],military=military or {})
    return View(raw,config)


def combat(v,memory=None):
    memory=memory if memory is not None else {"combat":{"scouted":True}}
    orders=[]
    def emit(order,**kwargs):
        orders.append(order)
        return True
    plan(v,memory,emit)
    return orders,memory


def test_visible_tower_blocks_the_approach_before_army_enters_range():
    fort=actor(80,"tsla",65,65)
    v=view(forts=[fort])
    orders,memory=combat(v)
    assert memory["combat"]["mode"]=="contain fortifications"
    assert all(o["cmd"] in {"move","set_stance"} for o in orders)
    assert all(distance(o["to"],(65,65))>radius(v,fort) for o in orders if "to" in o)


def test_fogged_towers_remain_a_risk_after_the_old_retreat_timer():
    v=view(forts=[actor(80,"tsla",65,65)])
    _,memory=combat(v)
    later=view(now=200)
    orders,memory=combat(later,memory)
    assert fortifications(later)
    assert memory["combat"]["mode"]=="contain fortifications"
    assert not any(o["cmd"]=="attack" or o.get("to")==[80,80] for o in orders)


def test_confirmed_empty_nearby_cell_removes_old_tower_contact():
    memory={}
    observe(view(forts=[actor(80,"tsla",65,65)]),memory)
    later=view(units=[actor(1,x=65,y=65)])
    observe(later,memory)
    assert not fortifications(later)


def test_late_deficit_does_not_override_tower_safety():
    v=view(forts=[actor(80,"tsla",65,65)],remaining=30,military={"deaths_cost":1000})
    orders,memory=combat(v)
    assert memory["combat"]["mode"]=="contain fortifications"
    assert not any(o.get("to")==[65,65] or o["cmd"]=="attack" for o in orders)


def test_exposed_economy_is_still_attacked_instead_of_permanent_turtling():
    v=view(units=[actor(i,x=35,y=20) for i in range(1,16)],
           forts=[actor(80,"tsla",75,75),actor(81,"proc",43,20)])
    orders,memory=combat(v)
    assert memory["combat"]["mode"]=="pressure enemy"
    assert any(o.get("target")==81 or o.get("to")==[43,20] for o in orders)


def test_recent_losing_exchange_regroups_before_feeding_more_units():
    _,memory=combat(view(military={"kills_cost":0,"deaths_cost":0}))
    orders,memory=combat(view(now=170,military={"kills_cost":100,"deaths_cost":800}),memory)
    assert memory["combat"]["mode"]=="recover after bad exchange"
    assert all(o["cmd"]=="move" for o in orders)
    assert not any(o.get("to")==[80,80] for o in orders)


def test_endgame_lead_does_not_abandon_an_attacked_economy():
    units=[actor(i,x=15,y=15) for i in range(1,16)]
    orders,memory=combat(view(units=units,enemies=[actor(80,x=18,y=15)],
                               remaining=40,military={"kills_cost":1000,"deaths_cost":0}))
    assert memory["combat"]["mode"]=="defend economy"
    assert any(o.get("to")==[18,15] for o in orders)


def test_reserve_is_small_stable_and_not_the_entire_army():
    units=[actor(i,x=15,y=15) for i in range(1,21)]
    orders,memory=combat(view(units=units))
    reserve=set(memory["combat"]["reserve_ids"])
    attacking={i for o in orders if o.get("to")==[80,80] for i in o["units"]}
    assert len(reserve)==4 and len(attacking)==16
    assert not reserve&attacking
    _,again=combat(view(units=units,now=151),memory)
    assert set(again["combat"]["reserve_ids"])==reserve


def siege_view(gun_x=60,gun_range=12):
    units=[actor(i,x=55,y=60) for i in range(1,13)]+[actor(40,"arty",gun_x,60)]
    cfg={"rules":{"units":{"arty":{"weapon":{"range":gun_range}}},
                  "buildings":{"tsla":{"weapon":{"range":8}}}}}
    return view(units=units,forts=[actor(80,"tsla",70,60)],config=cfg)


def test_ranged_siege_attacks_with_artillery_only_and_keeps_screen_outside():
    v=siege_view()
    orders,memory=combat(v)
    shots=[o for o in orders if o["cmd"]=="attack"]
    assert shots and all(o["units"]==[40] and o["target"]==80 for o in shots)
    assert memory["combat"]["mode"]=="ranged siege"
    assert all(distance(o["to"],(70,60))>9 for o in orders if "to" in o)


def test_out_of_range_artillery_gets_a_safe_move_not_a_chasing_attack():
    orders,_=combat(siege_view(gun_x=40))
    assert not any(o["cmd"]=="attack" for o in orders)
    assert any(o["cmd"]=="move" and o["units"]==[40] for o in orders)


def test_live_range_override_prevents_an_invalid_siege_advantage():
    orders,_=combat(siege_view(gun_range=7))
    assert not any(o["cmd"]=="attack" for o in orders)


@pytest.mark.parametrize("value,expected",[(11,11),("10c512",10.5),("bad",9),(float("nan"),9)])
def test_weapon_range_is_checked_and_prefers_live_rules(value,expected):
    v=view(config={"rules":{"units":{"arty":{"weapon":{"range":value}}}}})
    assert weapon_range(v,"arty",9)==expected


def econ_view(cash=2000,miners=4,available=None,power=300,drain=120):
    v=view(forts=[actor(80,"tsla",75,75)],units=[actor(i,"harv",12,12) for i in range(100,100+miners)]
           +[actor(i,"e1",15,15) for i in range(1,13)])
    v.buildings=[actor(i,t,10,10) for i,t in enumerate(["fact","powr","powr","barr","proc","proc","weap"],1000)]
    v.available=set(available or ["powr","fix","dome","harv","e1","e3","1tnk","arty"])
    v.econ.update(cash=cash,ore=0,power_provided=power,power_drained=drain,harvesters=miners)
    return v


def econ_orders(v):
    orders=[]
    economy(v,{},lambda order,**kw: orders.append(order) or True)
    return orders


def test_fortification_prompts_siege_tech_before_more_barracks():
    assert {"cmd":"build","item":"dome"} in econ_orders(econ_view())


def test_siege_tech_gets_power_first_if_it_would_cause_a_brownout():
    orders=econ_orders(econ_view(power=150,drain=120))
    assert {"cmd":"build","item":"powr"} in orders
    assert {"cmd":"build","item":"dome"} not in orders


def test_miner_replacement_outranks_artillery_even_when_enemy_has_towers():
    orders=econ_orders(econ_view(cash=400,miners=1,available=["harv","arty","e1","e3"]))
    assert {"cmd":"train","item":"harv","count":1} in orders
    assert not any(o.get("item")=="arty" for o in orders)


def test_artillery_can_be_built_with_infantry_screen_without_two_tanks():
    orders=econ_orders(econ_view(available=["harv","arty","e1","e3"]))
    assert {"cmd":"train","item":"arty","count":1} in orders


def test_containment_preserves_operating_cash_without_halting_surplus_spending():
    poor=econ_orders(econ_view(cash=350,available=["e1","e3","arty"]))
    rich=econ_orders(econ_view(cash=2000,available=["e1","e3","arty"]))
    assert not any(o["cmd"]=="train" for o in poor)
    assert any(o["cmd"]=="train" for o in rich)


def test_expansion_site_is_not_planned_next_to_a_known_tower():
    v=econ_view()
    v.ore_cells=[(30,10)]
    v.map_info={"layout":{"origin":[0,0],"rows":["."*100]*100}}
    v.enemy_buildings=[actor(80,"tsla",31,10)]
    assert _expansion_site(v,{}) is None


def test_full_agent_fortified_batch_respects_small_wire_limits():
    v=view(units=[actor(i) for i in range(1,150)],forts=[actor(800,"tsla",65,65)])
    raw=deepcopy(v.raw)
    raw["limits"]={"max_units_per_order":7,"max_orders_per_batch":12,"max_engine_commands_per_batch":60}
    ctx=DecisionContext("offline",None,"red_alert","offline",0)
    action=create_agent().choose_action(GameState.from_mcp_state(raw),ctx)
    assert len(action["orders"])<=12
    assert all(len(o.get("units",[]))<=7 for o in action["orders"])
    assert sum(len(o["units"]) if "units" in o else o.get("count",1) for o in action["orders"])<=60


def test_new_tower_contact_interrupts_recent_attack_order_immediately():
    units=[actor(i,x=50,y=50) for i in range(1,16)]
    _,memory=combat(view(units=units))
    for a in units:
        a["idle"]=False
    orders,memory=combat(view(units=units,forts=[actor(80,"tsla",62,62)],now=150.2),memory)
    assert memory["combat"]["mode"]=="contain fortifications"
    assert any(o["cmd"]=="move" for o in orders)


def test_mobile_army_behind_tower_line_prevents_unsafe_siege_advance():
    enemies=[actor(i,"3tnk",55,55) for i in range(100,110)]
    orders,memory=combat(view(forts=[actor(80,"tsla",62,62)],enemies=enemies))
    assert memory["combat"]["mode"]=="retreat from bad trade"
    assert any(o["cmd"]=="move" and o["to"][0]<40 for o in orders)
