# 她的反馈记录：`feedback/records.yaml`（`gameanything feedback …`）

谁读这份：resident（每次她提意见）、builder（开工前、交付前）、协调员。设计和论文用的指标定义在 `docs/feedback-loop.md`。

她的每一条意见（对话里的一句话、试玩录像某一秒的留言、截图上框出来的地方、她发来的图）都是**一条记录**：她的原话（照抄，永远不改）、
你的理解、类别、和哪条 STATUS 要求连着、怎么修的、同一画面改前 / 改后、她最后点头没有。目的是让她**不用把同一件事说第二遍**。

## 1. 记录从哪来
- `gameanything chat read` 自动给带「锚点」的话建记录（状态 `new`，类别是关键词猜的）：试玩页某一秒的留言（录像时间 + 那一帧 + 章节）、
  截图上的框、她发的图、时刻 / 检查的意见。输出里会有 `[feedback] 新记录 f12 …`。
- 只有文字的话由你判断：是对作品的意见（要改什么、哪里不对、问这是什么）就 `gameanything feedback add --project "$P" --event <事件 id>`；
  问进度、说「开始吧」这类不是反馈，不建。一句话里说了两件事，建两条，`--words` 各抄她原话的一段。

## 2. 每条都要写清你的理解（resident，读完她的话就做）
```
gameanything feedback set --project "$P" --id f12 --interpretation "客厅太简陋，要有欧式酒店的奢华感" \
  --class taste --kind sparse_plain --scope user --certainty high [--target 客厅]
```
- `--class`：bug（坏了）/ taste（不好看、不对味）/ request（要加、要改）/ question（她在问）。
- `--kind`：意见的种类，看 `docs/feedback-loop.md` 7.2 的表（sparse_plain 简陋、not_like_reference 不像、mood 氛围、color_light 颜色光线、
  clipping 穿模、unreadable_object 看不出是什么、layout_scale 位置比例、model_quality 模型贴图、missing_content 少了东西、npc_life 人物不动、
  camera 录像镜头、text_language 游戏里的文字、ui_delivery 网页 / 卡片 / 汇报、game_error 游戏报错、other）。同一种再出现就是「她第二次说」。
- `--scope`：project（只关这个项目）/ user（她个人的口味）/ game / mode / craft（通用手艺）/ system（我们系统自己的 bug：交给协调员修代码，不写进提示词）。
- 输出说「和 f3 是同一类意见」时，这是她第二次说同一件事：回答她时承认这一点，并在要求里写清这次和上次的修法有什么不同。

## 3. 理解不确定：先问她，再动手（硬规则）
`--certainty low` 的情况：她是在问「这是什么」；画面里有好几样东西都可能是她说的；按你的理解要删掉或换掉她以前要过的东西；
需要只有她知道的事实。真事：她问「飘着的白色、黄色方块是啥」，其实是她要的水晶吊灯从下面看像浮块——按「删掉浮块」改就把吊灯删了。
```
F=$(mktemp "$TMPDIR/card-XXXXXX.yaml") && gameanything feedback card --project "$P" --ids f12 --out "$F" && gameanything chat card --project "$P" --file "$F"
```
（`questions` 卡，key `fbc-f12`，那一帧当图。）她答了：`gameanything feedback confirm --project "$P" --id f12 --as confirmed|corrected [--interpretation "改正后的理解"] --event <她回答的事件>`。
确认之前不要把这条交给构建。

## 4. 连到 STATUS
`gameanything feedback link --project "$P" --id f12 --new-item "客厅要有欧式酒店的奢华感…"`（或 `--item r8`，已有的要求）。之后 builder
`gameanything status set-item --id r8 --state done …` 会把连着的记录自动改成 fixed（记下哪一版修的）。

## 5. 同一画面复拍、她点头（builder 交付前，resident 发结果时）
- builder：`gameanything feedback pairs --project "$P" --m <m> --todo` 列出这一版修好、要在**同一个画面**复拍的记录（改前那一帧、录像时间、章节、地方）。
  把镜头放回原来的位置截图，存到 `5_build/<m>/play/verify/<id>_after.png`，然后 `gameanything feedback verify --project "$P" --id <id> --m <m> --after <图>`。
  `gameanything build deliver` 会给剩下的自动从新录像同一章节的同一时刻取一帧（章节 id 相同时），实在没有的列出来并提醒。
- resident：结果卡（`gameanything status card`）里有「同一画面复拍 X 条」和第一对对比图；另外发 `gameanything feedback card --project "$P" --kind-of-card verify --m <m>`
  （key `verify-<m>`，每对一张图）问她改好了没有。她说好：`gameanything feedback verdict --id f12 --ok`；不好：`--not-ok`（记录重新打开）。
  她说「这一版可以了」/ 选了「带回家」：`gameanything feedback accept --project "$P" --m <m> --how all_ok|take_home|explicit`。
- 记录只有在她点头后才关掉；builder 说修好了不算。

## 6. 其他
- `gameanything feedback show` 看全部。
- `gameanything feedback brief --project "$P"`：builder 开工前看的简报（她的偏好、她说过不止一次的、要复拍的、相关经验），会记下给了哪些。
- 她的偏好（个人口味）在「我的偏好」页，她自己能看、能改、能关；`gameanything profile add --project "$P" --text … --kind … --from <项目>:<记录>`
  只加候选（默认关），她打开或第二个项目里证实后才用。偏好和记录都不进公开的经验文件（lessons.md 第 3 节）。
- **回顾**：一版交付、她的意见进来以后，下一版开工时 builder 会先做回顾（agentd 在开工消息里写明）；最后一版（没有下一版）由你做：
  `gameanything feedback retro --project "$P" --todo` 列出还没回顾的版本，`--m <m> --emit` / `--collect`。回顾给她的偏好加的是**候选**（默认关），
  输出说有新候选时告诉她「我的偏好」页上可以看、打开或删掉（她打开就算她确认了）。

## 7. 研究用的数据（只在研究模式开着的项目里）
第 1–6 节是产品，每个项目、每一版都做（完整的流程）。这一节只在**研究模式**开着时才有：`gameanything project set-study <项目 id>` 显示开没开，
默认关（她 2026-10-27 定的：做研究时才开，不能影响她的体验）。研究模式没开时：不发 `feedback-judge` 卡（`chat card` 也会拒绝），
不跑 judge / label / metrics / datacheck / condition（命令会说「研究模式没开」），开发状态页上没有「反馈和改进」面板，
**不要跟她提研究、实验、对照或条件**。开关只由协调员按维护者的话改，你不要自己开或关。
- `gameanything feedback metrics` 看重复意见率等数字（研究模式下开发状态页的「反馈和改进」面板上也有）。
- `gameanything feedback accept` 只记进研究的日志：研究模式没开时它什么也不记，照常调用没关系。
- **盲法条件**：每一版按一个固定的规则（`docs/feedback-loop.md` 7.8）跑完整的流程（C4）或只带经验（C1），开工时定好、记下来。
  她不知道哪一版是哪种：**永远不要**在对话、卡片、消息里提条件、对照、实验分组，也不要替她查 `gameanything feedback condition`。她问起「为什么这次没有对比图」，
  就说这一版没有做同一画面的对比，下一版会看情况。
- **模型标注（LLM judge）**：研究模式开着的项目，先发一次许可卡：`F=$(mktemp "$TMPDIR/card-XXXXXX.yaml") && gameanything feedback judge --project "$P" --card --out "$F" && gameanything chat card --project "$P" --file "$F"`
  （key `feedback-judge`，说清楚发什么、不发什么、只做统计）。她不同意就不做，不再问。她同意后（不急，闲的时候）：
  `gameanything feedback judge --project "$P" --emit --model <你的模型>`，每个请求文件在一个新的上下文里答（子 agent 最好，只给它那个文件），写到文件里给的路径，
  然后 `gameanything feedback judge --project "$P" --collect`（记进 privacy_ledger.yaml）。标签只放在记录的 `labels` 里，不改你写的类别。
- `gameanything feedback datacheck --project "$P"`：论文要的每一项数据有没有在记（✗ = 缺了，告诉协调员）。
