# UCLA AI Agent Tournament

AltruAgent 双游戏 self-hosted agent：宝可梦 VGC 双打选秀 + 红警 OpenRA。策略在本机计算，不需要 OpenAI 或其他模型 API key。

## 当前策略

- 红警：默认 `eco_guard` / `armor_guard_v4`。地图自适应，电力与矿车优先，坦克主力、有限步兵/火箭兵辅助，保护坦克生产预算；对炮塔与不利交战采取保守检查。保留 `balanced` 作为可选实验基线。
- 宝可梦：选秀、六选四、双打联合动作搜索、状态/伤害近似模拟与合法动作回退。
- 统一 agent：自动分流两种游戏，使用每席位独立策略状态，运行组件负责认证、MCP、租约、重连与工作进程。
- 监控：己方可见状态、拟提交动作、执行回执和正式赛果写入本地；确认失败的局进入复盘清单。不使用隐藏信息或另一席位的观测。

## 运行

Python 3.11+；保持网络连接。同一 Official Agent Key 只运行一个监听器。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python exe_entry.py --self-test
.venv/bin/python exe_entry.py
```

按隐藏输入提示粘贴比赛平台的 Official Agent Key，不是 GitHub token。密钥不作为命令行参数，也不写入仓库。默认同时接测试赛和正式赛；使用 `--match` 或 `--tournament` 可限定范围。参赛报名和 Testing 房间创建仍需在平台完成。

可复制 `.env.example` 为未跟踪的 `.env` 使用自己的配置。不要提交 `.env`、密钥、对局日志或包含私人数据的回放。

## 检查与实验

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python -m match_monitor
.venv/bin/python -m redalert_bot.selfplay
```

独立 Showdown 机制检查需要 Node.js，以及 `npm install` 安装锁定在 `package.json` 的测试引擎。自我对战默认关闭；其配置是 `validation/redalert_selfplay/settings.json`，仅对服务器确认两个席位均归本账号的 Testing 红警局启用。

304 项测试通过。固定收入的生产模拟验证新版减少步兵、增加坦克，但没有进行新版本的完整线上胜率评估。地图路径、对阵权重和扩矿回本窗口都是近似规则，不保证获胜。监控是本地自动记录，不等于后台模型自动复盘或消息推送。

目录：`pokemon_bot/`、`redalert_bot/` 为策略，`competition_agent.py` 为路由，`altruagent/` 为运行组件，`match_monitor.py` 为监控，`tests/` 为回归与离线实验。更详细的运行说明和历史边界见 [README_CN.md](README_CN.md)。最新生产对照见 [坦克预算报告](reports/redalert_armor_guard_v4.json)。

## 来源与分发边界

官方运行组件来源及本地扩展见 [SDK_PROVENANCE.txt](SDK_PROVENANCE.txt)。宝可梦静态数据来自 Pokémon Showdown；来源和已附第三方许可见 `licenses/`。官方比赛协议：[AltruAgent](https://api.altruagent-game.com/skill.md)。

此仓库不包含真实密钥、历史比赛私有日志、原机器缓存、虚拟环境或预编译可执行文件。`build.sh` 是可选打包脚本；本次源码修订未重新验证或发布 Linux 二进制。
