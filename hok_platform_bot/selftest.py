"""Synthetic platform-contract smoke checks, not live-engine validation."""
from altruagent import WAIT
from altruagent.models import GameState
from .agent import GAME_TYPE, create_agent


def sample(camp=1, mode="realtime"):
    seats = list(range((camp - 1) * 5, camp * 5))
    return {
        "session_id": "offline-hok-team", "game_type": GAME_TYPE,
        "status": "in_progress", "phase": "moving", "state_version": 10,
        "is_terminal": False, "is_current_actor": True,
        "pacing": {"mode": mode, "step_interval_s": .2}, "seats": seats, "camp": camp,
        "max_steps": 3000, "seconds_left": 600,
        "observation": {"seats": {str(s): {"summary": {
            "my_hero": {"hp": 3000, "max_hp": 3000, "level": 2, "camp": camp,
                        "x": s * 100, "z": 0, "revive_time": 0},
            "other_heroes": [], "structures": [], "frame_no": 30,
        }} for s in seats}},
        "simultaneous": {"your_pending_seats": seats[:], "standing_orders": {}},
        "legal_actions": {"actions": [entry for s in seats for entry in [
            {"action_id": f"s{s}:button_0", "input": {"action": {"which_button": 0, "seat": s}}},
            *[{"action_id": f"s{s}:{macro}", "label": f"{macro} (nearest: target, 12000 away)",
               "input": {"action": {"which_button": 2, "seat": s}}}
              for macro in ("macro_advance", "macro_retreat")],
        ]]},
    }


def run():
    for camp in (1, 2):
        raw, bot = sample(camp), create_agent()
        for seat in raw["seats"]:
            action = bot.choose_action(GameState.from_mcp_state(raw))
            assert action == {"macro": "macro_advance", "seat": seat}
            bot.on_action_result({"accepted": True})
            raw["simultaneous"]["standing_orders"][str(seat)] = action["macro"]
        assert bot.choose_action(GameState.from_mcp_state(raw)) is WAIT
    print("HoK 5v5 team protocol checks passed (synthetic, not a live match).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
