"""The latest policy is selected at every deployed entry/fallback path."""
import json

import pytest

from altruagent.models import DecisionContext, GameState
from competition_agent import create_agent as create_competition
from redalert_bot.agent import create_agent
from redalert_bot.selfplay import make_policy
from redalert_bot.selftest import sample


def context(tournament=None):
    return DecisionContext('deployment', tournament, 'red_alert', 'own-seat', 0, {'rules': {}})


def test_standalone_factory_uses_latest_policy():
    assert create_agent().profile == 'eco_guard'


@pytest.mark.parametrize('tournament', [None, 'tournament-1'])
def test_testing_and_tournament_routes_use_latest_policy(tournament):
    bot, ctx = create_competition(), context(tournament)
    raw = sample()
    raw['session_id'] = ctx.session_id
    bot.choose_action(GameState.from_mcp_state(raw), ctx)
    policy = next(iter(bot._policies.values()))
    assert policy.profile == 'eco_guard'
    assert 'map_adaptation' in policy._memory(ctx)


@pytest.mark.parametrize('verified,tournament', [(False,None),(True,'tournament-1')])
def test_ineligible_experiment_uses_latest_not_old_baseline(verified,tournament):
    bot = make_policy({'verified_selfplay':verified},context(tournament),GameState.from_mcp_state(sample()))
    assert bot.profile == 'eco_guard'


@pytest.mark.parametrize('contents', [json.dumps({'enabled':False,'profiles':['eco_guard','balanced']}), 'invalid json'])
def test_disabled_or_failed_experiment_uses_latest(monkeypatch,tmp_path,contents):
    import redalert_bot.selfplay as experiment
    (tmp_path/'settings.json').write_text(contents)
    monkeypatch.setattr(experiment,'ROOT',tmp_path)
    bot = make_policy({'verified_selfplay':True,'match_id':'mine'},context(),GameState.from_mcp_state(sample()))
    assert bot.profile == 'eco_guard'
