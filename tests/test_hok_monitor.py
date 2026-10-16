"""Passive team telemetry: bounded own observations and authoritative results."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from altruagent import WAIT
from altruagent.models import DecisionContext, GameState, LegalAction
import match_monitor as mm


def context():
    return DecisionContext('live-hok-session', None, mm.HOK, 'mine', 0)


def policy():
    return SimpleNamespace(strategy_version='hok_team_v1', profile='objective_team',
                           last_diagnostics={'seat': 0, 'macro': 'macro_advance',
                                             'pending': 5, 'reason': 'objective_advance'})


def state(version=0, result=None):
    views = {}
    for seat in range(5):
        views[str(seat)] = {'summary': {
            'my_hero': {'hero_id': 100 + seat, 'camp': 1, 'hp': 3000, 'max_hp': 4000,
                        'level': 3, 'deaths': 0, 'x': seat * 1000, 'z': 0},
            'other_heroes': [{'runtime_id': 10, 'hero_id': 110, 'camp': 2, 'visible': True,
                              'hp': 2000, 'max_hp': 4000, 'x': 7000, 'z': 1000},
                             {'runtime_id': 11, 'camp': 2, 'visible': False,
                              'hp': 123, 'x': 987654321, 'z': 123456789}],
            'structures': [{'type': 'ACTOR_TOWER', 'camp': 2, 'hp': 6000, 'max_hp': 6000,
                            'x': 20000, 'z': 20000}]}}
    raw = {'session_id': context().session_id, 'game_type': mm.HOK, 'phase': 'moving',
           'is_current_actor': True, 'state_version': version, 'seats': list(range(5)), 'camp': 1,
           'seconds_left': 600 - version * .2, 'max_steps': 3000,
           'pacing': {'mode': 'realtime'}, 'observation': {'seats': views},
           'simultaneous': {'standing_orders': {'0': 'macro_advance'}, 'your_pending_seats': list(range(5))}}
    return GameState.from_mcp_state(raw, result=result)


def read(path):
    return json.loads(path.read_text())


def test_hok_monitor_enabled_and_uses_team_source(monkeypatch, tmp_path):
    monkeypatch.delenv('COMPETITION_MONITOR_DISABLED', raising=False)
    monkeypatch.delenv('POKEMON_BOT_NO_CACHE', raising=False)
    monkeypatch.setattr(mm, 'ROOT', tmp_path)
    mon = mm.make_monitor(context(), policy())
    assert mon is not None and mon.meta['strategy_version'] == 'hok_team_v1'
    assert mon.meta['strategy_hash'] == mm.strategy_hash(mm.HOK)


def test_hok_existing_router_saves_final_even_before_first_decision(monkeypatch, tmp_path):
    from competition_agent import create_agent
    monkeypatch.delenv('COMPETITION_MONITOR_DISABLED', raising=False)
    monkeypatch.delenv('POKEMON_BOT_NO_CACHE', raising=False)
    monkeypatch.setattr(mm, 'ROOT', tmp_path)
    create_agent().on_game_end(state(result={'returns': {'mine': 0}, 'termination_reason': 'step_limit'}), context())
    final = list(tmp_path.glob('*-final.json'))
    assert len(final) == 1 and read(final[0])['outcome'] == 'drew'
    assert read(final[0])['strategy_version'] == 'hok_team_v1'


def test_hok_source_hash_excludes_other_games_and_legacy_sdk(monkeypatch, tmp_path):
    monkeypatch.setattr(mm, '__file__', str(tmp_path / 'match_monitor.py'))
    for folder in ('hok_platform', 'hok_bot', 'pokemon_bot', 'redalert_bot'):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'agent.py').write_text('version = 1\n')
    before = mm.strategy_hash(mm.HOK)
    for folder in ('hok_bot', 'pokemon_bot', 'redalert_bot'):
        (tmp_path / folder / 'agent.py').write_text('version = 2\n')
    assert mm.strategy_hash(mm.HOK) == before
    (tmp_path / 'hok_platform' / 'agent.py').write_text('version = 2\n')
    assert mm.strategy_hash(mm.HOK) != before


def test_team_snapshot_is_passive_and_redacts_tokens_and_hidden_positions(tmp_path):
    game, bot, ctx = state(), policy(), context()
    token = 'DO_NOT_PERSIST_SECRET'
    game.raw['access_token'] = token
    game.raw['observation']['seats']['0']['summary']['my_hero']['token'] = token
    game.raw['observation']['seats']['0']['summary']['other_heroes'][0]['token'] = token
    game.raw['observation']['seats']['5'] = {'summary': {'my_hero': {'x': 555555555}}}
    bot.last_diagnostics.update(secret=token, seconds=token, reason=token, raw_context={'token': token})
    action = {'seat': 0, 'macro': 'macro_advance', 'token': token}
    before = deepcopy((game.raw, action, vars(bot)))
    mon = mm.MatchMonitor(tmp_path, ctx, bot)
    mon.observe(game, ctx, action, bot, .001)
    assert before == (game.raw, action, vars(bot))
    text = mon.path.read_text()
    assert all(forbidden not in text for forbidden in (token, '987654321', '123456789', '555555555'))
    snap = read(mon.latest)['snapshot']
    assert len(snap['own']) == 5 and len(snap['visible_enemies']) == 1
    assert snap['structures'][0]['hp'] == 6000
    assert snap['proposed_action'] == {'seat': 0, 'macro': 'macro_advance'}
    assert snap['diagnostics'] == {'seat': 0, 'pending': 5, 'macro': 'macro_advance'}
    assert mon.path.stat().st_mode & 0o777 == 0o600


def test_hok_sampling_keeps_all_order_counts_and_bounded_pending_buffer(tmp_path):
    bot, ctx = policy(), context()
    mon = mm.MatchMonitor(tmp_path, ctx, bot)
    for version in range(21):
        for seat in range(5):
            mon.observe(state(version), ctx, {'seat': seat, 'macro': 'macro_advance'}, bot, .001)
    rows = [json.loads(line) for line in mon.path.read_text().splitlines()]
    assert [r['snapshot']['state_version'] for r in rows if r['kind'] == 'sample'] == [0, 10, 20]
    assert mon.decision_count == 105 and mon.commands == {'macro_advance': 105}
    assert read(mon.latest)['counters']['dropped_order_batches'] > 0
    assert len(read(mon.latest)['proposed_order_batches']) == 32
    assert all(order['orders'][0]['seat'] in range(5) for order in read(mon.latest)['proposed_order_batches'])


def test_hok_missing_versions_cannot_create_per_decision_log_or_freeze_later_versions(tmp_path):
    mon, bot, ctx = mm.MatchMonitor(tmp_path, context(), policy()), policy(), context()
    with patch.object(mm.time, 'monotonic', return_value=100):
        for _ in range(20):
            game = state()
            game.raw.pop('state_version')
            mon.observe(game, ctx, WAIT, bot, .001)
    mon.observe(state(10), ctx, WAIT, bot, .001)
    rows = [json.loads(line) for line in mon.path.read_text().splitlines()]
    assert len([r for r in rows if r['kind'] == 'sample']) == 2
    assert read(mon.latest)['snapshot']['state_version'] == 10


@pytest.mark.parametrize('action', [
    's3:macro_attack', {'seat': 3, 'macro': 'macro_attack'},
    LegalAction.from_dict({'action_id': 's3:macro_attack', 'input': {'action': {'seat': 3}}}),
])
def test_hok_order_accepts_only_known_seat_and_macro(action):
    assert mm.hok_order(action) == {'seat': 3, 'macro': 'macro_attack'}
    assert not mm.hok_order({'seat': 3, 'macro': 'secret-token'})
    assert not mm.hok_order({'seat': True, 'macro': 'macro_attack'})
    assert not mm.hok_order({'seat': 3, 'which_button': 2, 'token': 'secret-token'})


def test_hok_snapshot_bounds_large_observations_and_excludes_nonfinite_values(tmp_path):
    mon, game = mm.MatchMonitor(tmp_path, context(), policy()), state()
    for entry in game.raw['observation']['seats'].values():
        entry['summary']['my_hero'].update(x=float('nan'), z=10 ** 1000)
        entry['summary']['other_heroes'] = [dict(runtime_id=i, camp=2, visible=True, x=i, z=0) for i in range(100)]
        entry['summary']['structures'] = [dict(type='ACTOR_TOWER', camp=2, x=i, z=0, hp=100) for i in range(100)]
    mon.observe(game, context(), WAIT, policy(), .001)
    snap = read(mon.latest)['snapshot']
    assert len(snap['visible_enemies']) == 5 and len(snap['structures']) == 32
    assert 'x' not in snap['own'][0] and 'z' not in snap['own'][0]


def test_hok_missing_team_identity_does_not_collect_arbitrary_seat_views(tmp_path):
    mon, game = mm.MatchMonitor(tmp_path, context(), policy()), state()
    game.raw.pop('camp')
    mon.observe(game, context(), WAIT, policy(), .001)
    snapshot = read(mon.latest)['snapshot']
    assert snapshot['own'] == snapshot['visible_enemies'] == snapshot['structures'] == []


@pytest.mark.parametrize(('score', 'outcome'), [(1, 'won'), (-1, 'lost'), (0, 'drew')])
def test_hok_native_result_survives_full_timeline_without_prior_observation(tmp_path, score, outcome):
    bot, ctx = policy(), context()
    mon = mm.MatchMonitor(tmp_path, ctx, bot)
    terminal = state(result={'returns': {'mine': score}, 'termination_reason': 'step_limit',
                             'is_terminal': True, 'outcome': {'winner_camp': None, 'secret': 'TOKEN',
                             'score': {'1': {'enemy_structure_damage': 12000, 'kills': 9, 'secret': 'TOKEN'},
                                       '2': {'enemy_structure_damage': 13000, 'kills': 7}}}})
    terminal.raw = {}
    with patch.object(mm, 'LIMIT', 1):
        mon.finish(terminal, ctx, bot)
    row = read(mon.final)
    assert row['outcome'] == outcome and row['score'] == score
    assert row['hok_outcome']['score']['1'] == {'enemy_structure_damage': 12000, 'kills': 9}
    assert row['timeline_truncated'] is True and not mon.path.exists()
    assert 'TOKEN' not in mon.final.read_text()


@pytest.mark.parametrize('reason', ['start_failed', 'engine_failed', 'match_stalled', 'cancelled'])
def test_hok_no_result_termination_never_counts_as_loss(tmp_path, reason):
    mon = mm.MatchMonitor(tmp_path, context(), policy())
    mon.finish(state(result={'returns': {'mine': -1}, 'termination_reason': reason}), context(), policy())
    row = read(mon.final)
    assert row['outcome'] == 'no result' and row['server_failed'] and not row['review_needed']


def test_hok_winner_camp_and_plural_winners_are_authoritative(tmp_path):
    mon = mm.MatchMonitor(tmp_path, context(), policy())
    terminal = state(result={'returns': {'mine': 0}, 'termination_reason': 'crystal_destroyed',
                             'outcome': {'winner_camp': 2}})
    mon.finish(terminal, context(), policy())
    assert read(mon.final)['outcome'] == 'lost'
    terminal.final_result['winner_agent_ids'] = ['mine']
    with patch.object(mon, 'append', side_effect=OSError):
        mon.finish(terminal, context(), policy())
    assert read(mon.final)['outcome'] == 'won'
