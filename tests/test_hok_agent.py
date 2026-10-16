"""Contract and tactical regressions for the standalone Tencent HoK1v1 policy."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from hok_bot.agent import HonorOfKingsAgent, LegalActions, ProtocolError
from hok_bot.__main__ import main, smoke_state


def actor(runtime_id, camp, x=0, z=0, hp=1000, max_hp=1000, **extra):
    return dict(runtime_id=runtime_id, camp=camp, location=dict(x=x, z=z),
                hp=hp, max_hp=max_hp, **extra)


def state(camp=1, hp=3000, heroes=(), soldiers=(), organs=(), buttons=None):
    s = smoke_state()
    s["req_pb"]["hero_list"] = [actor(10, camp, hp=hp, max_hp=3000, config_id=133, phy_atk=200, atk_range=6000)] + list(heroes)
    s["req_pb"]["soldier_list"] = list(soldiers)
    s["req_pb"]["organ_list"] = list(organs)
    if buttons is not None:
        s["legal_action"][:12] = [int(i in buttons) for i in range(12)]
    return s


def target_mask(s, button, slots):
    s["legal_action"][76 + button * 8:84 + button * 8] = [int(i in slots) for i in range(8)]


def objects(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: objects(v) for k, v in value.items()})
    if isinstance(value, list):
        return [objects(v) for v in value]
    return value


def test_sdk_shaped_objects_and_last_hit():
    s = state(soldiers=[actor(40, 2, 2000, 2000, hp=100)])
    s["req_pb"] = objects(s["req_pb"])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert (action[0], action[5]) == (3, 3)
    assert agent.last_reason == "last_hit"


def test_soldier_target_slots_follow_alive_runtime_order():
    s = state(soldiers=[actor(90, 2, 2000, 0, hp=50), actor(20, 2, 2000, 0, hp=700),
                       actor(10, 2, 2000, 0, hp=0), actor(11, 1, hp=100)])
    action = HonorOfKingsAgent().act(s)
    assert (action[0], action[5]) == (3, 4)


def test_illegal_chosen_target_is_not_remapped_to_hero():
    s = state(soldiers=[actor(40, 2, 2000, 0, hp=50)], buttons=[1, 2, 3])
    target_mask(s, 3, [0, 1])
    action = HonorOfKingsAgent().act(s)
    assert action[0] != 3


def test_conditional_target_mask_uses_selected_button():
    s = state(buttons=[3, 4])
    target_mask(s, 3, [7])
    target_mask(s, 4, [1])
    legal = LegalActions(s)
    assert legal.build(3)[5] == 7
    assert legal.build(4)[5] == 1
    assert legal.validates(legal.build(3))
    assert not legal.validates((3, 8, 8, 8, 8, 1))


@pytest.mark.parametrize("camp,home_sign", [(1, -1), (2, 1)])
def test_retreat_camp_orientation(camp, home_sign):
    enemy = actor(11, 3-camp, 1000 * -home_sign, 1000 * -home_sign, config_id=112)
    s = state(camp=camp, hp=500, heroes=[enemy], buttons=[1, 2, 3])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert action[0] == 2
    assert action[1] < 8 and action[2] < 8
    assert agent.last_reason == "retreat_low_health"


def test_tower_without_wave_retreats_instead_of_attacking():
    s = state(organs=[actor(60, 2, 4500, 0, attack_range=8000, type=21)])
    agent = HonorOfKingsAgent()
    assert agent.act(s)[0] == 2
    assert agent.last_reason == "wait_for_wave"


def test_aggro_overrides_cover_and_objective_damage():
    s = state(organs=[actor(60, 2, 4500, 0, attack_range=8000, attack_target=10, type=21)],
              soldiers=[actor(20, 1, 4000, 0)])
    agent = HonorOfKingsAgent()
    assert agent.act(s)[0] == 2
    assert agent.last_reason == "leave_tower_aggro"


def test_safe_objective_push_uses_basic_attack():
    s = state(organs=[actor(60, 2, 4500, 0, attack_range=8000, type=21)],
              soldiers=[actor(20, 1, 4000, 0)])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert (action[0], action[5]) == (3, 7)
    assert agent.last_reason == "push_with_wave"


def test_finish_objective_before_chasing_hero():
    s = state(organs=[actor(60, 2, 4500, 0, hp=90, attack_range=8000, type=21)],
              soldiers=[actor(20, 1, 4000, 0)],
              heroes=[actor(11, 2, 4500, -3000, hp=50, config_id=112)])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert (action[0], action[5]) == (3, 7)
    assert agent.last_reason == "finish_objective"


@pytest.mark.parametrize("camp,flags", [(1, [False, True]), (2, [True, False])])
def test_hidden_hero_is_not_chased(camp, flags):
    s = state(camp=camp, heroes=[actor(11, 3-camp, 3000, 0, hp=10, config_id=112, camp_visible=flags)])
    agent = HonorOfKingsAgent()
    assert agent.act(s)[0] == 2
    assert agent.last_reason == "advance_lane"


def test_heal_before_recall_and_preserve_channel():
    agent = HonorOfKingsAgent()
    s = state(hp=500)
    assert agent.act(s)[0] == 7
    s["legal_action"][7] = 0
    assert agent.act(s)[0] == 9
    s["req_pb"]["frame_no"] += 3
    assert agent.act(s)[0] in (0, 1)
    assert agent.last_reason == "recall_channel"


def test_recall_is_cancelled_by_new_threat():
    agent = HonorOfKingsAgent()
    s = state(hp=500, buttons=[1, 2, 9])
    assert agent.act(s)[0] == 9
    s["req_pb"]["frame_no"] += 3
    s["req_pb"]["hero_list"].append(actor(11, 2, 4000, 0, config_id=112, camp_visible=[True, True]))
    assert agent.act(s)[0] == 2
    s["req_pb"]["hero_list"].pop()
    s["req_pb"]["frame_no"] += 3
    # The old channel was canceled, so start a fresh recall instead of waiting.
    assert agent.act(s)[0] == 9
    assert agent.last_reason == "safe_recall"


@pytest.mark.parametrize("interruption", ["damage", "soldier"])
def test_recall_cancels_on_damage_or_incoming_wave(interruption):
    agent = HonorOfKingsAgent()
    s = state(hp=500, buttons=[1, 2, 9])
    assert agent.act(s)[0] == 9
    s["req_pb"]["frame_no"] += 3
    if interruption == "damage":
        s["req_pb"]["hero_list"][0]["hp"] = 450
    else:
        s["req_pb"]["soldier_list"] = [actor(20, 2, 3000, 0, camp_visible=[True, True])]
    assert agent.act(s)[0] == 2
    assert agent.recall_until == -1


def test_dead_actor_waits():
    agent = HonorOfKingsAgent()
    assert agent.act(state(hp=0))[0] in (0, 1)
    assert agent.last_reason == "dead_wait"


def test_low_health_uses_hysteresis_until_recovered():
    agent = HonorOfKingsAgent()
    s = state(hp=500, buttons=[1, 2, 3])
    assert agent.act(s)[0] == 2
    s["req_pb"]["hero_list"][0]["hp"] = 1600
    assert agent.act(s)[0] == 2
    assert agent.last_reason == "retreat_low_health"
    s["req_pb"]["hero_list"][0]["hp"] = 2900
    agent.act(s)
    assert not agent.recovering


def test_camp2_advances_in_canonical_positive_direction():
    s = state(camp=2)
    action = HonorOfKingsAgent().act(s)
    assert action[0] == 2 and action[1] > 8 and action[2] > 8


def test_unknown_hero_does_not_cast_unverified_skill_combo():
    s = state(heroes=[actor(11, 2, 3000, 0, hp=100, config_id=112)])
    s["req_pb"]["hero_list"][0]["config_id"] = 999
    assert HonorOfKingsAgent().act(s)[0] == 3


@pytest.mark.parametrize("camp", [1, 2])
@pytest.mark.parametrize("minion_hp", [100, 1000])
def test_unfavorable_enemy_pressure_overrides_last_hit_and_farm(camp, minion_hp):
    enemy = actor(11, 3-camp, 2000, 0, config_id=112, atk_range=6000,
                  camp_visible=[True, True])
    s = state(camp=camp, hp=1800, heroes=[enemy],
              soldiers=[actor(40, 3-camp, 3000, 0, hp=minion_hp)], buttons=[1, 2, 3])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert action[0] == 2
    assert LegalActions(s).validates(action)
    assert agent.last_reason == "kite_unfavorable_trade"


@pytest.mark.parametrize("friend_position,friend_hp", [((-25000, -25000), 1000), ((1000, 0), 100)])
def test_distant_or_dying_allied_minion_does_not_suppress_kiting(friend_position, friend_hp):
    enemy = actor(11, 2, 2000, 0, config_id=112, atk_range=6000, camp_visible=[True, True])
    s = state(hp=1800, heroes=[enemy],
              soldiers=[actor(20, 1, *friend_position, hp=friend_hp)], buttons=[1, 2, 3])
    agent = HonorOfKingsAgent()
    assert agent.act(s)[0] == 2
    assert agent.last_reason == "kite_unfavorable_trade"


def test_healthy_local_wave_preserves_farm_under_enemy_pressure():
    enemy = actor(11, 2, 2000, 0, config_id=112, atk_range=6000, camp_visible=[True, True])
    s = state(hp=1800, heroes=[enemy], soldiers=[actor(20, 1, 1000, 0), actor(40, 2, 3000, 0)],
              buttons=[1, 2, 3])
    agent = HonorOfKingsAgent()
    action = agent.act(s)
    assert (action[0], action[5]) == (3, 3)
    assert agent.last_reason == "clear_wave"


@pytest.mark.parametrize("bad", [[1] * 84, [1] * 171, [float("nan")] * 172, [0.5] * 172])
def test_rejects_incompatible_masks(bad):
    s = state()
    s["legal_action"] = bad
    with pytest.raises(ProtocolError):
        HonorOfKingsAgent().act(s)


def test_does_not_mutate_input():
    s = smoke_state()
    before = deepcopy(s)
    HonorOfKingsAgent().act(s)
    assert s == before


def test_smoke_is_explicitly_synthetic(capsys):
    assert main(["--smoke"]) == 0
    assert '"engine_tested": false' in capsys.readouterr().out


@pytest.mark.parametrize("reset_fails", [False, True])
def test_real_runner_follows_official_reset_step_contract(monkeypatch, capsys, reset_fails):
    import hok_bot.__main__ as runner
    import sys
    calls = []
    class Env:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))
        def action_space(self):
            return [12, 16, 16, 16, 16, 8]
        def reset(self, camp, use_common_ai, eval):
            calls.append(("reset", camp, use_common_ai, eval))
            if reset_fails:
                raise RuntimeError("Gamecore is offline")
            return None, None, [False, False], [smoke_state(), None]
        def step(self, actions):
            assert LegalActions(smoke_state()).validates(actions[0])
            assert actions[1] == (0,) * 6
            return None, None, [True, False], [smoke_state(), None]
        def close_game(self):
            calls.append(("close",))
    modules = {
        "hok": SimpleNamespace(), "hok.hok1v1": SimpleNamespace(HoK1v1=Env),
        "hok.common": SimpleNamespace(),
        "hok.common.gamecore_client": SimpleNamespace(GamecoreClient=lambda **kw: kw),
        "hok.hok1v1.env1v1": SimpleNamespace(interface_default_config="sdk-config"),
        "hok.hok1v1.hero_config": SimpleNamespace(get_default_hero_config=lambda: {}),
        "hok.hok1v1.lib": SimpleNamespace(),
        "hok.hok1v1.lib.interface": SimpleNamespace(Interface=lambda: SimpleNamespace(Init=lambda x: None)),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    modules["hok"].hok1v1 = modules["hok.hok1v1"]
    modules["hok.hok1v1"].lib = modules["hok.hok1v1.lib"]
    modules["hok.hok1v1.lib"].interface = modules["hok.hok1v1.lib.interface"]
    monkeypatch.setattr(runner.sys, "version_info", (3, 8))
    if reset_fails:
        with pytest.raises(SystemExit) as error:
            main([])
        assert error.value.code == 1
        assert all(call[0] != "close" for call in calls)
        return
    assert main([]) == 0
    assert calls[-1] == ("close",)
    assert calls[1][2] == [False, True]
    assert '"result": "engine_terminated"' in capsys.readouterr().out
