# Red Alert economy review and guarded growth

This development candidate addresses an identified budget bottleneck. It is
not a claim that our agent survives every game or out-earns every opponent.
No completed Red Alert recording from our account was available in this
workspace; the accessible platform session required a new Google sign-in.

## What counts as winning

The [official Red Alert protocol](https://api.altruagent-game.com/skill/redalert),
checked on 2026-10-16, compares `(kills_cost - deaths_cost, assets_value)` at the
time limit, in that order. Cash and ore balances are not the first criterion.
A direct victory requires destroying all enemy buildings and MCVs. Economic
growth must therefore finance useful surviving assets and favorable trades.

The protocol lists a refinery at 1,400 credits, 33.6 seconds and 30 power drain,
with a harvester included. Live rules override these defaults. Static resource
cells describe the initial map, not current reserves or measured income.

## Available replay evidence

Two public JSONL traces from another contestant were inspected as data, without
running their code. They are not our agent's matches or a controlled comparison.
Both come from `Khuongtdm/altruagent-entry` at the pinned revision
`0f9996b71a8ee736a5a1163f64ed02790a381b63`:

- [Multi0](https://github.com/Khuongtdm/altruagent-entry/blob/0f9996b71a8ee736a5a1163f64ed02790a381b63/ra_logs/6e47359c_Multi0.jsonl), SHA256 `1e7476205e937f5295b6c80559195c0664da3cb597f4014031b39d106253a7d6`.
- [Multi1](https://github.com/Khuongtdm/altruagent-entry/blob/0f9996b71a8ee736a5a1163f64ed02790a381b63/ra_logs/6e47359c_Multi1.jsonl), SHA256 `11902ac3247c84e72b949bbd7a727c6248218aa947d8f9d7cc3dab3d894de630`.

Each contains 122 `type=snap` records. Reading their `gs`, `eco`, `bld` and `mil`
fields gives the following observations:

| Observation | Multi0 | Multi1 |
| --- | ---: | ---: |
| First snapshot with two harvesters | 450 s | 140 s |
| Harvesters at 300 s | 1 | 3 |
| Harvesters at 450 s | 2 | 6 |
| Refineries at 450 s | 1 | 3 |
| Assets at 450 s | 13,900 | 30,300 |
| Assets at 605 s | 0 | 38,500 |

The final snapshot suggests Multi0 was eliminated, but these files contain no
independent final-result record. The economic gap is observational, not proof
that a particular build order caused the outcome. Both sides repeatedly had
zero cash while spending ore, so banked cash alone would misdescribe their
economies. The inspected traces are not bundled into this repository.

## Change in this candidate

Previously, the third refinery needed its full price plus a tank operating
reserve until six tanks existed. Recurring tank purchases could keep a
low-income base below that full-price threshold. The earlier
[v6 report](../reports/redalert_armor_economy_v6.json) already documented the
resulting delay to economic growth.

`economy_growth_v13` adds one earlier financing window. The third refinery can
use progressive payments after five tanks when all of these checks pass:

- Exactly one construction yard and two refineries; at least four actual
  harvesters explicitly reporting non-idle activity.
- At least five tanks with at least 70% health within 22 cells of the same
  construction yard, and at least 360 seconds remaining.
- Power covers the refinery's live drain plus a 10-unit margin, and the policy
  is not recovering from a recent unfavorable trade.
- No nearby known threat or tower coverage contradicts investing at home.
  When terrain is supplied, the proposed site and a nearby initial resource
  hint must have reachable, screened routes. Missing terrain retains the
  existing placement fallback; it does not establish safety.

The next tank's operating reserve remains protected. The earlier three- and
four-tank candidates were rejected because the fixed-income development
fixtures could lose one completed tank at ten minutes. The existing six-tank
financing rule, full-price expansion-MCV rule, miner replacement, emergency
responses and late infrastructure cutoff remain in force. Active harvesters
are not redirected. Non-idle activity and an initial resource hint do not prove
successful deliveries or future payback.

## Reproduce the budget comparison

```bash
python tests/redalert_economy_compare.py \
  --baseline cc79a31fc8a5c433495deb9de484c86ecec27556 \
  --output reports/redalert_growth_v13.json
python -m pytest tests/test_redalert_growth.py tests/test_redalert_tank_priority.py -q
```

The comparison loads only the trusted baseline economy module from this
repository and holds the rest of the candidate code fixed. It records both
factions at 4, 8 and 16 credits per harvester per second, from a 5,000-credit
start through 1,200 seconds. Cumulative income, actual fixture spending,
completed tanks and refinery/harvester milestones are recorded separately;
income conservation is checked. The source hashes and full timelines are in
[the generated report](../reports/redalert_growth_v13.json).

| Fixed income per miner/s | Faction | Third refinery, baseline → candidate | Extra income at 20 min | Tanks at 20 min, baseline → candidate |
| --- | --- | --- | ---: | --- |
| 4 | Allies | 1,104 → 1,104 s | 0 | 7 → 7 |
| 4 | Soviets | Not completed in either run | 0 | 7 → 7 |
| 8 | Allies | 593 → 566 s | 432 | 32 → 33 |
| 8 | Soviets | 652 → 617 s | 568 | 23 → 24 |
| 16 | Allies | 385 → 376 s | 480 | 44 → 44 |
| 16 | Soviets | 389 → 389 s | 0 | 33 → 33 |

At ten minutes, tank counts remain unchanged in all six cases. At income 8,
the sixth harvester completes 27 seconds earlier for Allies and 36 seconds
earlier for Soviets. The very-low-income cases do not improve: this narrow
window is not a general solution for severe economic starvation.

Validation passed **887 tests**, including **42 new growth scenarios**, with
the optional pinned Showdown checks enabled. The frozen baseline fails nine
of those new scenarios. All four platform policy self-tests and spawned
runtime checks also passed. The other three games' strategy code is unchanged
from the pinned parent revision.

This is a production fixture with stationary actors, fixed income and no
opponent, combat, losses, harvesting routes, unloading queues, depletion,
power slowdown or multi-factory speed model. It uses no actual military-score
fields to infer wins. The scenarios informed threshold selection and are not
held-out validation. Safety decisions are checked separately with map,
threat, damaged-unit and endgame scenarios.

## Remaining live validation

Use completed, seat-local logs from `validation/match_monitor/` on the machine
running the agent, or export the relevant platform replay. Preserve match ID,
map, faction, policy hash, and independent result. At 5, 10, 15 and 20 minutes,
review miner/refinery counts, idle periods, power, accepted production,
`kills_cost - deaths_cost` and `assets_value`. Only compare both players'
economies when the completed replay legitimately exposes them. Visible enemy
units during play are not a complete economic census.

Do not infer live income from cash differences alone: construction, repairs,
sales and refunds also change the balance. Keep private recordings out of
GitHub. No running listener or formal tournament entry was changed by this
revision.
