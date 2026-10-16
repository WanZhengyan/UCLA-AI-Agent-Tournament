# Honor of Kings 1v1 agent

`hok_bot` is a standalone, objective-focused rule agent for Tencent's official **HoK1v1 research environment**. It is separate from this repository's AltruAgent listener. **For the newly published AltruAgent 5v5 platform interface, use `hok_platform_bot` and [HOK_PLATFORM.md](HOK_PLATFORM.md).** The event homepage's old “not playable yet” notice is superseded by the live HoK API guide and tournament listing. The 1v1 protocol documented below is not the platform protocol.

The latest `hok_objective_v2` module is on the development branch `improve/werewolf-defenses-v8`, based on the original v7 integration. Check out that branch before following the commands below; a clone of the unchanged `main` branch does not contain it. The v2 policy prioritizes retreat from an unfavorable nearby enemy before farming and only counts healthy local allied minions as support. These corrections passed adversarial fixtures, not a live Gamecore tournament.

The policy targets last hits, safe wave clearing, protected tower/crystal pressure, favorable ranged trades, and low-health recovery. It checks the official legal masks before emitting an action and preserves recall channels until completion or interruption. Current hero profiles are **112 (Lu Ban No.7)** and **133 (Di Renjie)**; the runner restricts the controlled hero to those profiles.

## Offline check

From the repository root, using the normal project Python:

```bash
python -m hok_bot --smoke
python -m pytest tests/test_hok_agent.py -q
```

The smoke input is synthetic. Passing it proves neither engine connectivity nor competitive strength. The rule module has no Tencent SDK dependency; SDK imports occur only when starting a real engine session.

## Real engine prerequisites

1. Obtain the gamecore and its license through Tencent's [official application page](https://aiarena.tencent.com/aiarena/en/open-gamecore), following the [pinned SDK instructions](https://github.com/tencent-ailab/hok_env/tree/c6e0029a5e4b6e037a049804fdbe23ac74484311). The license and proprietary engine are not included here.
2. Run the gamecore on Windows 10/11, or use the upstream Linux/Wine instructions. The pinned Python SDK bundles **x86_64 Linux** native extensions; use that architecture, including x86_64 WSL2.
3. Create a **separate CPython 3.8 environment**, the verified installation path for this runner. Do not install the SDK into the AltruAgent Python 3.11+ environment. The native extension has an older Python ABI. Although the runner also accepts Python 3.9 and upstream bundles that ABI, the pinned SDK's `requires-python <=3.9` metadata rejects ordinary 3.9.x patch releases greater than 3.9.0. Use Python 3.8 for the commands below.
4. Ensure the gamecore can reach the AI server's two consecutive TCP ports (default 35150 and 35151), and that the AI server can reach gamecore port 23432. Loopback addresses below apply only when both processes can actually reach one another through loopback. WSL, containers, and separate hosts usually require explicit reachable addresses.

For example, install the pinned SDK outside this repository:

```bash
python3.8 -m venv /path/to/hok-venv
git clone https://github.com/tencent-ailab/hok_env.git /path/to/hok-sdk
git -C /path/to/hok-sdk checkout c6e0029a5e4b6e037a049804fdbe23ac74484311
/path/to/hok-venv/bin/python -m pip install -e /path/to/hok-sdk/hok_env
```

Start the official gamecore server from its installed `gamecore` directory on Windows:

```powershell
.\gamecore-server.exe server --server-address :23432
```

Then, from this repository's root on the AI host:

```bash
/path/to/hok-venv/bin/python -m hok_bot \
  --gamecore 127.0.0.1:23432 \
  --ai-server 127.0.0.1 \
  --port 35150 \
  --hero 133 --enemy-hero 133 --seat 0
```

`--seat 0` controls the first camp; `--seat 1` controls the second. The other seat uses Tencent's built-in common AI. `GAMECORE_SERVER_ADDR` and `AI_SERVER_ADDR` provide the corresponding defaults. `--max-steps` defaults to 12000 decision steps.

The final JSON distinguishes `engine_terminated` from `step_limit_truncated`. Reaching the step limit exits with status 2. Engine termination is **not a win declaration**: the runner does not yet parse authoritative winners. Retain the engine's terminal result and statistics before computing any win rate.

## Contract and evidence

The pinned SDK supplies `player_id`, `req_pb`, and a 172-entry legal-action vector. Actions have six dimensions with sizes `(12, 16, 16, 16, 16, 8)`. Target legality depends on the selected button. Actor target slots, camp-relative movement, and visibility indexing follow the pinned official implementation. Invalid or incompatible inputs raise an explicit protocol error instead of guessing another game interface.

The implementation was reviewed against upstream source and the Python 3.8 native interface. Its action adapter was checked against **136,535 recorded actions** from **200 official HoKOff turret-destruction trajectories**, plus constructed actions across their legal masks. These tests validate encoding; the recordings' 725-feature observations are incompatible with the current SDK's 453-feature encoder and were not fed into this policy.

See [HOK_RESEARCH.md](HOK_RESEARCH.md) and [hok_dataset_review.json](../reports/hok_dataset_review.json) for source links, hashes, statistics, and pretrained-model compatibility findings. No gamecore match was run for this release, and no competitive win rate is claimed. Live engine validation across both camps and multiple opponents is required before treating it as a competitive agent.

## Replay-driven iteration

The licensed gamecore writes `.abs` replays and result/statistic files. Use Tencent's [ABS replay viewer](https://aiarena.tencent.com/hok/doc/quickstart/evaluation.html) to inspect them. Retain the engine version, hero/summoner configuration, camp, opponent, authoritative result, and source version together. Inspect tower deaths, missed last hits, abandoned objective windows, and time spent away from lane before changing priorities.

Keep gamecore licenses, private replay files, and downloaded models outside the public repository. The current runner does not upload agents to AltruAgent, register a tournament entry, or train a neural policy.
