"""Compare our frozen economy policy in the deterministic production fixture.

This is a budget experiment, not OpenRA self-play. The baseline must be a
trusted revision of THIS repository; never load external contestant code.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redalert_bot import economy
from redalert_bot.strategy import TANKS
from test_redalert_policy import mock_production_progression


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', args.baseline + '^{commit}'], cwd=ROOT, text=True).strip()
    baseline = subprocess.check_output(
        ['git', 'show', revision + ':redalert_bot/economy.py'], cwd=ROOT)
    module = types.ModuleType('redalert_bot._frozen_economy')
    module.__package__ = 'redalert_bot'
    exec(compile(baseline, revision + ':redalert_bot/economy.py', 'exec'), module.__dict__)
    candidate = economy.plan
    cases = []
    for faction in ('allies', 'soviets'):
        for income in (4, 8, 16):
            result = dict(faction=faction, income_per_harvester_second=income)
            for name, plan in [('baseline', module.plan), ('candidate', candidate)]:
                with patch.object(economy, 'plan', plan):
                    run = mock_production_progression(faction, 1200, income)
                units = Counter(run['units'])
                result[name] = dict(
                    income=run['income'], spending=run['spending'], cash=run['cash'],
                    tanks=sum(units[t] for t in TANKS), harvesters=units['harv'],
                    buildings=dict(Counter(run['buildings'])), pending=run['pending'],
                    milestones=run['milestones'], timeline=run['timeline'])
                # Independent conservation check for the fixture's money accounting.
                assert abs(5000 + run['income'] - run['spending'] - run['cash']) <= .02
            result['delta'] = {key: round(result['candidate'][key] - result['baseline'][key], 2)
                               for key in ('income', 'spending', 'cash', 'tanks', 'harvesters')}
            cases.append(result)
    digest = lambda b: hashlib.sha256(b).hexdigest()
    report = dict(
        strategy='economy_growth_v13', baseline_revision=revision,
        baseline_economy_sha256=digest(baseline),
        candidate_economy_sha256=digest((ROOT / 'redalert_bot/economy.py').read_bytes()),
        harness_sha256=digest((ROOT / 'tests/test_redalert_policy.py').read_bytes()),
        comparison_sha256=digest(Path(__file__).read_bytes()),
        method='Our baseline economy.plan versus candidate economy.plan; all other code fixed.',
        assumptions=dict(duration_seconds=1200, starting_cash=5000,
                         per_harvester_income=[4, 8, 16], progressive_payment=True,
                         map='No topology; stationary actors at home; independent category queues'),
        limitations=[
            'Development fixtures informed threshold selection; not held-out evaluation.',
            'No actual replay of our agent, enemy economy, combat, casualties or match result.',
            'No travel, unloading congestion, ore exhaustion, power slowdown or factory-speed model.',
            'Actor positions never move; safety gates require separate scenario tests.',
            'Income is a fixed modeling assumption, not measured map income or guaranteed payback.',
            'No win-rate improvement or promise of surviving 20 minutes can be inferred.'
        ], cases=cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps([dict(faction=c['faction'], income=c['income_per_harvester_second'],
                           delta=c['delta'], milestones={k:c[k]['milestones']
                           for k in ('baseline','candidate')}) for c in cases], indent=2))


if __name__ == '__main__':
    main()
