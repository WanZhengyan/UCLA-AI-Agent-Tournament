"""Offline contract check or a game against Tencent's licensed common AI."""

import argparse
import json
import os
import sys

from .agent import HonorOfKingsAgent, LegalActions, ProtocolError


def smoke_state():
    """Synthetic SDK-shaped example, not a recorded game or a win benchmark."""
    return {
        "player_id": 10, "game_id": "synthetic-smoke", "legal_action": [1] * 172,
        "req_pb": {
            "frame_no": 100,
            "hero_list": [{"runtime_id": 10, "config_id": 133, "camp": 1,
                           "hp": 3000, "max_hp": 3000, "phy_atk": 200, "atk_range": 6000,
                           "location": {"x": 0, "z": 0}}],
            "soldier_list": [{"runtime_id": 40, "camp": 2, "hp": 100,
                              "max_hp": 1000, "location": {"x": 2000, "z": 2000}}],
            "organ_list": [],
        },
    }


def run(args):
    # Imports are lazy: the AltruAgent Python 3.11+ runtime never imports the
    # separate Tencent extension, which has its own Python 3.6–3.9 ABI.
    if not (3, 8) <= sys.version_info[:2] <= (3, 9):
        raise RuntimeError("Tencent hok_env requires a separate Python 3.8/3.9 environment; see docs/HOK.md")
    try:
        from hok.hok1v1 import HoK1v1
        from hok.common.gamecore_client import GamecoreClient
        from hok.hok1v1.env1v1 import interface_default_config
        from hok.hok1v1.hero_config import get_default_hero_config
        import hok.hok1v1.lib.interface as interface
    except ImportError as exc:
        raise RuntimeError("Install the pinned official Tencent hok_env SDK in this environment first") from exc
    processor = interface.Interface()
    processor.Init(interface_default_config)
    launcher = GamecoreClient(server_addr=args.gamecore,
                              gamecore_req_timeout=3000,
                              default_hero_config=get_default_hero_config())
    env = HoK1v1("objective-agent-%d" % os.getpid(), launcher, processor,
                 ["tcp://0.0.0.0:%d" % (args.port + i) for i in range(2)],
                 aiserver_ip=args.ai_server)
    if tuple(env.action_space()) != (12, 16, 16, 16, 16, 8):
        raise RuntimeError("The installed SDK action schema differs from the pinned HoK1v1 contract")
    common_ai = [True, True]
    common_ai[args.seat] = False
    heroes = [[{"hero_id": args.enemy_hero}], [{"hero_id": args.enemy_hero}]]
    heroes[args.seat] = [{"hero_id": args.hero}]
    camp = {"mode": "1v1", "heroes": heroes}
    agent = HonorOfKingsAgent()
    terminal = False
    ready = False
    steps = 0
    try:
        _, _, done, states = env.reset(camp, use_common_ai=common_ai, eval=True)
        ready = True
        terminal = any(done)
        while not terminal and steps < args.max_steps:
            actions = [(0,) * 6, (0,) * 6]  # Engine controls the common-AI seat.
            actions[args.seat] = agent.act(states[args.seat])
            _, _, done, states = env.step(actions)
            steps += 1
            terminal = any(done)
        print(json.dumps({"strategy": agent.version, "steps": steps,
                          "terminal": terminal, "last_decision": agent.last_reason,
                          "result": "engine_terminated" if terminal else "step_limit_truncated"}))
    finally:
        # The upstream close_game waits for engine frames. Calling it after a
        # failed reset (for example, Gamecore offline) can block forever.
        if ready:
            env.close_game()
    # A cut-short simulation must never be counted as a win.
    return 0 if terminal else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Standalone Tencent HoK1v1 rule agent (not an AltruAgent tournament agent)")
    parser.add_argument("--smoke", action="store_true", help="Check a synthetic SDK-shaped state without Tencent dependencies")
    parser.add_argument("--gamecore", default=os.environ.get("GAMECORE_SERVER_ADDR", "127.0.0.1:23432"))
    parser.add_argument("--ai-server", default=os.environ.get("AI_SERVER_ADDR", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=35150)
    parser.add_argument("--hero", type=int, choices=(112, 133), default=133, help="112 Lu Ban No.7; 133 Di Renjie")
    parser.add_argument("--enemy-hero", type=int, default=133)
    parser.add_argument("--seat", type=int, choices=(0, 1), default=0)
    parser.add_argument("--max-steps", type=int, default=12000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65534 or args.max_steps < 1:
        parser.error("port must be 1..65534 and max-steps must be positive")
    if args.smoke:
        state = smoke_state()
        agent = HonorOfKingsAgent()
        action = agent.act(state)
        if not LegalActions(state).validates(action):
            raise ProtocolError("Smoke action failed the official legal masks")
        print(json.dumps({"strategy": agent.version, "action": action,
                          "reason": agent.last_reason, "synthetic": True, "engine_tested": False}))
        return 0
    try:
        return run(args)
    except (RuntimeError, ProtocolError) as exc:
        parser.exit(1, "%s\n" % exc)


if __name__ == "__main__":
    raise SystemExit(main())
