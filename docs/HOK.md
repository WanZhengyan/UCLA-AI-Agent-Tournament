# Honor of Kings 5v5 on AltruAgent

The platform now documents `honor_of_kings_5v5`: **one agent controls five heroes**, with one opponent controlling the other five. This repository's `hok_platform` policy implements that interface without an LLM or model API key. The separate Tencent 1v1 runner remains in `hok_bot`; its setup is archived in [HOK_TENCENT_1V1.md](HOK_TENCENT_1V1.md).

The current [official HOK guide](https://api.altruagent-game.com/skill/hok), retrieved October 16, 2026, supersedes older availability banners. The initial `hok_team_v1` release had offline validation only. Subsequent live records exposed excessive fighting and long recovery: one losing team had 27 kills but only about 2,375 observed damage to enemy structures. These observations motivated `hok_objectives_v2`; they do not establish its win rate.

## Current team-contact revision (`hok_team_guard_v14`)

Defense allocation and individual danger checks now use the same bounded set of current enemy contacts visible to our five owned heroes. This fixes an isolated defender attacking three enemies seen through a teammate while evaluating only its own narrower view. Contacts require explicit visibility, living health and finite coordinates; duplicates are reconciled conservatively, and conflicting identities or unowned views are rejected. No hidden positions or contact history enter this collection.

The inherited tower-defense, health, recovery and legal-action safeguards remain. Safe structure attacks and minion clearing still have priority: the timed HOK tiebreak compares enemy structure damage before hero kills, so passive defense alone is not the objective. See [the v14 review](FRIENDLY_FIGHTER_REVIEW.md) and [validation record](../reports/friendly_defense_v14.json). No v14 live win-rate comparison was run.

## Previous tower-defense revision (`hok_guard_v4`)

The goal remains destroying the enemy crystal and gaining structure damage, while preventing avoidable losses of our own towers. This adds ordinary-tower defense to v3's combat safety instead of reverting to constant retreat or sending all five heroes home.

- Track friendly tower/crystal HP across owned team observations. A decrease between observations no more than five game seconds apart triggers a four-second recent-hit alarm, even without a visible enemy hero (for example, a minion wave). A visible enemy within 9,000 units is a separate proximity warning, not proof of an attack. Old missing HP alone does not trigger defense.
- Deduplicate structures and visible attackers across the five owned views. Prefer nearby living heroes above 45% HP; do not call a distant hero from the other end of the map. Ordinary tower threats share a maximum of three defenders: one for damage without a visible hero, normally two for one visible attacker. Other heroes keep their offensive policy and receive fair command scheduling.
- Prioritize the crystal. At or below 35% HP under an active warning, up to five available heroes may reinforce; low-health and severe-damage safeguards still apply, with bounded last-stand behavior. A safe immediate enemy-crystal finish retains priority over ordinary rotations.
- Choose only offered advance/retreat macros whose direction toward an observed enemy structure/home fountain also points toward the threatened building. No lane IDs, raw movement coordinates, hidden positions or exact aggro are guessed. Once nearby, clear a legal nearest enemy/minion target or use a listed skill.
- If no attack is available at the guard point, an explicitly listed neutral button can cancel a stale advance standing order. Without that offered button, no neutral action is invented. When the enemy leaves and recent damage expires, ordinary objective pressure resumes; a destroyed tower is not defended.
- Reset building/assignment memory on a new game, account, camp or timeline rewind. A handful of old damaged towers cannot trap the whole team at home forever.

Validation: 882 tests passed, including 37 new tower-defense, damage-history, mirrored-camp, neutral-action and team-allocation regressions, plus existing safety/other-game tests. This is scenario/protocol validation, not a demonstrated win-rate increase. Exact pathing and target selection remain constrained by server macros. Updates load in new workers without interrupting current official games.

## Previous balanced revision (`hok_balanced_v3`)

This combines v1's combat/retreat safeguards with v2's structure objective. Live v2 observations showed isolated, freshly respawned heroes advancing into multiple defenders. The old disadvantage test only retreated below 70% HP; full health incorrectly bypassed it. The time-based advance window and 4,500-unit blocker cutoff also allowed walking past ranged threats. A seat-visible scenario from step 979 is now a regression test, not a simulated win-rate experiment.

- Remove the timed combat-to-advance window entirely. Fight visible blockers out to 9,000 units; bypass only distant or rearward distractions with no recent damage. Safe, offered structure attacks still take priority over optional hero combat.
- Compare nearby living allied/enemy health-and-level proxies even at full HP. A materially outnumbered hero retreats; dead, far-away or unowned heroes do not count as support. A two-second retreat hold reduces immediate re-entry, and adequate nearby reinforcements release it early.
- At a visibly defended enemy building, require at least two nearby allies above 45% HP and adequate relative strength before sieging. Missing minions or tower proximity alone do not cause retreat. Undefended buildings remain valid targets.
- Restore earlier burst-damage escape: 14% recent HP loss below 75% HP, or 30% loss at any HP. Minor chip damage does not cancel a safe siege. Start recovery at 32%, exit at 60% (55% near the observed fountain); this avoids both v2's early 42% re-entry and v1's long 68% wait.
- A low enemy crystal is not an unconditional suicide command: its finish exception requires over 32% own HP, no local disadvantage or fresh burst, and at most 10% crystal HP. Routine home defense also requires adequate health/safety. A friendly crystal below 20% can trigger a bounded last stand rather than ordinary healing.

Validation: 845 tests passed, including 28 additional safety regressions and updated intentional tactical expectations, plus four-game self-tests and spawned runtime checks. Only HoK strategy, its tests/documentation and HoK-only telemetry reasons changed. These checks do not establish competitive win rate. New match workers load this revision; existing official games are not restarted or modified mid-game.

## Historical objective-first revision (`hok_objectives_v2`)

- Keep legal tower/crystal attacks ahead of optional hero combat; ordinary chip damage does not interrupt a healthy siege. A legal attack on a crystal below 15% HP can finish it even during recovery, provided our hero has over 15% HP.
- Advance past distant or rearward enemy-hero distractions when an observed living enemy tower/crystal is the objective. Against a close blocker, a healthy supported hero fights briefly (2.4 seconds), then commits to a 3-second advance window. Low HP, severe incoming damage and an unfavorable local fight still cancel that push. Minion attacks remain available to clear waves.
- Reduce recovery exit from 68% to 55%, or 42% when the hero is actually near its observed friendly fountain. Enter recovery at 28%; do not confuse a respawn with an old recovery state.
- When a visible enemy threatens a nearby friendly crystal below 55%, heroes above 23% HP attack if possible, leave the fountain to rejoin the lane, or retreat from the frontline toward their own crystal. A crystal at risk overrides routine healing, not missing/hidden information.
- Use only listed macros. The server still attacks the nearest target: this policy cannot force an arbitrary tower target, lane or raw movement coordinate.

Validation: 817 tests passed, including 23 new objective/recovery/defense cases across both camps, plus the existing other-game suite. These are protocol and scenario checks, not a measured live win-rate improvement. Existing match workers retain their loaded policy; fresh workers load the deployed revision without restarting the listener.

## Start a test

Use `improve/friendly-defense-v14`. In an existing checkout:

```bash
git fetch origin
git switch improve/friendly-defense-v14
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py --check
.venv/bin/python exe_entry.py --match
```

If needed, create the environment with `python3 -m venv .venv` first. Enter the platform's Official Agent Key at the hidden prompt. No OpenAI key, local game installation or Tencent gamecore license is needed for this platform integration.

On **Dashboard → Testing**, select **Honor of Kings**, use **Mine (self-hosted)** for your team and create/join a test. Keep one listener per key. The initial HoK integration changed the assignment filter and runtime: a pre-HoK listener must be restarted after its active matches finish. Once running the four-game listener, subsequent policy-only updates load in fresh match workers without restarting existing games. Rebuild an old executable before use.

For official games, register in the applicable HOK tournament and run `exe_entry.py --tournament`, or run without flags to accept both testing and official assignments. A push, connection check or test match does not register a tournament entry. Follow the event's current version-lock instructions.

## Decisions

- Prioritize a listed tower/crystal basic attack when the current safety checks permit a siege. Offered attacks are already range-checked by the platform; a guessed skill range must not discard them.
- Advance toward objectives when no useful attack exists. Do not retreat solely because a tower is nearby or the summary omits minions.
- Retreat on low health, fresh severe damage, local disadvantage even at full HP, or an unsupported attack into visible building defenders, subject to the balanced revision's narrow finish/last-stand exceptions. A health/level proxy considers nearby healthy teammates rather than counting every hero equally.
- Keep recovery/damage history per hero and reset it on death, respawn, changed team/session, or timeline rewind. Separate recovery thresholds reduce oscillation. Critical own-crystal defense can interrupt ordinary recovery when an attack is legal and the local estimate permits it.
- Cast currently listed skills only with a parsed nearby enemy-hero target. Reserve the third skill for multiple nearby visible enemies, a weakened enemy, or immediate combat pressure. Unknown hero-specific effects remain a limitation.
- Replace unavailable skills with available attacks/advance; prioritize urgent retreats and otherwise rotate fairly across heroes. Do not overwrite unchanged standing orders.
- Ignore hidden enemies even if stale coordinates remain. No spectator data, messages or external network calls enter the policy.

Macros choose the **nearest target**. This version cannot select arbitrary targets, lanes, jungle routes, heroes, equipment or builds through undocumented raw fields. It does not claim precise focus fire or a complete mobile-game strategy. Raw listed actions are used only for an explicitly offered neutral guard hold or a protocol fallback; no button is guessed to be heal or recall. Thresholds are development heuristics requiring live calibration.

## Runtime and records

Macros remain standing orders and are re-evaluated by the server every 0.2-second game step. Real-time mode sends changed orders consecutively, pausing 0.6 seconds before re-reading only when no updates are needed. Lockstep sends an action for every pending hero even if its standing macro is unchanged. A rejection is not treated as confirmation; repeated invalid actions at one version are suppressed.

Bounded, sparse records under `validation/match_monitor/` contain team-visible health, deaths, positions, visible enemies, structures, orders, verdicts and independent final results. Credentials and hidden coordinates are excluded. HOK MCP returns `+1`, `-1`, `0` mean win, loss, draw; server failures are not losses. Keep local records outside GitHub.

Review actual tower/crystal HP changes, recovery time, stale skill orders and whether every hero receives updates. Compare both camps and multiple real opponents before claiming strength. [HOK_PLATFORM_RESEARCH.md](HOK_PLATFORM_RESEARCH.md) records sources and limits; [hok_platform_v11.json](../reports/hok_platform_v11.json) records validation and source hashes. Earlier [Tencent 1v1 research](HOK_RESEARCH.md) does not measure this policy's 5v5 performance.
