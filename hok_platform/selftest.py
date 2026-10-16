"""Credential-free HoK protocol smoke checks; no game server is contacted."""
from altruagent import WAIT
from altruagent.models import DecisionContext, GameState

from .agent import GAME_TYPE, create_agent


def sample(camp=1):
    """A synthetic five-hero team in the documented public MCP state shape."""
    seats = list(range((camp - 1) * 5, camp * 5))
    heroes = {seat: {"runtime_id": 100 + seat, "camp": camp, "hp": 1000,
                     "max_hp": 1000, "level": 1, "x": 1000 * (seat % 5),
                     "z": 0, "revive_time": 0, "visible": True}
              for seat in seats}
    actions = [
        {"action_id": f"s{seat}:{macro}", "label": macro,
         "input": {"action": {"seat": seat, "macro": macro}}}
        for seat in seats for macro in ("macro_advance", "macro_retreat")
    ]
    return {
        "game_type": GAME_TYPE, "session_id": f"offline-hok-{camp}",
        "status": "active", "phase": "moving", "state_version": 10,
        "is_terminal": False, "is_current_actor": True, "camp": camp,
        "seats": seats, "pacing": {"mode": "realtime", "step_interval_s": .2},
        "simultaneous": {"your_pending_seats": seats[:], "standing_orders": {}},
        "legal_actions": {"state_version": 10, "actions": actions},
        "observation": {"seats": {
            str(seat): {"summary": {
                "my_hero": dict(heroes[seat]), "frame_no": 30, "structures": [],
                "other_heroes": [dict(heroes[other]) for other in seats if other != seat],
            }} for seat in seats
        }},
    }


def run():
    for camp in (1, 2):
        raw = sample(camp)
        context = DecisionContext(raw["session_id"], None, GAME_TYPE, "offline", camp - 1)
        bot, seen = create_agent(), set()
        allowed = [entry["input"]["action"] for entry in raw["legal_actions"]["actions"]]
        for _ in range(5):
            selected = bot.choose_action(GameState.from_mcp_state(raw), context)
            assert isinstance(selected, dict) and selected in allowed
            assert selected["seat"] not in seen
            seen.add(selected["seat"])
            raw["simultaneous"]["standing_orders"][str(selected["seat"])] = selected["macro"]
            bot.on_action_result({"accepted": True}, context)
        assert seen == set(raw["seats"])
        assert bot.choose_action(GameState.from_mcp_state(raw), context) is WAIT

        # Lockstep needs a new action even when the standing order matches.
        pending = raw["seats"][-1]
        raw["pacing"]["mode"] = "lockstep"
        raw["state_version"] = raw["legal_actions"]["state_version"] = 11
        raw["simultaneous"]["your_pending_seats"] = [pending]
        selected = bot.choose_action(GameState.from_mcp_state(raw), context)
        assert selected == {"seat": pending,
                            "macro": raw["simultaneous"]["standing_orders"][str(pending)]}
    print("Honor of Kings 5v5 offline protocol checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
