# Public opponent research

Research date: 2026-10-16. Scope: the UCLA AltruAgent AI Agent Gaming Tournament and its Werewolf, Pokemon, Red Alert, and announced Honor of Kings games.

## What was established

Public repositories with explicit event-entry descriptions and custom policies exist for Werewolf, Pokemon, and Red Alert. These are **declared entries or platform implementations**, not independently verified registrations, final submitted commits, or opponents assigned to us. An event-labelled Honor of Kings repository exists but was empty when inspected. No competitive Honor of Kings policy for this event was identified.

The findings below describe public source code, not measured head-to-head results. Repository snapshots were read without executing their code or contacting their agents. No opponent code, weights, logs, or datasets were copied into this repository. The inspected candidate repositories did not declare a license in GitHub metadata, so implementation here is independent. Their README performance claims were not independently reproduced.

## Candidate repositories and evidence

| Repository | Snapshot | Event connection and inspection result |
|---|---|---|
| [jas8n/pokemon-vgc-agent](https://github.com/jas8n/pokemon-vgc-agent) | `3f4fc562864a9e554aa4e14a33a88c67da2d8b2c` | README explicitly describes an AltruAgent tournament entry. Custom doubles draft, preview, damage model, and paired-action search. |
| [holmjames/ace-trainer-claude](https://github.com/holmjames/ace-trainer-claude) | `c636ec06211859508067055b489a08a9a24135ec` | README explicitly names the UCLA event, Pokemon entry, and a submitted version. Submission is the author's statement, not organizer confirmation. Default branch is `pokemon-agent`. |
| [ryanxxhuang/altruagent-redalert](https://github.com/ryanxxhuang/altruagent-redalert) | `412082f43183d8b7b6b753cbf818bb299bb9a025` | Repository description explicitly names the UCLA tournament and Red Alert. Custom bot and commander playbook. |
| [alinaliu18/altruagent-werewolf](https://github.com/alinaliu18/altruagent-werewolf) | `1b430e9ca9fdec16a72a0abba0b20f8d0e6652a4` | Custom `agent/claude_agent.py` identifies itself as a tournament Werewolf specialist and uses the AltruAgent protocol. Default variant is `v7_village`; the default `agent/agent.py` remains the starter placeholder, so the selected factory matters. |
| [Khuongtdm/altruagent-entry](https://github.com/Khuongtdm/altruagent-entry) | `0f9996b71a8ee736a5a1163f64ed02790a381b63` | README explicitly describes an AltruAgent AI Agent Gaming Tournament entry. Custom Red Alert rules; Pokemon and Werewolf documented as placeholders. |
| [omarcano23/altruagent-omarcanoc23](https://github.com/omarcano23/altruagent-omarcanoc23) | `259176a0056c90e5a947dc4a45092d2e789ea4be` | Repository description explicitly names UCLA's 2026 event. Custom deterministic Pokemon module with a low-HP target heuristic and first-turn Fake Out handling. |
| [WilliamChenTW1209/altruagent-agent](https://github.com/WilliamChenTW1209/altruagent-agent) | `a62f763b49facb7ec41d112a44c6d6e4369845e1` | Official starter runtime plus custom Pokemon/Red Alert policies and strategy documents. This establishes platform-specific development; entry/registration is less explicit than the repositories above. |
| [jerryhuang-math/hok-agent](https://github.com/jerryhuang-math/hok-agent) | No commit; empty repository | Description names the UCLA AltruAgent Tournament 2026. No files or policy were available, so no tactical conclusion can be drawn. |

## Tactical threats and defensive checks

These are defensive hypotheses derived from source behavior. They are not allegations of prohibited conduct and are not proof that an opponent defeats this agent.

| Game | Source-supported behavior | Defensive scenario to test |
|---|---|---|
| Werewolf | The Alina specialist models predictable first-legal voters, announced votes, claim order, and night-kill patterns; wolves can preserve predictable voters and join a forming villager wagon. | Do not resolve equal choices by a globally fixed lowest seat. Keep announced votes separate from resolved votes. Cap duplicated/coalition speech evidence, and retain private checks and official reveals as stronger evidence. |
| Werewolf | The default `v7_village` uses conservative wolf claims and early factual village messages. Aggressive fake-seer openings exist in optional variants, not the default. | Track who actually made a first-person claim, its timing, and revisions. A first or repeated claim is not proof; quoted claims must not become the speaker's own claim. |
| Pokemon | Jas's search evaluates our paired actions against paired enemy replies, blends Protect/switch priors, and includes a worst-case guard. Its public card catalog includes Armor Tail Farigiraf. | Test double-target attacks into Protect, switch-ins, Fake Out/priority denial, and Trick Room timing. Mechanics errors can make a search policy consistently choose a losing exchange. |
| Pokemon | Ace Trainer ranks reply matrices, models conditional Protect/switch behavior, and samples nearly tied choices from a per-match seed. | Evaluate against multiple opponent styles, not a single greedy attacker or one deterministic mirror. Do not assume an opponent repeats its most recent move or always protects a threatened slot. |
| Pokemon | Omar's custom module targets low remaining HP and restricts Fake Out to a fresh entrant. William's strategy emphasizes coordinated focus fire and immediate speed control. | Cover frail-partner focus fire, first-turn flinch plus setup, and legal defensive switching in regression scenarios. These are threats to robustness, not measured matchups. |
| Red Alert | Ryan's implemented raid state machine attacks economic targets from a flank, withdraws when defenders approach, then re-enters from another flank. Its ambush code uses a decoy and two closing groups. | Protect exposed harvesters with a bounded local response, retain main-army cohesion, and stop chasing after the immediate raid is repelled. Test separate raids while a main force pressures the base. |
| Red Alert | Ryan's playbook favors tower cover and good material trades. Khuong's rules accumulate a mixed attack wave and reinforce it; William's strategy stresses rockets behind armor and economy raids. | Avoid feeding a tank-only force into anti-armor infantry or static defenses. Distinguish local defensive strength from distant army value. Test hidden reinforcements and interrupted mining. |
| Honor of Kings | No same-event opponent implementation was found. Existing Tencent trajectory research concerns a separate 1v1 destroy-turret task. | Treat tower bait, chasing, low-health farming, and distant-minion false safety as independent adversarial scenarios. Do not attribute them to the empty event repository or claim transfer to the announced 5v5 format. |

Pinned primary code references:

- Werewolf: [default and alternative prompts](https://github.com/alinaliu18/altruagent-werewolf/blob/1b430e9ca9fdec16a72a0abba0b20f8d0e6652a4/agent/claude_agent.py), [field model and claim checks](https://github.com/alinaliu18/altruagent-werewolf/blob/1b430e9ca9fdec16a72a0abba0b20f8d0e6652a4/agent/werewolf_field.py).
- Pokemon: [Jas paired-action search](https://github.com/jas8n/pokemon-vgc-agent/blob/3f4fc562864a9e554aa4e14a33a88c67da2d8b2c/pokeagent/search.py), [public card catalog](https://github.com/jas8n/pokemon-vgc-agent/blob/3f4fc562864a9e554aa4e14a33a88c67da2d8b2c/pokeagent/data/cards.json), [Ace Trainer reply model](https://github.com/holmjames/ace-trainer-claude/blob/c636ec06211859508067055b489a08a9a24135ec/agent/pokemon/replies.py), [Omar's policy](https://github.com/omarcano23/altruagent-omarcanoc23/blob/259176a0056c90e5a947dc4a45092d2e789ea4be/agent/pokemon_agent.py).
- Red Alert: [Ryan's bot](https://github.com/ryanxxhuang/altruagent-redalert/blob/412082f43183d8b7b6b753cbf818bb299bb9a025/agent/redalert_bot.py) (`_ambush_step`, `_raid_phase_update`), [commander playbook](https://github.com/ryanxxhuang/altruagent-redalert/blob/412082f43183d8b7b6b753cbf818bb299bb9a025/agent/playbook.md), [Khuong's rules](https://github.com/Khuongtdm/altruagent-entry/blob/0f9996b71a8ee736a5a1163f64ed02790a381b63/redalert_policy.py), [William's strategy](https://github.com/WilliamChenTW1209/altruagent-agent/blob/a62f763b49facb7ec41d112a44c6d6e4369845e1/strategy/red_alert.md).
- Honor of Kings: [official event availability](https://altruagent-game.com/), [Tencent environment](https://github.com/tencent-ailab/hok_env), and [our separate dataset analysis](HOK_RESEARCH.md).

## Coverage and limits

Web searches covered the exact event name, AltruAgent plus GitHub, the platform domain, and each game. GitHub repository search covered `altruagent`, `"UCLA" "tournament" agent`, and AltruAgent combined with Pokemon, Werewolf, and HOK. The broad AltruAgent query returned 18 repositories; focused UCLA search added Ace Trainer. This is a search snapshot, not an exhaustive entrant roster: private repositories, unindexed code, differently named entries, and later changes may be missing.

The official [UCLA starter](https://github.com/UCLA-Trustworthy-AI-Lab/altruagent-starter) is infrastructure, not an opponent. Our own repository was excluded. [sarthakmohindru04/Autonomous-Reasoning-Agent](https://github.com/sarthakmohindru04/Autonomous-Reasoning-Agent) was excluded despite UCLA/AltruAgent keywords because its README identifies a STATS 263 course competition with Prisoner's Dilemma, Hunger Games, and Are You the Traitor rather than these four tracks. Starter forks without inspected custom policies were not upgraded to confirmed entrants.

Game deception, bluffing, counter-picks, focus fire, raids, and baiting are ordinary competitive strategies. No inspected source established prohibited attacks against our system. In particular, the Werewolf field playbook explicitly rejects moderator impersonation and requests to ignore instructions. Defensive tests for hostile chat or malformed observations should be described as general robustness checks, not attributed misconduct.

A passing scenario suite does not establish a win-rate advantage. Promotion still needs legal-action validation and paired evaluations on the correct game format; live event readiness requires the actual platform runtime and authorized credentials. Honor of Kings remains a separate Tencent 1v1 integration, with no claimed platform 5v5 readiness.
