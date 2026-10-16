"""Regressions motivated by the first instrumented real-engine self-play."""
import pytest
import json
from types import SimpleNamespace
from unittest.mock import patch

from redalert_bot.agent import validate
from test_redalert_economy import view, orders
from redalert_bot.selfplay import RecordedAgent
from test_redalert_balance import view as combat_view, combat, actor


@pytest.mark.parametrize('item,queue', [('e1','Infantry'),('e3','Infantry'),('harv','Vehicle'),('arty','Vehicle')])
def test_ready_unit_never_gets_building_placement_order(item, queue):
    v = view(['fact','powr','tent','proc'], production=[dict(item=item,queue=queue,ready=True)], available=[])
    assert not any(o['cmd'] == 'place' for o in orders(v))
    assert validate({'cmd':'place','item':item},v) is None


def test_nonbuilding_place_hint_is_rejected_even_if_server_hint_is_malformed():
    v = view(['fact','powr'])
    v.hints['place'] = ['e1']
    assert not any(o['cmd'] == 'place' for o in orders(v))
    assert validate({'cmd':'place','item':'e1'},v) is None


@pytest.mark.parametrize('item,queue', [('powr','Building'),('pbox','Defense')])
def test_real_structure_still_placed_when_unit_and_building_finish_together(item, queue):
    v = view(['fact','powr','tent'], production=[dict(item='e1',queue='Infantry',ready=True),
                                               dict(item=item,queue=queue,ready=True)])
    out = orders(v)
    assert [o['item'] for o in out if o['cmd'] == 'place'] == [item]
    assert validate({'cmd':'place','item':item},v)


def test_observed_verdicts_deduplicate_repeated_batch_and_ignore_pending(tmp_path):
    bot = RecordedAgent(tmp_path,dict(profile='balanced',match_id='test',seat=0))
    raw = {'last_orders':{'batch':8,'results':[dict(index=0,status='pending',reason='pending')]}}
    bot._read_engine_verdicts(raw)
    assert not bot.engine_verdicts
    raw['last_orders']['results'][0].update(status='rejected',reason='invalid')
    raw['recent_order_problems'] = [dict(batch=8,index=0,status='rejected',reason='invalid')]
    bot._read_engine_verdicts(raw)
    bot._read_engine_verdicts(raw)
    assert dict(bot.engine_verdicts) == {'rejected:invalid':1}


def test_terminal_observation_failure_cannot_erase_authoritative_win(tmp_path):
    bot = RecordedAgent(tmp_path,dict(profile='balanced',match_id='test',seat=0))
    bot.last_snapshot = {'seconds':1198,'military':{'assets_value':12345}}
    final = SimpleNamespace(raw={'is_terminal':True,'observation':{'units':None}},
                            final_result={'your_return':1},termination_reason='time_limit')
    bot.on_game_end(final,SimpleNamespace(agent_id='seat0'))
    result = json.loads(bot.final_path.read_text())
    assert result['score'] == 1 and result['snapshot_error'] is True
    assert result['exact_final_observation'] is False
    assert result['last_observation']['seconds'] == 1198


def test_final_result_file_survives_timeline_write_failure(tmp_path):
    bot = RecordedAgent(tmp_path,dict(profile='balanced',match_id='test',seat=0))
    with patch.object(bot,'_append',side_effect=OSError('disk limit')):
        bot.on_game_end(SimpleNamespace(raw={},final_result={'your_return':0},termination_reason='time_limit'),
                        SimpleNamespace(agent_id='seat0'))
    assert json.loads(bot.final_path.read_text())['score'] == 0


def test_defensive_profile_keeps_economy_line_in_last_minute_instead_of_global_rear_retreat():
    v = combat_view(units=[actor(i,x=15,y=15) for i in range(1,21)],now=1140,remaining=60,
                    military={'kills_cost':10000,'deaths_cost':1000})
    v.profile = 'eco_guard'
    out,memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert all(o.get('to') != [6,6] for o in out)
