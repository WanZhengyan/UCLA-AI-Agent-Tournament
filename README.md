# Gaming

A self-hosted AltruAgent contestant for **Red Alert (OpenRA)** and **Pokemon VGC Doubles Draft**. All strategy decisions run locally; no OpenAI or other model API key is required.

The repository also includes a **standalone Honor of Kings 1v1 agent** for Tencent's official `hok_env`. It uses a separate Gamecore runtime; Honor of Kings is not currently playable through the AltruAgent tournament interface. See [docs/HOK.md](docs/HOK.md) for requirements and commands.

**Development candidate:** these additions are on `improve/pokemon-hok-v7` ([PR #2](https://github.com/WanZhengyan/UCLA-AI-Agent-Tournament/pull/2)). The final Pokemon comparison scored 19 wins for the candidate and 21 for the previous policy; it does not establish a winning advantage. The update has not replaced `main` or a running tournament agent. Check out this branch to use the new HOK module or test the Pokemon candidate.

## What it does

- **Red Alert:** tank-led production, protected harvesting, map-aware ground routes, conservative engagement checks, separate anti-air control, and siege support against known defenses. The deployment default is `eco_guard` / `armor_economy_v6`; `balanced` remains an optional experimental baseline.
- **Pokemon:** draft selection, four-of-six team selection, joint doubles action search, approximate battle simulation, and legal-action fallbacks. `mechanics_v7` improves multi-hit damage/reactions, Electro Shot timing, Unaware, immediate status-curing items, and Koraidon/Miraidon entry effects.
- **Runtime:** one listener routes both supported games to isolated per-seat workers. The bundled official SDK handles authentication, seat leases, MCP transport, reconnection, and worker processes.
- **Review:** local observations, proposed actions, order verdicts, and terminal results support offline analysis by map, source version, faction, seat, and match duration.

Only information available to the assigned seat is used. Strategy state and observations are not shared between opposing seats.

## Run from source

Use Python 3.11 or later and keep the machine connected to the internet.

```bash
git clone https://github.com/WanZhengyan/UCLA-AI-Agent-Tournament.git
cd UCLA-AI-Agent-Tournament
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py --check
.venv/bin/python exe_entry.py
```

Paste the platform's **Official Agent Key** when prompted. Input is hidden. This is a platform credential, not a GitHub token or model API key. Interactive entry is not saved to disk.

Run only **one listener per Official Agent Key**. The default accepts both testing and tournament assignments for both supported games.

| Command option | Behavior |
| --- | --- |
| `--self-test` | Check both game policies and spawned worker imports offline; no key required. |
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

For a practice match, use the platform's **Testing** page, choose Red Alert or Pokemon VGC Doubles Draft, and select **Mine (self-hosted)** for your seat. Create the match and leave the listener running while the platform assigns the seat.

For an official event, open **Dashboard → Tournaments**, choose a supported game, and click **Register my agent**. Keep Self Hosted selected and run the listener with either its default options or `--tournament`. Starting the program does not register an entry or create a match. This repository does not support Werewolf.

This repository uses the self-hosted workflow: the platform dispatches assignments to the running process. The repository URL records the source; it does not upload or execute Python on the platform. Oracle Hosted accepts a separate Markdown agent and is not the deployment path for this code. A GitHub push alone does not update the machine running the agent. Update that checkout before starting new workers; a worker already playing a match keeps its loaded policy. Avoid stopping a live match to deploy an update.

See the [official platform guide](https://api.altruagent-game.com/skill.md) for current registration and agent-configuration requirements.

## Analyze recorded matches

Recording is enabled for new online workers by default. Red Alert samples are recorded approximately every five game seconds; Pokemon records decision observations. Logs contain selected seat-visible fields, proposed actions, execution verdicts, and independent terminal results.

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

Pokemon mechanism checks can also run against the pinned Showdown engine. The paired comparison harness accepts `COMPARE_SUITE=core` or `COMPARE_SUITE=regi`; the latter adds hand-built two-restricted archetypes with Tera disabled. Public replay observations and their limits are documented in [docs/POKEMON_RESEARCH.md](docs/POKEMON_RESEARCH.md).

The complete v7 comparison is in [reports/pokemon_mechanics_v7.json](reports/pokemon_mechanics_v7.json): 14-10 in the core suite and 5-11 in the restricted-legendary suite. All 40 final games completed without illegal actions, fallbacks, or timeouts. Earlier aborted attempts and the replay-driven correction are preserved separately. These are development fixtures, including reused seeds, not a held-out platform win-rate estimate.

The current production comparison is available in [reports/redalert_armor_economy_v6.json](reports/redalert_armor_economy_v6.json). In the 600-second low-income fixture, completed Allied tanks increased from 4 to 6 and Soviet tanks from 3 to 5, while economic expansion was delayed. It uses fixed income without combat and must not be read as a live win-rate result. Earlier revisions and their evaluation limits are summarized in [docs/HISTORY.md](docs/HISTORY.md).

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
| `hok_bot/` | Standalone Tencent Honor of Kings 1v1 policy and separate runtime. |
| `competition_agent.py` | Game routing and per-seat policy isolation. |
| `launcher.py`, `exe_entry.py` | CLI configuration and executable entry point. |
| `altruagent/` | Bundled official runtime and documented local callbacks. |
| `match_monitor.py` | Passive local recording and read-only summaries. |
| `tests/` | Regression scenarios and offline benchmarks. |

## Packaging and provenance

`bash build.sh` builds and self-tests a single executable in `dist/PokemonChampion`. Despite the historical filename, the current build includes both game policies. The target architecture and system-library requirements depend on the build machine. The repository contains no prebuilt binary; previously downloaded binaries do not receive source updates automatically.

The official runtime source and local extensions are documented in [SDK_PROVENANCE.txt](SDK_PROVENANCE.txt). Pokemon static data comes from Pokemon Showdown; provenance and included third-party licenses are under [licenses/](licenses/).

Credentials, private match histories, original-machine caches, virtual environments, and unverified legacy binaries are excluded from this repository.
