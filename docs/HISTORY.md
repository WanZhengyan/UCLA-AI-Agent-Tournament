# Revision History and Evaluation Notes

This document preserves the relevant history of the original local builds. It is not a current deployment record. Some referenced experiment outputs were retained only on the original machine and are intentionally absent from GitHub. Use the main [README](../README.md) for current setup commands.

## Pokemon mechanics and standalone Honor of Kings (v7, 2026-10-16)

Pokemon `mechanics_v7` improves the approximate simulator used by joint-action search. Multi-hit attacks apply Stamina, Multiscale, Focus Sash, berries, and contact reactions per hit. Drain healing precedes contact recoil. Electro Shot and Meteor Beam gain their Special Attack boost before damage; rain, Power Herb, and Utility Umbrella affect the charge turn. Unaware, immediate Lum/Chesto/Mental Herb cures, Unnerve's berry suppression, and Punching Glove versus Unseen Fist are modeled more accurately. Koraidon and Miraidon set weather/terrain on entry and receive their conditional offensive-stat boosts. Variable hit counts and other damage details remain approximations.

Two public Showdown replay timelines and authored VGC strategy references informed focused scenarios; they are documented in [POKEMON_RESEARCH.md](POKEMON_RESEARCH.md). The old source fails 22 of the 30 new Python scenarios, while the new source passes all of them. An additional test makes nine independent checks against the pinned Showdown engine. The comparison harness now rounds opponent HP to displayed percentages and includes a separate suite of three hand-built two-restricted Regulation I archetypes. It still omits the actual platform draft, some volatile effects, and exact field durations.

The new `hok_objective_v1` is a separate Tencent HoK1v1 rule baseline: last hits, wave-backed structure pressure, favorable trades, legal actions, retreat, healing, and recall interruption handling. It has no AltruAgent game-type registration because the event website currently marks Honor of Kings unavailable. It is not the announced 5v5 event interface. [HOK.md](HOK.md) gives the licensed-engine prerequisites and commands.

Research inspected 200 official HoKOff turret-destruction trajectories containing 136,535 decisions. The action adapter passed every recorded action and 10,362 constructed choices across their masks. This checks action encoding, not the new policy's gameplay. The recordings remove the opposing hero; no competitive win rate is implied. Published TensorFlow checkpoints were not integrated because their 725-feature encoder does not match the pinned SDK's 453 features. Sources, integrity hashes, and limitations are in [HOK_RESEARCH.md](HOK_RESEARCH.md).

Validation: 468 Python tests passed with both optional Showdown tests enabled; the AltruAgent executable self-test and a separate Python 3.8 HOK smoke check passed. No licensed HOK engine match or live AltruAgent match was run for this revision. Repository documentation remains English, and the launcher reports version 1.3.0.

## Red Alert: armor budgets and idle harvesters (v6, 2026-10-16)

`armor_economy_v6` preserves tank production cash before optional infantry, defenses, radar, and early expansion. Power, replacement harvesters, tank technology, nearby enemy responses, and the guarded-map opening screen remain priorities. A six-tank core allows progressively financed refinery growth; expansion MCVs require their full price plus a tank operating reserve.

Idle harvesters first try native harvesting, then bounded retries toward reachable initial resource patches near surviving refineries. Assignments spread across patches and refineries, and repeatedly unsuccessful destinations receive temporary cooldowns. An idle harvester already in a known danger zone receives short escape waypoints that reduce exposure. Active movement, harvesting, and unloading are left alone. Initial resource cells are hints, not live ore or cargo measurements.

In the 600-second fixed-income production fixture, Allied tanks changed from 4 to 6 at low income and 14 to 16 at medium income; Soviet tanks changed from 3 to 5 and 11 to 11. Infantry decreased from 15 to 9 in each case. Low-income economic growth was delayed: Allied harvesters changed from 6 to 5 and Soviet harvesters from 6 to 4 at the cutoff; medium-income counts stayed at 6. Full data and reproduction details are in [redalert_armor_economy_v6.json](../reports/redalert_armor_economy_v6.json). This isolates production behavior and does not measure harvesting gains or match win rate.

Repository documentation and launcher output were converted to English, with deployment steps in [PLATFORM.md](PLATFORM.md). Documentation does not assert that an account has connected or registered successfully.

## Red Alert: replay and map corrections (v5, 2026-10-16)

`replay_map_guard_v5` retained `eco_guard` as the deployment profile and added:

- Persistent movement while retreating, preventing the next observation from immediately converting retreat into an attack-move.
- Separate anti-air orders for rocket infantry, preventing duplicate commands from invalidating a ground group's orders. Units return to the ground group when the air threat leaves.
- Rally points projected onto reachable land using the public terrain graph.
- Rechecking cached expansion destinations and routes against newly observed threats.
- Offline review of monitoring and older self-play records, with grouping by map, source version, faction, seat, and match duration, plus sampling gaps and economic/combat warning timelines.

The prior revision reported 363 passing Python tests and one optional Showdown test skipped. Seven focused regression scenarios failed on v4 and passed on v5. These were behavior checks, not win-rate comparisons. No private historical match logs or actual map-configuration snapshots were available for that revision; the route tests used synthetic terrain.

## Red Alert: tank-centered economy (v4, 2026-10-15)

`armor_guard_v4` prioritized power and harvesting, added the service depot needed for medium/heavy tanks, and preferred a second war factory over extra barracks once the economy supported it. Tank start/production reserves and infantry caps aimed to prevent small recurring infantry purchases from consuming all income.

Offensive groups needed healthy tanks rather than merely nominal tank counts. Matchup estimates reduced infantry strength against armor, while unfavorable engagement checks still applied when behind or near the time limit. Expansion required armored cover; known towers still triggered avoidance and conditional siege support.

The historical validation reported 304 checks plus game/worker self-tests. In a ten-minute, fixed-income simulation without combat, the earlier low-income policy produced 31 infantry and no tanks for either faction. The new policy produced 15 infantry and four Allied tanks, or 15 infantry and three Soviet tanks, with unchanged harvester counts. This supported the intended budget direction only. The retained report is [redalert_armor_guard_v4.json](../reports/redalert_armor_guard_v4.json).

## Red Alert: map adaptation (v3, 2026-10-15)

`map_guard_v3` used the current map identifier, public spawn locations, initial resource regions, and public terrain to build a conservative ground-connectivity graph. Short routes encouraged earlier defensive support and tighter expansion limits; sufficiently long connected routes with nearby initial resources permitted a more economic opening.

Expansion timing considered remaining match time, runtime build durations, approximate ground travel, and a conservative income window. Unknown or disconnected terrain triggered conservative fallbacks rather than mirrored-map assumptions. A limited forward infantry scout provided early warning without unlimited replacement attempts.

Initial resource metadata did not prove that ore remained at a location. Ground routes, payback windows, and matchup weights were approximations, not learned optima or engine-exact calculations. This revision had synthetic terrain checks but no recorded live map-by-map win-rate comparison.

## Red Alert: early balance and self-play work (v1-v2, 2026-10-15)

The first dual-game integration added protected economy growth, home defense, exposed-target selection, remembered tower avoidance, regrouping after poor trades, and separate siege attacks. Historical checks increased from 135 at integration to 159 after the initial balance update. Three paired decision scenarios showed the old group charging towers while the updated group held outside estimated range and used siege units separately.

The self-play framework only activated after official assignments confirmed both Testing seats belonged to the account. It isolated policy state, alternated seats on compatible successive games, and compared only complete, same-source-version results. Faction and random-seed differences remained potential confounders.

A live v1 finding exposed incorrect `place` orders for completed infantry and vehicles. v2 limited placement to Building and Defense queues for both comparison policies and improved final-order verdict logging. It also removed unconditional late-game retreat as a candidate response to observed late harvester losses. That observation did not establish a unique cause of those losses.

Some v1 terminal files were recovered from the authoritative supervisor console and explicitly marked `supervisor_console_recovered`; periodic samples were not relabeled as exact terminal observations. v2 separated saving the official outcome from parsing the terminal observation so a snapshot error would not discard the result.

Automatic comparison was later disabled. Current settings remain in `validation/redalert_selfplay/settings.json`; historical private logs are not included.

## Passive match monitoring (2026-10-15)

New online workers gained bounded local recording for both games. Red Alert sampled approximately every five game seconds; Pokemon recorded decision observations and elapsed time. Separate terminal-result files fed a review queue for confirmed losses, forfeits, and timeouts.

Logs contain selected seat-visible fields, not keys, raw contexts, hidden opponent state, or spectator data. A recorded proposed action does not establish that the server accepted it. Missing terminal results remain unknown, and a stale file alone does not establish a disconnect or loss. Existing workers were not instrumented retroactively.

## Pokemon search revisions (2026-10-15)

The local source first corrected speed-tie bias, Sucker Punch after a target had already acted, responses to stat drops, Ice Spinner terrain removal, and screen-breaking move simulation. Historical validation reported 70 passing tests, including eight independent Showdown mechanism checks. Thirteen new tactical scenarios failed on the older source and passed after the corrections. A 24-game comparison remained 20 wins and four losses for both versions; it did not demonstrate an improved live win rate.

A later revision simplified battle scoring to weighted expected value, removing additional CVaR/worst-case penalties while retaining the response candidates and tactical mechanisms. Draft and team selection were unchanged. Historical validation reported 75 passing tests and successful offline runtime checks. A corrected 48-game source comparison, with lineup/seat swaps and isolated per-game memory, yielded 25 wins for the new version and 23 for the old. Fixed greedy/random opponents remained 20 wins and four losses. A four-response speed variant fell to 18 wins and was not adopted.

An earlier comparison reused session identifiers across lineup swaps; its statistics were invalidated. The corrected small offline comparisons still did not measure platform draft or tournament performance.

## Original Linux release

The original Pokemon-only release was a Linux x86_64 ELF executable, despite informal references to an "exe." It was validated on a glibc-based build environment, not ARM64 or musl-only Alpine. Historical checks included 53 project tests, official runtime tests, frozen worker imports, dynamic policy loading, TLS/MCP initialization, and independent Pokemon Showdown 0.11.11 benchmarks.

That release's offline benchmark used four manually selected teams and simple greedy/random opponents. It did not validate live account assignments or real tournament drafts. Later source changes did not rebuild or update that downloaded binary. Build current source with the current `build.sh` instead of assuming an old artifact contains the new policies.
