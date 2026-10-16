"""Observation-driven Red Alert policy with bounded command and retry rates.

No external inference, hidden information, spectator view or model credentials.
The official SDK provides authentication and sequential real-time transport.
"""
from __future__ import annotations
from collections import OrderedDict
import json
import re
from altruagent import WAIT
from .common import View

FIELDS = {
    'build': ({'item'},set()), 'train': ({'item'},{'count'}),
    'place': ({'item'},{'at'}), 'cancel': ({'item'},set()),
    'move': ({'units','to'},{'queued'}), 'attack_move': ({'units','to'},{'queued'}),
    'attack': ({'units'},{'target','to','queued'}), 'deploy': ({'units'},set()),
    'stop': ({'units'},set()), 'harvest': ({'units'},{'to','queued'}),
    'set_stance': ({'units','stance'},set()), 'guard': ({'units','target'},{'queued'}),
    'repair': ({'building'},{'on'}), 'power_toggle': ({'building'},{'on'}),
    'rally': ({'building','to'},set()), 'set_primary': ({'building'},set()),
    'sell': ({'building'},set()),
}

def signature(order):
    return json.dumps(order,sort_keys=True,separators=(',',':'))

def validate(order, v):
    """Return a clean valid order or None; never infer a hidden enemy target."""
    if not isinstance(order,dict) or order.get('cmd') not in FIELDS: return None
    out = dict(order)
    cmd = out['cmd']
    required,optional = FIELDS[cmd]
    if not required.issubset(out) or set(out)-{'cmd'}-required-optional: return None
    own_units = {a['id']:a for a in v.units}
    own_buildings = {a['id']:a for a in v.buildings}
    if 'units' in out:
        allowed = set(own_units)
        if cmd in {'attack','stop','set_stance','guard'}: allowed |= set(own_buildings)
        if not isinstance(out['units'],list): return None
        ids = list(dict.fromkeys(i for i in out['units'] if type(i) is int and i in allowed))
        if cmd=='deploy': ids = [i for i in ids if own_units[i].get('type')=='mcv']
        if cmd=='harvest': ids = [i for i in ids if own_units[i].get('type')=='harv']
        max_units = min(50,int((v.raw.get('limits') or {}).get('max_units_per_order',50)))
        if not ids or len(ids)>max_units: return None
        out['units'] = ids
    if 'building' in out and (type(out['building']) is not int or out['building'] not in own_buildings): return None
    for field in ('to','at'):
        if field in out:
            c = out[field]
            if not isinstance(c,(list,tuple)) or len(c)!=2 or any(type(n) is not int for n in c): return None
            if list(c)!=v.clamp(c): return None
            out[field] = list(c)
    if cmd=='attack':
        if ('target' in out)==('to' in out): return None
        if 'target' in out and out['target'] not in {a['id'] for a in v.enemies+v.enemy_buildings}: return None
    if cmd=='guard' and out['target'] not in set(own_units)|set(own_buildings): return None
    if 'item' in out:
        item = out['item']
        if not isinstance(item,str): return None
        if cmd in {'build','train'} and item not in v.available: return None
        if cmd=='place' and v.queue(item) not in {'Building','Defense'}: return None
        if cmd=='place' and not (item in (v.hints.get('place') or []) or any(p.get('item')==item and p.get('ready') for p in v.production)): return None
        if cmd=='cancel' and not any(p.get('item')==item for p in v.production): return None
    if 'count' in out:
        count = out['count']
        cap = min(10,int((v.raw.get('limits') or {}).get('max_train_count',10)))
        if type(count) is not int or not 1<=count<=cap: return None
    if 'stance' in out and out['stance'] not in {'hold_fire','return_fire','defend','attack_anything'}: return None
    for field in ('on','queued'):
        if field in out and type(out[field]) is not bool: return None
    return out

class RedAlertAgent:
    def __init__(self, profile='balanced'):
        if profile not in {'balanced', 'eco_guard'}:
            raise ValueError('Unknown Red Alert policy profile')
        self.profile = profile
        self.strategy_version = 'economy_guard_v14' if profile == 'eco_guard' else 'balanced'
        self.sessions = {}

    def _memory(self, context):
        sid = getattr(context,'session_id',None) or 'default'
        if sid not in self.sessions:
            self.sessions[sid] = dict(economy={},combat={},cooldowns={},blocked={},failures={},inflight={},history=OrderedDict(),batches={},seen=set(),last=[],now=0)
        return self.sessions[sid]

    @staticmethod
    def _verdict(memory, record, status, reason):
        order,key = record
        sig = signature(order)
        now = memory['now']
        if status in {'rejected','lost'}:
            unit_history = memory['combat'].get('combat',{}).get('unit_orders',{})
            for ident in order.get('units',[]):
                unit_history.pop(str(ident),None)
            # A refused build was never queued; make room for a changed plan.
            for queue,entry in list(memory['inflight'].items()):
                if entry['sig']==sig: del memory['inflight'][queue]
            memory['cooldowns'].pop(key,None)
            if status=='lost':
                memory['blocked'][sig] = now+0.3
                return
            count = memory['failures'].get(sig,0)+1
            memory['failures'][sig] = count
            memory['blocked'][sig] = now+min(30,2**min(count,5))
        elif status=='ok':
            memory['failures'].pop(sig,None)
            memory['blocked'].pop(sig,None)

    def _read_verdicts(self,v,memory):
        last = v.raw.get('last_orders') or {}
        version = last.get('state_version')
        records = memory['history'].get(version) or memory['batches'].get(str(last.get('batch')),[])
        if records and last.get('batch') is not None:
            memory['batches'][str(last['batch'])] = records
        rows = [(last.get('batch',version),row,records) for row in last.get('results',[])]
        rows += [(row.get('batch'),row,memory['batches'].get(str(row.get('batch')),[])) for row in v.raw.get('recent_order_problems') or []]
        for batch,row,records in rows:
            index = row.get('index')
            stamp = (batch,index,row.get('status'),row.get('reason'))
            if stamp in memory['seen']: continue
            if type(index) is int and 0<=index<len(records) and row.get('status')!='pending':
                self._verdict(memory,records[index],row.get('status'),row.get('reason'))
                memory['seen'].add(stamp)
        if len(memory['seen'])>3000: memory['seen'].clear()
        if len(memory['batches'])>128:
            memory['batches'] = dict(list(memory['batches'].items())[-64:])
        for queue,entry in list(memory['inflight'].items()):
            observed = sum(p.get('count',1) for p in v.production if p.get('item')==entry['item'])
            if v.now>=entry['until'] or observed>entry['before']:
                del memory['inflight'][queue]

    def choose_action(self,state,context):
        raw = getattr(state,'raw',state)
        if raw.get('is_terminal') or raw.get('phase','playing')!='playing' or not raw.get('observation') or not raw.get('is_current_actor',True): return WAIT
        v = View(raw,getattr(context,'game_config',None))
        v.profile = self.profile
        memory = self._memory(context)
        memory['now'] = v.now
        self._read_verdicts(v,memory)
        from .strategy import observe
        observe(v,memory.setdefault('strategy',{}))
        if self.profile == 'eco_guard':
            from .maps import adapt
            adapt(v, memory.setdefault('map_adaptation', {}))
        orders,records = [],[]
        commands = 0
        ordered_units = set()
        limits = raw.get('limits') or {}
        max_orders = min(20,int(limits.get('max_orders_per_batch',20)))
        max_commands = min(200,int(limits.get('max_engine_commands_per_batch',200)))

        def emit(order,key=None,cooldown=3.0):
            nonlocal commands
            clean = validate(order,v)
            if clean is None or len(orders)>=max_orders: return False
            cost = len(clean.get('units',[])) or clean.get('count',1)
            if commands+cost>max_commands: return False
            sig = signature(clean)
            key = key or sig
            if memory['cooldowns'].get(key,-1)>v.now or memory['blocked'].get(sig,-1)>v.now: return False
            # Never overwrite an actor's movement twice within one batch.
            movement = clean['cmd'] in {'move','attack','attack_move','guard','deploy','harvest','stop'}
            if movement and ordered_units.intersection(clean.get('units',[])): return False
            if clean['cmd'] in {'build','train'}:
                queue = v.queue(clean['item'])
                if queue in memory['inflight']: return False
                memory['inflight'][queue] = dict(sig=sig,item=clean['item'],before=sum(p.get('count',1) for p in v.production if p.get('item')==clean['item']),until=v.now+2.5)
            orders.append(clean)
            records.append((clean,key))
            memory['cooldowns'][key] = v.now+max(0.2,cooldown)
            commands += cost
            if movement: ordered_units.update(clean.get('units',[]))
            return True

        from .economy import plan as economy
        from .combat import plan as combat
        economy(v,memory['economy'],emit)
        combat(v,memory['combat'],emit)
        if not orders: return WAIT
        version = raw.get('state_version',v.obs.get('tick',0))
        memory['history'][version] = records
        while len(memory['history'])>128: memory['history'].popitem(last=False)
        memory['last'] = records
        # Discard old one-off unit and target keys during long matches.
        if len(memory['cooldowns'])>4000:
            memory['cooldowns'] = {k:t for k,t in memory['cooldowns'].items() if t>v.now}
        return {'type':'orders','orders':orders}

    def on_action_result(self,result,context):
        memory = self._memory(context)
        records = memory['last']
        if result.get('batch') is not None: memory['batches'][str(result['batch'])] = records
        if result.get('error'):
            rejected = {int(i) for i in re.findall(r'\[(\d+)\]',str(result.get('detail','')))}
            for i,record in enumerate(records):
                # Whole-batch errors mean nothing was submitted. Generic stale /
                # temporary errors retry quickly on a fresh view, not forever.
                status = 'rejected' if result['error']=='INVALID_ACTION' and (not rejected or i in rejected) else 'lost'
                self._verdict(memory,record,status,result['error'])
            return
        for row in result.get('results') or []:
            i = row.get('index')
            if type(i) is int and 0<=i<len(records):
                self._verdict(memory,records[i],row.get('status'),row.get('reason'))

def create_agent():
    # Deployed default. The explicit balanced profile remains available for
    # controlled comparisons, but never silently replaces the current policy.
    return RedAlertAgent(profile='eco_guard')
