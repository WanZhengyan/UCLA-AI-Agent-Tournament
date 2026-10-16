# Platform Setup and Official Tournament Entry

This Python agent runs through AltruAgent's **Self Hosted** workflow. The platform assigns games to the listener running on your machine. Providing a repository URL or pushing a commit does not upload a running agent to the platform.

These instructions were checked against the official guides on October 16, 2026. The published dates conflict: the [rules dated October 6](https://platform.altruagent-game.com/tournament/rules) give October 13 at 11:59 p.m. Pacific for submitted-version locking; the [event homepage](https://altruagent-game.com/) gives October 15 at 7 p.m.; the official-agent API guide mentions October 16 at 9:30 a.m. for switching hosting mode. **The API guide's mode-switch time is not reliable evidence that a new competitive version may still be submitted.** Confirm the applicable version-lock deadline and any announced exception with the organizers before changing a submitted entry. Preserve its full commit ID and deployment configuration.

## 1. Configure the event agent

1. Sign in with Google at the [event site](https://platform.altruagent-game.com/tournament). UCLA participants should use their UCLA account (`@ucla.edu` or `@g.ucla.edu`).
2. Complete event onboarding: questionnaire, Official Rules acceptance, agent name, and required repository information.
3. Open [Agent Configuration](https://platform.altruagent-game.com/tournament/dashboard/agent-setup) and select **Self Hosted**.
4. Use this public repository URL: `https://github.com/WanZhengyan/UCLA-AI-Agent-Tournament`.
5. Generate an **Official Agent Key** if there is no active key. Keep an existing working key unless you need to rotate it; rotation invalidates the old key and its sessions.

The repository field identifies the source code. It does not clone, install, or launch the agent for you.

**Oracle Hosted is a different workflow.** It uses a submitted Markdown agent run by the platform, and official tournaments freeze an eligible Markdown version when the tournament starts. This repository's Python policy cannot be deployed by pasting it into that Markdown submission. An agent configured as Oracle Hosted cannot authenticate with an Official Agent Key.

## 2. Check and start the local agent

Run these commands in the updated repository after installing dependencies as described in the [README](../README.md):

```bash
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py --check
.venv/bin/python exe_entry.py
```

At the prompt, paste the Official Agent Key. The input is hidden and is not saved by the prompt. The key is a platform credential, not a GitHub token or an OpenAI API key.

For unattended operation, provide `ALTRUAGENT_OFFICIAL_AGENT_KEY` through the environment, an untracked `.env`, or a protected file read with `--key-file`. Never commit the real key. A credential file should be readable only by the account running the agent, for example with `chmod 600 /path/to/key.txt`.

Use **one persistent listener per key**. The listener starts separate workers for assignments and keeps polling between games.

| Launch command | Assignment scope |
| --- | --- |
| `.venv/bin/python exe_entry.py` | Testing and official tournament games. |
| `.venv/bin/python exe_entry.py --match` | Testing only; does not play official games. |
| `.venv/bin/python exe_entry.py --tournament` | Official tournament games only. |
| `.venv/bin/python exe_entry.py --check` | Authentication/loading check only; exits without playing. |

Keep the listener, computer, and network available throughout the event. The official runtime obtains seat grants and renews leases; you do not copy game IDs or enter claim codes. A successful `--check` confirms the connection and policy loading, not tournament registration or victory in a match.

## 3. Play a Testing match

1. Open the dashboard's **Testing** page.
2. Choose **Red Alert**, **Pokemon VGC Doubles Draft**, **Werewolf**, or **Honor of Kings 5v5**. Werewolf needs seven connected seats. HoK needs two agents, each controlling five heroes, and the v11 platform integration.
3. Select **Mine (self-hosted)** for your seat, configure the opponent and match settings, and create the match.
4. Keep the listener running with default options or `--match`.
5. Check the platform's match status and the local runtime output to confirm the agent connected. Watch the match and inspect its recorded outcome afterward.

Testing matches are separate from official tournament entries. Creating or playing one does not register the agent for a tournament.

## 4. Enter the official tournament

1. Open [Dashboard → Tournaments](https://platform.altruagent-game.com/tournament/dashboard/tournaments).
2. Select the intended **Red Alert**, **Pokemon**, **Werewolf**, or **Honor of Kings 5v5** tournament. Register each game separately. Werewolf tables require seven connected seats. HoK requires `improve/hok-platform-v11` or later; read [HOK_PLATFORM.md](HOK_PLATFORM.md). Validate the development version before entering it, subject to the event's version-lock rules.
3. Click **Register my agent** while registration is open and confirm that the agent appears as registered.
4. Leave the listener running with default options or `--tournament` before the event starts and between rounds.
5. Check the dashboard's next-game connection status and the terminal output. The platform automatically pairs opponents and sends each game as a tournament assignment.

The registration button requires a complete event registration and an active Official Agent Key for Self Hosted agents. If disabled, follow the displayed missing step: `no_agent`, `no_official_key`, or `registration_incomplete`.

For this Self Hosted code, there is no separate Oracle-style Markdown version to submit. The source deployed on the machine and loaded into the match worker determines the policy that plays. Record the deployed commit so results can be compared accurately, and follow any event rules about changes after the submission cutoff.

The live API now documents `honor_of_kings_5v5` and lists its tournament; the marketing homepage's “not playable yet” notice is stale. The new `hok_platform_bot` module implements that interface. The standalone Tencent `hok_env` 1v1 agent remains separate. See [HOK_PLATFORM.md](HOK_PLATFORM.md).

A listener running only with `--match` will not play official tournament assignments. Official games have a connection deadline; failure to connect in time can produce a no-show loss. The runtime must remain available while waiting for the next round, even when the assignment list is temporarily empty.

## 5. Deploy a code update

Update the actual checkout used by the persistent listener; changing GitHub alone is insufficient. Run the offline tests and self-test for that checkout before using the update. New source-based workers load the updated files; an already running worker keeps its loaded policy. Avoid replacing the running environment or stopping a match mid-game.

Adding a supported game also changes the parent's assignment filter: restart the
listener only when its game workers have finished, then confirm the new game's
assignment is accepted. Copying v11 source under an old running parent is not enough.

If using a packaged executable, rebuild from the updated source and deploy the new executable. The old binary does not acquire GitHub changes automatically. Do not run a second listener with the same key to test an update while the first listener is active.

## Official references

- [Official Agent Key and self-hosted runtime guide](https://api.altruagent-game.com/skill/official-agent)
- [Tournament guide](https://api.altruagent-game.com/skill/04-tournaments.md)
- [Platform guide index](https://api.altruagent-game.com/skill.md)

The setup instructions describe the workflow; they do not assert that a particular account has submitted, registered, or connected successfully.
