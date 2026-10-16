# Honor of Kings 5v5 on AltruAgent

The platform now documents `honor_of_kings_5v5`: **one agent controls five heroes**, with one opponent controlling the other five. This repository's `hok_platform` policy implements that interface without an LLM or model API key. The separate Tencent 1v1 runner remains in `hok_bot`; its setup is archived in [HOK_TENCENT_1V1.md](HOK_TENCENT_1V1.md).

The current [official HOK guide](https://api.altruagent-game.com/skill/hok), retrieved October 16, 2026, supersedes older availability banners. No live match was run for this release: the available browser session had expired and this workspace had no Official Agent Key. Local checks establish protocol and scenario behavior, not tournament win rate.

## Start a test

Use `improve/hok-team-v11`. In an existing checkout:

```bash
git fetch origin
git switch improve/hok-team-v11
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py --check
.venv/bin/python exe_entry.py --match
```

If needed, create the environment with `python3 -m venv .venv` first. Enter the platform's Official Agent Key at the hidden prompt. No OpenAI key, local game installation or Tencent gamecore license is needed for this platform integration.

On **Dashboard → Testing**, select **Honor of Kings**, use **Mine (self-hosted)** for your team and create/join a test. Keep one listener per key. This branch changes the assignment filter and runtime: an older listener must be restarted after its active matches finish. Updating files alone does not refresh that listener's loaded filter. Rebuild an old executable before use.

For official games, register in the applicable HOK tournament and run `exe_entry.py --tournament`, or run without flags to accept both testing and official assignments. A push, connection check or test match does not register a tournament entry. Follow the event's current version-lock instructions.

## Decisions

- Prioritize a listed tower/crystal basic attack. Offered attacks are already range-checked by the platform; a guessed skill range must not discard them.
- Advance toward objectives when no useful attack exists. Do not retreat solely because a tower is nearby or the summary omits minions.
- Retreat on low health, fresh substantial damage, or a wounded local disadvantage. A health/level proxy considers nearby healthy teammates rather than counting every hero equally.
- Keep recovery/damage history per hero and reset it on death, respawn, changed team/session, or timeline rewind. Separate recovery thresholds reduce oscillation. Critical own-crystal defense can interrupt ordinary recovery when an attack is legal and the local estimate permits it.
- Cast currently listed skills only with a parsed nearby enemy-hero target. Reserve the third skill for multiple nearby visible enemies, a weakened enemy, or immediate combat pressure. Unknown hero-specific effects remain a limitation.
- Replace unavailable skills with available attacks/advance; prioritize urgent retreats and otherwise rotate fairly across heroes. Do not overwrite unchanged standing orders.
- Ignore hidden enemies even if stale coordinates remain. No spectator data, messages or external network calls enter the policy.

Macros choose the **nearest target**. This version cannot select arbitrary targets, lanes, jungle routes, heroes, equipment or builds through undocumented raw fields. It does not claim precise focus fire or a complete mobile-game strategy. Raw listed actions are only a protocol fallback; no button is guessed to be heal or recall. Thresholds are development heuristics requiring live calibration.

## Runtime and records

Macros remain standing orders and are re-evaluated by the server every 0.2-second game step. Real-time mode sends changed orders consecutively, pausing 0.6 seconds before re-reading only when no updates are needed. Lockstep sends an action for every pending hero even if its standing macro is unchanged. A rejection is not treated as confirmation; repeated invalid actions at one version are suppressed.

Bounded, sparse records under `validation/match_monitor/` contain team-visible health, deaths, positions, visible enemies, structures, orders, verdicts and independent final results. Credentials and hidden coordinates are excluded. HOK MCP returns `+1`, `-1`, `0` mean win, loss, draw; server failures are not losses. Keep local records outside GitHub.

Review actual tower/crystal HP changes, recovery time, stale skill orders and whether every hero receives updates. Compare both camps and multiple real opponents before claiming strength. [HOK_PLATFORM_RESEARCH.md](HOK_PLATFORM_RESEARCH.md) records sources and limits; [hok_platform_v11.json](../reports/hok_platform_v11.json) records validation and source hashes. Earlier [Tencent 1v1 research](HOK_RESEARCH.md) does not measure this policy's 5v5 performance.
