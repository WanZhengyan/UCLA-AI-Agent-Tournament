# AltruAgent Honor of Kings 5v5

This is the platform policy, **not** `hok_bot` (the separate Tencent 1v1 SDK experiment).
Game type: `honor_of_kings_5v5`. Policy: `hok_team_v11`. Development branch:
`improve/hok-platform-v11`, based on Pokemon v10. The other three policies are unchanged.

## Verified platform contract

Checked on October 16, 2026 against the live [HoK guide](https://api.altruagent-game.com/skill/hok),
[guide index](https://api.altruagent-game.com/skill.md), and official starter
[`686e756` HoK example](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter/blob/686e7560708eaa595a409b330d0d1837d49ba9d5/examples/llm/hok.py)
and its `tests/test_hok.py` contract fixtures.

The live [tournament listing](https://api.altruagent-game.com/tournaments) includes
Honor of Kings 5v5. The event marketing homepage's “not playable yet” notice is
out of date relative to these API documents and the tournament listing.

- Two agents compete; each controls five heroes (camp 1 seats 0–4, camp 2 seats 5–9).
- Each hero has its own `observation.seats["<seat>"].summary` and legal actions.
- Commands are **one hero per call**: `{"macro":"macro_attack","seat":3}`.
  Macros persist as standing orders. A raw-button action instead clears that order.
- Real time advances every 0.2 seconds. Send changes only; re-read every second when
  no change is needed. Queue/start states still use long-polling.
- Lockstep requires an action for every pending hero, including a listed no-op
  for dead heroes. It must not skip a pending hero because its standing order matches.
- Win by destroying the crystal. At the limit: enemy structure damage first,
  hero kills second. Result returns are +1 / -1 / 0; zero is a draw, not a loss.

## Strategy

The deterministic policy is a conservative macro baseline:

1. Establish persistent orders for all five heroes, with emergency retreat first
   and fair scheduling so one changing hero cannot starve the other four.
2. Recover low-health heroes until 78% health. Visible local enemies, nearby
   living allies, absolute health, and levels inform a simple strength estimate.
3. React to rapid health loss, especially near enemy structures. Do not assume
   one allied unit makes a tower dive safe.
4. Attack available nearby targets; otherwise advance toward enemy objectives.
   Supported fights can use legal skill macros, followed by basic attacks rather
   than remaining parked on a skill during cooldown.
5. Recompute from fresh offers after a rejection. Only the server's standing
   orders confirm execution. Never command another team's seat or use hidden
   enemy coordinates.

Limitations: macros select nearest targets; this version cannot promise a chosen
lane, focus-fire target, exact last hit, tower aggro, or hero-specific combo. The
published summary does not include a minion/aggro contract. Health/level estimates
are heuristics, not a damage simulator. No LLM, neural training, Tencent client,
local Gamecore installation, or additional credential is required by this policy.

## Run and validate

```bash
python -m pytest tests/test_hok_platform.py -q
python -m hok_platform_bot.selftest
python exe_entry.py --self-test
python exe_entry.py --check
python exe_entry.py
```

Use the existing AltruAgent Official Agent Key and **one** listener for all four
platform games. The same listener takes Testing and official tournament assignments
by default. Updating source must be followed by a safe listener restart because
its supported-game filter is loaded in the parent process. Do not interrupt a live
match to do this; the old listener ignores HoK assignments until restarted.

This is Self Hosted: no Oracle Markdown upload is required or performed. Repository
publication, running-source deployment, tournament registration, and successful
game connection are separate checks. A GitHub push alone does not deploy the agent.
Follow the organizer's applicable submission/version rules.

The fixtures cover both camps, five-seat scheduling, legality, raw fallbacks,
real-time and lockstep runner integration, visibility, recovery, callbacks, and
result interpretation. They are **synthetic**, not a measured competitive win rate.
The v11 validation passed 696 repository tests (including optional Showdown
checks), all four offline policy checks, and the spawned worker/MCP/TLS import
probe. The 33 new HoK platform tests are separate from the 35 old Tencent 1v1
tests; passing the latter alone would not establish platform compatibility.
Validate a real Testing match and authoritative result before claiming engine
compatibility or competitive strength. Browser access is required to create a
Testing room or change the account's website configuration.
