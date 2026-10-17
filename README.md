# Gaming

A self-hosted AltruAgent contestant for **Red Alert (OpenRA)**, **Pokemon VGC Doubles Draft**, **Werewolf**, and **Honor of Kings 5v5**. All strategy decisions run locally; no OpenAI or other model API key is required.

The newly available platform HOK mode uses **one agent per five-hero team**. See [docs/HOK.md](docs/HOK.md) for setup. The older standalone Tencent `hok_env` 1v1 agent remains separate; its licensed-engine instructions are in [HOK_TENCENT_1V1.md](docs/HOK_TENCENT_1V1.md).

**Development candidate:** `improve/friendly-defense-v14` combines protected economic growth with score-aware Red Alert defense, productive-miner escape, shared power budgeting, and consistent HOK team-visible threat assessment. See [the Friendly Fighter review](docs/FRIENDLY_FIGHTER_REVIEW.md) for public-code findings, independent fixes and evaluation limits. This revision has not replaced `main` or a running tournament agent; local correctness is not proof of a win-rate improvement.

## What it does

- **Red Alert:** `eco_guard` / `economy_guard_v14_search1` prioritizes tanks, protected mining, escorts and rear artillery, with a bounded wider fallback search for idle miners. A nonnegative own kill/loss balance stops voluntary attack waves; a deficit permits only guarded counterattacks. See [Red Alert strategy](docs/REDALERT.md). `balanced` remains an optional experimental baseline.
- **Pokemon:** draft selection, four-of-six team selection, and joint doubles search. `paradox_damage_v10` combines type-aware damage with move priority, effective Speed, weather/Booster Energy, Unburden, and known Tailwind/Trick Room expiry. It also retains publicly announced offensive and defensive Paradox modifiers after item consumption. See [the replay review](docs/POKEMON_SPEED_RESEARCH.md) and [v10 mechanism checks](docs/POKEMON_PARADOX_V10.md).
- **Werewolf:** `evidence_v1` uses private checks, official reveals, bounded claim evidence, vote history, role-specific night choices, and limited public/private discussion. See [docs/WEREWOLF.md](docs/WEREWOLF.md).
- **Honor of Kings:** `hok_team_guard_v14` controls five heroes with listed standing orders, safe objective pressure, bounded tower defense, health-aware retreat/recovery and fair scheduling. Owned-team visible contacts inform both defense allocation and individual safety decisions. See [setup and limitations](docs/HOK.md).
- **Runtime:** one listener routes all four supported platform games to isolated assignment workers. The bundled SDK handles authentication, leases, MCP transport, reconnection and worker processes. Each HOK assignment controls the five heroes belonging to that team.
- **Review:** local observations, proposed actions, order verdicts, and terminal results support offline analysis by map, source version, faction, seat, and match duration.

Only information available to the assigned seat is used. Strategy state and observations are not shared between opposing seats.

## Run from source

Use Python 3.11 or later and keep the machine connected to the internet.

```bash
git clone --branch improve/friendly-defense-v14 https://github.com/WanZhengyan/UCLA-AI-Agent-Tournament.git
cd UCLA-AI-Agent-Tournament
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py --check
.venv/bin/python exe_entry.py
```

Paste the platform's **Official Agent Key** when prompted. Input is hidden. This is a platform credential, not a GitHub token or model API key. Interactive entry is not saved to disk.

Run only **one listener per Official Agent Key**. The default accepts testing and tournament assignments for all four supported platform games. When upgrading an older listener to add HOK, restart it after active games finish so the new assignment filter loads.

| Command option | Behavior |
| --- | --- |
| `--self-test` | Check platform policies and four-game spawned worker imports offline; no key required. |
| `--check` | Check authentication and policy loading without accepting matches. |
| `--match` | Accept testing assignments only. |
| `--tournament` | Accept tournament assignments only. |
| `--key-file /path/to/key.txt` | Read the key from a plain-text file. |
| `--no-prompt` | Disable interactive key entry for unattended operation. |
| `--decide state.json` | Produce an action from an offline MCP state snapshot. |
| `--jsonl` | Read offline state snapshots and return one action per line. |

For unattended use, set `ALTRUAGENT_OFFICIAL_AGENT_KEY` in the environment, or copy `.env.example` to an untracked `.env` and replace the example value. Restrict credential-file permissions, for example with `chmod 600 .env`. Do not put keys in command-line arguments, commits, screenshots, or match logs.

## Platform setup and tournament entry

Follow [docs/PLATFORM.md](docs/PLATFORM.md) for the full setup and official-tournament workflow. On the [AltruAgent dashboard](https://platform.altruagent-game.com/tournament/dashboard), complete event registration, select **Self Hosted** under **Agent Configuration**, record this public repository URL, and obtain the Official Agent Key. Start the listener using the command above.

For a practice match, use the platform's **Testing** page, choose Red Alert, Pokemon VGC Doubles Draft, Werewolf, or Honor of Kings, and select **Mine (self-hosted)**. Werewolf requires seven connected seats; HOK assigns five heroes to each team agent. Leave the listener running while the platform assigns the match.

For an official event, open **Dashboard → Tournaments**, choose a supported game, and click **Register my agent**. Each game needs its own entry. Keep Self Hosted selected and run the listener with either its default options or `--tournament`. Starting the program does not register an entry or create a match. Confirm version-lock eligibility before replacing a submitted entry.

This repository uses the self-hosted workflow: the platform dispatches assignments to the running process. The repository URL records the source; it does not upload or execute Python on the platform. Oracle Hosted accepts a separate Markdown agent and is not the deployment path for this code. A GitHub push alone does not update the machine running the agent. Update that checkout before starting new workers; a worker already playing a match keeps its loaded policy. Avoid stopping a live match to deploy an update.

See the [official platform guide](https://api.altruagent-game.com/skill.md) for current registration and agent-configuration requirements.

## Analyze recorded matches

Recording is enabled for new Red Alert, Pokemon and HOK workers by default. Red Alert samples approximately every five game seconds; HOK samples every ten state versions; Pokemon records decision observations. Logs contain selected seat/team-visible fields, proposed actions, execution verdicts and independent results. Werewolf private observations and messages remain excluded.

```bash
.venv/bin/python -m match_monitor
.venv/bin/python -m redalert_bot.review \
  --root validation/match_monitor \
  --root validation/redalert_selfplay \
  --output validation/review/redalert.json
```

Copy the original machine's log directories to the analysis machine first, or provide other directories with repeated `--root` options. The review groups outcomes by map, policy source version, faction, seat, and duration, and reports observed low power, missing harvesters, idle production, and sampling gaps.

- Private logs live under `validation/match_monitor/`; each seat has a timeline, latest snapshot, and separate final-result file. Timelines are capped at 8 MiB per seat; old match files are not automatically deleted.
- Missing results, contradictory terminal results, and server failures do not count as wins or losses. An unaccepted or `pending` order is not proof of execution.
- The review reads recorded JSON/JSONL, not MP4 files or OpenRA binary replays. Empty input produces no invented match results.
- Diagnostics identify events to investigate; they do not establish why a match was lost. The review does not change policy parameters or provide background analysis after the listener stops.
- Set `COMPETITION_MONITOR_DISABLED=1` or `POKEMON_BOT_NO_CACHE=1` to disable new recordings. Keep private logs and replay exports out of GitHub.

## Validation and experiments

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python exe_entry.py --self-test
```

The Red Alert tests exercise production budgets, harvesting, map geometry, combat commands, monitoring, and replay analysis using controlled scenarios. These checks detect behavior errors; they do not measure tournament win rate. Routing and combat estimates are heuristics, not the full OpenRA engine.

[Public opponent research](docs/OPPONENT_RESEARCH.md) preserves the earlier four-game survey. The [new HOK review](docs/HOK_PLATFORM_RESEARCH.md) adds an inspected platform-specific policy and supersedes the earlier empty-repository finding. Registration and deployed versions remain unverified. Defensive scenarios cover raids, conditional priority, untrusted Werewolf claims, HOK tower bait and order delivery. No opponent code was executed and no head-to-head winning advantage is claimed.

The current v14 validation passed **1108 tests**, plus four-game self-tests and spawned runtime checks. [friendly_defense_v14.json](reports/friendly_defense_v14.json) records the source hashes and checks for defense-first decisions, miner protection, combined power commitments and HOK team visibility. No live match or head-to-head win-rate comparison was run for this revision.

The historical v13 validation passed **887 tests**, including 42 new Red Alert growth scenarios, plus four-game self-tests and spawned worker checks. See [the economy review](docs/REDALERT_GROWTH_V13.md). No live match was run for that revision.

The historical v11 validation passed **794 tests**, including 129 tests in the new HOK policy/runtime/telemetry files, plus four-game self-tests and spawned worker checks. A local 1000-call synthetic measurement including state parsing had 0.19 ms median and 4.80 ms maximum latency. No live HOK game was run for that revision and no win-rate improvement was claimed. See [hok_platform_v11.json](reports/hok_platform_v11.json).

The historical v10 validation passed **663 tests**, including 21 focused regressions and 19 independent engine checks within one of those tests, plus the shared runtime self-test. Its frozen comparison against v9 finished **12-12**: 8-8 in six-member mirror fixtures and 4-4 in a coverage-driven four-member extension. The first suite had no non-Speed Paradox activations; all eight extension games exercised them. No overall winning advantage was demonstrated. [pokemon_paradox_v10.json](reports/pokemon_paradox_v10.json) records source hashes, outcomes, activation coverage, latency, and limitations.

The historical v9 validation passed 642 tests with the optional Showdown checks enabled, all three platform policy self-tests, and spawned runtime imports. [pokemon_type_speed_v9.json](reports/pokemon_type_speed_v9.json) records those source hashes and comparison results. The earlier four-game defense validation is preserved in [defense_v8.json](reports/defense_v8.json).

The frozen v9-versus-v8 comparison finished **14-14** across 28 paired games: 8-8 in speed-control fixtures and 6-6 in two-restricted fixtures. There were no illegal choices, fallbacks, timeouts, or incomplete games. This small handcrafted evaluation shows no overall winning advantage; the v9 candidate is a mechanics correction, not a proven tournament-strength upgrade.

Pokemon mechanism checks can also run against the pinned Showdown engine. The paired comparison harness accepts `COMPARE_SUITE=core`, `COMPARE_SUITE=regi`, or `COMPARE_SUITE=speed`. The latter two add hand-built two-restricted and speed-control archetypes, respectively, with Tera disabled. Public replay observations and their limits are documented in [docs/POKEMON_RESEARCH.md](docs/POKEMON_RESEARCH.md) and the [type/speed review](docs/POKEMON_SPEED_RESEARCH.md).

The complete v7 comparison is in [reports/pokemon_mechanics_v7.json](reports/pokemon_mechanics_v7.json): 14-10 in the core suite and 5-11 in the restricted-legendary suite. All 40 final games completed without illegal actions, fallbacks, or timeouts. Earlier aborted attempts and the replay-driven correction are preserved separately. These are development fixtures, including reused seeds, not a held-out platform win-rate estimate.

The latest Red Alert production comparison is [redalert_economy_v14.json](reports/redalert_economy_v14.json), comparing the integrated candidate against `b6be880`. It retains the guarded-growth gains from [v13](reports/redalert_growth_v13.json). See [replay sources, decision guards and evaluation limits](docs/REDALERT_GROWTH_V13.md). These fixed-income fixtures omit combat and must not be read as live win-rate results. Earlier revisions are summarized in [docs/HISTORY.md](docs/HISTORY.md).

Optional self-play is **disabled** in `validation/redalert_selfplay/settings.json`. When explicitly enabled, it applies only to Red Alert Testing matches for which official assignments confirm that both seats belong to this account. It compares `balanced` and `eco_guard`, alternates seats on successive compatible matches, and does not share either seat's observations. Read existing experiment summaries with:

```bash
.venv/bin/python -m redalert_bot.selfplay
```

Optional Pokemon mechanism checks use the Pokemon Showdown version pinned in `package.json`; install it with `npm install`. Enable the engine-backed Python tests explicitly:

```bash
SHOWDOWN_NODE=node .venv/bin/python -m pytest tests -q
```

Example offline benchmark:

```bash
PYTHON=.venv/bin/python node tests/showdown_benchmark.js 12 100
```

These small synthetic benchmarks do not represent the full platform draft or tournament field.

## Project layout

| Path | Purpose |
| --- | --- |
| `redalert_bot/` | Red Alert economy, combat, map handling, self-play, and review. |
| `pokemon_bot/` | Pokemon draft, team selection, battle search, and static data. |
| `werewolf_bot/` | Seven-seat role inference, legal actions, and bounded discussion. |
| `hok_bot/` | Standalone Tencent Honor of Kings 1v1 policy and separate runtime. |
| `competition_agent.py` | Game routing and per-seat policy isolation. |
| `launcher.py`, `exe_entry.py` | CLI configuration and executable entry point. |
| `altruagent/` | Bundled official runtime and documented local callbacks. |
| `match_monitor.py` | Passive local recording and read-only summaries. |
| `tests/` | Regression scenarios and offline benchmarks. |

## Packaging and provenance

`bash build.sh` builds and self-tests a single executable in `dist/PokemonChampion`. Despite the historical filename, the build includes all four AltruAgent policies, including HOK 5v5; Tencent HOK 1v1 remains separate. Architecture and system-library requirements depend on the build machine. No prebuilt v11 binary is included; previously downloaded binaries do not receive source updates automatically.

The official runtime source and local extensions are documented in [SDK_PROVENANCE.txt](SDK_PROVENANCE.txt). Pokemon static data comes from Pokemon Showdown; provenance and included third-party licenses are under [licenses/](licenses/).

Credentials, private match histories, original-machine caches, virtual environments, and unverified legacy binaries are excluded from this repository.
