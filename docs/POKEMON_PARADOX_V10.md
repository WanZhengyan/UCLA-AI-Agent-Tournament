# Paradox damage correction and evaluation design

This development change builds on `type_speed_v9`. It does not retune search or draft scoring coefficients, replace the tournament deployment, or establish a live win-rate improvement.

## Finding

Reviewing the previous comparison and the [public replay notes](POKEMON_SPEED_RESEARCH.md) prompted a check of the relationship between publicly announced stat boosts and predicted damage. Replay `gen9vgc2025regi-2341079661` includes a Special Attack Protosynthesis activation; not every activation is Speed. This observation motivates a mechanism check, not a claim that this bug caused that player's result or a particular recorded agent loss.

The v9 battle model recognized the announced stat for Speed. Its damage path still inferred an offensive boost from current weather/item and current highest stats, omitted consumed-Booster offensive activations outside that environment, and omitted defensive Paradox modifiers. Those inconsistencies could change a predicted knockout or survival threshold.

## Correction

- A shared helper prioritizes the announced stat for the Pokemon's actual Protosynthesis or Quark Drive ability. Only without that information does it infer a fresh activation from the public set and current environment.
- Consuming Booster Energy does not erase a publicly active Attack, Special Attack, Defense, or Special Defense modifier. Later stage changes do not reselect the announced stat.
- The damage modifier uses the pinned engine's `5325/4096` factor. Overall damage remains an approximate expected-value calculation, not engine-exact integer damage or a damage-roll distribution.
- Offensive modifier events follow the move's category: Body Press borrows the Defense stat, but an Attack Paradox modifier, not a Defense Paradox modifier, affects that offensive event. Defensive events follow the targeted stat, so Psyshock checks Defense modifiers.
- These Paradox abilities are not breakable by Mold Breaker. No additional opponent-private information is supplied to the policy.

The independent reference is the installed `pokemon-showdown@0.11.11`, specifically `data/abilities.ts` and `sim/battle-actions.ts`. The report records their content hashes. Corresponding upstream sources are [abilities](https://github.com/smogon/pokemon-showdown/blob/master/data/abilities.ts) and [damage calculation](https://github.com/smogon/pokemon-showdown/blob/master/sim/battle-actions.ts); those moving links are not the pinned evidence identity.

## Validation

`tests/test_pokemon_paradox.py` contains 21 cases. On frozen v9, 16 Python regressions fail, four pass, and the independent engine test is excluded because it does not execute the policy under comparison. The candidate passes all 21, including 19 independent engine checks inside that last test. The complete suite passed 663 tests, and the shared runtime self-test passed.

One full-decision fixture places Gholdengo at 40% HP against a faster Flutter Mane with a publicly announced Special Attack boost. The old estimate underestimates Moonblast and selects Make It Rain, assuming Gholdengo survives to attack. The corrected estimate selects Protect. This verifies the local survival decision, not that repeatedly protecting wins a full game.

The earlier v9-versus-v8 comparison ended 14-14, and six of seven blocks were dominated by roster differences. This revision therefore adds a mirror suite: identical rosters, paired seeds, and swapped player positions. Identical teams are not reversed again, because doing so would duplicate the same seed/game. Hand-built rosters and small samples still limit conclusions.

The first mirror block selected no non-Speed Paradox user. Those games are retained as general regressions, not counted as evidence that the new mechanism was exercised. Additional four-member fixtures ensure the relevant Pokemon must be brought. This is an explicitly coverage-driven extension of the evaluation, not an independently pre-registered tournament estimate. There is no policy tuning or seed replacement between comparisons.

The completed comparison finished **12-12**: 8-8 across 16 six-member mirror games and 4-4 across eight four-member games. All eight extension games announced a Special Attack Protosynthesis or Defense Quark Drive activation. Both policies remained frozen; all 24 games completed without harness errors, illegal choices, fallbacks, or timeouts. This does not demonstrate a winning advantage. The full test suite and self-test overlapped early extension games, so latency is not an uncontended benchmark.

Actual outcomes, latency, source hashes, activation coverage, and reproduction commands are recorded in [pokemon_paradox_v10.json](../reports/pokemon_paradox_v10.json).

## Remaining limits

Natural-versus-Booster activation source is still not fully represented. A simulated weather/terrain change can therefore retain an already-public activation when source attribution is unavailable. Other known approximations, including damage randomness, unsupported effects, and opponent response priors, remain. The comparison omits the actual platform draft and online opponents. No claim of guaranteed wins or automatic formal submission follows from these software checks.
