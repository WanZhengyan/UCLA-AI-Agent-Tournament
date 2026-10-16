"""Offline protocol checks, not a live Werewolf win-rate evaluation."""
from altruagent import SendMessage
from altruagent.models import DecisionContext, GameState

from .agent import create_agent


def sample():
    """Return a synthetic state using the official text/public-state schema."""
    return {
        "session_id": "offline-werewolf", "game_type": "werewolf",
        "status": "in_progress", "phase": "moving", "state_version": 3,
        "is_terminal": False, "is_current_actor": True, "eliminated": False,
        "your_position": 0, "messaging_enabled": True, "new_messages": [],
        "players": [{"position": seat, "name": f"Example {seat}"} for seat in range(7)],
        "observation": "=== Werewolf ===\nYour role: SEER\nYour investigations: Player3 is wolf\nDay 1 | phase day_vote | alive 7/7",
        "game_state": {"day": 1, "phase": "day_vote", "alive": [f"Example {seat}" for seat in range(7)],
                       "dead": [], "vote_history": [], "winner": None},
        "legal_actions": {"session_id": "offline-werewolf", "state_version": 3, "actions": [
            {"action_id": str(seat), "label": "Abstain" if seat == 7 else f"Vote to eliminate Player{seat}",
             "input": {"session_id": "offline-werewolf", "state_version": 3, "action_id": str(seat)}}
            for seat in range(1, 8)]}}


def run():
    raw = sample()
    context = DecisionContext(raw["session_id"], None, "werewolf", "offline", 0)
    bot = create_agent()
    assert bot.choose_action(GameState.from_mcp_state(raw), context) == "3"
    raw["phase"] = "messaging"
    raw["messaging_seconds_left"] = 90
    message = bot.choose_message(GameState.from_mcp_state(raw), context)
    assert isinstance(message, SendMessage)
    assert "Player3 is wolf" in message.content and len(message.content.split()) <= 50
    assert not message.recipients
    print("Werewolf offline policy checks passed. No live win-rate claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
