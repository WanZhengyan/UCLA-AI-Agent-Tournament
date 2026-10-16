"""Bounded, public-information doubles search.

This is an approximate evaluator, not a replacement for Pokemon Showdown.  It
enumerates the server's legal actions, models both players acting together, and
scores a small weighted response matrix.  No network/model call is needed.
"""
from __future__ import annotations

import copy
import itertools
import math
import time
from functools import lru_cache

from .dex import move, species, stats, effectiveness, idnorm, common_moves
from .state import build_battle


PROTECT = {"protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap", "burningbulwark", "obstruct"}
REDIRECT = {"followme", "ragepowder"}
SLEEP = {"spore", "sleeppowder", "hypnosis", "lovelykiss", "sing", "grasswhistle", "darkvoid"}
HEAL = {"recover", "roost", "slackoff", "softboiled", "milkdrink", "shoreup", "healorder", "synthesis", "moonlight", "morningsun"}
SPREAD_TARGETS = {"allAdjacent", "allAdjacentFoes", "all"}
PHYSICAL = "physical"


@lru_cache(maxsize=4096)
def md(name):
    """Normalize the handful of API and Dex naming differences once."""
    d = dict(move(name) or {})
    d["id"] = idnorm(name)
    d["type"] = str(d.get("type", d.get("move_type", "Normal"))).lower()
    d["category"] = str(d.get("category", "Physical")).lower()
    d["basePower"] = float(d.get("basePower", d.get("base_power", 0)) or 0)
    a = d.get("accuracy", 100)
    d["accuracy"] = 1.0 if a is True else min(1., float(a or 100) / (100 if float(a or 100) > 1 else 1))
    d["priority"] = int(d.get("priority", 0) or 0)
    return d


def alive(p):
    return bool(p) and p.get("hp", 0) > .0001 and not p.get("fainted", False)


def boost(n):
    n = max(-6, min(6, float(n or 0)))
    return (2+n)/2 if n >= 0 else 2/(2-n)


def getstat(p, k, crit=False, defending=False, ignore_boosts=False):
    b = 0. if ignore_boosts else float(p.get("boosts", {}).get(k, 0) or 0)
    if crit and ((defending and b > 0) or (not defending and b < 0)):
        b = 0
    return max(1., float(p.get("stats", {}).get(k, 100)) * boost(b))


def ability(p):
    return idnorm((p or {}).get("ability", ""))


def item(p):
    return idnorm((p or {}).get("item", ""))


def types(p):
    return [str(t).lower() for t in (p or {}).get("types", ["normal"])]


def grounded(p):
    return "flying" not in types(p) and ability(p) != "levitate" and item(p) != "airballoon"


def weather(f):
    return idnorm(f.get("weather", ""))


def terrain(f):
    return idnorm(f.get("terrain", ""))


def speed(p, side, field):
    v = getstat(p, "spe")
    ab, it, w = ability(p), item(p), weather(field)
    if it == "choicescarf": v *= 1.5
    if it in {"ironball", "machobrace"}: v *= .5
    if p.get("status") in {"par", "paralysis"} and ab != "quickfeet": v *= .5
    if ab == "quickfeet" and p.get("status"): v *= 1.5
    if field.get(("own_" if side == 0 else "foe_")+"tailwind"): v *= 2
    if (ab == "swiftswim" and w in {"rain", "raindance", "primordialsea"}) or (ab == "chlorophyll" and w in {"sun", "sunnyday", "desolateland"}) or (ab == "sandrush" and w == "sandstorm") or (ab == "slushrush" and w in {"snow", "hail", "snowscape"}): v *= 2
    if ab == "surgesurfer" and terrain(field) == "electricterrain": v *= 2
    if p.get("_unburden"): v *= 2
    if p.get("_quark_speed"): v *= 1.5
    effects=p.get("effects",{})
    if "protosynthesisspe" in effects or "quarkdrivespe" in effects:
        v *= 1.5
    elif (ab=="protosynthesis" and (w in {"sun","sunnyday","desolateland"} or it=="boosterenergy")) or (ab=="quarkdrive" and (terrain(field)=="electricterrain" or it=="boosterenergy")):
        best=max(("atk","def","spa","spd","spe"),key=lambda k:getstat(p,k))
        if best=="spe": v *= 1.5
    return v


def priority(p, a, field):
    if a.get("type") == "switch": return 6
    if a.get("type") != "move": return -20
    d = md(a["move_id"])
    pr = d["priority"]
    if ability(p) == "prankster" and d["category"] == "status": pr += 1
    if ability(p) == "galewings" and d["type"] == "flying" and p.get("hp", 0) >= .999: pr += 1
    if d["id"] == "grassyglide" and terrain(field) == "grassyterrain" and grounded(p): pr += 1
    if ability(p) == "triage" and (d.get("heal") or d.get("drain")): pr += 3
    return pr


def _crit_move(mid):
    return mid in {"surgingstrikes", "wickedblow", "flowertrick", "frostbreath", "stormthrow"}


def _needs_charge(p, d, field):
    if not d.get("flags",{}).get("charge"): return False
    mid=d["id"]; effects=p.get("effects",{})
    if "twoturnmove" in effects or mid in effects: return False
    if item(p)=="powerherb" and mid!="skydrop": return False
    if mid=="electroshot" and item(p)!="utilityumbrella" and weather(field) in {"rain","raindance","primordialsea"}: return False
    if mid in {"solarbeam","solarblade"} and weather(field) in {"sun","sunnyday","desolateland"}: return False
    return True


def _hit_weights(p, d):
    """Exact fixed hit counts; bounded mean approximations for random multi-hit moves."""
    hits=d.get("multihit",1)
    if isinstance(hits,(list,tuple)):
        hits=hits[-1] if ability(p)=="skilllink" else 4.5 if item(p)=="loadeddice" else 3.
    if d["id"]=="surgingstrikes": hits=3
    if d["id"]=="populationbomb": hits=6.5
    if d["id"] in {"tripleaxel","triplekick"}: return [1.,1.8,2.43]
    hits=float(hits or 1)
    return [1.] * int(hits) + ([hits % 1] if hits % 1 else [])


def _makes_contact(att, d):
    return bool(d.get("flags",{}).get("contact")) and ability(att)!="longreach" and not (item(att)=="punchingglove" and d.get("flags",{}).get("punch"))


def _contact_cost(att, defender, d):
    if not _makes_contact(att,d) or ability(att)=="magicguard" or item(att)=="protectivepads": return 0.
    return (1/6 if item(defender)=="rockyhelmet" else 0.) + (1/8 if ability(defender) in {"roughskin","ironbarbs"} else 0.)


def damage(att, defender, move_id, field=None, side=0, spread=False, friend=None, helping=False, _single_hit=False):
    """Expected HP fraction, using known fixed sets and common VGC mechanics."""
    if not alive(att) or not alive(defender): return 0.
    field = field or {}
    d = md(move_id); mid = d["id"]
    if d["category"] == "status": return 0.
    # Electro Shot/Meteor Beam boost before attacking, even with rain/Power Herb.
    # The simulator marks its explicit boost to avoid applying it twice here.
    if mid in {"electroshot","meteorbeam"} and not att.get("_charge_boost_applied") and not (mid in att.get("effects",{}) or "twoturnmove" in att.get("effects",{})):
        att=_clone_mon(att); _setboost(att,{"spa":1}); att["_charge_boost_applied"]=True
    hit_weights=_hit_weights(att,d)
    if not _single_hit and len(hit_weights)>1:
        q=_clone_mon(defender); total=0.
        for weight in hit_weights:
            part=damage(att,q,move_id,field,side,spread,friend,helping,_single_hit=True)*weight
            total+=part
            # Retain a positive HP floor so ranking sees damage beyond the KO
            # threshold, while only the first hit benefits from Multiscale.
            q["hp"]=max(.00001,q["hp"]-part)
            if part>0 and ability(q)=="stamina": _setboost(q,{"def":1})
        return total
    ab, db, it, di = ability(att), ability(defender), item(att), item(defender)
    if ab in {"moldbreaker", "teravolt", "turboblaze"} or d.get("ignoreAbility"): db = ""
    typ = d["type"]
    power = d["basePower"]
    w, tr = weather(field), terrain(field)
    if mid == "terablast": typ = "normal"
    if mid == "ivycudgel":
        form=idnorm(att.get("species",""))
        if "wellspring" in form: typ="water"
        elif "hearthflame" in form: typ="fire"
        elif "cornerstone" in form: typ="rock"
        if it in {"wellspringmask","hearthflamemask","cornerstonemask"}: power *= 1.2
    if mid == "weatherball":
        if w in {"sun", "sunnyday", "desolateland"}: typ, power = "fire", 100
        elif w in {"rain", "raindance", "primordialsea"}: typ, power = "water", 100
        elif w == "sandstorm": typ, power = "rock", 100
        elif w in {"snow", "snowscape", "hail"}: typ, power = "ice", 100
    if typ == "normal" and ab in {"pixilate", "aerilate", "refrigerate", "galvanize"}:
        typ = {"pixilate":"fairy", "aerilate":"flying", "refrigerate":"ice", "galvanize":"electric"}[ab]; power *= 1.2
    if mid == "terrainpulse" and grounded(att) and tr:
        typ = {"grassyterrain":"grass", "electricterrain":"electric", "psychicterrain":"psychic", "mistyterrain":"fairy"}.get(tr, typ); power *= 2
    eff = float(effectiveness(typ, types(defender)))
    if eff == 0: return 0.
    if typ == "ground" and (db == "levitate" or di == "airballoon") and mid != "thousandarrows": return 0.
    if typ == "fire" and db in {"flashfire", "wellbakedbody"}: return 0.
    if typ == "water" and db in {"waterabsorb", "stormdrain", "dryskin"}: return 0.
    if typ == "electric" and db in {"voltabsorb", "lightningrod", "motordrive"}: return 0.
    if typ == "grass" and db == "sapsipper": return 0.
    if db == "wonderguard" and eff <= 1: return 0.
    if db == "soundproof" and d.get("flags", {}).get("sound"): return 0.
    if db == "bulletproof" and d.get("flags", {}).get("bullet"): return 0.
    if mid in {"seismictoss", "nightshade"}: return float(att.get("level", 50))/max(1,defender.get("stats", {}).get("hp", 180))
    if mid in {"superfang", "naturesmadness", "ruination"}: return defender["hp"]*.5*d["accuracy"]
    if mid == "finalgambit": return att["hp"]*att.get("stats",{}).get("hp",180)/max(1,defender.get("stats",{}).get("hp",180))
    if mid == "endeavor": return max(0., defender["hp"] - att["hp"]*att.get("stats",{}).get("hp",180)/max(1,defender.get("stats",{}).get("hp",180)))
    if mid in {"eruption", "waterspout", "dragonenergy"}: power = max(1., 150*att["hp"])
    if mid in {"electroball"}: power = 150 if speed(att, side, field)/speed(defender,1-side,field)>=4 else 120 if speed(att,side,field)/speed(defender,1-side,field)>=3 else 80 if speed(att,side,field)/speed(defender,1-side,field)>=2 else 60
    if mid == "gyroball": power = min(150, 25*speed(defender,1-side,field)/speed(att,side,field)+1)
    if mid == "storedpower" or mid == "powertrip": power = 20 + 20*sum(max(0,v) for v in att.get("boosts",{}).values())
    if mid in {"lowkick", "grassknot"}:
        wt = float(defender.get("weightkg", 80) or 80); power = 120 if wt>=200 else 100 if wt>=100 else 80 if wt>=50 else 60 if wt>=25 else 40 if wt>=10 else 20
    if mid in {"heavyslam", "heatcrash"}:
        ratio = float(att.get("weightkg", 150) or 150)/max(1,float(defender.get("weightkg",80) or 80)); power = 120 if ratio>=5 else 100 if ratio>=4 else 80 if ratio>=3 else 60 if ratio>=2 else 40
    if mid == "knockoff" and di: power *= 1.5
    if mid == "lastrespects": power=50+50*min(3,int(att.get("fainted_allies",0)))
    if mid == "acrobatics" and not it: power *= 2
    if mid == "facade" and att.get("status"): power *= 2
    if mid == "hex" and defender.get("status"): power *= 2
    if mid == "brine" and defender["hp"] <= .5: power *= 2
    if mid == "expandingforce" and tr == "psychicterrain" and grounded(att): power *= 1.5
    if mid == "risingvoltage" and tr == "electricterrain" and grounded(defender): power *= 2
    if mid == "grassyglide": power = power or 55
    if not power: return 0.
    if ab == "technician" and power <= 60: power *= 1.5
    if ab == "strongjaw" and d.get("flags",{}).get("bite"): power *= 1.5
    if ab == "ironfist" and d.get("flags",{}).get("punch"): power *= 1.2
    if ab == "toughclaws" and _makes_contact(att,d): power *= 1.3
    if it == "punchingglove" and d.get("flags",{}).get("punch"): power *= 1.1
    if ab == "sharpness" and d.get("flags",{}).get("slicing"): power *= 1.5
    if ab == "punkrock" and d.get("flags",{}).get("sound"): power *= 1.3
    if ab == "sheerforce" and (d.get("secondary") or d.get("secondaries")): power *= 1.3
    crit = _crit_move(mid) and db not in {"battlearmor", "shellarmor"}
    physical = d["category"] == PHYSICAL
    atkkey = "atk" if physical else "spa"
    defkey = "def" if physical or mid in {"psyshock", "psystrike", "secretsword"} else "spd"
    atkp = defender if mid == "foulplay" else att
    if mid == "bodypress": atkkey = "def"
    atkval = getstat(atkp, atkkey, crit, ignore_boosts=db=="unaware" and atkp is att)
    defval = getstat(defender, defkey, crit, True, ignore_boosts=ab=="unaware")
    if ab in {"hugepower", "purepower"} and physical and mid != "bodypress": atkval *= 2
    if ab == "guts" and physical and att.get("status"): atkval *= 1.5
    if it == "choiceband" and physical: atkval *= 1.5
    if it == "choicespecs" and not physical: atkval *= 1.5
    if it == "assaultvest" and defkey == "spd": pass
    if di == "assaultvest" and defkey == "spd": defval *= 1.5
    if di == "eviolite": defval *= 1.5
    if (field.get("swordofruin") or ab == "swordofruin") and db != "swordofruin" and defkey == "def": defval *= .75
    if (field.get("beadsofruin") or ab == "beadsofruin") and db != "beadsofruin" and defkey == "spd": defval *= .75
    if field.get("tabletsofruin") and ab != "tabletsofruin" and atkkey == "atk": atkval *= .75
    if field.get("vesselofruin") and ab != "vesselofruin" and atkkey == "spa": atkval *= .75
    if w == "sandstorm" and "rock" in types(defender) and defkey == "spd": defval *= 1.5
    if w in {"snow","snowscape"} and "ice" in types(defender) and defkey == "def": defval *= 1.5
    if ab == "solarpower" and w in {"sun","sunnyday","desolateland"} and not physical: atkval *= 1.5
    if ab == "orichalcumpulse" and physical and it != "utilityumbrella" and w in {"sun","sunnyday","desolateland"}: atkval *= 5461/4096
    if ab == "hadronengine" and not physical and tr == "electricterrain": atkval *= 5461/4096
    if (ab == "protosynthesis" and (w in {"sun","sunnyday","desolateland"} or it=="boosterenergy")) or (ab=="quarkdrive" and (tr=="electricterrain" or it=="boosterenergy")):
        best = max(("atk","def","spa","spd","spe"),key=lambda k:getstat(att,k))
        if best == atkkey: atkval *= 1.3
    level = float(att.get("level", 50) or 50)
    dmg = ((2*level/5+2)*power*atkval/defval/50+2)*.925
    mult = eff
    if typ in types(att): mult *= 2 if ab=="adaptability" else 1.5
    if crit: mult *= 1.5
    if spread: mult *= .75
    if helping: mult *= 1.5
    if physical and att.get("status") in {"brn","burn"} and ab != "guts" and mid != "facade": mult *= .5
    if w in {"sun","sunnyday","desolateland"}:
        if typ=="fire": mult *= 1.5
        if typ=="water": mult *= .5
    if w in {"rain","raindance","primordialsea"}:
        if typ=="water": mult *= 1.5
        if typ=="fire": mult *= .5
    if grounded(att) and ((tr=="grassyterrain" and typ=="grass") or (tr=="electricterrain" and typ=="electric") or (tr=="psychicterrain" and typ=="psychic")): mult *= 1.3
    if grounded(defender) and tr=="mistyterrain" and typ=="dragon": mult *= .5
    if grounded(defender) and tr=="grassyterrain" and mid in {"earthquake","bulldoze","magnitude"}: mult *= .5
    if db in {"filter","solidrock","prismarmor"} and eff>1: mult *= .75
    if db in {"multiscale","shadowshield"} and defender["hp"]>=.999: mult *= .5
    if db=="thickfat" and typ in {"fire","ice"}: mult *= .5
    if db=="icescales" and not physical: mult *= .5
    if db=="furcoat" and physical: mult *= .5
    if db=="purifyingsalt" and typ=="ghost": mult *= .5
    if db=="heatproof" and typ=="fire": mult *= .5
    if db=="fluffy":
        if _makes_contact(att,d): mult *= .5
        if typ=="fire": mult *= 2
    if friend and alive(friend) and ability(friend)=="friendguard": mult *= .75
    if it=="lifeorb": mult *= 1.3
    if it=="expertbelt" and eff>1: mult *= 1.2
    boosters={"mysticwater":"water","charcoal":"fire","magnet":"electric","miracleseed":"grass","nevermeltice":"ice","blackbelt":"fighting","poisonbarb":"poison","softsand":"ground","sharpbeak":"flying","twistedspoon":"psychic","silverpowder":"bug","hardstone":"rock","spelltag":"ghost","dragonfang":"dragon","blackglasses":"dark","metalcoat":"steel","fairyfeather":"fairy","silkscarf":"normal"}
    if boosters.get(it)==typ: mult *= 1.2
    screen = ("foe_" if side==0 else "own_")+("reflect" if physical else "lightscreen")
    if (field.get(screen) or field.get(("foe_" if side==0 else "own_")+"auroraveil")) and not crit and ab!="infiltrator": mult *= 2/3
    dmg = dmg*mult/max(1,float(defender.get("stats",{}).get("hp",180)))
    acc = d["accuracy"]
    if ab=="noguard" or db=="noguard": acc=1.
    if mid in {"thunder","hurricane"} and w in {"rain","raindance","primordialsea"}: acc=1.
    if mid=="blizzard" and w in {"snow","snowscape","hail"}: acc=1.
    if it=="widelens": acc=min(1,acc*1.1)
    # Keep KO thresholds sharp for reliable attacks while pricing unreliable ones.
    return max(0.,dmg*(.6+.4*acc))


def _target_pairs(a, side, slot, board, field):
    if a.get("type") != "move": return []
    d=md(a["move_id"]); target=d.get("target","normal")
    if d["id"]=="expandingforce" and terrain(field)=="psychicterrain" and grounded(board[side][slot]): target="allAdjacentFoes"
    if target=="allAdjacentFoes": return [(1-side,j) for j in (0,1) if alive(board[1-side][j])]
    if target in {"allAdjacent","all"}: return [(s,j) for s in (0,1) for j in (0,1) if (s,j)!=(side,slot) and alive(board[s][j])]
    t=a.get("target",0)
    if t>0: return [(1-side,min(1,t-1))]
    if t<0: return [(side,min(1,-t-1))]
    if target in {"self","allySide"}: return [(side,slot)]
    if target=="adjacentAlly": return [(side,1-slot)]
    if d["category"]!="status": return [(1-side,next((j for j in (0,1) if alive(board[1-side][j])),0))]
    return []


def enumerate_slot(template_slot):
    out=[]
    for opt in template_slot.get("options",[]):
        kind=opt.get("type")
        if kind=="move":
            for t in opt.get("targets") or [None]:
                a={"type":"move","move_id":opt["move_id"]}
                if t is not None: a["target"]=t
                out.append(a)
        elif kind=="switch": out.append({"type":"switch","species":opt["species"]})
        elif kind=="pass": out.append({"type":"pass"})
    return out or [{"type":"pass"}]


def opponent_slot(p, slot, board, bench, field):
    if not alive(p):
        return [{"type":"switch","species":x["species"]} for x in bench if alive(x)] or [{"type":"pass"}]
    out=[]
    for m in p.get("moves",[]):
        if isinstance(m,dict): m=m.get("id",m.get("name",""))
        if not m: continue
        m=idnorm(m); d=md(m); target=d.get("target","normal")
        if m=="fakeout" and not p.get("first_turn",True): continue
        if target in {"allAdjacentFoes","allAdjacent","self","allySide","foeSide","all"}: ts=[0]
        elif target=="adjacentAlly": ts=[-(2-slot)]
        elif target=="adjacentAllyOrSelf": ts=[-1,-2]
        else: ts=[j+1 for j in (0,1) if alive(board[0][j])]
        out.extend({"type":"move","move_id":m,"target":t} for t in ts)
    # A reasonable uncertainty fallback only when no public move set is known.
    if not out:
        for t in (1,2):
            if alive(board[0][t-1]): out.append({"type":"move","move_id":"struggle","target":t})
    out.extend({"type":"switch","species":x["species"]} for x in bench if alive(x))
    return out or [{"type":"pass"}]


def _status_possible(att, target, mid, field):
    if not alive(target) or target.get("status"): return False
    ab=ability(target); tt=types(target)
    if ab in {"purifyingsalt","comatose","goodasgold"}: return False
    if terrain(field)=="mistyterrain" and grounded(target): return False
    if mid in SLEEP or mid=="yawn":
        if ab in {"insomnia","vitalspirit","sweetveil"}: return False
        if terrain(field)=="electricterrain" and grounded(target): return False
        if mid in {"spore","sleeppowder"} and ("grass" in tt or ab=="overcoat" or item(target)=="safetygoggles"): return False
    if mid in {"willowisp"} and ("fire" in tt or ab in {"waterveil","waterbubble"}): return False
    if mid=="thunderwave" and ("ground" in tt or "electric" in tt or ab in {"limber","voltabsorb","lightningrod","motordrive"}): return False
    if mid in {"toxic","poisonpowder"} and ("poison" in tt or "steel" in tt or ab=="immunity"): return False
    if ability(att)=="prankster" and "dark" in tt: return False
    return True


def _incoming(p, foes, field, side):
    risks=[]
    for foe in foes:
        if alive(foe):
            risks.append(max([damage(foe,p,m.get("id","") if isinstance(m,dict) else m,field,1-side) for m in foe.get("moves",[])] or [.12]))
    return sum(risks)


def action_value(a, p, side, slot, board, bench, field):
    if a["type"]=="pass": return -5 if alive(p) else 0
    foes=board[1-side]
    if a["type"]=="switch":
        q=next((x for x in bench if idnorm(x.get("species",""))==idnorm(a["species"])),None)
        if not q: return -.1
        if not alive(p): return 1+q.get("hp",1)*.3+max([damage(q,x,m,field,side) for x in foes if alive(x) for m in q.get("moves",[]) if isinstance(m,str)] or [0])
        incoming=_incoming(p,foes,field,side); after=_incoming(q,foes,field,side)
        val=.45*(min(p["hp"],incoming)-min(q["hp"],after))-.18
        if ability(q)=="intimidate": val+=.16*sum(alive(x) and getstat(x,"atk")>getstat(x,"spa")*.8 and ability(x) not in {"defiant","competitive","clearbody","innerfocus","oblivious","owntempo"} for x in foes)
        if ability(p)=="regenerator": val+=min(.333,1-p["hp"])*.8
        return val
    if not alive(p): return -5
    d=md(a["move_id"]); mid=d["id"]
    if mid in PROTECT:
        if p.get("protect_count",0): return -.7
        risk=_incoming(p,foes,field,side)
        return .12+min(.7,risk)*.22+(0.12 if risk>=p["hp"] else 0)
    if mid in {"wideguard","quickguard"}:
        threats=sum(1 for f in foes if alive(f) for m in f.get("moves",[]) if isinstance(m,str) and (md(m).get("target") in SPREAD_TARGETS if mid=="wideguard" else md(m)["priority"]>0))
        return min(.55,threats*.18)-.05
    if mid=="tailwind":
        if field.get(("own_" if side==0 else "foe_")+"tailwind"): return -.5
        swings=sum(speed(x,side,field)<speed(y,1-side,field)<2*speed(x,side,field) for x in board[side] if alive(x) for y in foes if alive(y))
        return .15+.18*swings if not field.get("trickroom") else -.3
    if mid=="trickroom":
        adv=sum(1 if speed(x,side,field)<speed(y,1-side,field) else -1 for x in board[side] if alive(x) for y in foes if alive(y))
        return adv*(.23 if not field.get("trickroom") else -.23)
    if mid in REDIRECT: return .2 if alive(board[side][1-slot]) else -.5
    if mid=="helpinghand": return .23 if alive(board[side][1-slot]) else -1
    if mid in HEAL: return min(.5,1-p["hp"])*1.2-.06
    if mid=="pollenpuff" and a.get("target",0)<0:
        q=board[side][-a["target"]-1]; return min(.5,1-q.get("hp",1)) if alive(q) else -1
    pairs=_target_pairs(a,side,slot,board,field)
    val=0
    if mid=="fakeout" and not p.get("first_turn",True): return -2
    for s,j in pairs:
        q=board[s][j]
        if not alive(q): continue
        sign=1 if s!=side else -1.2
        if d["category"]!="status":
            dmg=damage(p,q,mid,field,side,len(pairs)>1,board[s][1-j])
            if _needs_charge(p,d,field): dmg *= .4
            val+=sign*(min(dmg,q["hp"])+(.75 if dmg>=q["hp"] else .25*dmg/max(.15,q["hp"])))
            if mid=="fakeout" and dmg>0 and ability(q) not in {"innerfocus","shielddust"} and item(q)!="covertcloak" and "ghost" not in types(q): val+=.45
            if mid in {"icywind","electroweb","bulldoze"}: val+=sign*.12
            if mid=="snarl" and getstat(q,"spa")>getstat(q,"atk"): val+=sign*.12
        elif mid in SLEEP or mid in {"yawn","willowisp","thunderwave","toxic"}:
            if _status_possible(p,q,mid,field):
                val+=sign*({"willowisp":.45 if getstat(q,"atk")>getstat(q,"spa") else .13,"thunderwave":.4,"toxic":.15,"yawn":.35}.get(mid,.7)*d["accuracy"])
        elif mid=="taunt": val+=sign*(.28 if any(md(m)["category"]=="status" for m in q.get("moves",[]) if isinstance(m,str)) else .03)
    if d["category"]=="status" and d.get("boosts"):
        val+=sum(v*(.11 if k in {"atk","spa","spe"} else .045) for k,v in d["boosts"].items() if v>0)
    return val


def joint_options(lists, board, bench, field, side, cap):
    ranked=[]
    values=[]
    for slot in (0,1):
        vals=[(action_value(a,board[side][slot],side,slot,board,bench,field),a) for a in lists[slot]]
        vals.sort(key=lambda x:x[0],reverse=True)
        values.append(vals[:14])
    for (v,a),(w,b) in itertools.product(*values):
        if a["type"]==b["type"]=="pass": continue
        if a["type"]==b["type"]=="switch" and idnorm(a["species"])==idnorm(b["species"]): continue
        score=v+w
        mids=[idnorm(x.get("move_id","")) for x in (a,b)]
        if mids[0]==mids[1] and mids[0] in {"tailwind","trickroom","wideguard","quickguard","followme","ragepowder"}: score-=1.5
        if mids[0] in PROTECT and mids[1] in PROTECT: score-=.2
        if "helpinghand" in mids:
            k=mids.index("helpinghand"); other=(a,b)[1-k]
            if other["type"]!="move" or md(other["move_id"])["category"]=="status": score-=1
        # Reward double targets that jointly cross the important knockout boundary.
        if a["type"]==b["type"]=="move" and a.get("target",0)==b.get("target",0) and a.get("target",0)>0:
            q=board[1-side][a["target"]-1]
            if alive(q):
                ds=[damage(board[side][k],q,(a,b)[k]["move_id"],field,side) for k in (0,1)]
                if max(ds)<q["hp"]<=sum(ds): score+=.55
                if min(ds)>=q["hp"]: score-=.5
        ranked.append((score,(a,b)))
    ranked.sort(key=lambda x:x[0],reverse=True)
    selected=ranked[:cap]
    # Keep tactical responses represented even when raw damage ranks highest.
    tactical={"guard":PROTECT,"redirect":REDIRECT,"speed":{"tailwind","trickroom"},"wideguard":{"wideguard"},"fakeout":{"fakeout"},"support":{"helpinghand"},"disrupt":SLEEP|{"taunt"}}
    for slot in (0,1):
        for family in tactical.values():
            candidate=next((x for x in ranked if x[1][slot].get("type")=="move" and idnorm(x[1][slot].get("move_id","")) in family),None)
            if candidate is not None and candidate not in selected: selected.append(candidate)
        # Preserve each switch destination: a low immediate damage score must
        # not eliminate an immune/resistant pivot before responses are simulated.
        switches={idnorm(a["species"]) for a in lists[slot] if a.get("type")=="switch"}
        for destination in sorted(switches):
            candidate=next((x for x in ranked if x[1][slot].get("type")=="switch" and idnorm(x[1][slot]["species"])==destination),None)
            if candidate is not None and candidate not in selected: selected.append(candidate)
    return selected or [(0.,({"type":"pass"},{"type":"pass"}))]


def _setboost(p, changes, *, opposing=False, bypass=False):
    """Apply stage changes, including actual-drop-triggered Defiant/Competitive."""
    b=p.setdefault("boosts",{})
    ab=ability(p)
    for k,v in changes.items():
        if ab=="contrary" and not bypass: v=-v
        elif ab=="simple" and not bypass: v*=2
        if opposing and v<0:
            if item(p)=="clearamulet" or ab=="fullmetalbody": continue
            if not bypass and (ab in {"clearbody","whitesmoke"} or
                               (ab=="hypercutter" and k=="atk") or
                               (ab=="bigpecks" and k=="def") or
                               (ab in {"keeneye","mindseye"} and k=="accuracy")):
                continue
        before=float(b.get(k,0))
        b[k]=max(-6,min(6,before+v))
        if opposing and b[k]<before and ab in {"defiant","competitive"}:
            response="atk" if ab=="defiant" else "spa"
            b[response]=min(6,b.get(response,0)+2)


def _entry(q, side, board, field):
    ab=ability(q)
    if ab=="intimidate":
        for foe in board[1-side]:
            if not alive(foe) or ability(foe) in {"clearbody","whitesmoke","fullmetalbody","innerfocus","oblivious","owntempo","scrappy"} or item(foe)=="clearamulet": continue
            _setboost(foe,{"atk":-1},opposing=True)
    if ab in {"drizzle","drought","orichalcumpulse","sandstream","snowwarning"}: field["weather"]={"drizzle":"raindance","drought":"sunnyday","orichalcumpulse":"sunnyday","sandstream":"sandstorm","snowwarning":"snowscape"}[ab]
    if ab in {"electricsurge","hadronengine","grassysurge","psychicsurge","mistysurge"}: field["terrain"]={"electricsurge":"electricterrain","hadronengine":"electricterrain","grassysurge":"grassyterrain","psychicsurge":"psychicterrain","mistysurge":"mistyterrain"}[ab]


def _berries_blocked(foes):
    return any(alive(q) and ability(q) in {"unnerve","asoneglastrier","asonespectrier"} for q in foes)


def _activate_cure(p, foes):
    """Immediate held-item cures happen before a later move in the same turn."""
    it=item(p)
    blocked=_berries_blocked(foes)
    status=p.get("status","")
    cures_status=(it=="lumberry" and bool(status)) or (it=="chestoberry" and status in {"slp","sleep"})
    if cures_status and not blocked:
        p["status"]=""; p["item"]=""
    elif it=="mentalherb" and p.get("_taunt"):
        p.pop("_taunt",None); p["item"]=""
    else:
        return
    if ability(p)=="unburden": p["_unburden"]=True


def _clone_mon(p):
    q=dict(p or {})
    q["boosts"]=dict(q.get("boosts",{}))
    effects=q.get("effects",{})
    if "taunt" in effects: q["_taunt"]=True
    if "saltcure" in effects: q["_saltcure"]=True
    return q


def _status_value(p):
    s=p.get("status","")
    if s in {"slp","sleep"}: return -.48
    if s in {"frz","freeze"}: return -.65
    if s in {"par","paralysis"}: return -.14
    if s in {"brn","burn"}: return -.23 if getstat(p,"atk")>getstat(p,"spa") and ability(p)!="guts" else -.07
    if s in {"tox","psn","poison","toxic"}: return -.1
    return 0


def evaluate(board, benches, field, horizon=True):
    score=0
    for s in (0,1):
        sign=1 if s==0 else -1
        living=[p for p in board[s]+benches[s] if alive(p)]
        for p in living:
            value=1.85+1.10*p["hp"]+_status_value(p)
            if p in board[s]:
                value+=sum(p.get("boosts",{}).get(k,0)*(.11 if k in {"atk","spa"} else .06) for k in ("atk","def","spa","spd"))
                value+=.04 if p.get("_redirect") else 0
            score+=sign*value
        unknown=field.get("_unknown_reserves",[0,0])[s]
        score+=sign*2.95*unknown
        if not living and not unknown: score-=sign*18
        prefix="own_" if s==0 else "foe_"
        if field.get(prefix+"tailwind"):
            swings=sum(speed(p,s,field)/2 < speed(q,1-s,field) < speed(p,s,field) for p in board[s] if alive(p) for q in board[1-s] if alive(q))
            score+=sign*(.14+.15*swings)
        for screen in ("reflect","lightscreen","auroraveil"):
            if field.get(prefix+screen): score+=sign*.14
    if field.get("trickroom"):
        score+=.16*sum(1 if speed(p,0,field)<speed(q,1,field) else -1 for p in board[0] if alive(p) for q in board[1] if alive(q))
        # Trick Room enables the reserves brought specifically for that mode.
        for s in (0,1):
            adv=sum(1 if speed(p,s,field)<speed(q,1-s,field) else -1 for p in benches[s] if alive(p) for q in board[1-s] if alive(q))
            score+=(1 if s==0 else -1)*.055*adv
    if horizon:
        # Discounted next-turn tactical potential: surviving faster attackers,
        # useful damage coverage and immediate cleanup opportunities.
        potentials=[0.,0.]
        for s in (0,1):
            for p in board[s]:
                if not alive(p): continue
                best=0
                for q in board[1-s]:
                    if not alive(q): continue
                    dm=max([damage(p,q,m,field,s) for m in p.get("moves",[]) if isinstance(m,str)] or [0])
                    fast=(speed(p,s,field)>speed(q,1-s,field)) != bool(field.get("trickroom"))
                    v=min(dm,q["hp"])*(.20 if fast else .09)+(.15 if dm>=q["hp"] and fast else 0)
                    best=max(best,v)
                potentials[s]+=best
        score+=potentials[0]-potentials[1]
    return score


def simulate(base, actions, horizon=True):
    """Average opposite tie orders when speed ties can affect the turn.

    This bounded two-order approximation removes the old fixed own-side bias;
    it is not an exhaustive random-event tree for three or more tied Pokemon.
    """
    value,tied=_simulate(base,actions,horizon,tie_order=1)
    if tied:
        reverse,_=_simulate(base,actions,horizon,tie_order=-1)
        return (value+reverse)/2
    return value


def _simulate(base, actions, horizon, tie_order):
    board=[[_clone_mon(p) for p in base["own"]],[_clone_mon(p) for p in base["foe"]]]
    benches=[[_clone_mon(p) for p in base.get("own_bench",[])],[_clone_mon(p) for p in base.get("foe_bench",[])]]
    field=dict(base.get("field",{}))
    field["_unknown_reserves"]=[base.get("own_unknown_reserves",0),base.get("foe_unknown_reserves",0)]
    events=[]
    had_speed_tie=False
    for side in (0,1):
        for slot in (0,1):
            a=actions[side][slot]; p=board[side][slot]
            sp=speed(p,side,field) if alive(p) else 0
            events.append((priority(p,a,field),-sp if field.get("trickroom") else sp,side,slot,a))
    # Gen 9 recalculates speed order during a turn, including Tailwind/Icy Wind.
    # Reversed tie orders are evaluated by simulate() only when needed.
    while events:
        def order(e):
            _,_,s,j,act=e
            mon=board[s][j]
            sp=speed(mon,s,field) if alive(mon) else 0
            return priority(mon,act,field), -sp if field.get("trickroom") else sp, -s*tie_order, -j*tie_order
        top=max(events,key=order)
        if alive(board[top[2]][top[3]]) and top[4]["type"] in {"move","switch"}:
            had_speed_tie |= any(e is not top and alive(board[e[2]][e[3]]) and
                                 e[4]["type"] in {"move","switch"} and
                                 order(e)[:2]==order(top)[:2] for e in events)
        event=max(events,key=order); events.remove(event)
        _,_,side,slot,a=event
        p=board[side][slot]
        if a["type"]=="switch":
            idx=next((i for i,q in enumerate(benches[side]) if idnorm(q.get("species",""))==idnorm(a["species"]) and alive(q)),None)
            if idx is None: continue
            q=benches[side].pop(idx)
            if alive(p):
                p["boosts"]={}; p["first_turn"]=True
                if ability(p)=="regenerator": p["hp"]=min(1.,p["hp"]+1/3)
                if ability(p)=="naturalcure": p["status"]=""
                benches[side].append(p)
            q["first_turn"]=True; board[side][slot]=q
            _entry(q,side,board,field)
            for ruin in ("swordofruin","beadsofruin","tabletsofruin","vesselofruin"):
                field[ruin]=any(alive(x) and ability(x)==ruin for line in board for x in line)
            continue
        if base.get("forced_switch") or a["type"]!="move" or not alive(p) or p.get("_flinch"): continue
        mid=idnorm(a["move_id"]); d=md(mid)
        if p.get("status") in {"slp","sleep","frz","freeze"} and mid not in {"sleeptalk","snore"}: continue
        if p.get("_taunt") and d["category"]=="status": continue
        if mid=="fakeout" and not p.get("first_turn",True): continue
        prefix="own_" if side==0 else "foe_"
        if mid in PROTECT:
            p["_protect"]=1/(3**min(5,int(p.get("protect_count",0))))
            continue
        if mid in {"wideguard","quickguard"}:
            field[prefix+mid]=True; continue
        if mid in REDIRECT: p["_redirect"]=mid; continue
        if mid=="helpinghand":
            if alive(board[side][1-slot]): board[side][1-slot]["_helping"]=True
            continue
        if mid=="tailwind": field[prefix+"tailwind"]=True; continue
        if mid=="trickroom": field["trickroom"]=not field.get("trickroom"); continue
        if mid in {"reflect","lightscreen","auroraveil"}:
            if mid!="auroraveil" or weather(field) in {"snow","snowscape","hail"}: field[prefix+mid]=True
            continue
        if mid in {"sunnyday","raindance","sandstorm","snowscape","hail"}: field["weather"]=mid; continue
        if mid in {"electricterrain","grassyterrain","psychicterrain","mistyterrain"}: field["terrain"]=mid; continue
        if mid in HEAL: p["hp"]=min(1,p["hp"]+.5); continue
        if mid=="rest":
            if _status_possible(p,p,"spore",field):
                p["hp"]=1.; p["status"]="slp"; _activate_cure(p,board[1-side])
            continue
        if mid=="haze":
            for line in board:
                for q in line: q["boosts"]={}
            continue
        beginning_charge=d.get("flags",{}).get("charge") and not (mid in p.get("effects",{}) or "twoturnmove" in p.get("effects",{}))
        if beginning_charge and mid in {"electroshot","meteorbeam"}:
            _setboost(p,{"spa":1}); p["_charge_boost_applied"]=True
        if _needs_charge(p,d,field):
            p["_charging"]=mid
            continue
        if beginning_charge and item(p)=="powerherb" and mid!="skydrop":
            no_herb=dict(p,item="")
            if _needs_charge(no_herb,d,field):
                p["item"]=""
                if ability(p)=="unburden": p["_unburden"]=True
        if d["category"]=="status" and d.get("boosts") and d.get("target") in {"self","allySide"}:
            _setboost(p,d["boosts"]); continue
        targets=_target_pairs(a,side,slot,board,field)
        spread=len(targets)>1 and d.get("target") in SPREAD_TARGETS
        if mid=="expandingforce" and len(targets)>1: spread=True
        total_dealt=0.
        for ts,tj in targets:
            q=board[ts][tj]
            if not alive(q) and ts!=side and not spread:
                tj=1-tj; q=board[ts][tj]
            if not alive(q): continue
            # Follow Me/Rage Powder redirect only single-target opposing moves.
            if ts!=side and not spread and mid not in {"snipeshot"}:
                partner=board[ts][1-tj]
                if alive(partner) and partner.get("_redirect") and ability(p)!="stalwart" and ability(p)!="propellertail":
                    powder=partner["_redirect"]=="ragepowder"
                    if not powder or ("grass" not in types(p) and ability(p)!="overcoat" and item(p)!="safetygoggles"):
                        tj=1-tj; q=partner
            # Priority denial is checked after redirection and against the field.
            pr=priority(p,a,field)
            if ts!=side and pr>0:
                if terrain(field)=="psychicterrain" and grounded(q): continue
                # Mold Breaker ignores a defending ally's breakable ability,
                # but not terrain, Quick Guard, or an Ability Shield holder.
                bypass=ability(p) in {"moldbreaker","teravolt","turboblaze"} or d.get("ignoreAbility",False)
                if any(alive(x) and ability(x) in {"armortail","queenlymajesty","dazzling"}
                       and (not bypass or item(x)=="abilityshield") for x in board[ts]): continue
                if field.get(("own_" if ts==0 else "foe_")+"quickguard"): continue
            native_spread=d.get("target") in SPREAD_TARGETS or (mid=="expandingforce" and terrain(field)=="psychicterrain" and grounded(p))
            if ts!=side and native_spread and field.get(("own_" if ts==0 else "foe_")+"wideguard"): continue
            protect=q.get("_protect",0)
            if mid in {"feint","hyperspacefury","hyperspacehole","phantomforce","shadowforce"}: protect=0
            if ability(p)=="unseenfist" and _makes_contact(p,d): protect=0
            if ts==side and d["category"]=="status": protect=0
            if protect>=1: continue
            if d["category"]=="status":
                if ability(q)=="goodasgold" and ts!=side: continue
                if ability(p)=="prankster" and "dark" in types(q) and ts!=side: continue
                if mid in SLEEP or mid in {"willowisp","thunderwave","toxic","poisonpowder","yawn"}:
                    if _status_possible(p,q,mid,field):
                        if mid in SLEEP and d["accuracy"]>=.7: q["status"]="slp"
                        elif mid=="yawn": q["_yawn"]=True
                        elif mid=="willowisp": q["status"]="brn"
                        elif mid=="thunderwave": q["status"]="par"
                        elif mid in {"toxic","poisonpowder"}: q["status"]="tox"
                elif mid=="taunt": q["_taunt"]=True
                elif mid=="encore": q["_taunt"]=True
                elif mid in {"healpulse","lifedew","junglehealing"}: q["hp"]=min(1,q["hp"]+.5)
                elif mid=="partingshot": _setboost(q,{"atk":-1,"spa":-1},opposing=ts!=side)
                elif d.get("boosts"): _setboost(q,d["boosts"],opposing=ts!=side)
                _activate_cure(q,board[1-ts])
                continue
            if mid=="pollenpuff" and ts==side:
                q["hp"]=min(1,q["hp"]+.5); continue
            if mid in {"suckerpunch","thunderclap"}:
                # A target that already moved (e.g. Extreme Speed) cannot be
                # hit by conditional priority, even if it selected an attack.
                # Status and incoming switches can deliberately bait failure.
                pending=next((e[4] for e in events if e[2]==ts and e[3]==tj),None)
                if not pending or pending.get("type")!="move" or "mustrecharge" in q.get("effects",{}): continue
                target_move=md(pending["move_id"])
                if target_move["category"]=="status" and target_move["id"]!="mefirst": continue
            if mid in {"brickbreak","psychicfangs"}:
                for sc in ("reflect","lightscreen","auroraveil"):
                    field[("own_" if ts==0 else "foe_")+sc]=False
            dealt_this_target=0.
            bypass=ability(p) in {"moldbreaker","teravolt","turboblaze"} or d.get("ignoreAbility",False)
            for hit_weight in _hit_weights(p,d):
                if not alive(p) or not alive(q): break
                amount=damage(p,q,mid,field,side,spread,board[ts][1-tj],p.get("_helping",False),_single_hit=True)*hit_weight*(1-protect)
                if amount<=0: break
                # Each hit gets its own Sash/Sturdy, berry and contact reaction.
                # A full-HP Sash cannot block later hits after the first consumes it.
                if q["hp"]>=.999 and (item(q)=="focussash" or (ability(q)=="sturdy" and not bypass)):
                    amount=min(amount,q["hp"]-.006)
                    if amount>=q["hp"]-.007 and item(q)=="focussash": q["item"]=""
                contact_cost=_contact_cost(p,q,d)
                before=q["hp"]; q["hp"]=max(0,q["hp"]-amount)
                hit_dealt=min(before,amount)*q.get("stats",{}).get("hp",180)
                dealt_this_target+=hit_dealt
                # Drain recovery precedes Rocky Helmet/Rough Skin. A low-HP
                # Drain Punch user may survive contact by healing on this hit.
                if d.get("drain"):
                    n,den=d["drain"]
                    p["hp"]=min(1.,p["hp"]+hit_dealt*n/den/p.get("stats",{}).get("hp",180))
                if alive(q) and item(q)=="sitrusberry" and q["hp"]<=.5 and not _berries_blocked(board[1-ts]):
                    q["hp"]=min(1.,q["hp"]+.25); q["item"]=""
                    if ability(q)=="unburden": q["_unburden"]=True
                if alive(q) and ability(q)=="stamina": _setboost(q,{"def":1})
                if alive(q) and ability(q)=="weakarmor" and d["category"]==PHYSICAL:
                    _setboost(q,{"def":-1,"spe":2})
                p["hp"]=max(0.,p["hp"]-contact_cost*min(1.,hit_weight))
            total_dealt+=dealt_this_target
            if not dealt_this_target: continue
            secondaries=item(q)!="covertcloak" and ability(q)!="shielddust"
            if secondaries and mid=="fakeout" and ability(q)!="innerfocus" and "ghost" not in types(q): q["_flinch"]=True
            bypass=ability(p) in {"moldbreaker","teravolt","turboblaze"} or d.get("ignoreAbility",False)
            if secondaries and mid in {"icywind","electroweb","bulldoze"}: _setboost(q,{"spe":-1},opposing=ts!=side,bypass=bypass)
            if secondaries and mid=="snarl": _setboost(q,{"spa":-1},opposing=ts!=side,bypass=bypass)
            if secondaries and mid=="breakingswipe": _setboost(q,{"atk":-1},opposing=ts!=side,bypass=bypass)
            if secondaries and mid=="acidspray": _setboost(q,{"spd":-2},opposing=ts!=side,bypass=bypass)
            if mid=="knockoff": q["item"]=""
            if mid=="clearsmog": q["boosts"]={}
            if mid in {"icespinner","steelroller"}: field["terrain"]=""
            if secondaries and mid=="nuzzle" and not q.get("status") and "electric" not in types(q):
                q["status"]="par"; _activate_cure(q,board[1-ts])
            if secondaries and mid=="saltcure": q["_saltcure"]=True
            if secondaries and mid=="throatchop": q["_taunt"]=True
            if not alive(q) and ability(p) in {"moxie","chillingneigh","grimneigh","asoneglastrier","asonespectrier","beastboost"}:
                _setboost(p,{"spa" if ability(p) in {"grimneigh","asonespectrier"} else "atk":1})
        selfpart=d.get("self",{}) or {}
        if selfpart.get("boosts"): _setboost(p,selfpart["boosts"])
        if mid=="makeitrain" and not selfpart.get("boosts"): _setboost(p,{"spa":-1})
        if mid in {"overheat","dracometeor","leafstorm","fleurcannon","psychoboost"} and not selfpart.get("boosts"): _setboost(p,{"spa":-2})
        if total_dealt>0 and alive(p):
            if d.get("recoil"):
                n,den=d["recoil"]; p["hp"]=max(0.,p["hp"]-total_dealt*n/den/p.get("stats",{}).get("hp",180))
            if item(p)=="lifeorb" and ability(p) not in {"magicguard","sheerforce"}: p["hp"]=max(0,p["hp"]-.1)
        if d.get("selfdestruct") or mid in {"explosion","selfdestruct","finalgambit","mistyexplosion"}: p["hp"]=0
    if base.get("forced_switch"):
        return evaluate(board,benches,field,horizon),had_speed_tie
    for side in (0,1):
        for p in board[side]:
            if not alive(p): continue
            status=p.get("status","")
            if ability(p)!="magicguard":
                if status in {"brn","burn"}: p["hp"]-=1/16
                if status in {"psn","tox","poison","toxic"}: p["hp"]-=1/8
                if weather(field)=="sandstorm" and not set(types(p)).intersection({"rock","ground","steel"}) and ability(p) not in {"sandveil","sandrush","sandforce","overcoat"} and item(p)!="safetygoggles": p["hp"]-=1/16
                if p.get("_saltcure"): p["hp"]-=.25 if set(types(p)).intersection({"water","steel"}) else .125
            if item(p)=="leftovers" or (item(p)=="blacksludge" and "poison" in types(p)): p["hp"]=min(1,p["hp"]+1/16)
            if item(p)=="flameorb" and not p.get("status") and "fire" not in types(p): p["status"]="brn"
            if item(p)=="toxicorb" and not p.get("status") and not set(types(p)).intersection({"poison","steel"}): p["status"]="tox"
            if terrain(field)=="grassyterrain" and grounded(p): p["hp"]=min(1,p["hp"]+1/16)
            if p.get("_yawn") and not p.get("status"): p["status"]="slp"
            _activate_cure(p,board[1-side])
            p["hp"]=max(0,p["hp"])
    result=evaluate(board,benches,field,horizon)
    for s in (0,1):
        guards=sum(a.get("type")=="move" and idnorm(a.get("move_id","")) in PROTECT for a in actions[s])
        # A guard can protect a partner's productive turn, but spending both
        # actions simply waiting gives away tempo and future flexibility.
        cost=.10*guards+(.25 if guards==2 else 0)
        result-=cost if s==0 else -cost
    return result,had_speed_tie


def choose_battle(obs:dict, template:dict, memory:dict, budget:float=2.5)->dict:
    start=time.monotonic(); deadline=start+max(.08,float(budget))
    state=build_battle(obs,template,memory)
    board=[state["own"],state["foe"]]; field=state.get("field",{})
    for ruin in ("swordofruin","beadsofruin","tabletsofruin","vesselofruin"):
        field[ruin]=any(alive(x) and ability(x)==ruin for line in board for x in line)
    # These are uncertainty priors, used exclusively for opponent modelling.
    # Actual submitted moves always originate in the authoritative template.
    for p in state["foe"]+state.get("foe_bench",[]):
        if p and not p.get("moves"):
            p["moves"]=common_moves(p.get("species",""),limit=6)
            p["_moves_inferred"]=True
    own_bench=state.get("own_bench",[]); foe_bench=state.get("foe_bench",[])
    slots=sorted(template.get("slots",[]),key=lambda x:x.get("slot",0))
    if len(slots)!=2: raise ValueError("Doubles template requires two slots")
    lists=[enumerate_slot(s) for s in slots]
    own=joint_options(lists,board,own_bench,field,0,48)
    foe_lists=[opponent_slot(board[1][i],i,board,foe_bench,field) for i in (0,1)]
    if state.get("forced_switch"):
        foe_lists=[[{"type":"pass"}] if alive(board[1][i]) else foe_lists[i] for i in (0,1)]
    foes=joint_options(foe_lists,board,foe_bench,field,1,18)
    # Rank-derived opponent prior mixes strong direct attacks and tactical moves.
    # Evaluate every retained response, including switches and disruption.
    peak=foes[0][0]
    weights=[math.exp(max(-12,(v-peak)*1.65)) for v,_ in foes]
    z=sum(weights); weights=[w/z for w in weights]
    rows=[]
    for index,(heur,ours) in enumerate(own):
        values=[]
        for _,theirs in foes:
            values.append(simulate(state,(ours,theirs),horizon=True))
        mean=sum(w*v for w,v in zip(weights,values))
        # Choose expected board value without stacking pessimistic tail terms.
        rows.append((mean,heur,ours,values))
        if time.monotonic()>=deadline and index>=0: break
    rows.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=rows[0][2]
    memory["last_search"]={"candidates":len(rows),"responses":len(foes),"elapsed_ms":round((time.monotonic()-start)*1000),"score":round(rows[0][0],3)}
    return {"type":"doubles_turn","slot_0":chosen[0],"slot_1":chosen[1]}
