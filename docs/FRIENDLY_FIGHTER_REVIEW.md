# Friendly Fighter review and defensive improvements

Reviewed on 2026-10-16. This is public-code research followed by independent
regression fixes, not a head-to-head match or a claim of guaranteed wins.

## Source identity and scope

The public repository [lukemt/friendly-fighter](https://github.com/lukemt/friendly-fighter)
explicitly identifies itself as a UCLA AltruAgent Red Alert agent. The reviewed
revision is `a11f1624609646d5dcbf0f6033677ee0f9fee244`. Its deployed platform
version and account identity were not independently verified.

The only public branch found was `main`. The repository's
[dispatcher](https://github.com/lukemt/friendly-fighter/blob/a11f1624609646d5dcbf0f6033677ee0f9fee244/agent/agent.py)
has a dedicated Red Alert path and generic fallback for other games. No
verified Honor of Kings implementation was found in this repository or the
owner's public repositories. Our HOK correction below addresses our own
reproduced behavior; it is not attributed to this opponent.

The opponent's source was read as text. No opponent code, simulator, tests or
installation script was executed, and no implementation was copied. The
current policy uses only our assigned seat/team observations.

## What is useful to learn

The [Red Alert controller](https://github.com/lukemt/friendly-fighter/blob/a11f1624609646d5dcbf0f6033677ee0f9fee244/agent/redalert_bot.py)
provides the following useful engineering patterns:

| Pattern | Our assessment and action |
| --- | --- |
| Plan power ahead of the next building | Already present for individual purchases; this revision extends our accounting to simultaneous known construction commitments. |
| Maintain miners and promptly place finished buildings | Already present, including future miners supplied by refineries and bounded idle-miner recovery. Preserve this behavior. |
| Gather reinforcements and avoid small unsupported waves | Our army already stages near home and uses local trade/defense gates. Retain the guarded posture instead of blindly increasing attack frequency. |
| Stop launching unnecessary waves when ahead late | Apply the requested stronger defensive posture throughout the game: a nonnegative own trade balance cancels voluntary waves. Cash alone does not determine the Red Alert tiebreak. |
| Factory before the second refinery | A different opening tradeoff, not established as superior on our maps. Retain our current opening pending real match evidence. |

The controller also supports an optional harvester-targeting mode, grouped
armored waves, and occasional artillery. These are possible public-code
behaviors, not proof of the opponent's current configuration. Its local
benchmark notes warn about greedy openings and poor attacks into defended
bases; those are self-reported experiments, not our validation results.

## Reproduced gaps and independent corrections

### Defend the economy while the trade score is nonnegative

The [official Red Alert tiebreak](https://api.altruagent-game.com/skill/redalert)
compares `(kills_cost - deaths_cost, assets_value)` in that order. Cash alone
cannot compensate for a worse first component. The default policy now avoids
voluntary economic raids at zero or positive own trade balance, cancels existing
attack waves and retains local responses to incursions. A positive balance also
recalls the optional forward scout. At a tie, the existing bounded cheap warning
scout remains available to reduce blindness; it is not an attack wave.

A deficit can still justify a favorable armored counterattack, including near
the deadline, subject to the existing trade and known-tower safeguards. This is
a defensive preference, not knowledge of the opponent's complete score or a
guarantee that waiting wins. Recall paths must respect supplied terrain and
known fortifications; an obsolete forward order must be canceled when a safe
return route is unavailable.

The integrated mining escorts and rear artillery share this route controller.
Artillery target IDs are tracked explicitly: if the old target leaves range,
an in-range replacement is not suppressed merely because it stands near the
old target's last position. Refused retargets attempt a local stop; only accepted
orders update history. This closes a merge-time regression that could otherwise
turn defensive fire into pursuit.

HOK retains safe structure pressure: its timed tiebreak uses enemy structure
damage before kills. The same passive-only policy would not optimize that rule.

### Protect productive harvesters under a confirmed threat

Previously, the recovery controller skipped every non-idle miner. In a mapped
fixture, a harvester actively mining beside a visible tank received no escape
order when its observed HP fell from 100 to 70. The same unit received a safe
escape as soon as it was marked idle.

The new exception uses recent observed damage plus a currently visible armed
threat near the miner to permit a short escape. It reuses bounded, terrain-aware
waypoints and throttling. Existing wounds alone, healthy production, unknown
or stale health, and unseen enemies do not justify interrupting productive
traffic. This protects the economic asset; it does not estimate exact damage,
cargo value, or the cause of the observed hit.

### Budget construction and defense power together

The prior planner checked each purchase against the same current surplus.
With 60 power spare, a queued refinery consuming 30 and a new gun consuming 40
could each pass alone and leave a 10-power deficit together. The same problem
could occur when both orders were emitted in one batch.

The correction accounts for known outstanding consumers and accepted new
construction before admitting a powered defense. Live item rules override
defaults. An unplaced generator does not supply power yet. Zero-drain
defenses remain possible. This reduces avoidable production slowdown without
changing the tank reserve or copying an opponent's build order.

The projection includes observed production queues and accepted construction
from the current planning batch. Earlier submitted orders absent from the
observation are not visible to this planner's separate runtime in-flight map;
the correction does not invent persistent estimated reservations for them.

The guarded third-refinery window from
[v13](REDALERT_GROWTH_V13.md) remains included. Its fixed-income gains are
historical development evidence, not a real-map return-on-investment promise.

### Use the same team-visible threat picture in HOK

The inherited HOK policy pooled owned-team contacts for assigning defenders,
but each hero assessed local danger using only its own view. A test with three
enemies visible through a teammate assigned a lone hero to attack; copying
those identical already-authorized contacts into that hero's view correctly
caused retreat.

One current-snapshot contact collector now supplies both decisions. Contacts
are deduplicated and limited to explicitly visible living opponents reported
by our owned heroes. Hidden, stale, malformed and opposing-seat observations
cannot expand the threat picture. This does not reveal fog or guess enemy
positions. Existing objective pressure, minion clearing and bounded defender
allocation remain intact.

## Validation and deployment boundaries

Focused regression files exercise the reproduced cases and their safety
boundaries:

```bash
python -m pytest tests/test_redalert_defensive_posture.py tests/test_redalert_raid_safety.py \
  tests/test_redalert_artillery_safety.py tests/test_redalert_power_commitments.py \
  tests/test_redalert_growth_integration.py tests/test_hok_team_contacts.py -q
python -m pytest tests -q
python exe_entry.py --self-test
```

The source hashes and final checks are recorded in
[friendly_defense_v14.json](../reports/friendly_defense_v14.json).
The complete suite passed **1108 tests**, including 138 new v14 scenarios, plus
four-game policy self-tests and spawned worker/MCP/entry/TLS checks. Independent
review found and verified fixes for covered terrain detours, disconnected-unit
recall, stale artillery targets and the merged mining financing gate.

The [fixed-income comparison](../reports/redalert_economy_v14.json) against our
own `b6be880` economy preserves ten-minute tank counts in all six cases. At
income 8 per harvester per second, the third refinery completes 27/35 seconds
earlier for Allies/Soviets; cumulative twenty-minute income rises by 432/568
and completed tanks by one each. Income-4 cases do not improve. This retains
the earlier guarded-growth effect; it does not measure travel, congestion,
ore depletion, power slowdown, enemy economy, combat or a match result.

No live match, opponent-code execution or win-rate comparison was run. The
changes integrate protected mining/escorts/artillery from `b6be880`, HOK tower
defense from `1817737`, and guarded third-refinery growth from `ebd78e4`.
The five-tank financing exception checks the actual selected mining-site hint.
Pokemon and Werewolf strategies are unchanged.

This is a GitHub development candidate. A source push does not update a
running self-hosted listener or formal tournament entry. Private logs and
credentials are not included in the repository.
