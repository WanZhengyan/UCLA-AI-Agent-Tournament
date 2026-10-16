"""Offline, seat-local review of monitor/self-play telemetry; never a live policy input.

These are sampled observations, not engine replays or causal explanations.
Missing terminal results and gaps remain unknown. Reports are private by default.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from .strategy import TANKS

ROOT = Path(__file__).resolve().parents[1] / 'validation'
GROUP_FIELDS = ('map', 'strategy_version', 'strategy_hash', 'profile', 'seat',
                'faction', 'enemy_faction', 'max_minutes', 'competition')
META_FIELDS = ('session_id', 'match_id', 'run_id', 'seat', 'profile',
               'strategy_version', 'strategy_hash', 'code_hash', 'map', 'max_minutes', 'competition')
METRICS = ('low_power', 'no_harvesters_after_120', 'negative_trade_over_2000',
           'cash_over_2500', 'empty_production_with_factory')
MAX_FILE_BYTES = 32 * 1024 * 1024


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def scalar(value):
    return value if value is None or type(value) in (int, bool) or (
        type(value) is float and math.isfinite(value)) or (
        isinstance(value, str) and len(value) <= 256) else None


def mapping(value):
    return value if isinstance(value, dict) else {}


def compact(snapshot):
    """Keep analysis fields only; never copy contexts, actors or arbitrary payloads."""
    s = mapping(snapshot)
    if not number(s.get('seconds')) or s['seconds'] < 0:
        return None
    result = {'seconds': s['seconds']}
    for key in ('map', 'max_minutes', 'remaining', 'faction', 'enemy_faction'):
        if key in s and scalar(s[key]) is not None:
            result[key] = scalar(s[key])
    for key in ('economy', 'military', 'units', 'buildings'):
        if isinstance(s.get(key), dict):
            allowed = {'economy': ('cash', 'ore', 'power_provided', 'power_drained'),
                       'military': ('kills_cost', 'deaths_cost', 'army_value', 'assets_value'),
                       'units': ('harv', *sorted(TANKS)),
                       'buildings': ('proc', 'weap')}[key]
            result[key] = {k: s[key][k] for k in allowed if number(s[key].get(k))}
            # Unit/building maps are complete count dictionaries: absent type means zero.
            if key in ('units', 'buildings'):
                for name in allowed:
                    if name not in s[key]:
                        result[key][name] = 0
    if isinstance(s.get('production'), list):
        result['production_empty'] = not s['production']
    return result


def terminal(row):
    status = scalar(row.get('outcome'))
    if (status == 'no result' or row.get('status') == 'failed'
            or row.get('result_status') == 'failed' or row.get('failure_reason')
            or row.get('server_failed') is True):
        return 'failed'
    score = row.get('score')
    by_name = {'won': 1, 'lost': 0, 'drew': .5}.get(status)
    if number(score) and score in (0, .5, 1):
        return 'conflict' if by_name is not None and by_name != score else score
    if score is not None:
        return None  # An explicit invalid score cannot be rescued by a display label.
    return by_name if by_name is not None else None


def records(path, diagnostics):
    """Stream bounded telemetry files. Truncated lines do not erase earlier evidence."""
    try:
        with path.open() as stream:
            if path.suffix != '.jsonl':
                if path.stat().st_size > MAX_FILE_BYTES:
                    diagnostics['oversized_files'] += 1
                    return
                rows = [json.load(stream)]
            else:
                rows = stream
            consumed = 0
            for raw in rows:
                if isinstance(raw, str):
                    consumed += len(raw.encode())
                    if consumed > MAX_FILE_BYTES:
                        diagnostics['oversized_files'] += 1
                        break
                    try:
                        raw = json.loads(raw)
                    except ValueError:
                        diagnostics['malformed_records'] += 1
                        continue
                if isinstance(raw, dict) and raw.get('kind') in ('start', 'sample', 'final'):
                    yield raw
    except (OSError, ValueError, UnicodeError):
        diagnostics['unreadable_files'] += 1


def ingest(roots):
    games, diagnostics, seen_paths = {}, Counter(), set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            diagnostics['missing_roots'] += 1
            continue
        paths = [root] if root.is_file() else sorted(root.rglob('*'))
        for path in paths:
            if path.suffix not in {'.json', '.jsonl'} or not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            context = {}
            for row in records(path, diagnostics):
                if row.get('kind') == 'start':
                    context = {}
                context.update({k: scalar(row[k]) for k in META_FIELDS if k in row})
                if 'game' in row:
                    context['game'] = row['game']
                if context.get('game') not in (None, 'red_alert'):
                    continue
                if context.get('game') is None and not context.get('code_hash'):
                    continue  # Unrelated JSON and unidentifiable orphan samples.
                if context.get('game') is None:
                    context['competition'] = 'testing'
                identity = context.get('session_id') or context.get('match_id')
                if not identity:
                    diagnostics['unidentified_records'] += 1
                    continue
                seat = context.get('seat')
                # Never merge unknown seats: file stems identify paired timeline/final sinks.
                seat_key = seat if seat is not None else path.stem.removesuffix('-final').removesuffix('-latest')
                key = (str(identity), str(seat_key))
                game = games.setdefault(key, {'identity': str(identity), 'seat': seat,
                    'meta': {}, 'samples': {}, 'sample_conflicts': set(), 'finals': set(),
                    'terminal_records': 0, 'exact_final': False, 'source_kinds': set(),
                    'timeline_truncated': False})
                game['timeline_truncated'] |= row.get('timeline_truncated') is True
                game['source_kinds'].add('monitor' if context.get('game') else 'selfplay')
                for name in META_FIELDS:
                    value = context.get(name)
                    if value is not None:
                        game['meta'].setdefault(name, set()).add(value)
                snapshot = row.get('snapshot') if 'snapshot' in row else (
                    row.get('last_observation') if row.get('kind') == 'final' else row)
                s = compact(snapshot)
                if s is not None:
                    for name in ('map', 'max_minutes', 'faction', 'enemy_faction'):
                        if name in s:
                            game['meta'].setdefault(name, set()).add(s[name])
                    # A selfplay sample may lack map/duration, supplied by its start entry.
                    second = s['seconds']
                    if second not in game['samples']:
                        game['samples'][second] = s
                    else:
                        old = game['samples'][second]
                        for name in old.keys() & s.keys():
                            if isinstance(old[name], dict) and isinstance(s[name], dict):
                                if any(old[name][k] != s[name][k] for k in old[name].keys() & s[name].keys()):
                                    game['sample_conflicts'].add(second)
                                old[name].update({k:v for k,v in s[name].items() if k not in old[name]})
                            elif old[name] != s[name]:
                                game['sample_conflicts'].add(second)
                        old.update({k: v for k, v in s.items() if k not in old})
                if row['kind'] == 'final':
                    game['terminal_records'] += 1
                    verdict = terminal(row)
                    if verdict is not None:
                        game['finals'].add(verdict)
                    game['exact_final'] |= row.get('exact_final_observation') is True
    return games, diagnostics


def flags(sample):
    economy, military = sample.get('economy', {}), sample.get('military', {})
    units, buildings = sample.get('units', {}), sample.get('buildings', {})
    def compare(values, names, predicate):
        return predicate(*(values[n] for n in names)) if all(n in values for n in names) else None
    return dict(
        low_power=compare(economy, ('power_provided', 'power_drained'), lambda p, d: d > p),
        no_harvesters_after_120=(units['harv'] == 0 and sample['seconds'] >= 120
                                if 'harv' in units else None),
        negative_trade_over_2000=compare(military, ('kills_cost', 'deaths_cost'), lambda k, d: d-k > 2000),
        cash_over_2500=compare(economy, ('cash',), lambda c: c > 2500),
        empty_production_with_factory=(buildings['weap'] > 0 and sample['production_empty']
            if 'weap' in buildings and 'production_empty' in sample else None))


def timeline(game, max_gap):
    samples = [game['samples'][t] for t in sorted(game['samples'])]
    metrics = {name: dict(known_seconds=0., flagged_seconds=0.,
                         first_observed_at=None, last_observed_at=None) for name in METRICS}
    coverage, cash_integral, cash_seconds = 0., 0., 0.
    milestones = {}
    for index, sample in enumerate(samples):
        second = sample['seconds']
        if second in game['sample_conflicts']:
            continue
        observed = flags(sample)
        for name, value in observed.items():
            if value:
                metric = metrics[name]
                if metric['first_observed_at'] is None:
                    metric['first_observed_at'] = second
                metric['last_observed_at'] = second
        units, buildings = sample.get('units', {}), sample.get('buildings', {})
        tank_names = tuple(sorted(TANKS))
        tanks = sum(units[name] for name in tank_names) if all(name in units for name in tank_names) else None
        for name, reached in (('second_refinery', buildings.get('proc', 0) >= 2),
                              ('four_harvesters', units.get('harv', 0) >= 4),
                              ('first_tank', tanks is not None and tanks >= 1),
                              ('three_tanks', tanks is not None and tanks >= 3)):
            if reached:
                milestones.setdefault(name, second)
        if index+1 == len(samples):
            continue
        following = samples[index+1]['seconds']
        delta = following-second
        if delta > max_gap or following in game['sample_conflicts']:
            continue
        coverage += delta
        for name, value in observed.items():
            if value is not None:
                metrics[name]['known_seconds'] += delta
                metrics[name]['flagged_seconds'] += delta if value else 0
        cash = sample.get('economy', {}).get('cash')
        if number(cash):
            cash_integral += cash*delta
            cash_seconds += delta
    for metric in metrics.values():
        known = metric['known_seconds']
        metric['fraction_of_known_time'] = metric['flagged_seconds']/known if known else None
    first, last = (samples[0]['seconds'], samples[-1]['seconds']) if samples else (None, None)
    span = last-first if samples else 0
    return dict(sample_count=len(samples), conflicting_sample_times=sorted(game['sample_conflicts']),
                first_sample_seconds=first, last_sample_seconds=last,
                sampled_span_seconds=span, covered_seconds=coverage,
                unobserved_seconds_within_span=span-coverage,
                coverage_of_sampled_span=coverage/span if span else None,
                initial_unobserved_seconds=first,
                coverage_through_last_sample=coverage/last if last else None,
                largest_sample_gap_seconds=max((b['seconds']-a['seconds'] for a,b in zip(samples, samples[1:])), default=None),
                time_weighted_cash=cash_integral/cash_seconds if cash_seconds else None,
                cash_known_seconds=cash_seconds, first_observed_milestones=milestones, diagnostics=metrics)


def one(values, default=None):
    return next(iter(values)) if len(values) == 1 else ('mixed' if values else default)


def analyze(game, max_gap):
    meta = game['meta']
    row = {name: one(meta.get(name, set())) for name in GROUP_FIELDS}
    row['strategy_hash'] = one(meta.get('strategy_hash') or meta.get('code_hash', set()))
    row['strategy_version'] = one(meta.get('strategy_version') or meta.get('run_id', set()), 'unknown')
    versions = ('strategy_hash', 'code_hash', 'strategy_version', 'profile')
    mixed = any(len(meta.get(name, set())) > 1 for name in versions)
    if mixed:
        row['strategy_version'] = row['strategy_hash'] = 'mixed'
    finals = game['finals']
    if 'conflict' in finals or len(finals) > 1:
        outcome, score = 'conflicting_results', None
    elif finals == {'failed'}:
        outcome, score = 'no_result', None
    elif finals:
        score = next(iter(finals))
        outcome = {0: 'lost', .5: 'drew', 1: 'won'}[score]
    else:
        outcome, score = 'unknown', None
    row.update(identity=game['identity'], outcome=outcome, score=score,
               mixed_strategy_versions=mixed, source_kinds=sorted(game['source_kinds']),
               terminal_record_present=bool(game['terminal_records']),
               exact_final_observation=game['exact_final'],
               timeline_truncated=game['timeline_truncated'], **timeline(game, max_gap))
    return row


def tally(rows):
    counts = Counter(row['outcome'] for row in rows)
    known = sum(counts[name] for name in ('won', 'lost', 'drew'))
    return dict(seat_records=len(rows), distinct_sessions=len({r['identity'] for r in rows}),
                completed_seat_results=known, wins=counts['won'], losses=counts['lost'], draws=counts['drew'],
                excluded_results=len(rows)-known, exclusion_reasons={k:v for k,v in counts.items()
                    if k not in ('won', 'lost', 'drew')},
                win_fraction=counts['won']/known if known else None,
                mean_score=(counts['won']+.5*counts['drew'])/known if known else None)


def summarize(roots=None, max_gap=10.):
    if not number(max_gap) or max_gap <= 0:
        raise ValueError('max_gap must be a positive finite number')
    games, diagnostics = ingest(roots if roots is not None else [ROOT/'match_monitor', ROOT/'redalert_selfplay'])
    rows = [analyze(game, max_gap) for _, game in sorted(games.items())]
    grouped, by_map = {}, {}
    for row in rows:
        grouped.setdefault(tuple(row[name] for name in GROUP_FIELDS), []).append(row)
        by_map.setdefault(row['map'], []).append(row)
    return dict(schema=1, coverage='Only imported seat-local telemetry; no historical recordings are bundled.',
        interpretation=[
            'Descriptive results, not evidence that one strategy improves win rate; maps, opponents and seeds differ.',
            'Two recorded seats in one match are correlated; seat_results are not independent matches.',
            'Diagnostics use left-sample values only across adjacent, nonconflicting samples within max_gap_seconds.',
            'Missing fields and larger gaps remain unknown; milestones are first observations, not exact event times.',
            'Unknown, server-failed and contradictory terminal results are excluded from result denominators.',
            'Reports are offline only and are never read automatically by a live agent.'],
        max_gap_seconds=max_gap, input_diagnostics=dict(diagnostics), totals=tally(rows),
        per_map=[dict(map=key, **tally(value)) for key,value in sorted(by_map.items(), key=lambda x:str(x[0]))],
        groups=[dict(zip(GROUP_FIELDS, key), **tally(value)) for key,value in sorted(grouped.items(), key=lambda x:str(x[0]))],
        games=rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='append', type=Path, help='Telemetry file/directory; repeat to import several.')
    parser.add_argument('--output', type=Path, default=ROOT/'review', help='Private report directory or .json file.')
    parser.add_argument('--max-gap', type=float, default=10., help='Largest interval eligible for sampled diagnostics (seconds).')
    args = parser.parse_args(argv)
    report = summarize(args.root, args.max_gap)
    output = args.output if args.output.suffix == '.json' else args.output/'review.json'
    from match_monitor import atomic_json
    atomic_json(output, report)
    print(json.dumps(dict(output=str(output), **report['totals'], input_diagnostics=report['input_diagnostics']), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
