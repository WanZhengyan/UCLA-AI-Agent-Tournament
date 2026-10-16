from redalert_bot.common import View
from redalert_bot.economy import plan, _expansion_site


def view(buildings=(), units=(), production=(), available=None, cash=5000,
         power=100, drain=0, enemies=(), config=None, seconds=0):
    def actor(t, i):
        if isinstance(t, dict):
            return t
        return {"type": t, "id": i, "x": 10 + i % 4, "y": 10,
                "hp": 100, "idle": True}
    raw = {"map": {"id": "test", "bounds": [0, 0, 64, 64]},
           "time": {"game_seconds": seconds, "remaining_seconds": 1200-seconds},
           "legal_actions": {"enemy_base": [54, 54]},
           "observation": {"base_center": [10, 10],
               "units": [actor(t, i+100) for i, t in enumerate(units)],
               "buildings": [actor(t, i+1) for i, t in enumerate(buildings)],
               "production": list(production),
               "available_production": list(available or []),
               "economy": {"cash": cash, "power_provided": power, "power_drained": drain},
               "visible_enemies": list(enemies)}}
    return View(raw, config)


def orders(v):
    out = []
    def emit(order, key=None, cooldown=3):
        out.append(order)
        return True
    plan(v, {}, emit)
    return out


def test_initial_mcv_deploys_without_production_guess():
    out = orders(view(units=["mcv"]))
    assert out == [{"cmd": "deploy", "units": [100]}]


def test_two_refinery_opening_before_factory():
    v = view(["fact", "powr", "barr", "proc"], available=["powr", "proc", "weap", "e1"], drain=50)
    out = orders(v)
    assert {"cmd": "build", "item": "proc"} in out
    assert {"cmd": "build", "item": "weap"} not in out


def test_power_precedes_factory_when_next_build_would_brownout():
    v = view(["fact", "powr", "barr", "proc", "proc"],
             available=["powr", "proc", "weap", "e1"], drain=80)
    assert {"cmd": "build", "item": "powr"} in orders(v)


def test_ready_building_placed_even_if_no_longer_available_to_build():
    v = view(["fact", "powr"], production=[{"item": "barr", "queue": "Building", "ready": True}],
             available=["powr"])
    out = orders(v)
    assert {"cmd": "place", "item": "barr"} in out
    assert not any(o["cmd"] == "build" for o in out)


def test_existing_queues_not_requeued():
    production = [{"item": "proc", "queue": "Building"},
                  {"item": "e1", "queue": "Infantry", "count": 4},
                  {"item": "harv", "queue": "Vehicle"}]
    v = view(["fact", "powr", "barr", "proc", "weap"], production=production,
             available=["powr", "proc", "weap", "e1", "e3", "harv"])
    assert not any(o["cmd"] in {"train", "build"} for o in orders(v))


def test_economy_recovery_prioritizes_miners_over_tanks():
    v = view(["fact", "powr", "barr", "proc", "proc", "weap", "fix"],
             available=["e1", "e3", "harv", "3tnk"], cash=1200)
    out = orders(v)
    assert {"cmd": "train", "item": "harv", "count": 1} in out
    assert not any(o.get("item") == "3tnk" for o in out)


def test_no_income_reserves_cash_for_full_miner_replacement():
    v = view(["fact", "powr", "barr", "proc", "proc", "weap", "fix"],
             available=["e1", "e3", "harv", "3tnk"], cash=900)
    assert not any(o["cmd"] in {"train", "build"} for o in orders(v))


def test_low_cash_can_finance_one_rocket_with_two_working_miners():
    v = view(["fact", "powr", "barr", "proc", "proc", "weap"],
             units=["harv"]*2 + ["e1"]*10, available=["e1", "e3", "harv", "1tnk"], cash=225,
             production=[{"item": "harv", "queue": "Vehicle", "progress": .4}])
    out = orders(v)
    assert {"cmd": "train", "item": "e3", "count": 1} in out
    assert not any(o.get("item") == "1tnk" for o in out)


def test_infantry_does_not_starve_next_needed_miner():
    v = view(["fact", "powr", "barr", "proc", "proc", "weap"],
             units=["harv"]*2 + ["e1"]*10, available=["e1", "e3", "harv", "1tnk"], cash=300)
    out = orders(v)
    assert {"cmd": "train", "item": "harv", "count": 1} in out
    assert not any(o.get("item") == "e3" for o in out)


def test_service_depot_reserve_blocks_recurring_light_tank_starvation():
    v = view(["fact", "powr", "powr", "barr", "proc", "proc", "weap"],
             units=["harv"]*4 + ["e1"]*10 + ["e3"]*5,
             available=["fix", "e1", "e3", "harv", "1tnk"], cash=350)
    out = orders(v)
    assert not any(o["cmd"] == "train" for o in out)


def test_harvest_does_not_interrupt_active_miners():
    v = view(["fact", "powr", "proc"], units=[
        {"id": 100, "type": "harv", "idle": False, "x": 15, "y": 15},
        {"id": 101, "type": "harv", "idle": True, "x": 15, "y": 15}])
    harvest = [o for o in orders(v) if o["cmd"] == "harvest"]
    assert harvest == [{"cmd": "harvest", "units": [101]}]


def test_rocket_catchup_for_rifle_heavy_army():
    v = view(["fact", "powr", "barr", "proc", "proc"], units=["e1"]*12,
             available=["e1", "e3"], cash=1500)
    assert {"cmd": "train", "item": "e3", "count": 1} in orders(v)


def test_no_exploration_expansion_when_map_connectivity_unknown():
    v = view(["fact", "proc"], seconds=400)
    v.ore_cells = [(30, 12)]
    assert _expansion_site(v, {}) is None


def test_island_ore_not_selected_for_ground_expansion():
    rows = ["."*64 for _ in range(64)]
    rows = [row[:24]+"~"+row[25:] for row in rows]
    rows[12] = rows[12][:30]+"M"+rows[12][31:]
    cfg = {"rules": {"maps": {"test": {"layout": {"origin": [0, 0], "rows": rows}}}}}
    v = view(["fact", "proc"], config=cfg, seconds=400)
    assert _expansion_site(v, {}) is None


def test_live_threat_can_trigger_defense_in_parallel_queue():
    enemy = {"id": 500, "type": "e1", "x": 13, "y": 14, "hp": 100}
    v = view(["fact", "powr", "tent", "proc"], available=["pbox", "proc"],
             enemies=[dict(enemy, id=i) for i in range(500, 506)])
    assert {"cmd": "build", "item": "pbox"} in orders(v)
