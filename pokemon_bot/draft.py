"""Fast, deterministic VGC draft and team-preview policy.

Uses only the public draft sets and observed roster. All returns retain the
server's identifiers. Ratings are transparent heuristics, not win probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import exp, sqrt, log
from time import monotonic
from typing import Any

from . import dex


def _id(value: Any) -> str:
    if value is None:
        return ""
    return dex.idnorm(value)


def _move_names(card: dict) -> list[str]:
    moves = card.get("moves") or []
    if isinstance(moves, dict):
        moves = list(moves)
    result = []
    for mv in moves:
        if isinstance(mv, str):
            result.append(mv)
        elif isinstance(mv, dict):
            result.append(mv.get("id") or mv.get("move_id") or mv.get("name") or "")
    return [m for m in result if m]


# Modest priors supplement actual move/stat/ability evaluation; they never
# substitute ideal moves for the fixed set offered by the game.
_PRIORS = {
    "incineroar": 2.2, "rillaboom": 1.8, "fluttermane": 2.4,
    "urshifurapidstrike": 2.3, "urshifu": 1.9, "tornadus": 1.5,
    "amoonguss": 1.4, "gholdengo": 1.7, "ironhands": 1.4,
    "ogerponwellspring": 1.8, "ogerponhearthflame": 1.5, "ogerpon": 1.2,
    "landorustherian": 1.3, "landorus": 1.8, "chienpao": 1.5,
    "chiyu": 1.5, "tinglu": 1.0, "dondozo": 0.2, "tatsugiri": -1.4,
    "farigiraf": 1.2, "porygon2": 0.7, "indeedeef": 1.0,
    "ursalunabloodmoon": 1.8, "ursaluna": 1.4, "dragonite": 1.2,
    "regidrago": 0.8, "archaludon": 1.3, "pelipper": 0.8,
    "whimsicott": 0.8, "grimmsnarl": 0.8, "kingambit": 1.1,
    "calyrexshadow": 4.5, "calyrexice": 4.2, "miraidon": 4.2,
    "koraidon": 3.7, "kyogre": 3.5, "groudon": 3.0,
    "zamazentacrowned": 3.4, "zaciancrowned": 3.2, "terapagos": 2.5,
    "lunala": 2.8, "necrozmaduskmane": 2.2,
    "rayquaza": 2.0, "dialgaorigin": 2.3, "palkiaorigin": 2.4,
}

_ABILITY_VALUE = {
    "intimidate": 1.5, "prankster": 0.9, "regenerator": 0.8,
    "goodasgold": 0.9, "unseenfist": 1.2,
    "grassysurge": 0.8, "psychicsurge": 0.65, "electricsurge": 0.7,
    "drizzle": 0.8, "drought": 0.8, "snowwarning": 0.35,
    "sandstream": 0.3, "hugepower": 0.5, "purepower": 0.5,
    "defiant": 0.8, "competitive": 0.8,
    "armortail": 0.9, "queenlymajesty": 0.5, "dazzling": 0.5,
    "friendguard": 1.1, "multiscale": 0.7, "shadowshield": 0.9,
    "sturdy": 0.35, "beadsofruin": 0.7, "swordofruin": 0.7,
    "tabletsofruin": 0.6, "vesselofruin": 0.6, "levitate": 0.5,
    "orichalcumpulse": 1.1, "hadronengine": 1.1, "asone": 1.0,
    "asoneglastrier": 1.2, "asonespectrier": 1.2, "innerfocus": 0.45,
}
_ITEM_VALUE = {
    "focussash": 1.0, "assaultvest": 0.6, "lifeorb": 0.45,
    "choicespecs": 0.45, "choiceband": 0.35, "choicescarf": 0.55,
    "sitrusberry": 0.6, "leftovers": 0.3, "eviolite": 0.8,
    "safetygoggles": 0.5, "clearamulet": 0.55, "boosterenergy": 0.6,
    "flameorb": 0.0, "covertcloak": 0.35, "rockyhelmet": 0.3,
    "mentalherb": 0.3, "lightclay": 0.15,
}
_WEATHER_SETTERS = {
    "drizzle": "rain", "drought": "sun", "orichalcumpulse": "sun",
    "sandstream": "sand", "snowwarning": "snow",
}
_SPREAD = {"alladjacentfoes", "alladjacent"}
_PROTECT = {"protect", "detect", "spikyshield", "kingsshield", "silktrap", "burningbulwark", "banefulbunker"}
_SETUP = {"swordsdance", "nastyplot", "calmmind", "bulkup", "quiverdance", "dragondance", "irondefense", "bellydrum"}
_REDIRECT = {"ragepowder", "followme"}


@dataclass(frozen=True)
class Attack:
    mid: str
    typ: str
    power: float
    category: str
    accuracy: float
    priority: int
    target: str
    contact: bool


@dataclass
class Profile:
    name: str
    sid: str
    cid: str
    types: tuple[str, ...]
    ability: str
    item: str
    stats: dict
    moves: frozenset[str]
    attacks: tuple[Attack, ...]
    quality: float
    speed: float
    offense: float
    physical: bool
    weather: str


def _profile(card: dict) -> Profile:
    name = str(card.get("species") or card.get("name") or card.get("card_id") or "Pikachu")
    sid = _id(name)
    raw = dex.species(name) or {}
    types = tuple(str(t).lower() for t in (card.get("types") or raw.get("types") or ["normal"]))
    stats = dex.stats(card)
    # A missing ability in a reconnect snapshot is an uncertainty; using the
    # species' first listed ability is only a fallback, never overwrites a set.
    ability = _id(card.get("ability") or "")
    if not ability:
        abilities = raw.get("abilities") or {}
        ability = _id(abilities.get("0", "") if isinstance(abilities, dict) else "")
    item = _id(card.get("item"))
    names = _move_names(card)
    moves = frozenset(_id(m) for m in names)
    attacks = []
    for name_ in names:
        data = dex.move(name_) or {}
        cat = str(data.get("category") or "Status").lower()
        if cat == "status":
            continue
        mid = _id(name_)
        bp = float(data.get("basePower") or data.get("base_power") or 0)
        if mid in {"surgingstrikes", "tripleaxel", "triplekick"}:
            bp = 112.5 if mid == "surgingstrikes" else (120 if mid == "tripleaxel" else 60)
        elif mid == "wickedblow":
            bp *= 1.5
        elif mid == "populationbomb":
            bp *= 9.0 if item == "widelens" else 6.5
        elif data.get("multihit"):
            mh = data["multihit"]
            bp *= (4.5 if item == "loadeddice" else 3.0) if isinstance(mh, list) else float(mh)
        if mid in {"bodypress"}:
            bp = bp or 80
        if mid == "electroball":
            bp = 80
        if mid == "gyroball":
            bp = 90
        if mid in {"grassknot", "lowkick", "heavyslam", "heatcrash"}:
            bp = 90
        if mid == "terablast":
            bp = 80  # No Terastallization on the platform.
        if mid == "foulplay":
            bp = 95
        if mid in {"seismictoss", "nightshade"}:
            bp = 65
        if not bp:
            continue
        accuracy = data.get("accuracy", 100)
        accuracy = 1.0 if accuracy is True else float(accuracy or 100)
        if accuracy > 1:
            accuracy /= 100
        typ = str(data.get("type") or data.get("move_type") or "Normal").lower()
        attacks.append(Attack(mid, typ, bp, cat, accuracy, int(data.get("priority", 0)),
                              _id(data.get("target", "normal")), bool((data.get("flags") or {}).get("contact"))))
    # Unknown sets at reconnect: neutral STAB threat, not invented legal moves.
    if not names:
        cat = "physical" if stats["atk"] >= stats["spa"] else "special"
        attacks = [Attack("unknown", t, 80, cat, 1.0, 0, "normal", False) for t in types]
    speed = float(stats["spe"])
    if item == "choicescarf":
        speed *= 1.5
    offense = 0.0
    physical_weight = special_weight = 0.0
    for a in attacks:
        atk = float(stats["atk"] if a.category == "physical" else stats["spa"])
        if a.mid == "bodypress":
            atk = float(stats["def"])
        if ability in {"hugepower", "purepower"} and a.category == "physical":
            atk *= 2
        if ability == "guts" and item in {"flameorb", "toxicorb"} and a.category == "physical":
            atk *= 1.5
        if (item == "choiceband" and a.category == "physical") or (item == "choicespecs" and a.category == "special"):
            atk *= 1.5
        p = a.power * atk / 150 * a.accuracy * (1.5 if a.typ in types else 1)
        if a.target in _SPREAD:
            p *= 1.25
        if a.mid == "fakeout":
            p *= 0.35
        offense = max(offense, p)
        if a.category == "physical":
            physical_weight = max(physical_weight, p)
        else:
            special_weight = max(special_weight, p)
    bulk = sqrt(float(stats["hp"]) * sqrt(float(stats["def"]) * float(stats["spd"])))
    if item == "assaultvest":
        bulk *= 1.11
    if item == "eviolite" and raw.get("nfe"):
        bulk *= 1.22
    q = 0.025 * offense + 0.025 * bulk + 0.012 * min(speed, 230)
    q += _PRIORS.get(sid, 0.0) + _ABILITY_VALUE.get(ability, 0.0) + _ITEM_VALUE.get(item, 0.0)
    q += 1.15 * ("fakeout" in moves) + 1.1 * ("tailwind" in moves)
    q += 0.65 * ("trickroom" in moves) + 1.2 * ("spore" in moves)
    q += 0.9 * bool(moves & _REDIRECT) + 0.4 * bool(moves & _PROTECT)
    q += 0.35 * ("wideguard" in moves) + 0.35 * ("taunt" in moves)
    q += 0.30 * ("partingshot" in moves) + 0.25 * ("helpinghand" in moves)
    q += 0.4 * ("auroraveil" in moves and ability == "snowwarning")
    if {"reflect", "lightscreen"} <= moves:
        q += 0.7
    if not attacks:
        q -= 1.2
    return Profile(name, sid, str(card.get("card_id") or sid), types, ability, item, stats,
                   moves, tuple(attacks), q, speed, offense,
                   physical_weight >= special_weight, _WEATHER_SETTERS.get(ability, ""))


def _effectiveness(typ: str, defender: Profile, attacker: Profile) -> float:
    bypass = attacker.ability in {"moldbreaker", "teravolt", "turboblaze"}
    if not bypass:
        a = defender.ability
        if typ == "ground" and a == "levitate":
            return 0.0
        if typ == "water" and a in {"waterabsorb", "stormdrain", "dryskin"}:
            return 0.0
        if typ == "electric" and a in {"voltabsorb", "motordrive", "lightningrod"}:
            return 0.0
        if typ == "fire" and a in {"flashfire", "wellbakedbody"}:
            return 0.0
        if typ == "grass" and a == "sapsipper":
            return 0.0
    eff = dex.effectiveness(typ, list(defender.types))
    if not bypass:
        if defender.ability == "thickfat" and typ in {"ice", "fire"}:
            eff *= 0.5
        if defender.ability in {"filter", "solidrock", "prismarmor"} and eff > 1:
            eff *= 0.75
    return float(eff)


def _attack_damage(attacker: Profile, defender: Profile, a: Attack, weather: str = "") -> float:
    atk = float(attacker.stats["atk"] if a.category == "physical" else attacker.stats["spa"])
    defense = float(defender.stats["def"] if a.category == "physical" else defender.stats["spd"])
    if a.mid == "bodypress":
        atk = float(attacker.stats["def"])
    if a.mid == "foulplay":
        atk = float(defender.stats["atk"])
    if a.category == "physical":
        if attacker.ability in {"hugepower", "purepower"}:
            atk *= 2
        if attacker.ability == "guts" and attacker.item in {"flameorb", "toxicorb"}:
            atk *= 1.5
        if attacker.item == "choiceband":
            atk *= 1.5
    elif attacker.item == "choicespecs":
        atk *= 1.5
    if defender.item == "assaultvest" and a.category == "special":
        defense *= 1.5
    if defender.item == "eviolite":
        defense *= 1.5
    if attacker.ability in {"hadronengine", "orichalcumpulse"}:
        if (a.category == "special") == (attacker.ability == "hadronengine"):
            atk *= 1.33
    stab = (2 if attacker.ability == "adaptability" else 1.5) if a.typ in attacker.types else 1
    factor = stab * _effectiveness(a.typ, defender, attacker) * a.accuracy
    if a.target in _SPREAD:
        factor *= 0.75
    if attacker.item == "lifeorb":
        factor *= 1.3
    if a.typ == "water" and attacker.item == "mysticwater":
        factor *= 1.2
    if a.typ == "grass" and (attacker.ability == "grassysurge" or attacker.item == "miracleseed"):
        factor *= 1.3 if attacker.ability == "grassysurge" else 1.2
    if attacker.ability == "technician" and a.power <= 60:
        factor *= 1.5
    if a.mid == "grassyglide" and attacker.ability == "grassysurge":
        factor *= 1.05
    if weather == "rain":
        factor *= 1.5 if a.typ == "water" else (0.5 if a.typ == "fire" else 1)
    if weather == "sun":
        factor *= 1.5 if a.typ == "fire" else (0.5 if a.typ == "water" else 1)
    if defender.ability in {"multiscale", "shadowshield"}:
        factor *= 0.65
    damage = (22 * a.power * atk / max(1, defense) / 50 + 2) * 0.925 * factor / max(1, float(defender.stats["hp"]))
    if a.mid in {"seismictoss", "nightshade"}:
        damage = 50 / float(defender.stats["hp"]) if factor else 0
    return min(2.5, damage)


class Evaluator:
    def __init__(self, cards: list[dict]):
        self.profiles = [_profile(c) for c in cards]
        self.damage_cache: dict[tuple, float] = {}
        self.pair_cache: dict[tuple, float] = {}
        self.team_cache: dict[tuple, float] = {}

    def damage(self, a: Profile, b: Profile, weather: str = "") -> float:
        key = (a.cid, b.cid, weather)
        if key not in self.damage_cache:
            attacks = [m for m in a.attacks if m.mid not in {"fakeout", "selfdestruct", "explosion"}]
            self.damage_cache[key] = max((_attack_damage(a, b, m, weather) for m in attacks), default=0.0)
        return self.damage_cache[key]

    def pair(self, a: Profile, b: Profile) -> float:
        key = tuple(sorted((a.cid, b.cid)))
        if key in self.pair_cache:
            return self.pair_cache[key]
        value = 0.0
        for x, y in ((a, b), (b, a)):
            if "tailwind" in x.moves:
                value += 0.85 if y.offense > 120 and y.speed >= 80 else 0.2
            if "trickroom" in x.moves and y.speed < 90:
                value += (1.3 if y.offense > 135 else 0.35) * min(1.4, (110-y.speed)/40)
            if x.moves & _REDIRECT:
                value += 1.1 if ("trickroom" in y.moves or bool(y.moves & _SETUP)) else (0.45 if y.offense > 140 else 0.0)
            if "fakeout" in x.moves:
                value += 0.6 if ("tailwind" in y.moves or "trickroom" in y.moves or bool(y.moves & _SETUP)) else 0.15
            if x.ability == "intimidate" and y.stats["def"] < 100:
                value += 0.3
            if x.ability == "swordofruin":
                value += 0.8 if y.physical and y.offense > 125 else -0.1
            if x.ability == "beadsofruin":
                value += 0.8 if not y.physical and y.offense > 125 else -0.1
            if x.ability == "psychicsurge":
                value += 1.1 if "expandingforce" in y.moves else 0.0
                value -= 0.7 if "fakeout" in y.moves or "grassyglide" in y.moves else 0.0
            if x.ability == "grassysurge":
                value += 0.8 if "grassyglide" in y.moves else 0.0
                value -= 0.3 if "earthquake" in y.moves else 0.0
            if x.weather:
                if x.weather == "rain":
                    value += 2.0 if y.ability == "swiftswim" else 0.0
                    value += 1.3 if "electroshot" in y.moves else 0.0
                    value += 0.75 if "water" in y.types and y.offense > 100 else 0.0
                    value -= 0.8 if "fire" in y.types and y.offense > 100 else 0.0
                elif x.weather == "sun":
                    value += 1.7 if y.ability == "chlorophyll" else 0.0
                    value += 0.9 if y.ability == "protosynthesis" else 0.0
                    value += 0.65 if "fire" in y.types and y.offense > 100 else 0.0
                    value -= 0.8 if "water" in y.types and y.offense > 100 else 0.0
                elif x.weather == "sand":
                    value += 1.8 if y.ability == "sandrush" else 0.0
                    value += 0.25 if "rock" in y.types else 0.0
                elif x.weather == "snow":
                    value += 1.6 if y.ability == "slushrush" else 0.0
                    value += 0.35 if "ice" in y.types else 0.0
            if "earthquake" in x.moves:
                immune = "flying" in y.types or y.ability == "levitate"
                value += 0.35 if immune else -0.15
        if a.weather and b.weather and a.weather != b.weather:
            value -= 1.5
        if {a.sid, b.sid} == {"dondozo", "tatsugiri"}:
            value += 6.5 if a.ability == "commander" or b.ability == "commander" else 0.0
        self.pair_cache[key] = value
        return value

    def team(self, own: list[Profile] | tuple, foe: list[Profile] | tuple) -> float:
        key = (tuple(sorted(c.cid for c in own)), tuple(sorted(c.cid for c in foe)))
        if key in self.team_cache:
            return self.team_cache[key]
        n = len(own)
        if not n:
            return 0.0
        quality = sorted((c.quality for c in own), reverse=True)
        value = sum(quality[:4]) + 0.28 * sum(quality[4:])
        value += sum(self.pair(a, b) for a,b in combinations(own,2)) * (1.0 if n <=4 else 0.70)
        physical = sum(c.physical and c.offense > 100 for c in own)
        special = sum(not c.physical and c.offense > 100 for c in own)
        attackers = physical + special
        if physical and special:
            value += 0.8
        elif n >= 3 and physical >= 3:
            value -= 1.0
        if n >= 3 and attackers < 2:
            value -= (2 - attackers) * 2.5
        tw = sum("tailwind" in c.moves for c in own)
        tr = sum("trickroom" in c.moves for c in own)
        slow = sum(c.speed < 90 and c.offense > 110 for c in own)
        if n >= 3 and not tw and not tr:
            value -= 1.1 if sum(c.speed < 115 for c in own) >= 3 else 0.0
        if slow >= 2 and not tr:
            value -= 0.6 * slow
        if tw > 1:
            value -= 0.4 * (tw - 1)
        if sum(bool(c.moves & _REDIRECT) for c in own) > 1:
            value -= 0.6
        if foe:
            weather = next((c.weather for c in own if c.weather), "")
            for enemy in foe:
                output = sorted((self.damage(c, enemy, weather) for c in own), reverse=True)
                incoming = sorted(self.damage(enemy, c, enemy.weather) for c in own)
                # Backup answers count, and diminishing returns discourage taking
                # multiple redundant super-effective attackers.
                hit = 0.7 * min(output[0],1.5) + 0.3 * min(output[min(1,n-1)],1.5)
                safe = 0.5*incoming[0] + 0.25*incoming[min(1,n-1)] + 0.25*sum(incoming)/n
                value += (2.3 * hit - 1.65 * min(safe,1.8)) / len(foe) * min(n,4)
            if any(c.ability in {"defiant", "competitive"} for c in foe):
                value -= 0.6 * sum(c.ability == "intimidate" for c in own)
            if any("spore" in c.moves for c in foe):
                sleep_weak = sum("grass" not in c.types and c.item != "safetygoggles" and c.ability not in {"overcoat", "goodasgold", "insomnia", "vitalspirit"} for c in own)
                value -= 0.35 * max(0, sleep_weak-2)
        self.team_cache[key] = value
        return value

    def lead(self, own: tuple[Profile,Profile], foe: tuple[Profile,Profile], bench: tuple = ()) -> float:
        a,b = own
        x,y = foe
        weather_sources = [c for c in (*own,*foe) if c.weather]
        # Slower weather setters activate last at simultaneous lead entry.
        weather = min(weather_sources,key=lambda c:c.speed).weather if weather_sources else ""
        outgoing = [[self.damage(c,d,weather) for d in foe] for c in own]
        incoming = [[self.damage(c,d,weather) for d in own] for c in foe]
        for attackers, defenders, matrix in ((own,foe,outgoing),(foe,own,incoming)):
            intim = sum(c.ability == "intimidate" for c in defenders)
            for i,c in enumerate(attackers):
                if c.physical and intim and c.item != "clearamulet" and c.ability not in {"defiant","competitive","innerfocus","oblivious","owntempo","scrappy","fullmetalbody","clearbody"}:
                    for j in range(2):
                        matrix[i][j] *= (2 / (2+intim))
        def output(matrix, attackers, defenders):
            scores=[]
            for t0 in (0,1):
                for t1 in (0,1):
                    total = [0.0,0.0]
                    tempo = 0.0
                    for i,t in enumerate((t0,t1)):
                        dmg=matrix[i][t]
                        total[t]+=dmg
                        # Earlier pressure is worth more, but don't model all
                        # slow bulky Pokemon as dead before they act.
                        c,d=attackers[i],defenders[t]
                        speed=c.speed
                        if weather=="rain" and c.ability=="swiftswim": speed*=2
                        if weather=="sun" and c.ability=="chlorophyll": speed*=2
                        if speed>d.speed: tempo+=0.12*min(1,dmg)
                    score=sum(min(t,1.25) + (0.65 if t>=1 else 0.0) for t in total)+tempo
                    scores.append(score)
            return max(scores)
        value=output(outgoing,own,foe)-output(incoming,foe,own)
        value+=0.12*(a.quality+b.quality-x.quality-y.quality)
        value+=0.28*self.pair(a,b)-0.20*self.pair(x,y)
        for team,enemies,sign in ((own,foe,1),(foe,own,-1)):
            priority_block=any(c.ability in {"armortail","queenlymajesty","dazzling"} for c in enemies)
            psychic=any(c.ability=="psychicsurge" for c in (*team,*enemies))
            usable_fake=[]
            for c in team:
                if "fakeout" in c.moves and not priority_block:
                    targets=[e for e in enemies if "ghost" not in e.types and e.ability!="innerfocus" and e.item!="covertcloak" and not(psychic and "flying" not in e.types)]
                    if targets: usable_fake.append(c)
            if usable_fake:
                value+=sign*(0.48+0.15*(len(usable_fake)>1))
                if any("tailwind" in c.moves or "trickroom" in c.moves or bool(c.moves&_SETUP) for c in team):
                    value+=sign*0.25
            if any(c.moves&_REDIRECT for c in team):
                if any("trickroom" in c.moves for c in team):
                    value+=sign*0.4
            ourspeed=sum(c.speed for c in team)/2
            theirspeed=sum(c.speed for c in enemies)/2
            if any("tailwind" in c.moves for c in team) and ourspeed<theirspeed*1.4:
                value+=sign*0.35
            if any("trickroom" in c.moves for c in team) and ourspeed<theirspeed*0.8:
                value+=sign*0.55
            if any("taunt" in c.moves for c in team) and any("trickroom" in c.moves or "tailwind" in c.moves for c in enemies):
                value+=sign*0.25
            if any("wideguard" in c.moves for c in team):
                spread=sum(any(m.target in _SPREAD and m.power>=75 for m in c.attacks) for c in enemies)
                value+=sign*0.23*spread
            for c in team:
                if "spore" in c.moves:
                    targets=sum("grass" not in e.types and e.item!="safetygoggles" and e.ability not in {"overcoat","goodasgold"} for e in enemies)
                    value+=sign*0.16*targets
        # Score each lead pair with its actual reserves, not a separately
        # selected best pair: preserves useful pivot/switch combinations.
        if bench:
            for c in own:
                for e in foe:
                    threat=self.damage(e,c,weather)
                    if threat>0.65:
                        safer=min(self.damage(e,r,weather) for r in bench)
                        value+=0.22*max(0,threat-safer)
        return value


def _merged(card: dict, memory: dict) -> dict:
    name = card.get("species") or card.get("name") or ""
    known = (memory.get("cards") or {}).get(_id(name), {})
    result = dict(known)
    for key,value in card.items():
        if value is None or value == [] or value == {} or value == "":
            continue
        if isinstance(value,str) and (value.strip() in {"?","???"} or _id(value) in {"unknown","unknownitem","unknownability","unrevealed","unrevealeditem","unrevealedability","null"}):
            continue
        if key in {"base_stats","baseStats","evs","ivs","stats","actual_stats"} and isinstance(value,dict):
            accepted={k:v for k,v in value.items() if isinstance(v,(int,float)) and (v>0 or key in {"evs","ivs"})}
            if accepted:
                result[key]={**(result.get(key) or {}),**accepted}
        else:
            result[key]=value
    # Revealed-only move dicts must not erase a known public four-move set.
    if known.get("moves") and len(_move_names(card)) < len(_move_names(known)):
        result["moves"] = known["moves"]
    return result


def _rosters(obs: dict, memory: dict) -> tuple[list[dict], list[dict]]:
    if obs.get("phase") == "draft" or obs.get("available_cards") is not None:
        rosters = obs.get("rosters") or {}
        seat = obs.get("current_seat") or memory.get("own_seat")
        own=rosters.get(seat, memory.get("own_roster", []))
        foe=[c for key,roster in rosters.items() if key!=seat for c in roster]
        if not rosters:
            foe=memory.get("foe_roster", [])
    else:
        own=obs.get("your_roster") or memory.get("own_roster", [])
        foe=obs.get("opponent_roster") or memory.get("foe_roster", [])
    if isinstance(own,dict): own=list(own.values())
    if isinstance(foe,dict): foe=list(foe.values())
    return ([_merged(c,memory) for c in own if isinstance(c,dict)],
            [_merged(c,memory) for c in foe if isinstance(c,dict)])


def _action_card_id(action: Any) -> str:
    raw=action if isinstance(action,dict) else vars(action)
    inp=raw.get("input") or {}
    act=inp.get("action") or {}
    cid=act.get("card_id")
    if cid: return str(cid)
    aid=raw.get("action_id") or getattr(action,"action_id","")
    return str(aid).split(":",1)[-1]


def _legal_for(card: Profile, roster: list[Profile]) -> bool:
    return not card.item or all(c.item!=card.item for c in roster)


def choose_draft(obs: dict, legal_actions: list, memory: dict) -> Any:
    """Return the original legal action object after a short snake rollout."""
    if not legal_actions:
        raise ValueError("No legal draft action")
    if len(legal_actions)==1:
        return legal_actions[0]
    start=monotonic()
    budget=max(0.001,min(1.6,float(memory.get("_budget",1.6))))
    owncards,foecards=_rosters(obs,memory)
    poolcards=[_merged(c,memory) for c in obs.get("available_cards",[]) if isinstance(c,dict)]
    bycid={str(c.get("card_id")):c for c in poolcards}
    for action in legal_actions:
        cid=_action_card_id(action)
        if cid not in bycid:
            known=next((c for c in (memory.get("cards") or {}).values() if c.get("card_id")==cid),None)
            bycid[cid]=known or {"species":cid.removeprefix("vgc-").removeprefix("ou-"),"card_id":cid}
    poolcards=list(bycid.values())
    evaluator=Evaluator(owncards+foecards+poolcards)
    n,m=len(owncards),len(foecards)
    own=evaluator.profiles[:n]
    foe=evaluator.profiles[n:n+m]
    pool=evaluator.profiles[n+m:]
    poolmap={p.cid:p for p in pool}
    actions={_action_card_id(a):a for a in legal_actions}
    base=evaluator.team(own,foe)
    oppbase=evaluator.team(foe,own)
    def marginal(card,ours,theirs):
        return evaluator.team(ours+[card],theirs)-evaluator.team(ours,theirs)
    def immediate(card,ours,theirs,remaining,denial=0.14):
        gain=marginal(card,ours,theirs)
        if _legal_for(card,theirs):
            gain+=denial*marginal(card,theirs,ours)
        if len(ours)<4:
            potential=max((evaluator.pair(card,c) for c in remaining if c.cid!=card.cid and c.item!=card.item and _legal_for(c,ours)),default=0)
            gain+=0.3*max(0,potential)
        return gain
    ranked=sorted(((immediate(poolmap[cid],own,foe,pool),cid) for cid in actions if cid in poolmap),reverse=True)
    if not ranked: return legal_actions[0]
    snake=(0,1,1,0,0,1,1,0,0,1,1,0)
    pick=int(obs.get("pick_number") or n+m+1)-1
    pick=max(0,min(11,pick))
    first=obs.get("first_drafter")
    seat=obs.get("current_seat") or memory.get("own_seat")
    ours_index=0 if first==seat else 1
    if first is None: ours_index=snake[pick]
    best=(float("-inf"),ranked[0][1])
    for immediate_score,cid in ranked[:7]:
        if monotonic()-start>budget: break
        ours=own+[poolmap[cid]]
        theirs=list(foe)
        remaining=[c for c in pool if c.cid!=cid]
        own_future=0
        for k in range(pick+1,min(12,pick+6)):
            ourturn=snake[k]==ours_index
            active,other=(ours,theirs) if ourturn else (theirs,ours)
            candidates=[c for c in remaining if _legal_for(c,active)]
            if not candidates: continue
            chosen=max(candidates,key=lambda c:immediate(c,active,other,remaining,0.10))
            active.append(chosen)
            remaining=[c for c in remaining if c.cid!=chosen.cid]
            if ourturn:
                own_future+=1
                if own_future>=2 or (k+1<12 and snake[k+1]!=ours_index):
                    break
        val=evaluator.team(ours,theirs)-base-0.70*(evaluator.team(theirs,ours)-oppbase)+0.20*immediate_score
        if val>best[0]: best=(val,cid)
    if best[0]==float("-inf"):
        best=ranked[0]
    memory["draft_summary"]={"pick":pick+1,"card_id":best[1],"score":round(best[0],3),"seconds":round(monotonic()-start,4)}
    return actions[best[1]]


def _robust(values: list[tuple[float,float]], tail: float=0.25) -> float:
    if not values: return 0.0
    total=sum(w for _,w in values)
    mean=sum(v*w for v,w in values)/total
    needed=tail*total
    lower=0.0
    left=needed
    for val,w in sorted(values):
        take=min(w,left)
        lower+=val*take
        left-=take
        if left<=0: break
    return 0.65*mean+0.35*lower/max(needed,1e-9)


def choose_lineup(obs: dict, template: dict, memory: dict) -> dict:
    """Jointly enumerate all bring-four and lead-two combinations."""
    started=monotonic()
    budget=max(0.001,min(2.5,float(memory.get("_budget",2.5))))
    roster=template.get("roster") or []
    if isinstance(roster,dict): roster=list(roster)
    roster=[str(x.get("species") or x.get("id")) if isinstance(x,dict) else str(x) for x in roster]
    owncards,foecards=_rosters(obs,memory)
    # Public opponent summaries can report HP on a 100-point display scale.
    # Fixed-set EV/IV calculations remain the source of actual opponent HP.
    for card in foecards:
        card.pop("max_hp",None)
        card.pop("maxhp",None)
        for key in ("stats","actual_stats"):
            if isinstance(card.get(key),dict):
                card[key]={k:v for k,v in card[key].items() if k!="hp"}
    ownmap={_id(c.get("species") or c.get("name")):c for c in owncards}
    if not roster: roster=[str(c.get("species") or c.get("name")) for c in owncards]
    roster=list(dict.fromkeys(roster))
    if len(roster)<4:
        raise ValueError("Team preview requires four available species")
    owncards=[_merged(ownmap.get(_id(name),{"species":name}),memory) for name in roster]
    evaluator=Evaluator(owncards+foecards)
    own=evaluator.profiles[:len(owncards)]
    foe=evaluator.profiles[len(owncards):]
    ownteams=list(combinations(own,4))
    foeteams=list(combinations(foe,min(4,len(foe)))) if foe else [()]
    foeprior=[evaluator.team(team,own) for team in foeteams]
    peak=max(foeprior,default=0)
    foeweights=[max(0.015,exp((v-peak)/3.5)) for v in foeprior]
    # Every plausible enemy pair remains represented; likelihood is inferred
    # from the public team quality and pair support, never hidden commands.
    enemyleads: dict[tuple,tuple[tuple,float]]={}
    for team,weight in zip(foeteams,foeweights):
        pairs=list(combinations(team,2))
        if not pairs: continue
        priors=[]
        for pair in pairs:
            score=sum(c.quality for c in pair)+evaluator.pair(*pair)
            score+=0.7*sum("fakeout" in c.moves for c in pair)
            score+=0.4*sum("tailwind" in c.moves or "trickroom" in c.moves for c in pair)
            priors.append(score)
        best=max(priors)
        pairweights=[exp((p-best)/2.5) for p in priors]
        z=sum(pairweights)
        for pair,pw in zip(pairs,pairweights):
            key=tuple(c.cid for c in pair)
            prev=enemyleads.get(key,(pair,0.0))[1]
            enemyleads[key]=(pair,prev+weight*pw/z)
    best_score=float("-inf")
    best_team=ownteams[0]
    best_leads=best_team[:2]
    for team in ownteams:
        # Always complete the first candidate so even a nearly expired clock
        # returns a scored, legal selection.
        if best_score>float("-inf") and monotonic()-started>budget:
            break
        matchup=[]
        for enemy,weight in zip(foeteams,foeweights):
            # Opponent strength is relevant when choosing robust counters;
            # own quality alone would prefer merely easier foe subsets.
            matchup.append((evaluator.team(team,enemy)-0.35*evaluator.team(enemy,team),weight))
        team_score=_robust(matchup)
        for leads in combinations(team,2):
            bench=tuple(c for c in team if c not in leads)
            leadvals=[(evaluator.lead(leads,pair,bench),w) for pair,w in enemyleads.values()]
            leadscore=_robust(leadvals) if leadvals else 0.1*sum(c.quality for c in leads)+0.4*evaluator.pair(*leads)
            score=team_score+2.2*leadscore
            if score>best_score:
                best_score,best_team,best_leads=score,team,leads
    original={c.sid:name for c,name in zip(own,roster)}
    leads=[original[c.sid] for c in best_leads]
    bring=leads+[original[c.sid] for c in best_team if c not in best_leads]
    memory["lineup_summary"]={"bring":bring,"leads":leads,"score":round(best_score,3),"seconds":round(monotonic()-started,4)}
    return {"type":"select_lineup","bring":bring,"leads":leads}
