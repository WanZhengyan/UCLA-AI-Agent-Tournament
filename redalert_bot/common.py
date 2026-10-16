"""Small, read-only projection of the platform's public observation."""
from __future__ import annotations
import math

DEFAULT_COSTS = {
    'powr': 300, 'apwr': 500, 'tent': 500, 'barr': 500, 'proc': 1400,
    'weap': 2000, 'fix': 1200, 'dome': 1000, 'e1': 100, 'e3': 300,
    'e6': 500, 'medi': 200, 'harv': 1100, 'mcv': 2500, '1tnk': 700,
    '2tnk': 850, '3tnk': 1150, '4tnk': 2000, 'jeep': 500, 'ftrk': 600,
    'apc': 850, 'arty': 800, 'v2rl': 900, 'pbox': 400, 'gun': 800,
    'ftur': 600, 'tsla': 1500, 'agun': 800, 'sam': 750,
}
DEFENSES = {'pbox','hbox','gun','ftur','tsla','agun','sam','sbag','fenc','brik','gap'}
BUILDINGS = {'fact','powr','apwr','tent','barr','proc','weap','fix','dome','atek','stek','hpad','afld','silo','spen','syrd'}
INFANTRY = {'e1','e2','e3','e4','e6','e7','medi','mech','shok','dog','spy','thf'}
NONCOMBAT = {'mcv','harv','e6','medi','mech','spy','thf','lst','ss','msub','dd','ca','pt'}

def cell(actor):
    if isinstance(actor, dict):
        return (int(actor.get('x',0)), int(actor.get('y',0)))
    return (int(actor[0]), int(actor[1]))

def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

def alive(a):
    return isinstance(a,dict) and isinstance(a.get('id'),int) and not a.get('wreck') and not str(a.get('type','')).endswith('husk') and a.get('hp',100) > 0

class View:
    def __init__(self, raw, config=None):
        self.raw = raw or {}
        self.config = config or {}
        self.obs = self.raw.get('observation') or {}
        self.rules = self.config.get('rules') or {}
        self.units = [a for a in self.obs.get('units',[]) if alive(a)]
        self.buildings = [a for a in self.obs.get('buildings',[]) if alive(a)]
        self.enemies = [a for a in self.obs.get('visible_enemies',[]) if alive(a)]
        self.enemy_buildings = [a for a in self.obs.get('visible_enemy_buildings',[]) if alive(a)]
        self.production = self.obs.get('production') or []
        self.hints = self.raw.get('legal_actions') or {}
        if not isinstance(self.hints,dict): self.hints = {}
        self.available = set(self.obs.get('available_production') or [])
        self.econ = self.obs.get('economy') or {}
        self.military = self.obs.get('military') or {}
        time = self.raw.get('time') or {}
        self.now = float(time.get('game_seconds', self.obs.get('tick',self.raw.get('state_version',0))/25))
        duration = time.get('max_minutes', 20)
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 10 <= duration <= 20:
            duration = 20
        self.remaining = float(time.get('remaining_seconds', max(0,duration*60-self.now)))
        map_state = self.raw.get('map') or self.obs.get('map') or {}
        self.map_id = map_state.get('id', 'unknown')
        self.map_info = (self.rules.get('maps') or {}).get(map_state.get('id'),{})
        self.bounds = tuple(map_state.get('bounds') or self.map_info.get('bounds') or [0,0,map_state.get('width',128),map_state.get('height',128)])
        base = self.obs.get('base_center')
        if base is None:
            own = self.buildings or self.units
            base = cell(own[0]) if own else (self.bounds[0]+self.bounds[2]//2,self.bounds[1]+self.bounds[3]//2)
        self.base = cell(base)
        enemy = self.hints.get('enemy_base')
        spawns = self.map_info.get('spawns') or []
        if not enemy and spawns: enemy = max(spawns,key=lambda s: distance(cell(s),self.base))
        if not enemy:
            x,y,w,h = self.bounds
            enemy = [2*x+w-1-self.base[0],2*y+h-1-self.base[1]]
        self.enemy_base = tuple(self.clamp(cell(enemy)))
        layout = self.map_info.get('layout') or {}
        origin = layout.get('origin') or self.bounds[:2]
        self.ore_cells = [(origin[0]+x,origin[1]+y) for y,row in enumerate(layout.get('rows') or []) for x,c in enumerate(row) if c in '$*M']

    cell = staticmethod(cell)

    def clamp(self, position):
        x,y,w,h = self.bounds
        return [max(x,min(x+w-1,int(round(position[0])))),max(y,min(y+h-1,int(round(position[1]))))]

    def item_rule(self,item):
        return (self.rules.get('units') or {}).get(item) or (self.rules.get('buildings') or {}).get(item) or {}

    def cost(self,item):
        return float(self.item_rule(item).get('cost',DEFAULT_COSTS.get(item,700)))

    def queue(self,item):
        return self.item_rule(item).get('queue') or ('Defense' if item in DEFENSES else 'Building' if item in BUILDINGS else 'Infantry' if item in INFANTRY else 'Vehicle')

    def count(self,item):
        return sum(a.get('type')==item for a in self.units+self.buildings)

    def queue_count(self,queue):
        return sum(int(p.get('count',1)) for p in self.production if p.get('queue',self.queue(p.get('item','')))==queue)
