"""Contract/recovery tests, not a simulator or a measurement of win rate."""
from copy import deepcopy

import pytest

from altruagent import WAIT, WithReasoning
from altruagent.models import DecisionContext, GameState
from redalert_bot.agent import create_agent


FIELDS = {
    "move": {"cmd", "units", "to", "queued"},
    "attack_move": {"cmd", "units", "to", "queued"},
    "attack": {"cmd", "units", "target", "to", "queued"},
    "stop": {"cmd", "units"}, "deploy": {"cmd", "units"},
    "unload": {"cmd", "units"},
    "guard": {"cmd", "units", "target", "queued"},
    "enter_transport": {"cmd", "units", "target", "queued"},
    "harvest": {"cmd", "units", "to", "queued"},
    "set_stance": {"cmd", "units", "stance"},
    "build": {"cmd", "item"}, "train": {"cmd", "item", "count"},
    "place": {"cmd", "item", "at"}, "cancel": {"cmd", "item"},
    "sell": {"cmd", "building"}, "set_primary": {"cmd", "building"},
    "repair": {"cmd", "building", "on"},
    "power_toggle": {"cmd", "building", "on"},
    "rally": {"cmd", "building", "to"},
}


def actor(id, type, x=16, y=16, **kw):
    return dict(id=id, type=type, x=x, y=y, hp=100, idle=True, **kw)


def fixture(*, seconds=0, faction="allies", session="contract"):
    return {
        "session_id": session, "game_type": "red_alert", "phase": "playing",
        "is_current_actor": True, "is_terminal": False,
        "state_version": int(seconds * 25), "pacing": {"mode": "realtime"},
        "limits": {"max_orders_per_batch": 20, "max_units_per_order": 50,
                   "max_train_count": 10, "min_batch_interval_s": 0.2},
        "time": {"game_seconds": seconds, "remaining_seconds": 1200-seconds},
        "map": {"id": "fixture", "width": 104, "height": 104,
                "bounds": [4, 4, 96, 96]},
        "observation": {
            "tick": int(seconds*25), "faction": faction, "enemy_faction": "soviets",
            "economy": {"cash": 5000, "ore": 0, "power_provided": 0,
                        "power_drained": 0, "resource_capacity": 2000, "harvesters": 0},
            "military": {"kills_cost": 0, "deaths_cost": 0, "assets_value": 2500,
                         "army_value": 0},
            "units": [actor(1, "mcv")], "buildings": [], "production": [],
            "available_production": [], "visible_enemies": [],
            "visible_enemy_buildings": [], "base_center": [16, 16], "events": [],
        },
        "legal_actions": {"deploy": [1], "build": [], "train": [], "place": [],
                          "repair": [], "combat_units": [], "idle_units": [1],
                          "harvesters": [], "production_buildings": [],
                          "enemy_base": [82, 82], "attack_now": None},
    }


def context(raw, config=None):
    return DecisionContext(raw["session_id"], None, "red_alert", "fixture-agent",
                           seat_position=0, game_config=config)


def decide(agent, raw, config=None):
    result = agent.choose_action(GameState.from_mcp_state(deepcopy(raw)), context(raw, config))
    if isinstance(result, WithReasoning):
        result = result.action
    if result is WAIT:
        return []
    assert isinstance(result, dict) and result["type"] == "orders"
    orders = result["orders"]
    assert orders
    validate_batch(orders, raw)
    return orders


def validate_batch(orders, raw):
    """Independent oracle for documented wire limits and visible actor use."""
    limits, obs = raw["limits"], raw["observation"]
    assert len(orders) <= min(20, limits["max_orders_per_batch"])
    own = {a["id"] for a in obs["units"] if not a.get("wreck") and not a["type"].endswith("husk") and a["hp"] > 0}
    buildings = {a["id"] for a in obs["buildings"] if a["hp"] > 0}
    enemies = {a["id"] for a in obs["visible_enemies"]+obs["visible_enemy_buildings"] if not a.get("wreck") and not a["type"].endswith("husk") and a["hp"] > 0}
    commands = 0
    for order in orders:
        cmd = order["cmd"]
        assert cmd in FIELDS
        assert set(order) <= FIELDS[cmd]
        if "units" in order:
            ids = order["units"]
            assert 1 <= len(ids) <= min(50, limits["max_units_per_order"])
            assert len(set(ids)) == len(ids)
            accepted = own | buildings if cmd in ("attack", "stop", "guard", "set_stance") else own
            assert set(ids) <= accepted
        if "building" in order:
            assert order["building"] in buildings
        if cmd in ("build", "train"):
            assert order["item"] in obs["available_production"]
        if cmd == "train":
            assert 1 <= order.get("count", 1) <= min(10, limits["max_train_count"])
        if cmd == "place":
            assert order["item"] in raw["legal_actions"]["place"] or any(
                p["item"] == order["item"] and p.get("ready") for p in obs["production"])
        if cmd == "attack" and "target" in order:
            assert order["target"] in enemies
        if cmd in ("guard", "enter_transport"):
            assert order["target"] in own | buildings
        for field in ("to", "at"):
            if field in order:
                x, y = order[field]
                left, top, width, height = raw["map"]["bounds"]
                assert isinstance(x, int) and isinstance(y, int)
                assert left <= x < left+width and top <= y < top+height
        commands += len(order["units"]) if "units" in order else order.get("count", 1) if cmd == "train" else 1
    assert commands <= 200


@pytest.mark.parametrize("phase", ["queued", "starting", "waiting_for_agents", "finished"])
def test_no_orders_before_or_after_play(phase):
    raw = fixture()
    raw["phase"] = phase
    raw["is_current_actor"] = False
    raw["is_terminal"] = phase == "finished"
    raw["observation"] = None
    assert decide(create_agent(), raw) == []


def test_deploy_is_sent_once_while_verdict_is_pending():
    raw, agent = fixture(), create_agent()
    first = decide(agent, raw)
    assert any(o["cmd"] == "deploy" and o["units"] == [1] for o in first)
    agent.on_action_result({"accepted": True, "batch": 1, "pending": True,
                           "results": [{"index": 0, "cmd": "deploy", "status": "pending"}]}, context(raw))
    raw["time"]["game_seconds"] = 0.2
    raw["state_version"] = 5
    raw["last_orders"] = {"batch": 1, "pending": True, "results": []}
    assert not any(o["cmd"] == "deploy" for o in decide(agent, raw))


def test_changed_actor_id_after_deploy_builds_power():
    raw, agent = fixture(), create_agent()
    decide(agent, raw)
    raw["state_version"] = 50
    raw["time"]["game_seconds"] = 2
    obs = raw["observation"]
    obs["units"] = []
    obs["buildings"] = [actor(302, "fact")]
    obs["available_production"] = ["powr"]
    raw["legal_actions"].update(deploy=[], build=["powr"], idle_units=[])
    orders = decide(agent, raw)
    assert any(o["cmd"] == "build" and o["item"] == "powr" for o in orders)


def power_fixture():
    raw = fixture()
    raw["observation"].update(units=[], buildings=[actor(302, "fact")],
                              available_production=["powr"])
    raw["legal_actions"].update(deploy=[], build=["powr"], idle_units=[])
    return raw


def at(raw, seconds):
    raw["time"]["game_seconds"] = seconds
    raw["state_version"] = raw["observation"]["tick"] = round(seconds * 25)
    return raw


def test_failed_transport_build_retries_on_fresh_view():
    raw, agent = power_fixture(), create_agent()
    first = decide(agent, raw)
    assert first == [{"cmd": "build", "item": "powr"}]
    agent.on_action_result({"error": "RUNTIME_TEMPORARILY_UNAVAILABLE", "detail": "Nothing submitted"}, context(raw))
    assert decide(agent, at(raw, .4)) == first


def test_rejected_order_backs_off_then_retries_instead_of_stalling():
    raw, agent = power_fixture(), create_agent()
    first = decide(agent, raw)
    agent.on_action_result({"error": "INVALID_ACTION", "detail": "[0] build: not_ready (queue full)"}, context(raw))
    assert decide(agent, at(raw, .4)) == []
    assert decide(agent, at(raw, 3.0)) == first


def test_lost_verdict_in_later_state_unlocks_production_retry():
    raw, agent = power_fixture(), create_agent()
    first = decide(agent, raw)
    agent.on_action_result({"accepted": True, "batch": 7, "results": [
        {"index": 0, "cmd": "build", "status": "pending"}]}, context(raw))
    raw["last_orders"] = {"batch": 7, "state_version": 0, "pending": False,
        "results": [{"index": 0, "cmd": "build", "status": "lost", "reason": "not_applied"}]}
    assert decide(agent, at(raw, 1.0)) == []
    assert decide(agent, at(raw, 1.4)) == first


def test_lost_movement_does_not_leave_false_combat_history():
    raw, agent = fixture(seconds=200), create_agent()
    obs = raw["observation"]
    obs.update(units=[actor(100+i, "e1") for i in range(13)],
               buildings=[actor(302, "fact")])
    obs["economy"]["cash"] = 0
    raw["legal_actions"].update(deploy=[], idle_units=[a["id"] for a in obs["units"]])
    first = decide(agent, raw)
    sent = {u for o in first if o["cmd"] in ("move", "attack_move") for u in o["units"]}
    assert sent
    agent.on_action_result({"accepted": True, "batch": 1, "results": [
        {"index": i, "cmd": o["cmd"], "status": "lost", "reason": "not_applied"}
        for i, o in enumerate(first)]}, context(raw))
    again = decide(agent, at(raw, 200.4))
    resent = {u for o in again if o["cmd"] in ("move", "attack_move") for u in o["units"]}
    assert sent <= resent


@pytest.mark.parametrize("size", [1, 11, 71, 240])
def test_large_army_and_wrecks_stay_inside_wire_limits(size):
    raw = fixture(seconds=400)
    obs = raw["observation"]
    obs["units"] = [actor(1000+i, "e1", 20+i%5, 20+i%7) for i in range(size)]
    obs["units"] += [actor(900, "harv"), actor(901, "mcv"), actor(902, "3tnkhusk", wreck=True)]
    obs["visible_enemies"] = [actor(950, "3tnkhusk", 25, 25, wreck=True)]
    obs["visible_enemy_buildings"] = [actor(990, "proc", 80, 80)]
    obs["buildings"] = [actor(303, "fact"), actor(304, "powr")]
    obs["economy"].update(cash=0, power_provided=100)
    obs["military"]["army_value"] = size * 100
    raw["legal_actions"].update(deploy=[901], idle_units=[a["id"] for a in obs["units"]])
    orders = decide(create_agent(), raw)
    for order in orders:
        if order["cmd"] in ("attack", "attack_move"):
            assert not ({900, 901, 902} & set(order["units"]))


def test_lower_server_caps_are_respected():
    raw = fixture(seconds=400)
    raw["limits"].update(max_orders_per_batch=3, max_units_per_order=7, max_train_count=2)
    obs = raw["observation"]
    obs["units"] = [actor(100+i, "e1") for i in range(50)]
    obs["buildings"] = [actor(2, "fact"), actor(3, "powr"), actor(4, "tent"), actor(5, "proc")]
    obs["available_production"] = ["powr", "tent", "proc", "weap", "e1", "e3"]
    obs["economy"].update(power_provided=100, power_drained=50, harvesters=1)
    obs["military"]["army_value"] = 5000
    raw["legal_actions"].update(deploy=[], idle_units=[a["id"] for a in obs["units"]],
                                build=["powr", "tent", "proc", "weap"], train=["e1", "e3"])
    assert decide(create_agent(), raw)


def mock_production_progression(faction, end_seconds, income_per_miner=8):
    """Advance production/resources under scarcity; this is not an RTS battle."""
    from redalert_bot.common import DEFAULT_COSTS, View

    duration = {"powr": 7.2, "apwr": 12, "tent": 12, "barr": 12,
                "proc": 33.6, "weap": 48, "fix": 28.8, "dome": 24,
                "e1": 2.4, "e3": 7.2, "harv": 26.4, "1tnk": 16.8,
                "2tnk": 20.4, "3tnk": 27.6, "apc": 20.4}
    raw, agent = fixture(faction=faction), create_agent()
    obs, hints = raw["observation"], raw["legal_actions"]
    cash, next_id, batch, trained = 5000., 10, 0, []
    pending = []

    def add(type, building=False):
        nonlocal next_id
        item = actor(next_id, type)
        next_id += 1
        obs["buildings" if building else "units"].append(item)

    for seconds in range(end_seconds + 1):
        types = {a["type"] for a in obs["buildings"]}
        harvesters = sum(a["type"] == "harv" for a in obs["units"])
        cash += income_per_miner * harvesters
        # Each category progresses independently; purchases are paid gradually,
        # as in the documented server, with no free completion when cash is low.
        handled = set()
        for row in list(pending):
            if row["queue"] in handled:
                continue
            handled.add(row["queue"])
            if row["ready"]:
                continue
            expense = DEFAULT_COSTS[row["item"]] / duration[row["item"]]
            fraction = min(1., row["remaining_s"], cash / expense)
            cash -= expense * fraction
            row["remaining_s"] = max(0., row["remaining_s"] - fraction)
            row["progress"] = 1. - row["remaining_s"] / duration[row["item"]]
            if row["remaining_s"] < 1e-6:
                if row["queue"] in ("Building", "Defense"):
                    row["ready"] = True
                else:
                    add(row["item"])
                    trained.append(row["item"])
                    pending.remove(row)

        available = set()
        if "fact" in types:
            available.add("powr")
        if "powr" in types:
            available |= {"proc", "tent" if faction == "allies" else "barr"}
        if types & {"tent", "barr"}:
            available |= {"e1", "e3"}
        if "proc" in types:
            available |= {"weap", "dome"}
        if "weap" in types:
            available |= {"fix", "harv", "1tnk" if faction == "allies" else "apc"}
        if "fix" in types:
            available.add("2tnk" if faction == "allies" else "3tnk")
        obs["available_production"] = sorted(available)
        obs["production"] = deepcopy(pending)
        obs["economy"].update(cash=max(0, cash), harvesters=harvesters,
            power_provided=100*sum(b["type"] == "powr" for b in obs["buildings"]),
            power_drained=sum({"tent": 20, "barr": 20, "proc": 30, "weap": 30,
                               "fix": 30, "dome": 40}.get(b["type"], 0) for b in obs["buildings"]))
        hints["deploy"] = [u["id"] for u in obs["units"] if u["type"] == "mcv"]
        hints["idle_units"] = [u["id"] for u in obs["units"] if u.get("idle")]
        hints["place"] = [p["item"] for p in pending if p["ready"]]
        hints["build"] = [i for i in available if View(raw).queue(i) == "Building"]
        hints["train"] = [i for i in available if View(raw).queue(i) not in ("Building", "Defense")]
        raw["time"].update(game_seconds=seconds, remaining_seconds=1200-seconds)
        raw["state_version"] = obs["tick"] = seconds*25
        orders = decide(agent, raw)
        if not orders:
            continue
        batch += 1
        rows = []
        for index, order in enumerate(orders):
            cmd = order["cmd"]
            if cmd == "deploy":
                obs["units"] = [u for u in obs["units"] if u["id"] not in order["units"]]
                add("fact", building=True)
            elif cmd in ("build", "train"):
                item = order["item"]
                queue = View(raw).queue(item)
                # A delayed observation must not duplicate the construction
                # queue. Unit queues are allowed but must remain short.
                if cmd == "build":
                    assert not any(p["queue"] == queue for p in pending)
                for _ in range(order.get("count", 1)):
                    pending.append(dict(queue=queue, item=item, progress=0,
                        remaining_s=duration[item], ready=False, paused=False))
            elif cmd == "place":
                row = next(p for p in pending if p["item"] == order["item"] and p["ready"])
                pending.remove(row)
                add(order["item"], building=True)
                if order["item"] == "proc":
                    add("harv")
            elif cmd == "rally":
                next(b for b in obs["buildings"] if b["id"] == order["building"])["rally"] = order["to"]
            elif "units" in order:
                for unit in obs["units"]:
                    if unit["id"] in order["units"]:
                        unit["idle"] = False
            rows.append(dict(index=index, cmd=cmd, status="ok"))
        agent.on_action_result({"accepted": True, "batch": batch, "results": rows}, context(raw))
        raw["last_orders"] = dict(batch=batch, state_version=raw["state_version"], pending=False, results=rows)

    built = [b["type"] for b in obs["buildings"]]
    return dict(buildings=built, trained=trained, cash=round(cash, 2),
                units=[u['type'] for u in obs['units']],
                pending=[p['item'] for p in pending])


@pytest.mark.parametrize("faction", ["allies", "soviets"])
@pytest.mark.parametrize("end_seconds", [300, 600])
def test_mock_production_progression_does_not_stall(faction, end_seconds):
    result = mock_production_progression(faction, end_seconds)
    built, trained = result['buildings'], result['trained']
    assert {"powr", "proc", "weap", "tent" if faction == "allies" else "barr"} <= set(built)
    assert built.count("proc") >= 2
    assert "e1" in trained and "e3" in trained
    # The intentionally scarce, fixed income is not an estimate of real maps.
    # Opening completion must be followed by investment rather than infantry
    # forever consuming every credit. Give that second stage its own horizon.
    if end_seconds >= 600:
        assert trained.count("harv") >= 2
        assert "fix" in built
