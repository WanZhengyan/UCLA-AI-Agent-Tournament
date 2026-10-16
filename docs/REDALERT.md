# Red Alert: defensive economy (`economy_guard_v14`)

The default profile remains `eco_guard`. This development candidate combines
the inherited protected-mining revision with score-aware defense, productive
miner protection and combined construction-power budgeting. The related HOK
team-contact correction is documented separately in [HOK.md](HOK.md).

## Objective and platform constraints

The [platform rules](https://api.altruagent-game.com/skill/redalert), checked on
2026-10-16, score time-limit matches by `(kills_cost - deaths_cost, assets_value)`:
efficient trades **first**, assets second. Cash alone is not a winning condition.
The policy reads the current match clock and live production availability/costs.
Destroying every enemy building and MCV still wins outright.

A refinery (`proc`) provides an unloading location and comes with a harvester.
It cannot be built anywhere merely because friendly units occupy that location:
`place.at` is only a top-left hint. The engine may place it near the construction
yard instead. Static map resources are initial hints, not current ore reserves.

## Economy and expansion

- Keep the two-refinery opening, essential power, factory and tank tech.
- Search reachable resource patches near an existing construction area for a
  refinery that shortens the delivery route by at least four estimated cells.
  Require a clear 3x3 hint, nearby owned infrastructure, safe delivery route,
  distance from known towers/enemies, and no nearby existing drop-off.
- After five game minutes, require own harvesting activity near the patch.
  A `FindAndDeliverResources` parent activity needs repeated nearby observations
  over 12 seconds; long observation gaps reset that evidence. This is still a
  heuristic, not proof of ore quantity. Suspect patches from idle-miner recovery
  and failed placement locations are temporarily excluded.
- Build useful local refineries before buying another MCV. Require at least
  three tanks, four miners, operating cash and roughly three productive minutes
  after construction. Once six tanks exist, use progressive-payment growth
  rather than waiting indefinitely for the entire purchase price in cash.
  A narrower third-refinery financing exception is available with five healthy
  home tanks, four explicitly active miners, six minutes remaining, sufficient
  projected power and screened infrastructure/placement. See [the growth
  review](REDALERT_GROWTH_V13.md); its earlier fixed-income results are historical.
- Observe where each refinery actually appeared. A fallback to home does not
  count as successful remote expansion; back off the same patch for 180 seconds.
  If a completed refinery's location becomes unsafe, place it at home to free
  the construction queue. Actual building positions govern subsequent choices.
- At most six refineries; the eight-miner ceiling can rise to 10–12 only with
  five/six actual refineries, an armored screen, observable mining activity,
  sufficient remaining time, and no genuinely idle miners. Active harvesting,
  return and unloading remain uninterrupted unless fresh observed damage and
  a currently visible nearby armed threat justify a short bounded escape.
- Preserve conservative MCV timing, terrain/fortification checks and withdrawal.
  An MCV already moving away from home receives a bounded tank escort.

## Defense and combat

- Prefer tank production over extra infantry. Keep at least three healthy tanks
  in the home group when assigning two tanks per separated mining post/MCV;
  handle at most two such posts and leave small armies concentrated.
- Place affordable ground defenses near uncovered mining areas, globally capped
  at three, with power and tank-budget checks. Prefer anti-tank defenses once the
  tank core exists or hostile armor is visible. Placement remains an engine hint.
  Reserve power for observed construction queues and accepted new construction
  in the current batch; an unplaced generator grants no future power credit.
- After five tanks, add roughly one artillery unit per five tanks, at most three,
  even without visible enemy towers. Never replace the first tanks; if artillery
  is unaffordable, continue affordable tank production instead of idling.
- Artillery guards behind the screen. In economic defense it directly attacks
  only currently visible enemies already within firing range, with two healthy
  nearby tanks ahead. Otherwise reposition behind the line; never attack-move
  artillery toward a fleeing raider. Close threats trigger withdrawal.
- Retain small-raid and major-incursion responses while guarding the economy.
  At zero or positive own kill/loss balance, cancel voluntary attack waves and
  recall them through terrain- and tower-screened holds. A positive balance
  also recalls the optional forward scout; at a tie its bounded warning role
  remains. A deficit permits only counterattacks passing the existing armor,
  trade and fortification gates. The clock does not override those safeguards.
  Own balance is not omniscient knowledge of the opponent's complete score.

## Validation and limitations

`tests/test_redalert_mining_guard.py` covers site selection, mirrored terrain,
delivery routes, hostile/depleted hints, placement fallback, budget/timing gates,
miner caps, mine/MCV guards, artillery range/screen/retreat and legal action batches.
The full suite also checks unchanged games and production/transport regressions.
Historical validation for `mining_guard_v9` on 2026-10-16: **928 tests passed**, including 46 new mining-guard
scenarios; four-game offline self-tests and spawned runtime/TLS checks passed.
A 500-decision synthetic policy check measured 0.338 ms median and 5.986 ms
maximum. A frozen-code comparison confirmed that the old four-refinery fixture
does not request a fifth refinery while the candidate does; the candidate also
requests screened artillery without requiring visible enemy towers.
These are deterministic behavior checks, **not an OpenRA match simulation or a
measured improvement in tournament win rate**. Economic thresholds and strength
estimates remain heuristics requiring live comparison.

Current v14 validation and source hashes are in
[friendly_defense_v14.json](../reports/friendly_defense_v14.json), with the
[public-code review and reproduced gaps](FRIENDLY_FIGHTER_REVIEW.md). No live
match or head-to-head win-rate comparison was run for v14.

The inherited `mining_guard_v9` review records a pre-change Sidestep formal replay
ending with a time-limit
loss: 8 miners, 4 refineries, 45 medium tanks, zero recorded kill/loss costs and
68,950 assets in the last sample. This motivates removing fixed mining limits
and improving placement, but does not establish the opponent's exact economy or
prove a counterfactual win. It is evidence about `defense_v8`, not this version.

The listener starts a fresh spawned worker for each new assignment. Source-only
deployment affects new Red Alert matches; existing games retain their already
loaded policy. No web-upload, live hot-swap or listener restart is necessary.
