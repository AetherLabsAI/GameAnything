# 一个功能项目的流程（D15）

> 2026-10-26 起 agent 按状态机做：`gameanything flow next` / `gameanything flow check`，文档是 `core.md` + `modes/feature.md` + `steps/feature/<步骤>.md`。这份长文件留作参考。

用户说"想加一个 X"：
1. 先回一句收到；
2. 用问题卡问清楚（放在哪、怎么用、素材从哪来）；
3. 把需求单写进 `3_remember/feature.yaml`（界面的“需求”页读它，用户在那里对每条标“保留 / 要改 / 不要”并点“确认需求”），同时发一张 `understanding` 卡，卡里链接到 `#spec`：做什么、怎么用、怎样算做好、存档里会多什么，用户确认后再开工；
4. 大功能先用方案卡定"做到多大"；
5. 开工、回放、审阅，然后发成果卡。构建 agent 报告做完之前最后一步跑 `gameanything build deliver --project P --m <m> --name "第 N 版 …"`（查录像、补 play.yaml、登记里程碑；退出码 1 = 没交付好）；
   每一轮开工前构建 / 试玩 agent 先读经验和开发状态，做完更新 `5_build/STATUS.yaml`（`gameanything status …`），一轮结束记候选经验（`gameanything lessons add`）：规则和 BRIEF 里要写的句子见 `memory-project-flow.md` 第 7 步「每一轮的经验和开发状态」、`dev-status.md`；成果卡用 `gameanything status card` 生成。
   发成果卡之前跑 `gameanything build check --project P --m <m>`，不是 OK 就不发（规则见 `memory-project-flow.md` 第 7 步「交付的最后一步」）。在哪里构建看 `config/project.yaml` 的 `build_mode`（`lab` 服务器沙箱 / `native` 用户自己的游戏，native 不碰 docker），规则同 `memory-project-flow.md` 第 7 步「先看在哪里做」。

要亲手试的功能（小游戏、手感），第一版就请用户装进自己的游戏试玩（`task` 卡，打开"带回家"）。


## 需求单 `3_remember/feature.yaml`

这是 agent 的文件，界面只读它，不改它：

```yaml
title: 香港美食            # 功能叫什么
goal: 一句话说清要做什么
game: overcooked2
items:
  - id: f1                 # 稳定的短 id，用户的意见按它记
    what: 做什么
    how: 玩家怎么用
    done_when: 怎样算做好（怎么知道它有用）
    saves: 存档里会多什么，没有就写 none
    status: open           # open | confirmed
open_questions: [还没问清的问题]
updated: 2026-10-23
```

用户的选择在 `feedback/feature_review.yaml`（键 `item:<id>`，choice 为 keep / change / drop，note 是原话，也会进对话）；`state: confirmed` 表示点了“确认需求”。看到 change / drop 就改 feature.yaml 的对应条目，再请用户确认。

## 3D 物品：用 Meshy 做，先给用户看预览图

功能里要新的 3D 物品（菜、道具、摆件）时，固定这样做：
1. 先有 2D 参考图（用户给的，或已批准的生成图），放 `4_design/art/<类>/`；
2. 发 `permission` 卡问能不能把这些图发给 Meshy，再发开工卡写明数量和积分（Image to 3D、Meshy-6 带贴图约 30 积分一个）；
3. 不用再写脚本：把要做的写进 `4_design/gen/3d.yaml`（`jobs: [{name: <名字>, images: [4_design/art/<类>/<名字>.png], options: {target_polycount: 8000, should_remesh: true}}]`，可选 `crop`），`gameanything gen estimate --project "$P" --tool meshy:image-to-3d --inputs 4_design/gen/3d.yaml` 的花费写进开工卡；两张卡都通过后排队：`gameanything gen request --project "$P" --tool meshy:image-to-3d --inputs 4_design/gen/3d.yaml --permission <许可卡> --go <开工卡>`。后台核对两张卡后用项目所有者的 key 运行，完成或被拒都会通知你。agent 自己不运行 gen_*.py；一张开工卡只能运行一次；
4. 后台把每个模型的 glb、贴图和 Meshy 的缩略图下载到 `4_design/art/3d/<名字>/`（缩略图是 `preview.png`，`4_design/art/3d/index.yaml` 有 sha256），**先发卡给用户看预览图**，她选“保留 / 重做 / 不要”后再进游戏；
5. 进游戏前在 host 上把 glb 转成游戏能读的格式（OC2：`oc2lab/hkfood/tools/glb2obj.py` 转 obj+png，mod 运行时加载），游戏内特写截图放 `5_build/<轮>/preview/`。
