# Pokemon research notes — 2026-10-16

These notes document public observations and implementation hypotheses. They are not a live win-rate estimate. No private match replay was available.

The later [type and speed-control review](POKEMON_SPEED_RESEARCH.md) inspects three additional public timelines for v9. It records the distinction between type matchups, move priority, current effective Speed, and control duration. The v9 comparison adapter adds a narrow public Speed-effect whitelist; the policy can infer Tailwind/Trick Room age from uninterrupted observed activation, but leaves duration unknown when it first sees an already-active condition or misses turns. Other volatile effects and field durations remain approximate.

## Platform format

Official guide: https://api.altruagent-game.com/skill/pokemon

The UCLA event uses `pokemon_vgc_doubles_draft`: 18 public fixed-set cards, snake draft `A B B A A B B A A B B A`, six picks per player, per-player Item Clause, then bring four and lead two. Each draft decision has a 15-second deadline. Battle format example is `gen9vgc2025regi`, with Terastallization disabled by the platform. Do not copy Tera-dependent decisions from ordinary VGC replays.

## Public replay observations

Raw `.log` and `.json` retrieval was inaccessible, but the public replay UI rendered successfully. The observations below were read from the complete visible timeline after clicking **Skip to end**. URLs were checked with the browser URL API.

### Electro Shot boosts before damage

https://replay.pokemonshowdown.com/gen9vgc2025regg-2290695151

- Turn 3: Rain is active. Archaludon uses Electro Shot, gains one Special Attack stage, and immediately deals 95% to Braviary-Hisui. Kyogre finishes Braviary.
- Turn 4: Archaludon gains another Special Attack stage before Electro Shot KOs Growlithe-Hisui.
- These interactions precede Archaludon's turn-5 Terastallization. They support testing rain-based Electro Shot's boost timing, not a claim about which opening is optimal.
- Turn 2: Amoonguss puts Calyrex-Ice to sleep; Lum Berry immediately cures it, and Calyrex-Ice then uses Glacial Lance to KO Amoonguss. A simulator that treats this Spore as an unconditional lost turn overvalues the action.

### Wide Guard changes the joint-action result

https://replay.pokemonshowdown.com/gen9vgc2025regi-2367786123

- Turn 5: Hitmontop uses Wide Guard, which blocks both targets of Tornadus's Bleakwind Storm. Zacian's single-target Behemoth Blade still damages Terapagos. Terapagos KOs Tornadus that turn.
- Turn 7: Urshifu's Surging Strikes resolves three separate critical hits against Kyogre before Kyogre attacks.
- This match uses Terastallization and ends by forfeit. It is evidence for particular mechanics and candidate coverage, not a platform win-rate or strategy ranking.

## Primary authored strategy references

- https://www.smogon.com/dex/sv/pokemon/archaludon/vgc/ — authored VGC analysis linking Stamina defense boosts, Body Press, Electro Shot Special Attack boosts and Pelipper rain.
- https://www.smogon.com/dex/sv/moves/electro-shot/ — boost and charge semantics; rain/Power Herb permit immediate execution, while Utility Umbrella changes the rain interaction.
- https://www.smogon.com/dex/sv/pokemon/urshifu-rapid-strike/vgc25-regulation-i/ — authored Regulation I analysis specifically describing Amoonguss redirection and Rocky Helmet as a response to Surging Strikes.
- Repository's installed `pokemon-showdown@0.11.11` source is the definitive independent mechanism reference for its pinned offline engine.

## Evaluator observations

The first completed v7 Regulation I comparison scored six wins for the candidate and ten for the old policy. Reviewing its local Showdown logs exposed a concrete simulation omission: switching Koraidon into Archaludon's Electro Shot replaced rain with sun in the engine, but the policy's switch-entry model left rain active. The candidate therefore predicted an immediate attack where the engine required charging. The follow-up correction adds Orichalcum Pulse's sun, Hadron Engine's Electric Terrain, and their conditional offensive-stat boosts, with independent engine checks. These development games informed the correction; rerunning their seeds is a regression comparison, not a held-out estimate of tournament strength. All completed experiments and aborted attempts are recorded in the final report.

`tests/showdown_compare.js` correctly uses isolated policy processes, unique per-game/session identities, paired seeds with team/seat swaps, code hashes and explicit limitations.

Remaining limitations:

1. Handcrafted rosters rather than the actual platform card pool; no full 18-card draft evaluation. The v7 harness now adds three two-restricted archetypes in its separate `regi` suite.
2. The v7 comparison adapter now rounds opponent HP to displayed percentages; it previously exposed exact fractions to both policies. This corrects the evaluator, not the online policy.
3. The adapter omits volatile effects and exact field durations, limiting whole-game checks of Substitute, Encore and expiring speed control.
4. Focused independent Showdown mechanism tests are the appropriate evidence for current damage/reaction fixes. A small A/B result does not establish tournament superiority.
