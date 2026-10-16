import json
from types import SimpleNamespace
from unittest.mock import patch

from pokemon_bot.agent import PokemonAgent


def test_trace_records_only_public_fields_and_proposed_action(tmp_path):
    bot=PokemonAgent()
    secret='never-serialize-this-token'
    state=SimpleNamespace(phase='moving',state_version=7,access_token=secret)
    obs={'turn':2,'access_token':secret,'active_pokemon':[{'species':'gengar','current_hp_fraction':.7,'access_token':secret}],
         'opponent_active_pokemon':[{'species':'pikachu','current_hp_fraction':.1}]}
    action={'type':'doubles_turn','slot_0':{'type':'move','move_id':'shadowball','target':1,'secret':secret},'slot_1':{'type':'pass'},'secret':secret}
    bot.last_diagnostics={'fallback':False,'seconds':.2}
    with patch.object(bot,'_memory_path',return_value=tmp_path/'match.json'):
        bot._save_decision_trace('match','seat',state,obs,action,{'last_search':{'candidates':5}})
    text=(tmp_path/'match-decisions.jsonl').read_text()
    assert secret not in text
    record=json.loads(text)
    assert record['proposed_action']['slot_0']=={'type':'move','move_id':'shadowball','target':1}
    assert record['own'][0]=={'species':'gengar','current_hp_fraction':.7}
    assert record['search']['candidates']==5
    assert (tmp_path/'match-decisions.jsonl').stat().st_mode & 0o777 == 0o600


def test_trace_disk_failure_cannot_abort_a_decision(tmp_path):
    bot=PokemonAgent()
    state=SimpleNamespace(phase='moving',state_version=1)
    with patch.object(bot,'_memory_path',return_value=tmp_path/'match.json'),patch('os.open',side_effect=OSError('disk full')):
        bot._save_decision_trace('match','seat',state,{}, {'type':'doubles_turn'}, {})


def test_offline_sessions_do_not_create_traces():
    bot=PokemonAgent()
    with patch('os.open') as opened:
        bot._save_decision_trace('offline-check','seat',None,{}, {}, {})
    opened.assert_not_called()
