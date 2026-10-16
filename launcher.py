"""Multi-game launcher for the official AltruAgent contestant runtime.

The official SDK owns authentication, seat leases, MCP, retries and workers.
This module supplies safe configuration and limits assignments to this bot's
three supported games. Secrets are never put in command-line arguments or logs.
"""
from __future__ import annotations

import argparse
import getpass
import json
import multiprocessing
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from competition_agent import SUPPORTED_GAME_TYPES

VERSION = "1.4.0"
GAME_TYPE = "pokemon_vgc_doubles_draft"
AGENT_SPEC = "competition_agent:create_agent"
CONTROL_URL = "https://api.altruagent-game.com"
KEY_ENV = "ALTRUAGENT_OFFICIAL_AGENT_KEY"


def binary_directory() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def load_configuration(key_file: str | None = None, *, prompt: bool = True) -> None:
    from dotenv import load_dotenv
    from altruagent.official import load_official_agent_key
    # Existing environment values take priority, then cwd, then the binary's directory.
    load_dotenv(Path.cwd() / ".env", override=False)
    load_dotenv(binary_directory() / ".env", override=False)
    os.environ.setdefault("ALTRUAGENT_CONTROL_URL", CONTROL_URL)
    url = urlparse(os.environ["ALTRUAGENT_CONTROL_URL"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("ALTRUAGENT_CONTROL_URL must be an HTTPS URL without embedded credentials.")
    if key_file:
        os.environ[KEY_ENV] = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
    if not os.environ.get(KEY_ENV) and prompt and sys.stdin.isatty():
        print("Enter your platform Official Agent Key (starts with eak_live_; input is hidden).")
        os.environ[KEY_ENV] = getpass.getpass("Official Agent Key: ").strip()
    load_official_agent_key()  # Validates locally without printing the value.


def make_official_client():
    from altruagent.official import OfficialAgentClient

    class CompetitionOfficialClient(OfficialAgentClient):
        """Filter discovery, leaving unsupported assignments entirely untouched."""
        def assignments(self):
            assignments = super().assignments()
            return [assignment for assignment in assignments if assignment.game_type in SUPPORTED_GAME_TYPES]

    return CompetitionOfficialClient(load_env_file=False)


def check_connection() -> int:
    from altruagent.agent_loader import load_agent_factory
    from altruagent.runner import _resolve_decision_fn
    official = make_official_client()
    try:
        official.authenticate()
        assignments = official.assignments()
        _resolve_decision_fn(load_agent_factory(AGENT_SPEC)())
        print(f"Connected: key verified and game router loaded; {len(assignments)} Pokemon/Red Alert/Werewolf assignments available.")
        print("Connection check complete. Run without --check to accept matches.")
        return 0
    finally:
        official.close()


def run_online(kinds: frozenset[str]) -> int:
    from altruagent.agent_loader import load_agent_factory
    from altruagent.errors import AltruAgentError
    from altruagent.official import is_registration_incomplete
    from altruagent.supervisor import run_tournament_forever
    load_agent_factory(AGENT_SPEC)
    official = make_official_client()
    try:
        try:
            official.authenticate()
            print("Connected to AltruAgent.", flush=True)
        except AltruAgentError as exc:
            if not is_registration_incomplete(exc):
                raise
            print(str(exc), flush=True)
        names = "+".join("tournament" if kind == "tournament" else "testing" for kind in sorted(kinds))
        print(f"Waiting for Pokemon VGC Doubles Draft / Red Alert / Werewolf assignments ({names}). Keep this process running; press Ctrl+C to stop.", flush=True)
        run_tournament_forever(official, agent_spec=AGENT_SPEC, kinds=kinds)
        return 0
    finally:
        official.close()


def decide_offline(path: str) -> int:
    from altruagent.agent_loader import load_agent_factory
    from altruagent.runner import _resolve_decision_fn, _resolve_message_decision_fn
    stream = sys.stdin if path == "-" else open(path, "r", encoding="utf-8")
    try:
        payload = json.load(stream)
    finally:
        if stream is not sys.stdin:
            stream.close()
    agent = load_agent_factory(AGENT_SPEC)()
    action = _offline_action(payload, _resolve_decision_fn(agent), _resolve_message_decision_fn(agent))
    print(json.dumps(action, ensure_ascii=False))
    return 0


def _offline_action(payload: dict, choose, choose_message=None) -> dict:
    from altruagent.models import DecisionContext, GameState, LegalAction
    raw = payload.get("state", payload)
    state = GameState.from_mcp_state(raw)
    context = DecisionContext(
        session_id=state.session_id or "offline",
        tournament_id=None,
        game_type=raw.get("game_type", GAME_TYPE),
        agent_id=payload.get("agent_id", "offline"),
        seat_position=payload.get("seat_position", raw.get("your_position", 0)),
        game_config=payload.get("game_config"),
    )
    from altruagent import WAIT, WithReasoning, SendMessage, TERMINATE_MESSAGING
    action = ((choose_message(state, context) if choose_message else TERMINATE_MESSAGING)
              if state.phase == "messaging" else choose(state, context))
    if isinstance(action, WithReasoning):
        action = action.action
    if action is WAIT:
        return {"type": "wait"}
    if action is TERMINATE_MESSAGING:
        return {"type": "terminate"}
    if isinstance(action, SendMessage):
        return {"type": "chat", "content": action.content, "recipients": list(action.recipients)}
    if isinstance(action, LegalAction):
        action = action.input.get("action", {"action_id": action.action_id})
    if isinstance(action, str):
        return {"action_id": action}
    return action


def decide_jsonl() -> int:
    """Keep one agent alive for many local engine decisions; stdout is JSON only."""
    from contextlib import redirect_stdout
    from altruagent.agent_loader import load_agent_factory
    from altruagent.runner import _resolve_decision_fn, _resolve_message_decision_fn
    with redirect_stdout(sys.stderr):
        agent = load_agent_factory(AGENT_SPEC)()
        choose = _resolve_decision_fn(agent)
        choose_message = _resolve_message_decision_fn(agent)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            with redirect_stdout(sys.stderr):
                action = _offline_action(json.loads(line), choose, choose_message)
            print(json.dumps(action, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)
    return 0


def _probe_worker(queue) -> None:
    """A real spawned process probe, including frozen dynamic imports."""
    from altruagent.agent_loader import load_agent_factory
    from altruagent.runner import _resolve_decision_fn
    from altruagent.worker import _tournament_process_entry
    from mcp.client.streamable_http import streamablehttp_client
    import httpx
    _resolve_decision_fn(load_agent_factory(AGENT_SPEC)())
    # Lazy routing must not hide a missing game module in a spawned worker.
    from pokemon_bot.agent import create_agent as create_pokemon
    from redalert_bot.agent import create_agent as create_redalert
    from werewolf_bot.agent import create_agent as create_werewolf
    for factory in (create_pokemon, create_redalert, create_werewolf):
        _resolve_decision_fn(factory())
    # No request is made: construction catches absent CA bundles and optional
    # proxy dependencies in the packaged artifact before a real match starts.
    with httpx.Client() as client:
        assert client is not None
    queue.put({"worker": True, "mcp": callable(streamablehttp_client), "entry": callable(_tournament_process_entry), "tls": True})


def runtime_self_test() -> dict:
    """No credentials/network; ensures single-file workers can load all code."""
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_probe_worker, args=(queue,))
    process.start()
    try:
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
            raise RuntimeError("Worker import probe timed out")
        if process.exitcode != 0:
            raise RuntimeError(f"Worker import probe failed (exit {process.exitcode})")
        return queue.get(timeout=3)
    finally:
        queue.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="AltruAgent Pokemon + Red Alert + Werewolf agent. Accepts tournament and testing matches by default.")
    result.add_argument("--version", action="version", version=f"Gaming Agent {VERSION}")
    result.add_argument("--check", "--check-tournament", action="store_true", help="check the key, connection and policy without accepting matches")
    result.add_argument("--self-test", action="store_true", help="run offline self-tests; no key required")
    result.add_argument("--runtime-test", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--decide", metavar="JSON_FILE", help="choose an action from offline MCP state JSON; use - for stdin")
    result.add_argument("--jsonl", action="store_true", help="keep an offline process alive, reading state JSON and writing one action per line")
    result.add_argument("--tournament", action="store_true", help="accept tournament matches; may be combined with --match")
    result.add_argument("--match", action="store_true", help="accept testing matches; may be combined with --tournament")
    result.add_argument("--key-file", metavar="PATH", help="read the Official Agent Key from a plain-text file")
    result.add_argument("--no-prompt", action="store_true", help="disable the interactive key prompt for unattended operation")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.environ.setdefault("POKEMON_BOT_BUDGET", "2.0")
    try:
        if args.runtime_test:
            print(json.dumps(runtime_self_test()))
            return 0
        if args.self_test:
            from pokemon_bot.selftest import run as pokemon_test
            from redalert_bot.selftest import run as redalert_test
            from werewolf_bot.selftest import run as werewolf_test
            result = pokemon_test()
            redalert_result = redalert_test()
            werewolf_result = werewolf_test()
            print("Runtime:", json.dumps(runtime_self_test()))
            return int(result or redalert_result or werewolf_result or 0)
        if args.decide:
            return decide_offline(args.decide)
        if args.jsonl:
            return decide_jsonl()
        load_configuration(args.key_file, prompt=not args.no_prompt)
        if args.check:
            return check_connection()
        kinds = frozenset(kind for kind, enabled in (("tournament", args.tournament), ("testing", args.match)) if enabled)
        return run_online(kinds or frozenset({"tournament", "testing"}))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as exc:
        # SDK errors are redacted. Do not log credential-bearing objects or traceback locals.
        message = str(exc)
        secret = os.environ.get(KEY_ENV)
        if secret:
            message = message.replace(secret, "<redacted>")
        print(f"Startup or runtime failed: {message}", file=sys.stderr)
        return 1

