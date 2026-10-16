"""SDK policy entry, with per-seat state, duplicate detection and legal fallback."""
from __future__ import annotations
import copy
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timezone

from .state import update_memory, idnorm
from .legal import validate_action, fallback

LOG=logging.getLogger('pokemon_bot')


class PokemonAgent:
    def __init__(self):
        self.memories={}
        self.last_diagnostics={}

    def choose_action(self,state,context=None):
        raw=state.raw
        obs=raw.get('observation') or {}
        if isinstance(obs,str):
            try:obs=json.loads(obs)
            except (ValueError,TypeError):obs={}
        legal=state.legal_actions
        if not legal:raise ValueError('No pending legal actions')
        sid=getattr(context,'session_id',None) or state.session_id or 'offline'
        seat=getattr(context,'agent_id',None) or ''
        key=(sid,seat)
        if len(self.memories)>64 and key not in self.memories:self.memories.pop(next(iter(self.memories)))
        if key not in self.memories:
            self.memories[key]=self._load_public_memory(sid,seat)
        memory=self.memories[key]
        # Include legal templates: state_version resets between draft and battle.
        stable_obs={k:v for k,v in obs.items() if k not in ('clock','decision_deadline_at','decision_timeout_seconds')}
        signature=hashlib.sha256(json.dumps({'phase':state.phase,'version':state.state_version,'observation':stable_obs,'legal':[x.input for x in legal]},sort_keys=True,default=str).encode()).hexdigest()
        if memory.get('_signature')==signature:return copy.deepcopy(memory['_answer'])
        update_memory(obs,memory,seat)
        first=legal[0];template=first.input.get('action') or {}
        start=time.monotonic();fallback_used=False
        budget=max(.05,min(8.,float(os.environ.get('POKEMON_BOT_BUDGET','2.0'))))
        clock=obs.get('clock') or {}
        for name in ('decision_seconds_left','bank_seconds_left'):
            remaining=clock.get(name)
            if isinstance(remaining,(int,float)):budget=min(budget,max(.01,remaining-1.5))
        if obs.get('decision_deadline_at'):
            try:
                deadline=datetime.fromisoformat(obs['decision_deadline_at'].replace('Z','+00:00'))
                budget=min(budget,max(.01,(deadline-datetime.now(timezone.utc)).total_seconds()-1.2))
            except (ValueError,TypeError):pass
        memory['_budget']=budget
        try:
            if first.action_id.startswith('draft_pick:'):
                from .draft import choose_draft
                answer=choose_draft(obs,legal,memory)
                if answer not in legal:raise ValueError('Draft result not offered by server')
            elif first.action_id=='select_lineup':
                from .draft import choose_lineup
                answer=choose_lineup(obs,template,memory)
                if not validate_action(answer,template):raise ValueError('Invalid lineup result')
                memory['bring']=list(answer['bring']);memory['leads']=list(answer['leads'])
            elif first.action_id=='doubles_turn':
                from .battle import choose_battle
                answer=choose_battle(obs,template,memory,budget=budget)
                if not validate_action(answer,template):raise ValueError('Invalid battle result')
            else:
                raise ValueError('Unsupported game template: '+first.action_id)
        except Exception as exc:
            # Never log raw state/context: these might grow credential fields later.
            LOG.warning('Strategy fallback (%s)',type(exc).__name__)
            if first.action_id.startswith('draft_pick:'):answer=first
            elif template.get('type') in ('select_lineup','doubles_turn'):answer=fallback(template)
            else:raise
            fallback_used=True
        self.last_diagnostics={'phase':state.phase,'seconds':round(time.monotonic()-start,4),'fallback':fallback_used}
        memory['_signature']=signature;memory['_answer']=copy.deepcopy(answer)
        # Store intended actions separately; no claim that a submitted action succeeded.
        memory['_planned_action']=copy.deepcopy(answer if isinstance(answer,dict) else answer.input.get('action',{}))
        if first.action_id.startswith('draft_pick:') or first.action_id=='select_lineup':
            self._save_public_memory(sid,seat,memory)
        self._save_decision_trace(sid,seat,state,obs,answer,memory)
        return answer

    @staticmethod
    def _memory_path(sid,seat):
        if not sid or sid.startswith(('offline','selftest','test')) or os.environ.get('POKEMON_BOT_NO_CACHE')=='1':return None
        folder=Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'AltruAgentPokemon'/'public'
        token=hashlib.sha256((sid+'|'+seat).encode()).hexdigest()
        return folder/(token+'.json')

    def _load_public_memory(self,sid,seat):
        path=self._memory_path(sid,seat)
        if path is None:return {}
        try:
            data=json.loads(path.read_text())
            return {k:v for k,v in data.items() if k in ('cards','own_roster','foe_roster','bring','leads','own_seat')}
        except (OSError,ValueError,AttributeError):return {}

    def _save_public_memory(self,sid,seat,memory):
        path=self._memory_path(sid,seat)
        if path is None:return
        try:
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            data={k:v for k,v in memory.items() if k in ('cards','own_roster','foe_roster','bring','leads','own_seat')}
            temp=path.with_suffix('.tmp')
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(data,stream,ensure_ascii=False)
            os.replace(temp,path)
        except (OSError,TypeError,ValueError):pass

    def _save_decision_trace(self,sid,seat,state,obs,answer,memory):
        """Bounded local record of public positions and proposed actions.

        A proposal is not proof of server acceptance. Never serialize a raw
        state, context, HTTP object or environment into this file.
        """
        path=self._memory_path(sid,seat)
        if path is None:return
        path=path.with_name(path.stem+'-decisions.jsonl')
        def public_board(key):
            values=obs.get(key) or []
            if not isinstance(values,list):values=[values]
            fields=('species','current_hp_fraction','current_hp','max_hp','status','boosts','fainted')
            return [{k:mon[k] for k in fields if k in mon} if isinstance(mon,dict) else None for mon in values[:2]]
        action=answer if isinstance(answer,dict) else answer.input.get('action',{})
        allowed=('type','card_id','bring','leads','slot_0','slot_1')
        action={k:v for k,v in action.items() if k in allowed}
        for key in ('slot_0','slot_1'):
            if isinstance(action.get(key),dict):
                action[key]={k:v for k,v in action[key].items() if k in ('type','move_id','target','species')}
        record={'phase':state.phase,'state_version':state.state_version,'turn':obs.get('turn'),
                'own':public_board('active_pokemon'),'opponent':public_board('opponent_active_pokemon'),
                'proposed_action':action,'diagnostics':dict(self.last_diagnostics)}
        if state.phase=='moving':record['search']=dict(memory.get('last_search',{}))
        try:
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if path.exists() and path.stat().st_size>=8*1024*1024:return
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        except (OSError,TypeError,ValueError):pass

    def decide(self,raw):
        from altruagent.models import GameState,DecisionContext,LegalAction
        wrapper=raw;raw=wrapper.get('state',wrapper)
        state=GameState.from_mcp_state(raw)
        context=DecisionContext(session_id=state.session_id or 'offline',tournament_id=None,
                                game_type=raw.get('game_type','pokemon_vgc_doubles_draft'),
                                agent_id=wrapper.get('agent_id','offline'),seat_position=wrapper.get('seat_position',0))
        answer=self.choose_action(state,context)
        if isinstance(answer,LegalAction):return answer.input.get('action',{'action_id':answer.action_id})
        return answer


def create_agent():
    return PokemonAgent()
