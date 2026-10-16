"""Platform-shaped HoK 5v5 safety and tactical regression scenarios.

These fixtures exercise the public macro contract, not a licensed gamecore or
competitive win rate.  Every action offered here is an explicit per-seat entry.
"""

from copy import deepcopy

import pytest

from altruagent import WAIT
from altruagent.models import DecisionContext, GameState
from hok_platform.agent import HokPlatformAgent, create_agent


GAME = "honor_of_kings_5v5"


def hero(runtime_id, camp, hp=1000, x=0, z=0, **extra):
    return {"runtime_id": runtime_id, "camp": camp, "hp": hp,
            "max_hp": 1000, "x": x, "z": z, "level": 5,
            "ep": 100, "revive_time": 0, **extra}


def action(seat, macro, label=None):
    return {"action_id": f"s{seat}:{macro}", "label": label or macro,
            "input": {"action": {"seat": seat, "macro": macro}}}


def sample(*, camp=1, seats=None, hp=1000, version=10, session="hok-fixture",
           phase="moving", mode="realtime", macros=None, enemies=(),
           friends=(), structures=(), standing=None, pending=None):
    seats = list(seats if seats is not None else ([0] if camp == 1 else [5]))
    macros = list(macros or ["macro_advance", "macro_retreat"])
    summaries = {}
    for seat in seats:
        summaries[str(seat)] = {"summary": {
            "my_hero": hero(100 + seat, camp, hp=hp),
            "other_heroes": deepcopy(list(enemies) + list(friends)),
            "structures": deepcopy(list(structures)), "frame_no": 3 * version,
        }}
    return {"session_id": session, "game_type": GAME, "phase": phase,
            "status": "active", "is_terminal": False,
            "is_current_actor": True, "state_version": version,
            "camp": camp, "seats": seats,
            "observation": {"seats": summaries},
            "pacing": {"mode": mode, "step_interval_s": 0.2},
            "max_steps": 3000, "seconds_left": 400,
            "simultaneous": {"your_pending_seats": seats if pending is None else pending,
                             "standing_orders": standing or {}},
            "legal_actions": {"actions": [action(s, m) for s in seats for m in macros]}}


def choose(bot, raw, *, account="owner", position=0):
    ctx = DecisionContext(raw["session_id"], None, GAME, account, position)
    return bot.choose_action(GameState.from_mcp_state(raw), ctx)


def mine(raw, seat=None):
    seat = raw["seats"][0] if seat is None else seat
    return raw["observation"]["seats"][str(seat)]["summary"]["my_hero"]


def tick(raw, *, steps=1, hp=None):
    raw["state_version"] += steps
    for view in raw["observation"]["seats"].values():
        view["summary"]["frame_no"] = 3 * raw["state_version"]
    if hp is not None:
        mine(raw)["hp"] = hp


def acknowledge(raw, selected):
    assert isinstance(selected, dict)
    raw["simultaneous"]["standing_orders"][str(selected["seat"])] = selected["macro"]


def test_factory_returns_independent_platform_agents():
    first, second = create_agent(), create_agent()
    assert isinstance(first, HokPlatformAgent)
    assert isinstance(second, HokPlatformAgent)
    assert first is not second


@pytest.mark.parametrize("camp,seat", [(1, 0), (2, 5)])
def test_both_camps_send_only_explicit_owned_macro(camp, seat):
    result = choose(create_agent(), sample(camp=camp))
    assert result == {"seat": seat, "macro": "macro_advance"}


@pytest.mark.parametrize("phase", ["waiting_for_players", "queued", "starting", "finished", "failed", "unknown_phase"])
def test_nonplaying_phases_wait_even_with_stale_legal_actions(phase):
    assert choose(create_agent(), sample(phase=phase)) is WAIT


def test_terminal_state_waits_even_when_phase_is_stale():
    raw = sample()
    raw["is_terminal"] = True
    assert choose(create_agent(), raw) is WAIT


def test_missing_observation_does_not_invent_a_retreat_order():
    raw = sample()
    raw["observation"] = {}
    assert choose(create_agent(), raw) is WAIT


def test_missing_ownership_does_not_guess_team_from_legal_actions():
    raw = sample()
    raw.pop("seats")
    with pytest.raises(ValueError, match="owned"):
        choose(create_agent(), raw)


def test_empty_legal_actions_does_not_construct_unlisted_macro():
    raw = sample()
    raw["legal_actions"]["actions"] = []
    assert choose(create_agent(), raw) is WAIT


def test_cannot_control_enemy_seat_even_when_offered_as_legal():
    raw = sample(seats=[0, 5])
    raw["observation"]["seats"]["5"]["summary"]["my_hero"]["camp"] = 2
    results = []
    bot = create_agent()
    for _ in range(3):
        selected = choose(bot, raw)
        if selected is not WAIT:
            results.append(selected)
            acknowledge(raw, selected)
        tick(raw)
    assert results and all(result["seat"] == 0 for result in results)


def test_action_id_seat_does_not_authorize_another_input_seat():
    raw = sample()
    raw["legal_actions"]["actions"] = [action(0, "macro_advance")]
    raw["legal_actions"]["actions"][0]["input"]["action"]["seat"] = 5
    assert choose(create_agent(), raw) is WAIT


def test_raw_button_with_required_dimensions_is_not_guessed():
    raw = sample()
    raw["legal_actions"]["actions"] = [{
        "action_id": "s0:button_2", "label": "move",
        "input": {"action": {"seat": 0, "which_button": 2},
                  "legal_move_x": [0, 15], "legal_move_z": [0, 15]},
    }]
    assert choose(create_agent(), raw) is WAIT


def test_healthy_hero_does_not_retreat_from_tower_distance_alone():
    tower = hero(200, 2, x=1000, type="tower")
    raw = sample(structures=[tower], macros=["macro_attack", "macro_advance", "macro_retreat"])
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_server_legal_attack_remains_valid_without_parseable_target_distance():
    raw = sample(macros=["macro_attack", "macro_advance", "macro_retreat"])
    raw["legal_actions"]["actions"][0]["label"] = "Basic attack nearest target"
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_low_health_retreats_before_legal_attacks_or_skills():
    raw = sample(hp=180, enemies=[hero(200, 2, hp=150, x=1000, visible=True)],
                 macros=["macro_attack", "macro_skill3", "macro_retreat", "macro_advance"])
    assert choose(create_agent(), raw)["macro"] == "macro_retreat"


def test_recovery_hysteresis_does_not_oscillate_around_initial_threshold():
    raw, bot = sample(hp=200), create_agent()
    assert choose(bot, raw)["macro"] == "macro_retreat"
    tick(raw, hp=500)
    assert choose(bot, raw)["macro"] == "macro_retreat"
    tick(raw, hp=900)
    assert choose(bot, raw)["macro"] == "macro_advance"


def test_respawn_clears_old_recovery_state():
    raw, bot = sample(hp=150), create_agent()
    assert choose(bot, raw)["macro"] == "macro_retreat"
    tick(raw, hp=0)
    mine(raw)["revive_time"] = 6
    assert choose(bot, raw) is WAIT
    tick(raw, steps=35, hp=500)
    mine(raw)["revive_time"] = 0
    assert choose(bot, raw)["macro"] == "macro_advance"


@pytest.mark.parametrize("kind", ["zero_hp", "revive_timer"])
def test_dead_hero_never_issues_combat_macro(kind):
    raw = sample(macros=["macro_attack", "macro_skill3", "macro_advance"])
    if kind == "zero_hp":
        mine(raw)["hp"] = 0
    else:
        mine(raw)["revive_time"] = 3
    assert choose(create_agent(), raw) is WAIT


def test_sudden_damage_causes_escape_without_needing_visible_attacker():
    raw, bot = sample(), create_agent()
    choose(bot, raw)
    tick(raw, steps=5, hp=600)
    assert choose(bot, raw)["macro"] == "macro_retreat"


def test_long_gap_damage_is_not_treated_as_current_burst():
    raw, bot = sample(), create_agent()
    choose(bot, raw)
    tick(raw, steps=100, hp=600)
    assert choose(bot, raw)["macro"] == "macro_advance"


def test_small_health_change_does_not_cause_passive_overretreat():
    raw, bot = sample(hp=650), create_agent()
    choose(bot, raw)
    tick(raw, hp=620)
    assert choose(bot, raw)["macro"] == "macro_advance"


def test_visible_outnumbering_overrides_chasing_low_health_bait():
    enemies = [hero(200, 2, hp=100, x=1000, visible=True),
               hero(201, 2, x=1500, visible=True), hero(202, 2, x=2000, visible=True)]
    raw = sample(hp=450, enemies=enemies,
                 macros=["macro_attack", "macro_skill3", "macro_retreat", "macro_advance"])
    assert choose(create_agent(), raw)["macro"] == "macro_retreat"


def test_healthy_local_group_does_not_retreat_only_because_enemies_exist():
    friends = [hero(110 + i, 1, x=500 * i, visible=True) for i in range(4)]
    enemies = [hero(200 + i, 2, x=1000 + 500 * i, visible=True) for i in range(2)]
    raw = sample(hp=850, friends=friends, enemies=enemies,
                 macros=["macro_attack", "macro_retreat", "macro_advance"])
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_local_team_support_changes_an_outnumbered_trade():
    enemies = [hero(200 + i, 2, hp=900, x=1000 + 500 * i, visible=True) for i in range(3)]
    isolated = sample(hp=600, enemies=enemies,
                      macros=["macro_attack", "macro_retreat", "macro_advance"])
    supported = sample(seats=[0, 1, 2, 3, 4], hp=600, enemies=enemies,
                       macros=["macro_attack", "macro_retreat", "macro_advance"])
    assert choose(create_agent(), isolated)["macro"] == "macro_retreat"
    assert choose(create_agent(), supported)["macro"] == "macro_attack"


def test_hidden_enemy_coordinates_cannot_change_the_decision():
    hidden = [hero(200 + i, 2, visible=False) for i in range(5)]
    raw = sample(hp=500, enemies=hidden,
                 macros=["macro_advance", "macro_retreat", "macro_skill3"])
    without_positions = deepcopy(raw)
    for enemy in without_positions["observation"]["seats"]["0"]["summary"]["other_heroes"]:
        enemy.pop("x")
        enemy.pop("z")
    assert choose(create_agent(), raw) == choose(create_agent(), without_positions)
    assert choose(create_agent(), raw)["macro"] == "macro_advance"


def test_skill_is_not_cast_without_visible_hero_even_when_listed():
    raw = sample(macros=["macro_skill1", "macro_skill2", "macro_skill3", "macro_advance"])
    assert choose(create_agent(), raw)["macro"] == "macro_advance"


def skill_state(*, enemy_hp=1000, own_hp=1000, count=1, skill="macro_skill3", distance=4000):
    enemies = [hero(200 + i, 2, hp=enemy_hp, x=distance, z=100 * i, visible=True)
               for i in range(count)]
    raw = sample(hp=own_hp, enemies=enemies,
                 macros=[skill, "macro_attack", "macro_advance", "macro_retreat"])
    raw["legal_actions"]["actions"][0]["label"] = (
        f"[seat 0] Cast skill {skill[-1]} toward enemy hero (nearest: enemy hero, {distance} away)"
    )
    return raw


@pytest.mark.parametrize("skill", ["macro_skill1", "macro_skill2"])
def test_legal_close_range_skill_is_usable(skill):
    assert choose(create_agent(), skill_state(skill=skill))["macro"] == skill


def test_ultimate_is_reserved_against_healthy_single_enemy():
    assert choose(create_agent(), skill_state())["macro"] == "macro_attack"


@pytest.mark.parametrize("kwargs", [{"enemy_hp": 200}, {"own_hp": 500}, {"count": 2}])
def test_ultimate_has_finishing_survival_and_group_opportunities(kwargs):
    assert choose(create_agent(), skill_state(**kwargs))["macro"] == "macro_skill3"


def test_skill_does_not_fire_at_a_distant_target_despite_being_listed():
    assert choose(create_agent(), skill_state(enemy_hp=200, distance=30000))["macro"] == "macro_attack"


def test_skill_label_without_confirmed_distance_does_not_guess_range():
    raw = skill_state(enemy_hp=200)
    raw["legal_actions"]["actions"][0]["label"] = "Cast skill 3 toward enemy hero"
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_skill_targeting_building_is_not_assumed_to_damage_it():
    raw = skill_state(enemy_hp=200)
    raw["legal_actions"]["actions"][0]["label"] = "Cast skill 3 toward enemy tower (4000 away)"
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_legal_tower_pressure_takes_priority_over_optional_hero_skill():
    raw = skill_state(enemy_hp=200)
    for offered in raw["legal_actions"]["actions"]:
        if offered["input"]["action"]["macro"] == "macro_attack":
            offered["label"] = "[seat 0] Attack nearest target (nearest: enemy tower, 4123 away)"
    assert choose(create_agent(), raw)["macro"] == "macro_attack"


def test_skill_standing_order_is_replaced_when_skill_is_on_cooldown():
    raw, bot = skill_state(enemy_hp=200), create_agent()
    selected = choose(bot, raw)
    assert selected["macro"] == "macro_skill3"
    acknowledge(raw, selected)
    tick(raw)
    raw["legal_actions"]["actions"] = [a for a in raw["legal_actions"]["actions"]
                                         if a["input"]["action"]["macro"] != "macro_skill3"]
    assert choose(bot, raw)["macro"] == "macro_attack"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "1000"])
def test_malformed_health_does_not_produce_fictional_combat_state(bad):
    raw = sample()
    mine(raw)["hp"] = bad
    assert choose(create_agent(), raw) is WAIT


def test_realtime_matching_standing_order_needs_no_duplicate_submission():
    raw = sample(standing={"0": "macro_advance"})
    assert choose(create_agent(), raw) is WAIT


def test_lockstep_pending_hero_gets_fresh_action_despite_matching_order():
    raw = sample(mode="lockstep", standing={"0": "macro_advance"}, pending=[0])
    assert choose(create_agent(), raw) == {"seat": 0, "macro": "macro_advance"}


def test_lockstep_does_not_act_for_nonpending_seat():
    raw = sample(mode="lockstep", seats=[0, 1], pending=[1])
    assert choose(create_agent(), raw)["seat"] == 1


def test_unchanged_first_seat_does_not_hide_another_heroes_new_order():
    raw = sample(seats=[0, 1, 2, 3, 4], standing={"0": "macro_advance"})
    result = choose(create_agent(), raw)
    assert result["seat"] in {1, 2, 3, 4}


def test_realtime_drains_all_five_heroes_then_waits():
    raw, bot = sample(seats=[0, 1, 2, 3, 4]), create_agent()
    chosen = []
    for _ in range(5):
        selected = choose(bot, raw)
        chosen.append(selected["seat"])
        acknowledge(raw, selected)
    assert set(chosen) == {0, 1, 2, 3, 4}
    assert choose(bot, raw) is WAIT


def test_newly_dangerous_later_seat_gets_priority():
    raw = sample(seats=[0, 1, 2, 3, 4])
    mine(raw, 4)["hp"] = 150
    result = choose(create_agent(), raw)
    assert result == {"seat": 4, "macro": "macro_retreat"}


def test_fresh_versions_with_busy_first_seat_do_not_starve_team():
    raw, bot = sample(seats=[0, 1, 2, 3, 4]), create_agent()
    chosen = []
    for index in range(5):
        raw["simultaneous"]["standing_orders"]["0"] = "macro_attack" if index % 2 else "macro_retreat"
        selected = choose(bot, raw)
        chosen.append(selected["seat"])
        acknowledge(raw, selected)
        tick(raw)
    assert set(chosen) == {0, 1, 2, 3, 4}


@pytest.mark.parametrize("change", ["session", "account", "camp"])
def test_recovery_memory_does_not_leak_across_matches_or_teams(change):
    bot, old = create_agent(), sample(hp=100)
    assert choose(bot, old)["macro"] == "macro_retreat"
    current = sample(hp=500, session="different" if change == "session" else "hok-fixture",
                     camp=2 if change == "camp" else 1)
    result = choose(bot, current, account="other-owner" if change == "account" else "owner")
    assert result["macro"] == "macro_advance"


def test_decision_does_not_mutate_server_state():
    raw = sample(seats=[0, 1, 2, 3, 4], hp=200)
    before = deepcopy(raw)
    choose(create_agent(), raw)
    assert raw == before


def test_rejected_macro_uses_different_legal_action_at_same_version():
    raw = sample(macros=["macro_attack", "macro_advance", "macro_retreat"])
    bot = create_agent()
    assert choose(bot, raw)["macro"] == "macro_attack"
    bot.on_action_result({"error": "INVALID_ACTION", "detail": "target disappeared"})
    assert choose(bot, raw)["macro"] == "macro_advance"


def test_rejected_macro_is_available_again_after_fresh_server_version():
    raw = sample(macros=["macro_attack", "macro_advance"])
    bot = create_agent()
    assert choose(bot, raw)["macro"] == "macro_attack"
    bot.on_action_result({"error": "INVALID_ACTION"})
    assert choose(bot, raw)["macro"] == "macro_advance"
    tick(raw)
    assert choose(bot, raw)["macro"] == "macro_attack"


@pytest.mark.parametrize("mode", ["realtime", "lockstep"])
def test_rejected_raw_fallback_cannot_loop_at_same_version(mode):
    raw = sample(mode=mode, standing={"0": "macro_skill3"})
    raw["legal_actions"]["actions"] = [{
        "action_id": "s0:button_0", "label": "No action",
        "input": {"action": {"seat": 0, "which_button": 0}},
    }]
    bot = create_agent()
    expected = {"seat": 0, "which_button": 0}
    assert choose(bot, raw) == expected
    bot.on_action_result({"error": "INVALID_ACTION", "detail": "stale raw action"})
    for _ in range(3):
        if mode == "realtime":
            assert choose(bot, raw) is WAIT
        else:
            with pytest.raises(ValueError, match="no complete listed action"):
                choose(bot, raw)
    tick(raw)
    assert choose(bot, raw) == expected


@pytest.mark.parametrize("field", ["other_heroes", "structures"])
@pytest.mark.parametrize("malformed", [None, "not a record list", {"hp": 100}, [None, 123, "bad"]])
def test_optional_record_lists_tolerate_nullable_or_malformed_payload(field, malformed):
    raw = sample()
    raw["observation"]["seats"]["0"]["summary"][field] = malformed
    assert choose(create_agent(), raw)["macro"] == "macro_advance"


def test_version_rewind_clears_recovery_and_rejection_history():
    raw, bot = sample(hp=100, version=200), create_agent()
    assert choose(bot, raw)["macro"] == "macro_retreat"
    bot.on_action_result({"error": "INVALID_ACTION"})
    restarted = sample(hp=500, version=1)
    assert choose(bot, restarted)["macro"] == "macro_advance"
    mine(restarted)["hp"] = 100
    tick(restarted)
    assert choose(bot, restarted)["macro"] == "macro_retreat"


@pytest.mark.parametrize("domain_location", ["payload", "input", "entry"])
def test_raw_fallback_keeps_all_explicit_legal_field_domains(domain_location):
    raw = sample(mode="lockstep")
    entry = {"action_id": "s0:button_2", "label": "Move",
             "input": {"action": {"seat": 0, "which_button": 2}}}
    target = {"payload": entry["input"]["action"],
              "input": entry["input"], "entry": entry}[domain_location]
    target.update({"legal_move_x": [3, 7], "legal_move_z": [9, 12]})
    raw["legal_actions"]["actions"] = [entry]
    selected = choose(create_agent(), raw)
    assert selected["seat"] == 0 and selected["which_button"] == 2
    assert selected["move_x"] in [3, 7] and selected["move_z"] in [9, 12]
    assert not any(key.startswith("legal_") for key in selected)


def test_contradictory_raw_domains_are_rejected_instead_of_guessed():
    raw = sample(mode="lockstep")
    raw["legal_actions"]["actions"] = [{
        "action_id": "s0:button_2", "label": "Move",
        "input": {"action": {"seat": 0, "which_button": 2, "legal_move_x": [3]},
                  "legal_move_x": [7]},
    }]
    with pytest.raises(ValueError, match="no complete listed action"):
        choose(create_agent(), raw)


def objective_state(*, camp=1, enemy_x=6500, hp=1000, target='hero'):
    sign = 1 if camp == 1 else -1
    seat = 0 if camp == 1 else 5
    tower = hero(300, 3-camp, x=20000*sign, type='ACTOR_TOWER')
    raw = sample(camp=camp, hp=hp, structures=[tower],
                 enemies=[hero(200, 3-camp, x=enemy_x*sign, visible=True)],
                 macros=['macro_attack', 'macro_skill1', 'macro_advance', 'macro_retreat'])
    raw['legal_actions']['actions'][0]['label'] = f'Attack nearest target (nearest: enemy {target}, 4000 away)'
    raw['legal_actions']['actions'][1]['label'] = 'Cast skill 1 toward enemy hero (nearest: enemy hero, 6500 away)'
    return raw


@pytest.mark.parametrize('camp', [1, 2])
@pytest.mark.parametrize('enemy_x', [6500, -4000])
def test_distant_or_rear_hero_does_not_distract_from_building(camp, enemy_x):
    raw = objective_state(camp=camp, enemy_x=enemy_x)
    assert choose(create_agent(), raw)['macro'] == 'macro_advance'


@pytest.mark.parametrize('camp', [1, 2])
def test_short_skirmish_then_committed_push_for_healthy_team(camp):
    raw, bot = objective_state(camp=camp, enemy_x=3000), create_agent()
    assert choose(bot, raw)['macro'] == 'macro_skill1'
    tick(raw, steps=13)
    assert choose(bot, raw)['macro'] == 'macro_advance'
    tick(raw, steps=5)
    assert choose(bot, raw)['macro'] == 'macro_advance'


def test_push_commit_never_overrides_low_health_escape():
    raw, bot = objective_state(enemy_x=3000), create_agent()
    choose(bot, raw)
    tick(raw, steps=13)
    assert choose(bot, raw)['macro'] == 'macro_advance'
    tick(raw, hp=180)
    assert choose(bot, raw)['macro'] == 'macro_retreat'


def test_new_legal_tower_attack_interrupts_advance_commit():
    raw, bot = objective_state(enemy_x=3000), create_agent()
    choose(bot, raw)
    tick(raw, steps=13)
    assert choose(bot, raw)['macro'] == 'macro_advance'
    raw['legal_actions']['actions'][0]['label'] = 'Attack enemy tower (3000 away)'
    tick(raw)
    assert choose(bot, raw)['macro'] == 'macro_attack'


def test_structure_attack_survives_minor_damage_without_panic_retreat():
    raw, bot = objective_state(hp=700, target='tower'), create_agent()
    assert choose(bot, raw)['macro'] == 'macro_attack'
    tick(raw, steps=5, hp=540)
    assert choose(bot, raw)['macro'] == 'macro_attack'


def test_major_burst_still_interrupts_siege():
    raw, bot = objective_state(target='tower'), create_agent()
    choose(bot, raw)
    tick(raw, steps=5, hp=500)
    assert choose(bot, raw)['macro'] == 'macro_retreat'


@pytest.mark.parametrize('camp', [1, 2])
def test_finishing_crystal_overrides_low_health_recovery(camp):
    raw = objective_state(camp=camp, hp=200, target='crystal')
    structure = raw['observation']['seats'][str(raw['seats'][0])]['summary']['structures'][0]
    structure.update(type='ACTOR_CRYSTAL', hp=100)
    assert choose(create_agent(), raw)['macro'] == 'macro_attack'


def test_healthy_crystal_is_not_a_suicide_finish():
    raw = objective_state(hp=200, target='crystal')
    raw['observation']['seats']['0']['summary']['structures'][0]['type'] = 'ACTOR_CRYSTAL'
    assert choose(create_agent(), raw)['macro'] == 'macro_retreat'


@pytest.mark.parametrize('camp', [1, 2])
@pytest.mark.parametrize('can_attack', [False, True])
def test_threatened_home_crystal_interrupts_fountain_recovery(camp, can_attack):
    seat = 0 if camp == 1 else 5
    home = hero(300, camp, hp=300, x=15000, type='ACTOR_CRYSTAL')
    enemy = hero(200, 3-camp, x=15000, visible=True)
    macros = ['macro_advance', 'macro_retreat'] + (['macro_attack'] if can_attack else [])
    raw = sample(camp=camp, hp=250, structures=[home], enemies=[enemy], macros=macros)
    assert choose(create_agent(), raw) == {'seat': seat, 'macro': 'macro_attack' if can_attack else 'macro_advance'}


def test_hidden_enemy_does_not_trigger_home_defense():
    raw = sample(hp=250, structures=[hero(300, 1, hp=300, type='ACTOR_CRYSTAL')],
                 enemies=[hero(200, 2, visible=False)],
                 macros=['macro_attack', 'macro_retreat', 'macro_advance'])
    assert choose(create_agent(), raw)['macro'] == 'macro_retreat'


def test_frontline_hero_returns_toward_own_threatened_crystal_not_enemy_base():
    raw = sample(hp=600, structures=[hero(300, 1, hp=300, x=-15000, type='ACTOR_CRYSTAL'),
                                   hero(301, 1, x=-30000, type='ACTOR_TOWER_SPRING')],
                 enemies=[hero(200, 2, x=-15000, visible=True)])
    bot = create_agent()
    assert choose(bot, raw)['macro'] == 'macro_retreat'
    assert bot.last_diagnostics['reason'] == 'home_defense'


def test_fountain_recovery_rejoins_at_42_percent_not_68():
    raw, bot = sample(hp=200, structures=[hero(300, 1, type='ACTOR_TOWER_SPRING')]), create_agent()
    assert choose(bot, raw)['macro'] == 'macro_retreat'
    tick(raw, steps=30, hp=430)
    assert choose(bot, raw)['macro'] == 'macro_advance'


def test_outside_fountain_recovery_does_not_end_at_42_percent():
    raw, bot = sample(hp=200, structures=[hero(300, 1, x=20000, type='ACTOR_TOWER_SPRING')]), create_agent()
    choose(bot, raw)
    tick(raw, steps=30, hp=430)
    assert choose(bot, raw)['macro'] == 'macro_retreat'
    tick(raw, steps=30, hp=560)
    assert choose(bot, raw)['macro'] == 'macro_advance'


def test_destroyed_building_does_not_invent_a_push_objective():
    raw = objective_state()
    raw['observation']['seats']['0']['summary']['structures'][0]['hp'] = 0
    assert choose(create_agent(), raw)['macro'] == 'macro_skill1'


def test_minion_wave_is_cleared_when_it_is_the_legal_attack_target():
    raw = objective_state(target='minion')
    raw['legal_actions']['actions'] = [a for a in raw['legal_actions']['actions']
                                     if a['input']['action']['macro'] != 'macro_skill1']
    assert choose(create_agent(), raw)['macro'] == 'macro_attack'
