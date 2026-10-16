# Werewolf Agent

`werewolf_bot` implements `evidence_v1` for the official AltruAgent seven-seat Werewolf game. It runs locally without a language model or model API key. The shared launcher routes `game_type="werewolf"` to this policy and keeps a separate instance for each game, session, account agent, and seat.

This is a development candidate on `improve/werewolf-defenses-v8`. Offline protocol and strategy checks passed; no live Werewolf match or competitive win-rate evaluation has been completed.

## Supported rules

The official format has two wolves, one seer, and four villagers. There is no doctor, witch, or hunter. The first night is peaceful, although the seer investigates. Dead players' roles are revealed. Villagers win by eliminating both wolves; wolves win at parity. Daytime votes use plurality, a tie eliminates nobody, and three consecutive days without an elimination give the wolves a win.

The outer `phase` determines whether the agent may discuss or move. The inner `game_state.phase` identifies `night_wolf`, `night_seer`, or `day_vote`. These are different fields: an available action list does not authorize an action during discussion. The policy returns only a canonical legal action ID, `"0"` through `"6"` for a target or `"7"` for abstention when available. The official runner supplies session and state-version envelopes.

## Policy

- **Villager:** score the 21 possible wolf pairs, constrained by official role reveals. Use bounded claim consistency, resolved votes, and weaker announced preferences to choose an elimination. Repetition is not independent evidence.
- **Seer:** constrain the same model with private investigations, prefer informative unchecked targets, and reveal results when a living wolf is found, a competing claim appears, or the game reaches the configured disclosure threshold.
- **Wolf:** protect the known partner, select non-wolf daytime targets, and prioritize threatening seer claimants or informed villagers at night. During discussion the lower-seat wolf can privately propose the next night target to its authenticated partner.
- **Discussion:** send concise English messages and terminate when finished. The policy sends at most three messages per day, including at most one revision of an announced vote. The server permits five messages, each limited to 50 words and 1,024 characters; this policy stays below those limits.
- **Equal choices:** use a private random seed per session and seat to break ties. Repeated observations retain the same tie ordering; opponents cannot infer it from a public session identifier or a fixed lowest-seat rule.

Claims are deliberately parsed using a narrow English grammar, such as `I am the seer. Player3 is wolf.` or `I recommend Player3.` The policy does not understand arbitrary natural-language arguments, sarcasm, or multilingual paraphrases. Its weights and night-target scores are heuristics, not a trained or solved strategy.

## Trust boundaries and isolation

The engine's private observation header supplies our role, wolf partner, and investigation results. Chat cannot replace that header. Public display names are mapped exactly through the engine's player list; digits or instructions embedded in a name do not change its seat. Public role reveals and resolved vote records come from `game_state`, not from a player's statement.

Player claims remain uncertain evidence. Quoted seer claims do not become the speaker's first-person claim. Contradictory reports, self-investigations, and impossible numbers of checks reduce credibility. Announced votes are stored separately from completed votes. Private wolf coordination is accepted only from the known ally's direct-message envelope, with the lower-seat convention used to resolve disagreements.

The router rejects conflicting game, session, and seat identities. Different seats owned by the same account do not share policy memory. The policy never executes chat, copies an action input template, reads a model key, or persists raw observations and discussion. The general match recorder is disabled for Werewolf, and game completion clears the policy's session memory. Private random seeds, role details, and reasoning are absent from diagnostics.

The hostile-message tests are general robustness checks. [Public opponent research](OPPONENT_RESEARCH.md) did not establish prohibited attacks by another entrant.

## Run and test

Use the development checkout and install dependencies as described in the [README](../README.md). Run the focused checks or the shared self-test:

```bash
.venv/bin/python -m pytest tests/test_werewolf_agent.py tests/test_werewolf_integration.py -q
.venv/bin/python -m werewolf_bot.selftest
.venv/bin/python exe_entry.py --self-test
```

The focused suite contains 54 tests covering roles, action legality, discussion limits, private observations, misleading claims, identity isolation, and the JSONL launcher. The full v8 suite contains 560 tests when the optional Showdown checks are enabled. These counts measure software checks, not games won.

For a live practice match:

1. Complete Self Hosted setup using the [platform instructions](PLATFORM.md).
2. Run `.venv/bin/python exe_entry.py --match` and enter the Official Agent Key when prompted. Use one listener per key.
3. On the platform's Testing page, choose Werewolf, fill all seven seats, and select the self-hosted agent for the intended seat or seats.
4. Create the match and verify connections and the final result on the platform. Keep the listener running throughout the game.

The default launcher also accepts official tournament assignments; `--match` accepts practice assignments only. Official entry requires separate Werewolf registration and compliance with the applicable version lock. Starting the listener or pushing this branch does not register an entry. Older downloaded executables do not include this new policy; rebuild from this branch if using a packaged executable.

For offline replay of an authorized seat-visible JSON snapshot, use `--decide snapshot.json` or stream snapshots to `--jsonl`. The latter retains session memory between lines. Messaging snapshots return a chat or termination response; moving snapshots return an action ID or wait response. Do not commit private snapshots to the repository.

## Official protocol references

- [Werewolf game guide](https://api.altruagent-game.com/skill/werewolf)
- [Messaging guide](https://api.altruagent-game.com/skill/06-messaging.md)
- [Official Agent runtime](https://api.altruagent-game.com/skill/official-agent)

The implementation follows the documented seven-seat format inspected on October 16, 2026. A different role set or changed server schema needs separate validation.
