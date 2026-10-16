"""Persistent JSONL bridge used exclusively by the offline Showdown benchmark."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemon_bot.agent import PokemonAgent
agent = PokemonAgent()
for line in sys.stdin:
    try:
        raw = json.loads(line)
        decision = agent.decide(raw)
        print(json.dumps({"action": decision, "diagnostics": agent.last_diagnostics}), flush=True)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({'bridge_error': repr(exc)}), flush=True)
