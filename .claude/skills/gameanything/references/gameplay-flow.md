# 玩法项目的流程（`kind: gameplay`，2026-10-22 起）

> 2026-10-26 起 agent 按状态机做：`gameanything flow next` / `gameanything flow check`，文档是 `core.md` + `modes/gameplay.md` + `steps/gameplay/<步骤>.md`。这份长文件留作参考。

把一段**抽象的人生经历**（读博、创业、带娃、备考……）做成某个游戏**原生机制**里的一套玩法。第一个例子：「PhD: The Spire」，CS 读博做成 Slay the Spire 的角色 mod（用户写的设计笔记就是这种模式的输入样例：映射表、新资源、卡、遗物、敌人、事件、幕和 Boss、流派、第一版范围）。
和另外三种模式的区别：回忆项目重建「那一天」，改编项目重建「作品里的地方」，玩法项目**不重建内容，而是把经历的意义翻译成机制**。核心产物是「经历 → 机制」映射，**先和用户定下映射，再展开内容**。
新建：`gameanything project new --title "PhD: The Spire" --kind gameplay`（游戏默认 `slay_the_spire`，网页新建对话框选「玩法项目」时也会自动选上；其他游戏照样能选）。

## 0. 题材规则（先于一切）
- **障碍不是人**：敌人、Boss 一律是事情（Bug、Scope Creep、The Deadline、Reviewer Concern），不是导师、审稿人、同事这些真人或某个角色化的人。
  泛称的人可以出现在**正面或中性**的文案里（例：结局写「导师笑了」、事件里「同学来聊天」），但不能当敌人、不能被嘲讽、不能指向具体某个人。
- **幽默要普遍**：用过来人都懂的梗，不点名、不影射真实的实验室、学校、公司或个人；用户给了具体人名、组名，进游戏前换成泛称，并在对话里说一句。
- 没有改编项目那种「逐字引用原文」的规则；用户自己的话照常原话记进 `feedback/answers.md`。
- **第一版要小**：Slay the Spire 的默认范围是 1 个角色、25–35 张卡、8–10 个遗物、6–8 个事件、5–6 个敌人、1 幕、1 个 Boss（例：The Deadline）。用户要加，先做完第一版再说。

## 1. 步骤
1. **收经历**：用户在「经历」页（就是素材页）上传文字、设计笔记，或者直接在对话里讲。读完先用一两句复述你理解的「这段经历的核心张力」（例：长期投入 vs 不确定的反馈）。
2. **问题卡**：用 `questions` 卡问只有用户知道的东西：每天在做什么、最难熬的是什么、什么时候最有成就感、有哪些圈内梗、想让玩家感受到什么、哪些是**不要**放进去的（敏感的经历、具体的人）。可以只答一部分。
3. **映射 + 核心循环**：写 `3_remember/gameplay.yaml` 的 `mapping` 和 `core`（格式见下），发 `task` 卡请用户去「机制映射」页（`open: "#mechanics"`）逐条选 保留 / 要改 / 不要，再点「确认机制映射」。
   好的映射是**主题和机制同构**：例「失败的实验也会带来理解」→ 失败给 Insight；「论文要走完 想法 → 实验 → 证据 → 写作 → 投稿」→ Paper Progress 只能在 Submit 时兑现。只是换皮的（把 Strike 改名 Experiment）不算。
   至少给出 3–4 个**能各自打通**的流派（`archetypes`），每个写清打法和关键卡。
4. **第一版范围**：映射确认后，发 `understanding` 卡复述第一版范围（角色、卡数、遗物、事件、敌人、幕、Boss），用户确认后写进 `gameplay.yaml` 的 `scope`。
5. **内容表**：写 `content`（卡、遗物、敌人、事件、Boss），发 `task` 卡请用户去「内容」页（`#content`）逐张看、选、写意见，再点「确认内容」。卡面文字要短而清楚（照 Slay the Spire 的写法：数字在前、关键词首字母大写）；每张卡标上 `archetype`（写 `archetypes` 里那一项的 `id`，页面显示它的 `name`）。
6. **卡图 / 预览图**：要用生图模型画卡图、遗物图、敌人图时，先发 `permission` 卡：会发什么（卡名、卡面文字、风格说明；不发用户的照片）、发给谁、多少张、约多少钱；**写明这些图会成为 mod 里的游戏内素材**（卡面、遗物图标、敌人立绘），会跟着 mod 一起安装和分发。
   两张卡都点了：`gameanything gen request --project "$P" --tool <adapter>:image --inputs 4_design/gen/art.yaml --permission <许可卡> --go <开工卡>` 排队（开工卡的花费来自 `gameanything gen estimate`），由后台执行（硬规则，见 memory-project-flow.md 第 5 步「付费生图由后台执行」）；不要自己调用，也不要找用户要 key。
   画好的图放在 `4_design/art/` 下（例 `4_design/art/cards/read_papers.png`），在 `gameplay.yaml` 里用 `art: 4_design/art/cards/read_papers.png` 指过去，内容页会直接显示；没有图的显示占位。发卡前照 `cards.md` 的规则 curl 一遍 `/media/...` 要 200。每次调用记进 `privacy_ledger.yaml`。
7. **开工**：写 BRIEF 到 `4_design/BRIEF.md`（映射、范围、内容表、题材规则、平衡要求、图尺寸、用户的修改原话），发 `go` 卡（同回忆项目：`estimate`（按构建模型估）、`playtest_rounds`、`wall_hours`）。用户点了开工就**停下交给主会话**启动实验室。
   同时在 `4_design/world_plan.yaml` 写里程碑，首页的「在做 / 做完」和轮次列表读它：`world_plan: {title, game: slay_the_spire, milestones: {m1: {name: 第一版, status: next|building|built, what: 一句话}}}`（标题里有冒号要加引号）。开工时改成 `building`；交付时由 `gameanything build deliver --project P --m <m> --name …` 改成 `built`（它同时查录像、补 play.yaml）。
   Slay the Spire 的耗时参考（2026-10-22 实测）：编译 + 重启约 1–2 分钟；软件渲染下一局模拟约 3 分钟，20 局约 1 小时；一轮构建约 2 小时。
8. **构建（主会话负责，常驻 agent 只转述）**：先看 `config/project.yaml` 的 `build_mode`（规则同 `memory-project-flow.md` 第 7 步「先看在哪里做」）；`lab` 是下面的实验室流程，`native` 在用户自己的游戏里做、不碰 docker，并守「本机模式少打扰」（同第 7 步：先 `gameanything native check`，一轮只 `gameanything native launch` 一次，她点了「现在可以」才开，只 `close` 自己开的；她在用电脑时不把游戏拉到前面，看和按只用 `gameanything native shot / drive`；杀戮尖塔不能热重载）。实验室里：构建 agent 写 mod → 编译 → 装进独立的游戏副本 → **agent 自己打**（试玩）→ 跑平衡模拟 → 写 `5_build/<m>/balance/report.yaml`（格式见下；上一轮的改名留在旁边：`report_round1.yaml`、`report_round2.yaml`，页面能切换）→ **独立评审亲自打两局完整的**（不同流派），按「评审看什么」写意见 → 按评审和平衡数据改 → 再跑。
   - 经验和开发状态：每轮开工前构建 agent 和评审都先读 `gameanything lessons show --game slay_the_spire --role builder|playtester` 和 `gameanything status show --project P`；构建 agent 做完一条 `gameanything status set-item … --by builder`，评审独立验证 `--by playtester`、跑复查清单、标回归；一轮结束各记候选经验（`gameanything lessons add`）。BRIEF 里要写的句子见 `memory-project-flow.md` 第 7 步「每一轮的经验和开发状态」。平衡数字的结论也写进 STATUS 的 items / known_issues。
   - 进度卡（`key: <项目>_m1_build`）的步骤：开工 / 实验室准备 / 第 N 轮 / 试玩评审 / 后续轮次 / 平衡测试 / 试玩录像；每一步主会话发消息来，你如实转述。实时画面：`http://127.0.0.1:6153`（共享沙箱里杀戮尖塔那块屏幕）。
   - **模拟器的数字要先能信再给用户看**：模拟用的出牌程序必须会玩这个角色（比如先攒进度再投稿），否则胜率没有意义（第一轮 0% 主要是程序太笨）。给用户的总结里**同时报**模拟胜率和评审亲自打的结果，并说明程序比真人笨，真人通常更容易赢。
9. **交付**（同 `memory-project-flow.md` 第 7 步的卡片顺序：一段如实的总结 → `result` 卡 → `task` 卡 → 下一步 `options` 卡）：
   - `result` 卡的图：玩法项目没有预览图对照，用录像里的关键一帧（例：Boss 被打倒、毕业画面），放在 `5_build/<m>/play/` 下，地址 `/build/<m>/<文件>`；照 `cards.md` curl 要 200。
   - 交付最后一步 `gameanything build deliver --project P --m <m> --name …`，发 `result` 卡之前 `gameanything build check --project P --m <m>` 要 OK（`memory-project-flow.md` 第 7 步「交付的最后一步」）。
   - 「试玩」页：`5_build/<m>/play/play.yaml` + `video.mp4`；`checks` 写评审的结论（每条：哪张卡 / 敌人、好 / 不清楚 / 太强 / 太弱、原话要点）。
   - **试玩录像（杀戮尖塔的录法）**：挑一个模拟程序**能赢**的种子，用正常速度（speed 1）录完整一局，带游戏声音；按层分章节（例「第 7 层 · 精英 Scope Creep」）；在说明里写清「是程序在打，出牌节奏偏快」。同一种子重放结果会变，录不赢就换次再录。录完自己用 `ffmpeg -af volumedetect` 查声音（`ffmpeg` 在 `source env.sh` 之后才在 PATH 上）、抽几帧看。
   - 「平衡」页：最终报告 + 前几轮的历史。
   - **带回家（让用户自己玩）**：告诉她 mod 的 jar 在哪、需要 ModTheSpire + BaseMod（Steam 创意工坊订阅）、放进游戏的 `mods/` 文件夹、启动时勾上；问她要不要打包成她电脑上能直接用的版本（打包由主会话做）。下一步选项卡里推荐「先自己玩一局」。
   - 把没验证的列清楚（例：某个营火选项在真实界面里没点过、商店库存没看过）。

## 2. 评审看什么（critic 判断**可玩性**，不是「像不像图」）
- **卡面清楚**：每张卡的文字一读就懂、没有歧义、数值和关键词一致；升级效果写清楚。
- **主题和机制贴合**：每条映射在游戏里真的起作用，玩家不看说明也能感到「这就是读博」。
- **流派可行**：每个 archetype 都能凑出一套能通关的牌组（平衡报告里看对应卡的选取率和胜率）。
- **数值**：整体通关率、每张卡「在牌组里时的胜率」比整体高或低 15 个百分点以上的标出来（页面上显示「偏强 / 偏弱」）；没人选的卡要么改要么删；Boss 战回合数合理。
- 不评：画风像不像某张参考图（卡图另由用户在内容页挑）。

## 3. 文件格式
`3_remember/gameplay.yaml`（只由你写；网页不改它）：
```yaml
title: "PhD: The Spire"
mapping:          # 机制映射页；kind: resource | card | relic | enemy | event | boss | rule
  - {id: m2, experience: 读论文、讨论、失败的实验带来的理解, mechanic: 新资源 Insight，强卡消耗它, kind: resource, note: 失败也有收获}
core:
  fantasy: Survive the PhD, build your research identity, and make it to graduation.
  character: {name: The Researcher, hp: 72, gold: 99, start: "起始牌组 …；起始遗物 …"}     # 可选
  resources: [{name: Insight, meaning: 对问题的理解, gain: Read Papers、失败的实验, spend: 强卡的额外费用}]
  loop: [选研究方向, 读论文, 跑实验, 打 Bug, 攒证据, 写论文, THE DEADLINE, Submit]          # 列表或一句话
  archetypes: [{id: theory, name: 理论流, idea: Insight 多、卡少而强, key_cards: [Read Papers, Office Hours]}]   # id: ASCII; name: what she reads
scope: {cards: [25, 35], relics: [8, 10], events: [6, 8], enemies: [5, 6], bosses: 1, acts: 1}   # 内容页显示「目标」
content:          # 内容页；art 是项目内路径，必须是网页能给的图（layout.media_file：工作文件夹下的图片，通常 4_design/art/），不存在就显示占位
  cards:   [{id: read_papers, name: Read Papers, type: attack|skill|power, cost: 1, rarity: basic|common|uncommon|rare, text: "获得 2 Insight。抽 1 张牌。", upgrade: "获得 3 Insight。", archetype: theory, art: 4_design/art/cards/read_papers.png}]
  relics:  [{id: gpu, name: GPU Cluster Access, rarity: uncommon, text: ..., archetype: experiment, art: ...}]   # archetype = an archetypes id
  enemies: [{id: bug, name: Bug, hp: 24, act: Act I, mechanic: 每回合可能复制自己, moves: [{name: Crash, effect: 造成 7 点伤害}, "Hide：获得 5 Block"], art: ...}]
  events:  [{id: e317, title: "Your experiment finally works at 3:17 AM.", text: ..., options: [{label: Go to sleep, effect: 回复 10 HP}], art: ...}]
  bosses:  [{id: deadline, name: The Deadline, hp: 220, act: Act I, mechanic: 倒计时 5 回合 …, moves: [...], art: ...}]
```
`feedback/gameplay_review.yaml`（网页写，你读）：`items` 的键 `map:<id>` / `card:<id>` / `relic:<id>` / `enemy:<id>` / `event:<id>` / `boss:<id>`，`choice: keep | change | drop` + `note`；
`mapping: {state: confirmed, at}`、`content: {state: confirmed, at}` 是用户点了确认。用户写的 note 会原话进对话，确认会有一条自动消息（「确认了机制映射（共 n 条）：…」）。改了 `gameplay.yaml` 的 id，旧的选择就对不上了：尽量别改 id。

`5_build/<m>/balance/report.yaml`（实验室的模拟器写；平衡页读最新一版，多版可切换）：
```yaml
runs: 500
at: "2026-10-22T06:00:00"
win_rate: 0.42                      # 0–1
cards:                              # {id: {...}} 或 [{id, ...}]；id 对上 content.cards 就显示卡名
  debug_overnight: {picked: 0.61, played: 2.4, win_rate_when_in_deck: 0.63}   # picked: 选进牌组的局数占比 0–1（>1 当次数显示）；played: 每局平均打出次数
enemies:
  bug: {avg_turns: 3.2, avg_damage_taken: 6.5}
boss: {id: deadline, avg_turns: 7.4, win_rate: 0.55}
notes: [Debug Overnight 偏强：建议伤害 18 → 15。]
```

## 4. 对话里要说清楚的
- 映射没确认之前不展开内容；内容没确认之前不画图、不开工。
- 平衡数字是模拟器打的，手感要用户自己玩；声音、动画同理。
- Slay the Spire 的实验室能编译角色 mod、自己打、跑平衡模拟、录试玩录像（第 8 步）；手感要用户自己玩，照实说。
