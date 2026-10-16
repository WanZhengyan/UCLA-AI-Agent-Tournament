import json
from pathlib import Path

import pytest

from redalert_bot.review import main, summarize


def write(root, name, rows):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    return path


def monitor(kind='sample', second=0, sid='match-a', seat=0, score=None, **extra):
    row = dict(kind=kind, game='red_alert', session_id=sid, seat=seat,
               profile='eco_guard', strategy_version='v5', strategy_hash='abc',
               snapshot=dict(seconds=second, map='sidestep', max_minutes=10,
                             faction='allies', enemy_faction='soviets'))
    if kind == 'final':
        row['score'] = score
    row.update(extra)
    return row


def test_empty_history_is_unknown_not_zero_win_rate(tmp_path):
    report = summarize([tmp_path, tmp_path/'missing'])
    assert report['games'] == report['groups'] == report['per_map'] == []
    assert report['totals']['win_fraction'] is None
    assert report['totals']['completed_seat_results'] == 0
    assert report['input_diagnostics']['missing_roots'] == 1


def test_deduplicates_timeline_latest_final_and_repeated_roots(tmp_path):
    final = monitor('final', 10, score=1)
    timeline = write(tmp_path, 'a.jsonl', [monitor('start'), monitor(second=0), final])
    write(tmp_path, 'a-final.json', [final])
    write(tmp_path, 'a-latest.json', [monitor(second=0)])
    report = summarize([tmp_path, timeline, tmp_path])
    assert report['totals']['wins'] == 1
    assert len(report['games']) == 1
    assert report['games'][0]['sample_count'] == 2
    assert report['groups'][0]['enemy_faction'] == 'soviets'
    assert report['groups'][0]['max_minutes'] == 10


def test_sources_share_seat_identity_but_not_hash_algorithms(tmp_path):
    first = monitor(second=5)
    last = monitor('final', 10, score=0)
    write(tmp_path, 'monitor.jsonl', [first, last])
    entry = dict(session_id='match-a', match_id='platform-match', seat=0,
                 profile='eco_guard', run_id='v5', code_hash='different-hash-algorithm', map='sidestep', max_minutes=10)
    write(tmp_path, 'selfplay.jsonl', [dict(kind='start', **entry),
        dict(kind='sample', seconds=5, faction='allies', enemy_faction='soviets'),
        dict(kind='final', score=0, last_observation=last['snapshot'], **entry)])
    game = summarize([tmp_path])['games'][0]
    assert game['source_kinds'] == ['monitor', 'selfplay']
    assert game['strategy_hash'] == 'abc'
    assert not game['mixed_strategy_versions']
    assert game['sample_count'] == 2
    assert game['conflicting_sample_times'] == []


def test_selfplay_flat_samples_and_final_only_records(tmp_path):
    entry = dict(session_id='only-selfplay', match_id='m', seat=1, profile='balanced',
                 run_id='v3', code_hash='sourcehash', map='forest', max_minutes=20)
    write(tmp_path, 'selfplay.jsonl', [dict(kind='start', **entry),
        dict(kind='sample', seconds=5, faction='soviets', units={'harv': 4}, buildings={'proc': 2}),
        dict(kind='sample', seconds=10, faction='soviets'),
        dict(kind='final', score=.5, last_observation=None, **entry)])
    write(tmp_path, 'other-final.json', [monitor('final', score=1, sid='other', snapshot=None)])
    report = summarize([tmp_path])
    game = next(g for g in report['games'] if g['identity'] == 'only-selfplay')
    assert game['map'] == 'forest' and game['max_minutes'] == 20
    assert game['strategy_hash'] == 'sourcehash' and game['strategy_version'] == 'v3'
    assert game['first_observed_milestones']['four_harvesters'] == 5
    assert report['totals']['draws'] == 1 and report['totals']['wins'] == 1


def test_missing_fields_and_time_gaps_are_unknown(tmp_path):
    rows = []
    for second, econ in [(0, {'cash': 4000, 'power_provided': 0, 'power_drained': 100}),
                         (5, {}), (10, {'cash': 1000}), (100, {}), (105, {})]:
        row = monitor(second=second)
        row['snapshot']['economy'] = econ
        rows.append(row)
    write(tmp_path, 'a.jsonl', rows)
    game = summarize([tmp_path])['games'][0]
    assert game['covered_seconds'] == 15
    assert game['unobserved_seconds_within_span'] == 90
    assert game['largest_sample_gap_seconds'] == 90
    assert game['time_weighted_cash'] == 4000  # Cannot carry the t=10 value across the 90s gap.
    assert game['cash_known_seconds'] == 5
    low = game['diagnostics']['low_power']
    assert low['known_seconds'] == low['flagged_seconds'] == 5
    assert low['first_observed_at'] == low['last_observed_at'] == 0
    assert game['diagnostics']['no_harvesters_after_120']['known_seconds'] == 0
    assert game['diagnostics']['empty_production_with_factory']['fraction_of_known_time'] is None


def test_known_empty_counts_and_first_observed_milestones(tmp_path):
    rows = []
    for second, units, cash in [(120, {}, 3000), (125, {'harv': 4, '2tnk': 3}, 1000), (130, {}, 1000)]:
        row = monitor(second=second)
        row['snapshot'].update(units=units, buildings={'proc': 2, 'weap': 1}, production=[],
            economy={'cash': cash}, military={'kills_cost': 100, 'deaths_cost': 2201})
        rows.append(row)
    write(tmp_path, 'a.jsonl', rows)
    game = summarize([tmp_path])['games'][0]
    assert game['time_weighted_cash'] == 2000
    assert game['initial_unobserved_seconds'] == 120
    assert game['diagnostics']['no_harvesters_after_120']['flagged_seconds'] == 5
    assert game['diagnostics']['no_harvesters_after_120']['last_observed_at'] == 130
    assert game['diagnostics']['negative_trade_over_2000']['flagged_seconds'] == 10
    assert game['diagnostics']['empty_production_with_factory']['flagged_seconds'] == 10
    assert game['first_observed_milestones'] == {'second_refinery': 120, 'four_harvesters': 125,
                                              'first_tank': 125, 'three_tanks': 125}


@pytest.mark.parametrize('extra', [dict(outcome='no result'), dict(status='failed'),
    dict(result_status='failed'), dict(failure_reason='server_error'), dict(server_failed=True)])
def test_server_failures_with_zero_scores_do_not_become_losses(tmp_path, extra):
    write(tmp_path, 'a-final.json', [monitor('final', score=0, **extra)])
    report = summarize([tmp_path])
    assert report['totals']['losses'] == 0 and report['totals']['excluded_results'] == 1
    assert report['games'][0]['outcome'] == 'no_result'


@pytest.mark.parametrize('scores', [(0, 1), (0, .5), (.5, 1)])
def test_contradictory_final_sinks_are_quarantined(tmp_path, scores):
    write(tmp_path, 'a.jsonl', [monitor('final', score=scores[0])])
    write(tmp_path, 'a-final.json', [monitor('final', score=scores[1])])
    report = summarize([tmp_path])
    assert report['totals']['completed_seat_results'] == 0
    assert report['games'][0]['outcome'] == 'conflicting_results'


def test_unknown_final_does_not_override_confirmed_result(tmp_path):
    write(tmp_path, 'a.jsonl', [monitor('final', score=1)])
    write(tmp_path, 'a-final.json', [monitor('final', score=None)])
    assert summarize([tmp_path])['totals']['wins'] == 1


@pytest.mark.parametrize('score', [True, False, float('nan'), float('inf'), '1', -1, 2])
def test_invalid_scores_are_not_outcomes(tmp_path, score):
    write(tmp_path, 'a-final.json', [monitor('final', score=score)])
    assert summarize([tmp_path])['games'][0]['outcome'] == 'unknown'


def test_restarted_version_does_not_receive_old_result_attribution(tmp_path):
    write(tmp_path, 'a.jsonl', [monitor(second=0), monitor(second=5, strategy_hash='newhash'),
                               monitor('final', 10, score=1, strategy_hash='newhash')])
    game = summarize([tmp_path])['games'][0]
    assert game['mixed_strategy_versions']
    assert game['strategy_hash'] == game['strategy_version'] == 'mixed'
    assert game['outcome'] == 'won'


def test_conflicting_samples_are_not_used_for_time_weighted_diagnosis(tmp_path):
    first, conflict, last = monitor(second=0), monitor(second=5), monitor(second=10)
    conflict['snapshot']['economy'] = {'cash': 5000}
    alternate = monitor(second=5)
    alternate['snapshot']['economy'] = {'cash': 0}
    write(tmp_path, 'a.jsonl', [first, conflict, last])
    write(tmp_path, 'a-latest.json', [alternate])
    game = summarize([tmp_path])['games'][0]
    assert game['conflicting_sample_times'] == [5]
    assert game['covered_seconds'] == 0
    assert game['time_weighted_cash'] is None


def test_seats_maps_factions_and_durations_remain_separate(tmp_path):
    rows = [monitor('final', score=1), monitor('final', seat=1, score=0)]
    other = monitor('final', sid='match-b', score=.5)
    other['snapshot'].update(map='other', max_minutes=20, faction='soviets')
    rows.append(other)
    write(tmp_path, 'a.jsonl', rows)
    report = summarize([tmp_path])
    assert len(report['groups']) == 3
    assert len(report['per_map']) == 2
    assert report['totals']['seat_records'] == 3
    assert report['totals']['distinct_sessions'] == 2
    assert report['totals']['mean_score'] == .5
    assert report['games'][0]['seat'] != report['games'][1]['seat']


def test_malformed_tail_unrelated_files_and_secrets_are_not_exported(tmp_path):
    secret = 'NEVER_COPY_CREDENTIAL'
    row = monitor(second=5, token=secret)
    row['snapshot']['economy'] = {'access_token': secret, 'cash': 500}
    row['snapshot']['own_positions'] = [{'id': 2, 'token': secret}]
    path = write(tmp_path, 'a.jsonl', [row, monitor('final', 10, score=1)])
    with path.open('a') as stream:
        stream.write('{broken')
    write(tmp_path, 'pokemon.jsonl', [dict(row, game='pokemon_vgc_doubles_draft')])
    write(tmp_path, 'unrelated.json', [dict(api_key=secret)])
    report = summarize([tmp_path])
    assert secret not in json.dumps(report)
    assert report['totals']['wins'] == 1
    assert report['input_diagnostics']['malformed_records'] == 1


def test_cli_writes_private_report_and_does_not_modify_input(tmp_path, capsys):
    path = write(tmp_path/'logs', 'a-final.json', [monitor('final', score=1)])
    before = path.read_bytes()
    assert main(['--root', str(path.parent), '--output', str(tmp_path/'report')]) == 0
    output = tmp_path/'report'/'review.json'
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())['totals']['wins'] == 1
    assert path.read_bytes() == before
    assert json.loads(capsys.readouterr().out)['wins'] == 1


@pytest.mark.parametrize('gap', [0, -1, float('inf'), float('nan'), True])
def test_invalid_time_gap_rejected(gap):
    with pytest.raises(ValueError):
        summarize([], gap)


def test_competition_separation_and_timeline_truncation(tmp_path):
    write(tmp_path, 'testing-final.json', [monitor('final', score=1, competition='testing')])
    write(tmp_path, 'tournament-final.json', [monitor('final', sid='tournament-session', score=0,
                                                     competition='tournament', timeline_truncated=True)])
    report = summarize([tmp_path])
    assert {row['competition'] for row in report['groups']} == {'testing', 'tournament'}
    assert report['totals']['wins'] == report['totals']['losses'] == 1
    game = next(g for g in report['games'] if g['identity'] == 'tournament-session')
    assert game['timeline_truncated'] is True


def test_selfplay_competition_inferred_and_tesla_tank_milestones(tmp_path):
    entry = dict(session_id='selfplay', seat=0, profile='eco_guard', code_hash='hash')
    write(tmp_path, 'a.jsonl', [dict(kind='start', **entry),
        dict(kind='sample', seconds=5, units={'ttnk': 3}), dict(kind='final', score=1, **entry)])
    game = summarize([tmp_path])['games'][0]
    assert game['competition'] == 'testing'
    assert game['first_observed_milestones']['first_tank'] == 5
    assert game['first_observed_milestones']['three_tanks'] == 5


def test_partial_snapshot_fields_merge_without_false_conflict(tmp_path):
    one, two = monitor(second=5), monitor(second=5)
    one['snapshot']['economy'] = {'cash': 3000}
    two['snapshot']['economy'] = {'cash': 3000, 'power_drained': 20, 'power_provided': 0}
    write(tmp_path, 'a.jsonl', [one, monitor(second=10)])
    write(tmp_path, 'a-latest.json', [two])
    game = summarize([tmp_path])['games'][0]
    assert game['conflicting_sample_times'] == []
    assert game['diagnostics']['low_power']['flagged_seconds'] == 5


@pytest.mark.parametrize('score', [True, False, 2, -1, '1', float('nan')])
def test_outcome_label_cannot_rescue_explicit_invalid_score(tmp_path, score):
    write(tmp_path, 'a-final.json', [monitor('final', score=score, outcome='won')])
    assert summarize([tmp_path])['totals']['completed_seat_results'] == 0


def test_legacy_named_outcome_without_score_still_usable(tmp_path):
    write(tmp_path, 'a-final.json', [monitor('final', outcome='won')])
    assert summarize([tmp_path])['totals']['wins'] == 1


def test_non_scalar_kind_and_outcome_do_not_abort_import(tmp_path):
    write(tmp_path, 'a.jsonl', [{'kind': []}, monitor('final', score=1, outcome={})])
    assert summarize([tmp_path])['totals']['wins'] == 1
