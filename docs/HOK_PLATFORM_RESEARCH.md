# Platform HOK 5v5 research

Research date: October 16, 2026. Implementation: independently authored `hok_platform`, strategy `hok_team_v1`.

## Primary sources

- [Current platform HOK guide](https://api.altruagent-game.com/skill/hok): five heroes per agent, standing macros, real-time/lockstep, terminal results and tower/crystal-damage tiebreak.
- Official starter [`686e7560708eaa595a409b330d0d1837d49ba9d5`](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter/tree/686e7560708eaa595a409b330d0d1837d49ba9d5): [GAMES.md](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter/blob/686e7560708eaa595a409b330d0d1837d49ba9d5/GAMES.md), [example policy](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter/blob/686e7560708eaa595a409b330d0d1837d49ba9d5/examples/llm/hok.py), [protocol tests](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter/blob/686e7560708eaa595a409b330d0d1837d49ba9d5/tests/test_hok.py).
- Tencent's [Towards Playing Full MOBA Games with Deep Reinforcement Learning](https://papers.nips.cc/paper/2020/file/06d5ae105ea1bea4d800bc96491876e9-Paper.pdf) separates farming, combat, pushing and terminal objectives. This motivates tracking more than kills; its trained system and performance do not transfer to this rule policy.

This five-seat macro interface differs from Tencent's 1v1 172-value action mask. No 1v1 weights are imported and no encoder compatibility is assumed.

## Public opponent review

Search covered 23 AltruAgent-named repositories, exact game IDs and macro names. The inspected custom same-event HOK policy was [Astro-wen/ucla-agent-tournament](https://github.com/Astro-wen/ucla-agent-tournament), snapshot `18856599509a9a234c69e0deb51e950c2ec7af62`: [policy](https://github.com/Astro-wen/ucla-agent-tournament/blob/18856599509a9a234c69e0deb51e950c2ec7af62/agent/hok/policy.py), [public development notes](https://github.com/Astro-wen/ucla-agent-tournament/blob/18856599509a9a234c69e0deb51e950c2ec7af62/docs/CODEX_HOK.md). No opponent code was executed or copied. GitHub identifies its license as MIT. Registration, deployed versions and claimed wins were not independently verified.

The formerly empty `jerryhuang-math/hok-agent` now contains Werewolf code rejecting other games. Its name does not establish a HOK competitor. Generic starter HOK tests in other repositories were not counted as custom policies. This is a search snapshot, not an exhaustive entrant list.

| Public observation or protocol fact | Independent check |
| --- | --- |
| Listed macros may include filled movement fields plus `legal_*` metadata. | Accept the macro identity/seat instead of discarding it as an unfinished raw button. |
| Skill labels may end `(4123 away)` without a comma and say `toward enemy hero`. | Parse both formats; reject distant or unidentified skill targets. |
| Offered basic attacks already have an in-range target. | Do not impose a generic skill-distance cutoff on attacks. |
| Each call updates one hero. | Fair scheduling and an independent MCP-contract server double requiring all five heroes. |
| Skill availability changes while standing orders persist. | Replace unavailable skills and replan rejected orders. |
| Public notes describe prolonged recovery and zero-objective-damage games, with uncertain causality. | Separate recovery thresholds, preserve healthy objective pressure, and record actual structure HP. Thresholds are uncalibrated. |
| Nearest-target commands can be distracted; full mobile controls are absent. | No claims of arbitrary focus fire, lane selection, item purchase or hero drafting. |

Tower bait, retreat oscillation, local health/level imbalance and stale actions are normal gameplay weaknesses to test. Source review does not prove an opponent can exploit this agent or that these fixes defeat them. Public source cannot guarantee secrecy; robustness matters more than hiding constants.

## Evidence limits

No new live match or gameplay video was observed for this implementation. Public development notes were read; their private replay files were unavailable. Tests use synthetic protocol-shaped observations and a transport double, not Tencent combat physics. No synthetic win rate or competitive advantage is claimed. An expired browser session and absent workspace Official Agent Key blocked live testing; that does not mean the platform is unavailable.
