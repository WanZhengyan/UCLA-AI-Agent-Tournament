# Pokemon type matchups and speed control — 2026-10-16

This review inspected three public Pokemon Showdown replay timelines to identify concrete decision requirements. These are examples, not a win-rate estimate, a representative metagame sample, or replays of our agent. No private platform replay was available.

## Scope and retrieval

The AltruAgent guide describes an 18-card public fixed-set pool, snake draft, six picks, bring four, and lead two. Terastallization is disabled. Ordinary VGC damage outcomes that rely on Terastallization therefore cannot be transferred directly to the platform. The existing [platform research](POKEMON_RESEARCH.md) records those format details and the official guide URL.

Search located the replay pages, then the public replay player was opened and **Skip to end** exposed the complete visible turn timeline. The final URL was verified in the browser. Direct `.log` and `.json` requests for the first replay returned HTTP 403; no raw replay log was retrieved or hashed. Observations below are paraphrases of the rendered timeline. The machine-readable record is [pokemon_speed_replays.json](../reports/pokemon_speed_replays.json).

## Replay 1: Tailwind and partner attacks in the same turn

[Mircat222 vs. yuki, Regulation I](https://replay.pokemonshowdown.com/gen9vgc2025regi-2346346650), April 19, 2025. Located through the participants' [VGC Seasonal round-two thread](https://www.smogon.com/forums/threads/vgc-seasonal-round-2.3763289/page-2).

- **Turn 1:** Whimsicott sets Tailwind. Its partner Miraidon then uses Volt Switch, knocking out Sneasler before Sneasler acts.
- **Turn 3:** The other side's Urshifu uses Aqua Jet before the Tailwind side's Whimsicott and Urshifu. Increased Speed does not override a higher move-priority bracket.
- **End of turn 4:** Tailwind expires. Lunala enters alongside Whimsicott.
- **Turn 5:** Whimsicott sets Tailwind again. Lunala then uses super-effective Moongeist Beam to knock out Calyrex-Shadow before Calyrex acts.

**Decision requirement:** Recompute the order of remaining moves after a Speed change. A turn-start sorted queue misses a support move enabling its partner's immediate knockout. Track expiry rather than assuming Tailwind remains active indefinitely. Evaluate the actual damaging type and target together with that order: moving first is valuable because it can remove an opponent's action.

**Transfer limit:** Miraidon Terastallizes into Fairy on turn 2, so its subsequent damage/resistance outcomes are not platform examples. Neither the turn-1 sequence nor the turn-5 Lunala/Calyrex typing depends on that transformation. The timeline alone does not reveal all EVs or establish a counterfactual win without Tailwind.

## Replay 2: Trick Room needs protection and a useful attacking partner

[sheepie_sheep vs. breakfast enjoyer, Regulation G best-of-three game 1](https://replay.pokemonshowdown.com/gen9vgc2025reggbo3-2305943594), February 22, 2025.

- **Turn 4:** Amoonguss uses Rage Powder, the opposing attackers remain asleep, and Calyrex-Ice sets Trick Room.
- **Turn 5:** Amoonguss again redirects. Calyrex-Ice moves before Zacian and lands super-effective High Horsepower. Zacian's Behemoth Blade is redirected to Amoonguss; Rocky Helmet damage then knocks out Zacian.
- The remaining Urshifu attacks Calyrex later in that turn. The opponent forfeits on turn 6.

**Decision requirement:** A slow team can prefer reversed Speed order; automatically rewarding raw Speed or Tailwind is incorrect. Setting Trick Room consumes an action and should be evaluated with protection, status, redirection, the setter's survival, and the partner's expected follow-up damage. A faster super-effective attack is not useful if the intended target is protected by redirection.

**Transfer limit:** Amoonguss had become Water-type on turn 2 and Entei had become Normal-type on turn 1. The observed Behemoth Blade resistance and earlier damage are Tera-dependent. Use the turn order and support interaction as hypotheses, not its exact HP outcomes as a no-Tera regression fixture. A forfeit is not a completed all-Pokemon-fainted simulation result.

## Replay 3: A speed plan can be undone by disruption

[starboymclovin vs. ghotul, Regulation I](https://replay.pokemonshowdown.com/gen9vgc2025regi-2341079661), April 12, 2025. Located through an [author-posted team page](https://www.coupcritique.fr/entity/teams/7497).

- **Turn 1:** Calyrex-Ice sets Trick Room after the opponents act.
- **Turn 2:** Sableye's Encore makes Calyrex repeat Trick Room, removing the field effect.
- **Turn 3:** Sableye's Prankster Disable fails against Dark-type Incineroar. Type interactions also govern whether an opponent's control move succeeds.
- **Turn 4:** Flutter Mane enters in sunlight, but its announced Protosynthesis boost is **Special Attack**, not Speed.

**Decision requirement:** Do not treat a Speed-control plan as guaranteed once its move is available. Account for Encore, Taunt, priority-blocking effects and typing where the simulator supports them. A paradox ability does not inherently mean a Speed boost; use the selected stat or the public fixed set. Avoid adding a blanket Speed bonus to every Flutter Mane in sun.

**Transfer limit:** Calyrex becomes Normal-type on turn 1, and Flutter Mane becomes Fairy-type on turn 5. The turn-1 survival and later knockouts are therefore excluded as platform damage evidence. This is a low-ladder example; it demonstrates interactions, not an optimal team or policy.

## Independent mechanic references

The locally installed `pokemon-showdown@0.11.11` source was read independently; source hashes are recorded in the JSON report. Its official repository provides the corresponding [battle engine](https://github.com/smogon/pokemon-showdown/blob/master/sim/battle.ts), [moves](https://github.com/smogon/pokemon-showdown/blob/master/data/moves.ts), and [abilities](https://github.com/smogon/pokemon-showdown/blob/master/data/abilities.ts). Those `master` links can change; hashes identify the actual local files inspected.

- Generation 8 and later update and re-sort remaining queued moves after actions. This applies to Generation 9.
- Tailwind doubles the affected side's Speed for four turns. Trick Room lasts five turns, has priority -7, and a second use removes it. Priority brackets remain separate from Speed order.
- Icy Wind and Electroweb each have 55 base power, 95% accuracy, and a one-stage Speed drop as a secondary effect. They require normal hit, immunity, protection and secondary-effect checks; the Speed drop must not be assumed to occur against every target. None of the three selected replays demonstrates these two moves; their regression requirements come from engine source rather than a claimed replay observation.
- Protosynthesis and Quark Drive select a stat; their Speed modifier is 1.5 only when Speed is the selected stat. Weather, terrain and Booster Energy activation must be represented separately from the Pokemon's base Speed.

The resulting implementation should combine type-aware damage, move priority, current effective Speed, control duration and both partners' actions. Focused engine comparisons can verify those mechanisms. Only new matches against relevant opponents can establish whether the policy wins more often.
