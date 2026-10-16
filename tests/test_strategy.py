"""Regression tests for authoritative-template legality and observation isolation."""
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pokemon_bot import legal
from pokemon_bot.state import normalize_mon, update_memory, build_battle
from pokemon_bot.agent import PokemonAgent


def template(a,b):
    return {'type':'doubles_turn','slots':[{'slot':0,'board_position':-1,'options':a},{'slot':1,'board_position':-2,'options':b}]}


def moving(t,version=1,sid='test',turn=1):
    return {'session_id':sid,'game_type':'pokemon_vgc_doubles_draft','phase':'moving','state_version':version,'is_current_actor':True,'status':'in_progress','observation':{'phase':'moving','turn':turn,'is_doubles':True},'legal_actions':{'actions':[{'action_id':'doubles_turn','input':{'session_id':sid,'state_version':version,'action':t}}]}}


class LegalTests(unittest.TestCase):
    def test_two_faints_one_reserve_requires_one_switch(self):
        opts=[{'type':'switch','species':'landorustherian'},{'type':'pass'}]
        t=template(opts,opts); aa=legal.enumerate_actions(t)
        self.assertEqual(len(aa),2)
        for a in aa:
            self.assertTrue(legal.validate_action(a,t))
            self.assertEqual(sorted([a['slot_0']['type'],a['slot_1']['type']]),['pass','switch'])

    def test_both_pass_rejected_even_without_other_options(self):
        t=template([{'type':'pass'}],[{'type':'pass'}])
        with self.assertRaises(ValueError):legal.enumerate_actions(t)
        self.assertFalse(legal.validate_action({'type':'doubles_turn','slot_0':{'type':'pass'},'slot_1':{'type':'pass'}},t))

    def test_forced_switch_other_slot_must_pass(self):
        t=template([{'type':'pass'}],[{'type':'switch','species':'rillaboom'}])
        a=legal.fallback(t)
        self.assertEqual(a['slot_0'],{'type':'pass'})
        self.assertEqual(a['slot_1'],{'type':'switch','species':'rillaboom'})

    def test_fixed_ally_coordinates_survive_enumeration(self):
        t=template([{'type':'move','move_id':'helpinghand','targets':[-2]}],[{'type':'move','move_id':'pollenpuff','targets':[-1,1,2]}])
        aa=legal.enumerate_actions(t)
        self.assertEqual(len(aa),3)
        self.assertTrue(all(a['slot_0']['target']==-2 for a in aa))
        self.assertEqual({a['slot_1']['target'] for a in aa},{-1,1,2})

    def test_reverse_slot_array_still_uses_slot_numbers(self):
        t=template([{'type':'move','move_id':'helpinghand','targets':[-2]}],[{'type':'move','move_id':'protect','targets':[0]}])
        t['slots'].reverse();a=legal.fallback(t)
        self.assertEqual(a['slot_0']['move_id'],'helpinghand')
        self.assertEqual(a['slot_1']['move_id'],'protect')

    def test_same_switch_destination_rejected(self):
        t=template([{'type':'switch','species':'rillaboom'},{'type':'pass'}],[{'type':'switch','species':'rillaboom'},{'type':'pass'}])
        a={'type':'doubles_turn','slot_0':{'type':'switch','species':'rillaboom'},'slot_1':{'type':'switch','species':'rillaboom'}}
        self.assertFalse(legal.validate_action(a,t))

    def test_unoffered_move_or_target_rejected(self):
        t=template([{'type':'move','move_id':'moonblast','targets':[1,2]}],[{'type':'move','move_id':'protect','targets':[0]}])
        a=legal.fallback(t);a['slot_0']['target']=-1
        self.assertFalse(legal.validate_action(a,t))
        a=legal.fallback(t);a['slot_0']['move_id']='explosion'
        self.assertFalse(legal.validate_action(a,t))

    def test_unoffered_tera_rejected(self):
        t=template([{'type':'move','move_id':'moonblast','targets':[1]}],[{'type':'pass'}])
        a=legal.fallback(t);a['slot_0']['terastallize']=True
        self.assertFalse(legal.validate_action(a,t))

    def test_fallback_avoids_direct_attack_on_ally(self):
        t=template([{'type':'move','move_id':'closecombat','targets':[-2,1,2]}],[{'type':'move','move_id':'protect','targets':[0]}])
        self.assertGreater(legal.fallback(t)['slot_0']['target'],0)

    def test_empty_targets_preserve_omission(self):
        t=template([{'type':'move','move_id':'protect','targets':[]}],[{'type':'pass'}])
        a=legal.fallback(t)
        self.assertNotIn('target',a['slot_0'])
        self.assertTrue(legal.validate_action(a,t))

    def test_malformed_duplicate_slots_raise(self):
        t=template([{'type':'pass'}],[{'type':'pass'}]);t['slots'][1]['slot']=0
        with self.assertRaises(ValueError):legal.enumerate_actions(t)

    def test_lineup_uniqueness_and_leads(self):
        t={'type':'select_lineup','roster':['a','b','c','d','e','f']}
        a=legal.fallback(t);self.assertTrue(legal.validate_action(a,t))
        a['bring'][3]='a';self.assertFalse(legal.validate_action(a,t))
        a=legal.fallback(t);a['leads'][1]='f';self.assertFalse(legal.validate_action(a,t))

    def test_enumeration_never_mutates_template(self):
        t=template([{'type':'move','move_id':'protect','targets':[0]}],[{'type':'pass'}]);before=copy.deepcopy(t)
        aa=legal.enumerate_actions(t);aa[0]['slot_0']['move_id']='tackle'
        self.assertEqual(t,before)


class ObservationTests(unittest.TestCase):
    def test_hp_percentage_uses_fraction_not_opponent_max(self):
        m=normalize_mon({'species':'Snorlax','current_hp':47,'max_hp':100}, {},'foe')
        self.assertAlmostEqual(m['hp'],.47)
        self.assertGreater(m['stats']['hp'],100)

    def test_fainted_overrides_stale_hp(self):
        m=normalize_mon({'species':'Pikachu','current_hp_fraction':.7,'fainted':True},{})
        self.assertEqual(m['hp'],0)

    def test_public_draft_moves_survive_sparse_preview(self):
        mem={};update_memory({'phase':'draft','current_seat':'me','available_cards':[{'species':'Incineroar','moves':['Fake Out','Parting Shot','Flare Blitz','Knock Off'],'item':'Safety Goggles'}],'rosters':{'me':[{'species':'Incineroar'}],'them':[]}},mem)
        update_memory({'phase':'team_preview','your_roster':[{'species':'incineroar','moves':['Fake Out']}]},mem)
        m=normalize_mon({'species':'incineroar'},mem)
        self.assertEqual(len(m['moves']),4)
        self.assertEqual(m['item'],'safetygoggles')

    def test_observed_item_loss_overrides_draft_item(self):
        mem={'cards':{'rillaboom':{'species':'rillaboom','item':'Assault Vest'}}}
        self.assertEqual(normalize_mon({'species':'rillaboom','item':''},mem)['item'],'')

    def test_field_name_variants_normalized(self):
        t=template([{'type':'pass'}],[{'type':'pass'}])
        b=build_battle({'fields':['TRICK_ROOM','PSYCHIC_TERRAIN'],'side_conditions':{'TAILWIND':2},'weather':'RAIN_DANCE'},t,{})
        self.assertTrue(b['field']['trickroom']);self.assertTrue(b['field']['own_tailwind'])
        self.assertEqual(b['field']['terrain'],'psychicterrain');self.assertEqual(b['field']['weather'],'raindance')

    def test_first_turn_not_reset_on_repeated_observation(self):
        t=template([{'type':'pass'}],[{'type':'pass'}]);mem={};obs={'turn':1,'active_pokemon':[{'species':'Incineroar'},None]}
        self.assertTrue(build_battle(obs,t,mem)['own'][0]['first_turn'])
        self.assertTrue(build_battle(obs,t,mem)['own'][0]['first_turn'])
        obs['turn']=2
        self.assertFalse(build_battle(obs,t,mem)['own'][0]['first_turn'])
        obs['active_pokemon']=[{'species':'Rillaboom'},None]
        self.assertTrue(build_battle(obs,t,mem)['own'][0]['first_turn'])

    def test_active_and_fainted_not_duplicated_in_bench(self):
        t=template([{'type':'pass'}],[{'type':'pass'}]);obs={'active_pokemon':[{'species':'Pikachu'},None],'team':{'p1:a':{'species':'Pikachu'},'p1:b':{'species':'Raichu','fainted':True},'p1:c':{'species':'Snorlax'}}}
        self.assertEqual([m['species'] for m in build_battle(obs,t,{})['own_bench']],['snorlax'])


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.t=template([{'type':'move','move_id':'protect','targets':[0]}],[{'type':'pass'}])

    def test_duplicate_decision_uses_cache_and_returns_copy(self):
        calls=[]
        def choose(obs,t,mem,budget):calls.append(1);return legal.fallback(t)
        with patch.dict(sys.modules,{'pokemon_bot.battle':types.SimpleNamespace(choose_battle=choose)}):
            bot=PokemonAgent();raw=moving(self.t);a=bot.decide(raw);a['slot_0']['move_id']='invalid';b=bot.decide(raw)
        self.assertEqual(len(calls),1);self.assertEqual(b['slot_0']['move_id'],'protect')

    def test_same_version_new_template_not_cached(self):
        calls=[]
        def choose(obs,t,mem,budget):calls.append(1);return legal.fallback(t)
        with patch.dict(sys.modules,{'pokemon_bot.battle':types.SimpleNamespace(choose_battle=choose)}):
            bot=PokemonAgent();bot.decide(moving(self.t));t=copy.deepcopy(self.t);t['slots'][0]['options'][0]={'type':'move','move_id':'moonblast','targets':[1]};answer=bot.decide(moving(t))
        self.assertEqual(len(calls),2);self.assertEqual(answer['slot_0']['move_id'],'moonblast')

    def test_sessions_have_separate_memories(self):
        def choose(obs,t,mem,budget):mem['count']=mem.get('count',0)+1;return legal.fallback(t)
        with patch.dict(sys.modules,{'pokemon_bot.battle':types.SimpleNamespace(choose_battle=choose)}):
            bot=PokemonAgent();bot.decide(moving(self.t,sid='A'));bot.decide(moving(self.t,sid='B'))
        self.assertEqual(len(bot.memories),2);self.assertEqual([m['count'] for m in bot.memories.values()],[1,1])

    def test_strategy_exception_returns_valid_fallback(self):
        def choose(*args,**kwargs):raise RuntimeError('simulated failure')
        with patch.dict(sys.modules,{'pokemon_bot.battle':types.SimpleNamespace(choose_battle=choose)}):
            bot=PokemonAgent();a=bot.decide(moving(self.t))
        self.assertTrue(legal.validate_action(a,self.t));self.assertTrue(bot.last_diagnostics['fallback'])


class DraftTests(unittest.TestCase):
    def cards(self):
        from pokemon_bot.selftest import fixture
        f=fixture()['observation']
        cards=f['active_pokemon']+f['opponent_active_pokemon']+[
            {'species':'Tornadus','moves':['Tailwind','Bleakwind Storm','Taunt','Protect'],'ability':'Prankster','item':'Covert Cloak'},
            {'species':'Amoonguss','moves':['Spore','Rage Powder','Pollen Puff','Protect'],'ability':'Regenerator','item':'Rocky Helmet'}]
        for i,c in enumerate(cards):c['card_id']='Server-Card-'+str(i)
        return cards

    def test_draft_returns_exact_server_object(self):
        from pokemon_bot.draft import choose_draft
        from altruagent.models import LegalAction
        cards=self.cards();actions=[LegalAction(action_id='draft_pick:'+c['card_id'],label=c['species'],input={'action':{'type':'draft_pick','card_id':c['card_id']}}) for c in cards]
        a=choose_draft({'phase':'draft','available_cards':cards,'rosters':{'me':[],'foe':[]},'current_seat':'me','first_drafter':'me','pick_number':1},actions,{'_budget':.1})
        self.assertTrue(any(a is x for x in actions))

    def test_unoffered_card_never_selected(self):
        from pokemon_bot.draft import choose_draft
        from altruagent.models import LegalAction
        cards=self.cards();actions=[LegalAction(action_id='draft_pick:'+c['card_id'],label=c['species'],input={'action':{'type':'draft_pick','card_id':c['card_id']}}) for c in cards[-2:]]
        a=choose_draft({'phase':'draft','available_cards':cards,'rosters':{'me':[],'foe':[]},'current_seat':'me'},actions,{})
        self.assertTrue(any(a is x for x in actions))

    def test_rollout_item_clause(self):
        from pokemon_bot.draft import _legal_for, _profile
        cards=self.cards();cards[1]['item']=cards[0]['item']
        first,duplicate,other=(_profile(cards[i]) for i in [0,1,4])
        self.assertFalse(_legal_for(duplicate,[first]))
        self.assertTrue(_legal_for(other,[first]))

    def test_preview_retains_original_identifiers(self):
        from pokemon_bot.draft import choose_lineup
        cards=self.cards();roster=[c['species'] for c in cards];t={'type':'select_lineup','roster':roster}
        a=choose_lineup({'your_roster':cards,'opponent_roster':list(reversed(cards))},t,{'_budget':.000001})
        self.assertTrue(legal.validate_action(a,t));self.assertEqual(len(set(a['bring'])),4)

    def test_tiny_budget_draft_stays_legal(self):
        from pokemon_bot.draft import choose_draft
        cards=self.cards();actions=[{'action_id':'draft_pick:'+c['card_id'],'input':{'action':{'type':'draft_pick','card_id':c['card_id']}}} for c in cards]
        a=choose_draft({'phase':'draft','available_cards':cards,'rosters':{},'current_seat':'me'},actions,{'_budget':.000001})
        self.assertTrue(any(a is x for x in actions))


if __name__=='__main__':unittest.main()
