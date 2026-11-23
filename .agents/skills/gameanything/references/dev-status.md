# 开发状态：`5_build/STATUS.yaml`

谁读这份：resident、构建 agent（builder）、试玩 / 评审 agent（playtester、critic）、协调员。
一个项目一份。它回答「现在到哪了」：她提的每条要求做到没有、谁验证的、有什么已知问题、哪些以前好的又坏了、每轮必须复查什么、
她还有哪些话没处理。网页「开发状态」页按它显示（她只看不改）。跨项目的做法不放这里，放经验（lessons.md）。

## 1. 结构
```yaml
build: m3                  # 这份状态对应的最新一版（gameanything status 的 --build 会更新它）
updated: 2026-10-25T14:05:00
items:                     # 她的每条要求（来自 go 卡、world_plan、她的反馈）
- id: r1
  text: 三道菜都能做完          # 写她的要求本身（可以照抄 go 卡那一条）
  text_en: All three dishes can be finished
  source: go:e_20261025T101500_ab12   # go:<卡片事件 id> | plan:<m> | feedback:<事件 id> | 手写
  state: done              # done | partial | todo | broken | regressed
  since: m3                # 从哪一版起是这个状态
  verified_by: playtester  # builder（自己说做好了）| playtester（独立试玩确认过）
  evidence: m3 第 2 轮 03:12，三道菜都出了餐
known_issues:
- id: k1
  text: 第二关开场镜头抖一下
  severity: low            # low | medium | high
  since: m3
  plan: m4 修
regressions:
- id: g1
  item: r2                 # 哪条要求（可以空）
  what: 菜单按钮点了没反应
  broke_in: m3
  cause: 换 UI 库时按钮层级变了
  fixed_in: null           # 修好后填版本
recheck:                   # 每一轮都要重新验一遍的清单（以前坏过、或她最在意的）
- id: c1
  text: 开局到第一关能走通
  last_build: m3           # 最近一次复查在哪一版
  last_result: pass        # pass | fail
  at: 2026-10-25T14:00:00
  by: playtester
open_feedback:             # 她说过、还没处理或还没回答的话
- event: e_20261025T120102_9f3c   # 对话事件 id（网页可以跳过去）
  text: 奶茶的颜色太浅了
  at: 2026-10-25T12:01:02
  state: open              # open | answered | handled
decisions:                 # 定下来的取舍（谁定的、哪天）
- at: 2026-10-25
  text: 只做三道菜，第四道放下一版
  event: e_…
```
`state` 的意思：`done` 做到了；`partial` 部分；`todo` 还没做；`broken` 做了但坏的；`regressed` 以前 done，现在坏了（一定要有一条 regressions）。

## 2. 命令（都要 `--project P`；P 是文件夹或项目 id）
| 命令 | 谁 | 做什么 |
|---|---|---|
| `gameanything status init` | resident / 协调员（第一次开工前） | 从最新的 go 卡条目、world_plan 最新里程碑、go 卡之后她还没处理的话播种；已有就不动（`--force` 重来，保留已有条目的状态） |
| `gameanything status show [--json]` | 所有人 | 打印（resident 回答「现在到哪了」就从这里讲） |
| `gameanything status set-item --id r1 --state done --build m3 --by builder --evidence "…"` | builder / playtester | 改一条；没有这个 id 时加 `--text` 新建。done 的条目被改成 broken / regressed 会自动记一条 regressions |
| `gameanything status add-issue --text … --severity low --since m3 --plan "…"` | builder / playtester | 已知问题；`--id k1 --fixed` 关掉 |
| `gameanything status add-regression --what … --broke-in m3 [--item r2] [--cause …]`；修好 `--id g1 --fixed-in m4` | playtester | 回归 |
| `gameanything status recheck --build m3 [--add "…"] [--pass c1 …] [--fail c2 --note …]` | playtester | 每轮复查；不带参数列出这一轮还没复查的 |
| `gameanything status feedback --event E --state answered\|handled` / `--add-event E` | resident | 她的话处理了 / 新加一条 |
| `gameanything status decide --text "…" [--event E]` | resident | 记一条决定 |
| `gameanything status card --m m3 [--out card.yaml]` | resident | 从 STATUS 生成 `result` 卡（统计行：做到 / 部分 / 没做 / 回归 / 已知问题） |
| `gameanything status --project P`（不带子命令） | — | 和以前一样：重写项目的 README.md |

## 3. 每一轮怎么用（硬规则，2026-10-25 起）
- **开工前**：builder 和 playtester 先读 `gameanything status show` 和经验（`gameanything lessons show --game <g> --role …`）。没有 STATUS 时 resident /
  协调员先 `gameanything status init`。
- **builder**：每做完一条就 `set-item --state done|partial --by builder --evidence …`；做不了的写 `todo` 和原因进 `add-issue`。
- **playtester**：独立验证每条（不信 builder 的结论），`set-item --by playtester`；跑完 recheck 清单（`gameanything status recheck --build <m> --pass … --fail …`）；
  以前 done 的现在坏了就 `--state regressed`（会自动记 regressions），说清 `--cause`。
- **两者在一轮结束时**：新坑 / 新做法写进经验（`gameanything lessons add …`，候选）。
- **交付**：`gameanything build deliver` 会提醒：STATUS 里还有 broken / regressed，或这一版的 recheck 没跑完。提醒不拦交付，但 result 卡里必须照实说。
- **resident**：她问「现在到哪了 / 做好了没」，从 `gameanything status show` 回答（做到几条、哪几条还没、已知问题、回归），不要凭记忆；
  result 卡用 `gameanything status card --m <m>` 生成再补图。她新提的要求、没回答的话记进 `open_feedback`，回答 / 处理后改状态。
