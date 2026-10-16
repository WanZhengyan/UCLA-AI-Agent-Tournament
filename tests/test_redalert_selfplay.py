from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from altruagent.models import DecisionContext, GameState
from altruagent.worker import _notify_experiment_start, _notify_experiment_end
from competition_agent import create_agent
from redalert_bot.agent import RedAlertAgent, validate
from redalert_bot.common import View
from redalert_bot.combat import plan
from redalert_bot.economy import _expansion_window
from redalert_bot.selftest import sample
from redalert_bot.selfplay import RecordedAgent, allocate, make_policy, summarize
from test_redalert_balance import actor, view, combat


def ctx(seat=0, session='session-1', tournament=None):
    return DecisionContext(session, tournament, 'red_alert', 'agent-' + str(seat), seat, {'rules': {}})


def settings(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'settings.json').write_text(json.dumps(dict(enabled=True, run_id='test', profiles=['balanced','eco_guard'])))


def raw():
    data = sample()
    data.update(time={'game_seconds':0, 'remaining_seconds':600, 'max_minutes':10},
                map={'id':'sidestep','bounds':[0,0,100,100]})
    return data


def assignment(seat=0, **overrides):
    data = dict(match_id='match-1', seat_id='seat-'+str(seat), seat_position=seat,
                context='testing', game_type='red_alert', seat_count=2)
    data.update(overrides)
    return SimpleNamespace(**data)


def test_hook_attests_only_two_owned_testing_seats():
    contestant, official = Mock(), Mock()
    official.assignments.return_value = [assignment(0), assignment(1)]
    worker = SimpleNamespace(match_id='match-1',seat_id='seat-0')
    _notify_experiment_start(contestant, worker, official, ctx())
    assert contestant.on_match_start.call_args.args[0] == dict(match_id='match-1', verified_selfplay=True)


@pytest.mark.parametrize('rows', [
    [assignment()],
    [assignment(), assignment(0,seat_id='duplicate')],
    [assignment(), assignment(1,context='tournament')],
    [assignment(), assignment(1,match_id='another-match')],
    [assignment(), assignment(1,seat_count=7)],
])
def test_hook_cannot_mark_other_matches_as_selfplay(rows):
    contestant, official = Mock(), Mock()
    official.assignments.return_value = rows
    _notify_experiment_start(contestant, SimpleNamespace(match_id='match-1',seat_id='seat-0'), official, ctx())
    assert contestant.on_match_start.call_args.args[0]['verified_selfplay'] is False


def test_tournament_skips_assignment_read_and_experiment():
    contestant, official = Mock(), Mock()
    _notify_experiment_start(contestant, SimpleNamespace(), official, ctx(tournament='cup'))
    official.assignments.assert_not_called()
    contestant.on_match_start.assert_not_called()


def test_network_and_end_callback_failure_do_not_abort_worker():
    contestant, official = Mock(), Mock()
    official.assignments.side_effect = OSError('offline')
    _notify_experiment_start(contestant, SimpleNamespace(match_id='m'), official, ctx())
    contestant.on_match_start.assert_not_called()
    contestant.on_game_end.side_effect = OSError('disk full')
    _notify_experiment_end(contestant, SimpleNamespace(), ctx())


def test_registry_gives_both_workers_same_pair_then_swaps_seats(tmp_path):
    settings(tmp_path)
    def allocate_one(seat):
        return allocate(tmp_path, {'match_id':'one'}, ctx(seat), raw(), 'code')[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        entries = list(pool.map(allocate_one, [1,0]))
    assert {e['seat']:e['profile'] for e in entries} == {0:'balanced',1:'eco_guard'}
    again = allocate_one(0)
    assert again['leg'] == 0
    _, second = allocate(tmp_path, {'match_id':'two'}, ctx(0,'session-2'), raw(), 'code')
    assert second['profile'] == 'eco_guard' and second['leg'] == 1
    longer = raw()
    longer['time']['max_minutes'] = 20
    _, separate = allocate(tmp_path, {'match_id':'three'}, ctx(0,'session-3'), longer, 'code')
    assert separate['profile'] == 'balanced' and separate['leg'] == 0


def test_registry_rejects_changed_source_or_session(tmp_path):
    settings(tmp_path)
    allocate(tmp_path, {'match_id':'one'}, ctx(), raw(), 'code')
    assert allocate(tmp_path, {'match_id':'one'}, ctx(), raw(), 'changed') is None
    assert allocate(tmp_path, {'match_id':'one'}, ctx(session='other'), raw(), 'code') is None


def test_unverified_metadata_cannot_enable_candidate():
    state = GameState.from_mcp_state(raw())
    assert type(make_policy({'verified_selfplay':False},ctx(),state)) is RedAlertAgent
    assert type(make_policy({'verified_selfplay':True},ctx(tournament='cup'),state)) is RedAlertAgent


def test_router_uses_profile_only_after_attestation(monkeypatch,tmp_path):
    import redalert_bot.selfplay as experiment
    settings(tmp_path)
    monkeypatch.setattr(experiment,'ROOT',tmp_path)
    bot, state = create_agent(), GameState.from_mcp_state(raw())
    bot.on_match_start({'match_id':'match-1','verified_selfplay':True},ctx(1))
    bot.choose_action(state,ctx(1))
    tested = next(iter(bot._policies.values()))
    assert tested.profile == 'eco_guard'
    production = create_agent()
    production.choose_action(state,ctx(1))
    assert type(next(iter(production._policies.values()))) is RedAlertAgent


def test_guard_profile_holds_bulk_instead_of_marching_to_enemy():
    v = view(units=[actor(i,x=15,y=15) for i in range(1,21)])
    v.profile = 'eco_guard'
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert not any(o['cmd'] in {'attack','attack_move'} for o in orders)
    assert all(o.get('to') != [80,80] for o in orders)


def test_guard_profile_still_responds_to_attack_on_economy():
    v = view(units=[actor(i,x=15,y=15) for i in range(1,21)],enemies=[actor(99,x=18,y=15)])
    v.profile = 'eco_guard'
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'defend economy'
    assert any(o.get('to') == [18,15] for o in orders)


def test_guard_profile_score_deficit_does_not_force_unarmored_attack():
    v = view(units=[actor(i,x=15,y=15) for i in range(1,21)],now=480,remaining=120,
             military={'kills_cost':0,'deaths_cost':1000,'assets_value':50000})
    v.profile = 'eco_guard'
    orders, memory = combat(v)
    # A score deficit is not permission to sacrifice another rifle-only wave.
    assert memory['combat']['mode'] == 'guard economy'
    assert not any(o.get('to') == [80,80] for o in orders)


def test_guard_profile_late_deficit_does_not_override_tower_check():
    v = view(forts=[actor(80,'tsla',65,65)],now=570,remaining=30,military={'deaths_cost':1000})
    v.profile = 'eco_guard'
    orders, memory = combat(v)
    assert memory['combat']['mode'] == 'guard economy'
    assert all(o['cmd'] != 'attack_move' for o in orders)


@pytest.mark.parametrize('duration', range(600,1201,60))
def test_expansion_window_uses_remaining_time_and_works_before_260_seconds(duration):
    v = view(units=[actor(i,x=15,y=15) for i in range(1,21)],now=220,remaining=duration-220)
    v.profile = 'eco_guard'
    memory = {'site_checked_at':220,'expansion_site':(30,10)}
    assert _expansion_window(v,memory)
    assert memory['expansion_required_seconds'] < v.remaining
    v.remaining = 120
    assert not _expansion_window(v,memory)


def test_expansion_requires_an_army_and_uses_live_build_times():
    v = view(units=[actor(1)],now=220,remaining=380)
    v.profile = 'eco_guard'
    memory = {'site_checked_at':220,'expansion_site':(30,10)}
    assert not _expansion_window(v,memory)
    v.units = [actor(i) for i in range(1,21)]
    v.rules = {'units':{'mcv':{'build_time_s':300}}}
    assert not _expansion_window(v,memory)


def test_balanced_timing_is_preserved():
    v = view(now=220,remaining=380)
    assert not _expansion_window(v,{})
    v.now = 261
    assert _expansion_window(v,{})


def test_experimental_batches_remain_valid_and_do_not_mutate_input():
    data = view(units=[actor(i,x=15,y=15) for i in range(1,181)]).raw
    before = deepcopy(data)
    state = GameState.from_mcp_state(data)
    orders = RedAlertAgent('eco_guard').choose_action(state,ctx())['orders']
    v = View(data)
    assert len(orders) <= 20
    assert sum(len(o.get('units',[])) or o.get('count',1) for o in orders) <= 200
    assert all(validate(o,v) for o in orders)
    assert data == before


def test_trace_whitelists_data_and_captures_terminal_score(tmp_path):
    settings(tmp_path)
    directory, entry = allocate(tmp_path, {'match_id':'one'}, ctx(), raw(), 'code')
    bot = RecordedAgent(directory,entry)
    data = raw()
    data['access_token'] = 'SECRET-SENTINEL'
    data['players'] = [{'private':'SECRET-SENTINEL'}]
    bot.choose_action(GameState.from_mcp_state(data),ctx())
    state = SimpleNamespace(raw={'is_terminal':True},final_result={'your_return':1},
                            termination_reason='time_limit',returns={})
    bot.on_game_end(state,ctx())
    assert 'SECRET-SENTINEL' not in bot.path.read_text()
    report = json.loads(bot.final_path.read_text())
    assert report['score'] == 1 and report['exact_final_observation'] is False
    assert report['last_observation']['seconds'] == 0
    assert summarize(tmp_path)['completed_comparisons'] == 0
    assert summarize(tmp_path)['incomplete_or_invalid'] == ['one']


def test_summary_requires_two_terminal_seats_and_never_counts_two_same_profiles(tmp_path):
    settings(tmp_path)
    for seat in (0,1):
        directory, entry = allocate(tmp_path, {'match_id':'one'}, ctx(seat), raw(), 'code')
        bot = RecordedAgent(directory,entry)
        bot.on_game_end(SimpleNamespace(raw={},final_result={'your_return':seat},returns={},
                                      termination_reason='time_limit'),ctx(seat))
    summary = summarize(tmp_path)
    assert summary['completed_comparisons'] == 1 and summary['candidate_wins'] == 1
    assert summary['complete_same_version_swapped_pairs'] == 0
    file = sorted((tmp_path/'test').glob('*-final.json'))[0]
    row = json.loads(file.read_text())
    row['profile'] = 'eco_guard'
    file.write_text(json.dumps(row))
    assert summarize(tmp_path)['completed_comparisons'] == 0


@pytest.mark.parametrize('change_version',[False,True])
def test_counterbalanced_pair_requires_same_source_version(tmp_path,change_version):
    settings(tmp_path)
    for game in range(2):
        for seat in (0,1):
            context = ctx(seat,session='session-'+str(game))
            code = 'new' if game and change_version else 'old'
            directory, entry = allocate(tmp_path,{'match_id':'game-'+str(game)},context,raw(),code)
            bot = RecordedAgent(directory,entry)
            score = 1 if entry['profile'] == 'eco_guard' else 0
            bot.on_game_end(SimpleNamespace(raw={},final_result={'your_return':score},returns={},
                                           termination_reason='time_limit'),context)
    summary = summarize(tmp_path)
    assert summary['completed_comparisons'] == 2
    assert summary['complete_same_version_swapped_pairs'] == (0 if change_version else 1)


@pytest.mark.parametrize('invalid', ['failure', 'failure_reason', 'boolean'])
def test_invalid_terminal_results_never_become_selfplay_evidence(tmp_path, invalid):
    settings(tmp_path)
    for seat in (0, 1):
        directory, entry = allocate(tmp_path, {'match_id': 'one'}, ctx(seat), raw(), 'code')
        bot = RecordedAgent(directory, entry)
        result = {'your_return': seat}
        if invalid == 'failure':
            result['status'] = 'failed'
        elif invalid == 'failure_reason':
            result['failure_reason'] = 'private failure details need not be stored'
        else:
            result['your_return'] = bool(seat)
        bot.on_game_end(SimpleNamespace(raw={}, final_result=result, returns={},
                                       termination_reason='time_limit'), ctx(seat))
        report = json.loads(bot.final_path.read_text())
        assert report['score'] is None
        assert 'private failure details' not in bot.final_path.read_text()
        assert report['strategy_version'] == bot.strategy_version
    assert summarize(tmp_path)['completed_comparisons'] == 0


def test_summary_rejects_legacy_boolean_score_files(tmp_path):
    settings(tmp_path)
    for seat in (0, 1):
        directory, entry = allocate(tmp_path, {'match_id': 'one'}, ctx(seat), raw(), 'code')
        (directory / f'seat{seat}-final.json').write_text(json.dumps(dict(entry, score=bool(seat))))
    assert summarize(tmp_path)['completed_comparisons'] == 0
