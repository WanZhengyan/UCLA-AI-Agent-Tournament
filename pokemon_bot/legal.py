"""Construct and validate choices against the current server template only."""
from itertools import product


def slot_options(template):
    slots = template.get('slots', [])
    if len(slots) != 2:
        raise ValueError('Expected two doubles slots')
    result = [None, None]
    for i, slot in enumerate(slots):
        k = slot.get('slot', i)
        if k not in (0, 1) or result[k] is not None:
            raise ValueError('Invalid slot indices')
        out = []
        for option in slot.get('options', []):
            typ = option.get('type')
            if typ == 'move' and option.get('move_id'):
                targets = option.get('targets') or []
                for target in targets or [None]:
                    a = {'type':'move','move_id':option['move_id']}
                    if target is not None:
                        if not isinstance(target,int) or isinstance(target,bool):
                            continue
                        a['target'] = target
                    out.append(a)
            elif typ == 'switch' and option.get('species'):
                out.append({'type':'switch','species':option['species']})
            elif typ == 'pass':
                out.append({'type':'pass'})
        result[k] = out
    if not all(result):
        raise ValueError('No legal choices in slot')
    return result


def enumerate_actions(template):
    options = slot_options(template)
    out = []
    for a,b in product(*options):
        if a['type']==b['type']=='switch' and a['species']==b['species']:
            continue
        if a['type']==b['type']=='pass':
            continue
        out.append({'type':'doubles_turn','slot_0':a.copy(),'slot_1':b.copy()})
    if not out:
        raise ValueError('No legal joint action')
    return out


def validate_action(action, template):
    if not isinstance(action,dict) or action.get('type')!=template.get('type'):
        return False
    if action['type']=='select_lineup':
        b,l = action.get('bring'),action.get('leads')
        return (isinstance(b,list) and isinstance(l,list) and len(b)==4 and len(l)==2
                and all(isinstance(x,str) for x in b+l)
                and len(set(b))==4 and len(set(l))==2
                and set(b)<=set(template.get('roster',[])) and set(l)<=set(b))
    if action['type']=='doubles_turn':
        try:
            options=slot_options(template)
            a,b=action.get('slot_0'),action.get('slot_1')
            if a not in options[0] or b not in options[1]: return False
            if a['type']==b['type']=='switch' and a['species']==b['species']: return False
            if a['type']==b['type']=='pass': return False
            return True
        except (ValueError,TypeError,KeyError):
            return False
    return False


def fallback(template):
    if template.get('type')=='select_lineup':
        roster=list(dict.fromkeys(template['roster']))
        if len(roster)<4: raise ValueError('Roster has fewer than four species')
        return {'type':'select_lineup','bring':roster[:4],'leads':roster[:2]}
    from .dex import move
    def score(action):
        value=0.
        for k in ('slot_0','slot_1'):
            a=action[k]
            if a['type']=='move':
                m=move(a['move_id']); p=m.get('basePower',m.get('base_power',0)) or 0
                target=a.get('target',0)
                value+=p*(1 if target>=0 else -2)
                if p: value+=10
                if target==0 and m.get('target')=='allAdjacent': value-=p*.6
            elif a['type']=='switch': value+=1
        return value
    return max(enumerate_actions(template),key=score)
