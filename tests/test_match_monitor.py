from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import match_monitor as mm
from altruagent import WAIT
from altruagent.models import DecisionContext, GameState
from competition_agent import create_agent
from redalert_bot.agent import create_agent as red_agent
from redalert_bot.selftest import sample


def ctx(game='red_alert', sid='live-session', seat='mine', tournament=None):
    return DecisionContext(sid, tournament, game, seat, 0)


def state(seconds=1, result=None):
    raw = sample()
    raw['session_id'] = 'live-session'
    raw['time']['game_seconds'] = seconds
    return GameState.from_mcp_state(raw, result=result)


def read(path):
    return json.loads(path.read_text())


def test_red_monitor_is_passive_private_and_permission_limited(tmp_path):
    policy, context, game = red_agent(), ctx(), state()
    mon = mm.MatchMonitor(tmp_path, context, policy)
    secret = 'DO_NOT_PERSIST_CREDENTIAL'
    game.raw['access_token'] = secret
    game.raw['observation']['economy']['access_token'] = secret
    context = SimpleNamespace(**vars(context), access_token=secret)
    action = {'orders': [{'cmd': 'deploy', 'units': [1]}]}
    before = deepcopy((game.raw, action, policy.sessions))
    mon.observe(game, context, action, policy, .02)
    assert before == (game.raw, action, policy.sessions)
    assert secret not in mon.path.read_text()
    row = read(mon.latest)
    assert row['profile'] == 'eco_guard'
    assert row['snapshot']['units'] == {'mcv': 1}
    assert row['counters']['proposed_commands'] == {'deploy': 1}
    assert row['proposed_order_batches'][0]['orders'] == [{'cmd': 'deploy', 'units': [1]}]
    assert len(row['strategy_hash']) == 64
    assert mon.path.stat().st_mode & 0o777 == 0o600
    assert mon.latest.stat().st_mode & 0o777 == 0o600


def test_sampling_keeps_cumulative_orders_and_latest_file(tmp_path):
    policy, context = red_agent(), ctx()
    mon = mm.MatchMonitor(tmp_path, context, policy)
    action = {'orders': [{'cmd': 'train', 'item': 'e1', 'count': 2}]}
    for seconds in (1, 2, 3, 6):
        mon.observe(state(seconds), context, action, policy, .01)
    rows = [json.loads(line) for line in mon.path.read_text().splitlines()]
    assert [row['kind'] for row in rows] == ['start', 'sample', 'sample']
    assert read(mon.latest)['counters']['proposed_commands'] == {'train:e1': 8}


def test_pending_is_not_final_acceptance_and_final_verdicts_deduplicate(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    mon.action_result({'results': [{'status': 'pending'}]})
    raw = {'last_orders': {'batch': 'b', 'results': [{'index': 0, 'status': 'rejected', 'reason': 'bad_item'}]}}
    mon.read_verdicts(raw)
    mon.read_verdicts(raw)
    assert mon.immediate == {'pending': 1}
    assert mon.engine == {'rejected:bad_item': 1}
    assert 'ok' not in mon.engine


@pytest.mark.parametrize(('score', 'outcome'), [(0, 'lost'), (.5, 'drew'), (1, 'won'), (None, 'unknown')])
def test_terminal_scores_and_no_result_are_distinct(tmp_path, score, outcome):
    context, policy = ctx(), red_agent()
    mon = mm.MatchMonitor(tmp_path, context, policy)
    terminal = state(result={'your_return': score, 'termination_reason': 'time_limit', 'is_terminal': True})
    terminal.raw = {}
    mon.finish(terminal, context, policy)
    row = read(mon.final)
    assert row['outcome'] == outcome
    assert row['review_needed'] == (outcome == 'lost')
    assert row['exact_final_observation'] is False


def test_server_failure_not_loss_even_with_zero_score(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    mon.finish(state(result={'status': 'failed', 'your_return': 0}), ctx(), None)
    assert read(mon.final)['outcome'] == 'no result'
    assert not read(mon.final)['review_needed']


def test_bad_terminal_observation_cannot_discard_authoritative_result(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    terminal = state(result={'your_return': 0})
    terminal.raw['observation'] = 'unparseable'
    mon.finish(terminal, ctx(), None)
    assert read(mon.final)['outcome'] == 'lost'
    assert read(mon.final)['snapshot_parse_error'] is True


def test_failed_diagnostic_does_not_discard_result(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    with patch.object(mon, 'flags', side_effect=TypeError):
        mon.finish(state(result={'your_return': 1}), ctx(), None)
    assert read(mon.final)['outcome'] == 'won'


def test_result_file_survives_timeline_failure(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    with patch.object(mon, 'append', side_effect=OSError):
        mon.finish(state(result={'your_return': 0}), ctx(), None)
    assert read(mon.final)['outcome'] == 'lost'


def test_result_timeline_survives_result_file_failure(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    with patch('match_monitor.atomic_json', side_effect=OSError):
        mon.finish(state(result={'your_return': 0}), ctx(), None)
    assert json.loads(mon.path.read_text())['outcome'] == 'lost'


def test_timeline_size_bound_does_not_block_final(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    with patch.object(mm, 'LIMIT', 1):
        mon.finish(state(result={'your_return': 1}), ctx(), None)
    assert not mon.path.exists()
    assert read(mon.final)['outcome'] == 'won'


def test_isolated_seats_and_modes(tmp_path):
    one = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    two = mm.MatchMonitor(tmp_path, ctx(seat='other', tournament='tournament'), red_agent())
    assert one.path != two.path
    assert one.meta['competition'] == 'testing'
    assert two.meta['competition'] == 'tournament'


@pytest.mark.parametrize('sid', ['offline', 'test-monitor', 'selftest', ''])
def test_offline_monitor_disabled(sid, monkeypatch):
    monkeypatch.delenv('POKEMON_BOT_NO_CACHE', raising=False)
    assert mm.make_monitor(ctx(sid=sid)) is None


def test_explicit_monitor_opt_out(monkeypatch):
    monkeypatch.setenv('COMPETITION_MONITOR_DISABLED', '1')
    assert mm.make_monitor(ctx()) is None


def test_pokemon_board_action_diagnostics_and_result(tmp_path):
    context = ctx('pokemon_vgc_doubles_draft')
    policy = SimpleNamespace(last_diagnostics={'fallback': True, 'seconds': .1, 'secret': 'never-save'})
    mon = mm.MatchMonitor(tmp_path, context, policy)
    raw = {'game_type': context.game_type, 'state_version': 3, 'phase': 'moving',
           'observation': {'turn': 2, 'active_pokemon': [{'species': 'pikachu', 'current_hp_fraction': .3, 'secret': 'never-save'}],
                           'opponent_active_pokemon': [{'species': 'gengar'}]}}
    game = GameState.from_mcp_state(raw)
    action = {'type': 'doubles_turn', 'slot_0': {'type': 'move', 'move_id': 'thunderbolt', 'target': 1, 'secret': 'never-save'}}
    for _ in range(2):
        mon.observe(game, context, action, policy, .2)
    row = read(mon.latest)
    assert row['snapshot']['own'][0]['species'] == 'pikachu'
    assert row['snapshot']['proposed_action']['slot_0']['target'] == 1
    assert mon.fallbacks == 1
    assert 'never-save' not in mon.path.read_text()
    terminal = GameState.from_mcp_state({}, result={'returns': {'mine': 0}, 'is_terminal': True})
    mon.finish(terminal, context, policy)
    assert read(mon.final)['outcome'] == 'lost'
    assert read(mon.final)['review_needed']


def test_dashboard_final_wins_over_stale_latest_and_missing_is_unknown(tmp_path):
    one = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    one.observe(state(), ctx(), WAIT, red_agent(), .1)
    one.finish(state(result={'your_return': 0}), ctx(), None)
    two = mm.MatchMonitor(tmp_path, ctx(sid='second'), red_agent())
    two.observe(state(), ctx(sid='second'), WAIT, red_agent(), .1)
    summary = mm.summarize(tmp_path, now=10**12)
    assert len(summary['games']) == 2
    assert len(summary['review_queue']) == 1
    assert {r['record_status'] for r in summary['games']} == {'finished', 'stale_or_waiting_no_result'}


def test_router_recorder_failure_does_not_change_actions_or_policy_callback(monkeypatch):
    monkeypatch.delenv('POKEMON_BOT_NO_CACHE', raising=False)
    bot, context = create_agent(), ctx()
    with patch('match_monitor.make_monitor', side_effect=OSError):
        assert bot.choose_action(state(), context)['orders'][0]['cmd'] == 'deploy'
        assert bot.choose_action(state(), context) is WAIT
        bot.on_action_result({'error': 'INVALID_ACTION'}, context)
        bot.on_game_end(state(result={'your_return': 0}), context)
    assert next(iter(bot._policies.values())).sessions[context.session_id]['failures']


def test_router_does_not_swallow_policy_exception():
    with patch('redalert_bot.agent.RedAlertAgent.choose_action', side_effect=RuntimeError('policy')):
        with pytest.raises(RuntimeError, match='policy'):
            create_agent().choose_action(state(), ctx())


def test_router_terminal_without_prior_decision_and_metadata(monkeypatch, tmp_path):
    monkeypatch.delenv('POKEMON_BOT_NO_CACHE', raising=False)
    monkeypatch.setattr(mm, 'ROOT', tmp_path)
    bot = create_agent()
    bot.on_game_end(state(result={'your_return': 0}), ctx())
    assert mm.summarize(tmp_path)['games'][0]['profile'] == 'unknown'
    assert mm.summarize(tmp_path)['games'][0]['outcome'] == 'lost'


def test_red_flags_are_observations_not_loss_inference(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    game = state(200)
    game.raw['observation']['buildings'] = [{'id': 2, 'type': 'proc', 'hp': 100, 'x': 20, 'y': 20}]
    game.raw['observation']['economy']['power_drained'] = 100
    game.raw['observation']['military'] = {'kills_cost': 1000, 'deaths_cost': 4000}
    mon.observe(game, ctx(), WAIT, red_agent(), .01)
    row = read(mon.latest)
    assert set(row['flags']) == {'low_power_observed', 'no_harvesters_observed', 'negative_trade_over_2000'}
    assert 'outcome' not in row


def test_oversized_order_buffer_is_bounded_and_reports_gaps(tmp_path):
    mon = mm.MatchMonitor(tmp_path, ctx(), red_agent())
    action = {'orders': [{'cmd': 'move', 'units': [1], 'to': [25, 30], 'secret': 'never-save'}]}
    for _ in range(50):
        mon.observe(state(1), ctx(), action, red_agent(), .001)
    assert len(mon.pending_orders) == 32
    assert mon.dropped_order_batches == 17
    mon.observe(state(6), ctx(), WAIT, red_agent(), .001)
    row = read(mon.latest)
    assert row['counters']['dropped_order_batches'] == 17
    assert len(row['proposed_order_batches']) == 32
    assert 'never-save' not in mon.path.read_text()
