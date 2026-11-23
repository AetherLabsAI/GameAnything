# 工作规则和对话循环

谁读这份：替用户干活的 agent 会话（D6：用户自己的 agent 会话，不限于 Claude Code）。每次接手一个项目都先读一遍，再读项目里的
`feedback/answers.md` 和对话。

## 0. 每次都要做的
- **先看后台调度在不在（默认）**：`gameanything agentd status`。`gameanything agentd` 在跑时，每个有新消息的项目它都会马上回一句「收到，agent 正在过来」，
  再启动一次无界面的 Claude Code 运行来回复（角色和规矩在 `resident-prompt.md`）。这时你不用自己挂 `wait --all` / `--unowned`；
  你就是被它启动的那次运行时，照 `resident-prompt.md` 做：claim、read、先回一句、做事、退出，不挂监听。下面的 `wait` 循环是没有 agentd 时的做法。
- **构建也由后台跑（`gameanything agentd run --builds auto`，默认；环境变量 GAMEANYTHING_BUILDS）**：resident 写了 `build_start` 请求，agentd 核对开工卡（点了开工、
  每张只开一次工），再起一个无界面的构建 agent（`roles/builder.md`），一个项目同时只有一个；lab 模式由构建 agent 自己用 `gameanything lab sandbox`
  起用户的沙箱。构建 agent 不进对话，进度和结果用 `gameanything agentd notify --from builder` 交给 resident 转告她。状态：`gameanything agentd status`、
  `5_build/<m>/.build_run.json`。agentd 第一次以 auto 运行之前的旧请求（`<data>/agentd-builds.json` 的 `since`）永远不会被它执行。
- **一直挂着等所有项目（D20，自动认领）**：后台跑
  `while true; do gameanything chat wait --all --session S --timeout 3600; rc=$?; [ $rc -ne 2 ] && break; done`。
  它盯着用户登记过的所有项目：没人管的项目来了消息，会自动认领（对话里出现"agent 接上了这个项目"），同时进行的项目最多
  `max_active_projects` 个（默认 3，用户在网页的「设置」里改），多出来的排队，有空位再按先来后到接上；2 小时没有对话的项目会自动放手。
  它一退出，就照它打印的每一行 `gameanything chat read --project P --session S`，先回一句，处理完再重新挂上。不挂着，用户在网页里说话就没人理。
  用户刚建的新项目不用等用户提醒：挂着 `--all` 就会接上。打开一个项目先读 `config/project.yaml` 的 `game`。
- 只想管一个项目时，也可以 `gameanything chat claim --project P --session S` 后用 `gameanything chat wait --project P --session S`。一个项目只能有一个会话负责对话。
- **网页上的「工作中」转圈要真实**（用户 2026-10-21：「agent 回复说收到开始整理，又没有那个工作中的加载圈，导致我不知道是不是在工作」）：`read / say / card / progress` 会把页面切成「工作中」，`wait` 会把它切回「空闲」。所以一边干活一边在**后台**挂等待时，必须用 `gameanything chat wait --listen ...`（不改状态），活干完、最后一句 `say` 之后再跑 `gameanything chat idle --project P --session S`，页面才显示空闲。前台阻塞等待（什么都不干、只等用户）用普通 `wait`。长任务每隔一段时间发一次 `progress`，让用户看到在动。
- **先读再挂监听**：接手一个对话时先 `gameanything chat claim`，再 `gameanything chat read`，然后才挂 `gameanything chat wait --listen`。有没读过的用户消息时，`wait` 会立刻返回，监听等于没挂上（2026-10-22 实际踩到）。
- **先回一句收到，再去做事**：用户说了什么，先在对话里回一句（`gameanything chat say`），说明你理解了什么、接下来做什么。
  长任务放到后台，做的过程中用进度卡（`gameanything chat progress`）更新。
- 你发的每条消息和卡片都带英文（`--text-en`，卡片 yaml 里写 `en:`）。只有用户自己说的话不翻译。
- **用户的原话不能改**：`chat read` 会把原话逐字记进 `feedback/answers.md`。你的理解另外写成"gameanything 的理解"，请用户确认。
- **不编造真人的事实**：习惯、往事、性格、地点、谁说了什么。台词草稿只用用户确认过的事实，标成 `source: draft`。
- **影响存档的取舍由用户选**（D8）：人物三档、地点三档、会改存档外观的东西。用方案卡给几个选项，每个都写清代价，给出建议，不替用户决定。
- **发送前先问**：要把照片、文字发给模型之前，先发许可卡（`permission`），写清发什么、不发什么、发给谁；每次都记进 `privacy_ledger.yaml`。
- 用户的东西只放在用户自己的电脑上；有版权的音乐和影视只用用户自己提供的文件（D9），不从网上下载，也不进备份。
- 只按确切的 PID 结束进程；长任务开始前看 `df -h`；临时文件放数据盘。

