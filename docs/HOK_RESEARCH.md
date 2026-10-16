# Honor of Kings research and recorded-data review

Reviewed on October 16, 2026. The implementation targets Tencent's **HoK1v1 research environment**, not the mobile game's 5v5 mode. The research below informs a rule baseline; it does not establish that this repository's agent wins competitive games.

## Sources and objective

The official [environment documentation](https://aiarena.tencent.com/hok/doc/environments/index.html) defines movement, attack, skills, legal actions, and button-dependent target masks. The [game description](https://aiarena.tencent.com/hok/doc/environments/game_description.html) identifies the enemy crystal as the final objective; the preceding turret must be destroyed first. Other competition variants can use different termination rules, so the runner follows the engine's terminal signal.

The SDK is pinned to [`tencent-ailab/hok_env` at `c6e0029`](https://github.com/tencent-ailab/hok_env/tree/c6e0029a5e4b6e037a049804fdbe23ac74484311). Its [official rule demo](https://github.com/tencent-ailab/hok_env/blob/c6e0029a5e4b6e037a049804fdbe23ac74484311/aiarena/1v1/actor/agent_demo.py) provides camp-relative steering and target-slot conventions. Its compiled interface, rather than an assumed mobile-game protocol, supplies actor attributes.

## Actual recorded trajectories inspected

Two small public datasets were downloaded from the authors' [HoKOff dataset page](https://sites.google.com/view/hok-offline/home/hok-1v1):

- [destroy_turret_expert.zip](https://kaiwu-assets-1258344700.cos.ap-shanghai.myqcloud.com/paper/hok-offline/1v1/destroy_turret_expert.zip): 5,537,569 bytes.
- [destroy_turret_medium.zip](https://kaiwu-assets-1258344700.cos.ap-shanghai.myqcloud.com/paper/hok-offline/1v1/destroy_turret_medium.zip): 7,159,760 bytes.

These are recorded state/action trajectories, not video files. The [paper supplement, Appendix C.1](https://proceedings.neurips.cc/paper_files/paper/2023/file/464fefa022aaefc85d901317bbf13f85-Supplemental-Datasets_and_Benchmarks.pdf) explains that this subtask removes the opposing hero and measures turret/crystal destruction. Therefore, the following comparison does **not** measure competitive win rate or our new policy's performance.

| Recorded measurement | Expert dataset | Medium dataset |
| --- | ---: | ---: |
| Completed trajectories (`done` markers) | 100 | 100 |
| Decision rows | 60,495 | 76,040 |
| Mean decisions per trajectory | 604.95 | 760.40 |
| Median decisions per trajectory | 599.5 | 739.0 |
| Normal attacks | 28,286 | 42,937 |
| Structure-targeted share of normal attacks | 48.26% | 28.03% |
| Empty-target share of normal attacks | 15.09% | 29.32% |
| Active action-component mask violations | 0 | 0 |

The expert recordings take about 20.4% fewer decisions on average. They have a larger share of structure-targeted attacks despite making fewer total attack decisions. This supports investigating target selection and objective uptime. It does not prove that copying the aggregate action frequencies would improve another agent.

## Decoder and integrity

The decoder follows the upstream [dataset loader](https://github.com/tencent-ailab/hokoff/blob/9b35f7e5891ad98df45a36e3a18f5192a31e72f4/hok1v1/offline_train/datasets.py) and [model configuration](https://github.com/tencent-ailab/hokoff/blob/9b35f7e5891ad98df45a36e3a18f5192a31e72f4/hok1v1/offline_train/train_eval_config/OneConfig.py). The HDF5 key is `datas`; each float32 row has 911 columns:

| Zero-based slice, end excluded | Meaning |
| --- | --- |
| `0:725` | Observation |
| `725:731` | Six action indices |
| `731:732` | Reward |
| `732:733` | Done marker |
| `733:905` | Legal-action mask |
| `905:911` | Selected button's sub-action mask |

Action dimensions are `[12, 16, 16, 16, 16, 8]`. Within the 172-element legal mask, target legality is indexed by `76 + 8 * button + target`. Episode lengths are differences between successive `done == 1` positions, including the terminal decision. Neither file has trailing incomplete rows. A terminal marker alone does not identify a winner.

Full archive/HDF5 SHA-256 hashes, counts, and source URLs are retained in [the machine-readable report](../reports/hok_dataset_review.json). Downloaded archives and HDF5 files are excluded from the repository.

## Mask adapter verification

The new `LegalActions` adapter was checked against all **136,535 recorded actions**: every action passed its six-component validation. Across 250 expert and 277 medium unique masks, 527 safe-action constructions and 10,362 button/target/direction constructions passed. The direction requests were `(0, 0)`, `(8, 8)`, and `(15, 15)` for every allowed button/target pair.

No recorded row had an empty shared movement/skill mask, an empty target mask for its selected button, or an allowed button with an empty conditional target mask. This dataset therefore does not exercise those edge cases. These checks test action encoding only; the recorded observations were never fed into the new policy.

## Policy decisions informed by the review

- Push an available turret/crystal with a supporting wave when the immediate danger permits it. Avoid prolonged hero pursuit that abandons a safe objective.
- Preserve basic-attack uptime and useful target selection. The official demo also treats structures as normal-attack targets.
- Treat tower aggro, low health, and recovery as explicit decisions. Returning to lane alive preserves future farming and objective pressure.
- Follow the legal-action and sub-action masks rather than guessing cooldown availability.
- Keep hero-specific skills separate from generic logic. For example, the official [Lu Ban ability description](https://pvp.qq.com/coming/v2/adjust/112.shtml) describes a barrage after a skill or the fifth basic attack. That suggests preserving follow-up attacks, but current mobile balance numbers should not be assumed to match the older research gamecore.

These are design hypotheses and protocol-grounded choices, not measured competitive gains. Live engine matches with both camps, multiple opponents, and held-out hero matchups are still needed.

## Pretrained-model compatibility review

The official [HoKOff repository](https://github.com/tencent-ailab/hokoff) publishes [1v1baselines.zip](https://kaiwu-assets-1258344700.cos.ap-shanghai.myqcloud.com/paper/hok-offline/1v1/1v1baselines.zip). HTTP HEAD reported 269,962,162 bytes. Only its central directory and two tiny configuration members were read with HTTP byte ranges; no checkpoint was executed.

The archive contains TensorFlow levels 0–8, each with roughly 30 MB of compressed tensor data. Level 7 configures Lu Ban with `intimidate`; level 8 uses Lu Ban with `stun`. The source code is Apache-2.0, while no separate LICENSE/NOTICE member was found in this checkpoint archive.

The published model configuration expects **725 observation features**, whereas the pinned SDK used by this runner reports **453**. Upstream additionally specifies TensorFlow 1.15 and Python 3.7.13. The weights are not integrated: an adapter cannot safely truncate or pad semantically different observations. A future learned backend should use its matching environment/feature encoder, preserve the configured hero and summoner skill, and pass actual gamecore evaluation before replacing the rule baseline.

## Replays for future iteration

Tencent's [official ABS replay tool](https://aiarena.tencent.com/hok/doc/quickstart/evaluation.html) renders `.abs` files produced by gamecore. For further work, retain engine version, hero and summoner configuration, camp, opponent, result, and corresponding per-player decision logs alongside each replay. Review deaths under towers, missed objective windows, empty attacks, and time spent away from lane. No ABS video was played and no gamecore match was run in this recorded-data review.
