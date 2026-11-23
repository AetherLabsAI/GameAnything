# 一个回忆项目的流程

> 2026-10-26 起 agent 按状态机做：`gameanything flow next` / `gameanything flow check`，文档是 `core.md` + `modes/memory.md` + `steps/memory/<步骤>.md`。这份长文件留作参考。

1. **素材**
   - 你做：用户在"素材"工作区拖进文件，或者给一个文件夹。你在本机整理：`gameanything ingest`，包括转写、去重、框出照片里的人。
   - 请用户：只有素材太少，或者缺了关键的东西时才问。
2. **看图**
   - 先发许可卡；用户同意后，由你的会话来看图（`gameanything perceive --emit/--collect`）。
3. **人物**：发一张 `task` 卡，请用户去"人物 → 标记照片里的人"（`open: "#people/tag"`）：
   - 框出每个人、起名字、拖进分组、选"在游戏里"的档位、改台词；
   - 告诉用户为什么要做这件事：人物名单决定谁出现在游戏里、怎么称呼；也说明大概要多久（照片多的话十几分钟）。
   - 用户点了"做好了"，或者你在 `people.yaml` 里看到了改动，再往下走。拿不准的人，用问题卡问。
4. **回忆板**
   - 你做：整理出这一天的时刻、段落、原话，写进 `3_remember/board.yaml`。
   - 请用户：用问题卡问只有用户知道的事；然后发 `task` 卡请用户去"这一天 → 确认"（`#board`），确认时刻和顺序、每个时刻有多重要。
5. **设计**
   - 用 `options` 卡问设计上的选择（玩家扮演谁、地点、衣服、留下什么……）；用 `understanding` 卡复述你的理解。
   - 写好 `4_design/world_plan.yaml`，确认的过程记进 `history.yaml`。
   - 再写 `5_build/<这一版>/plan.yaml`：`items:` 逐条列出这一版要做的事（每条 `n`、`title`、`title_en`、`desc`、`desc_en`，可选 `quote`、`quote_en` 放她的原话或原文）。「方案」页只显示这份清单，没写就显示「这一版的条目还没有写出来」：写好之前不要请她去看方案，也不要说「方案写好了」。
   - **预览图（方案定了之后、开工之前，每一版都做）**：文字方案（`world_plan.yaml` / 方案卡）用户确认**之后**，才出预览图；方案还在改的时候不画。
     这是 2026-10-17 圣地亚哥（my-san-diego-memory）里跑通的做法，照着来：
     1. 先发一句：方案定了，下面画每个场景的预览图，请你看。
     2. 要用生图模型：先发 `permission` 卡（发哪些图 / 参考图、发给谁、大概多少钱），再按 `go` 卡的做法写明张数和上限（每个场景 1–2 张，总数不超过 20 张）。用户点了才画；每次调用记进 `privacy_ledger.yaml`。
        不发人脸：用户本人 / 家人的照片，除非用户在许可卡里明确勾了。
        **硬规则：付费生图由后台执行，你不要自己运行 gen_*.py（会被权限检查拦下，重试也没用，别绕）。** 两张卡都点了以后：
        ① 不再写 gen_*.py：把每张图写成一个 job，放进 `4_design/gen/<名字>.yaml`（`out: targets`，`jobs: [{name, prompt, images}]`），发卡前 `gameanything gen estimate --project "$P" --tool <adapter>:<cap> --inputs …` 把花费写进开工卡（许可卡写 `to` 和 `files`）；
        ② 排队：`gameanything gen request --project "$P" --tool <adapter>:<cap> --inputs 4_design/gen/<名字>.yaml --permission <许可卡key> --go <开工卡key>`（只排队，不运行；后台记 privacy_ledger、更新进度卡、写 index.yaml）。老项目已有的 `--tool <名字>`（4_design/tools/gen_<名字>.py）照样能排队；
        ③ 在聊天里只说一句「已经开始画了」（不要说被拦、不要让用户配置任何东西）；后台核对两张卡、用项目所有者的 key 运行，完成、失败或被拒都会给你留言，图出现后你接着审图、发候选卡。
        一张开工卡只能运行一次，要重画请发新的开工卡；`gameanything gen status --project "$P"` 看队列。
     3. 画好后自己先看一遍（有没有商标、店名、真人脸、乱码文字），再把图发给用户：每个场景一张 `candidates` 卡（A/B 两张，`media: image`，图放在项目里并通过 `/media/...` 让网页能看到），
        用户选一张当「构建的样子」，都不满意就写哪里要改，你重画。卡片说明里写清楚：游戏里哪些东西是你自己建、哪些用现成的素材。
     4. 用户选定的预览图进构建包的 `targets/`，BRIEF 里写「照着它搭，搭完同一角度截图并排对比」，试玩评审也拿它来对照（见 landmark-references.md §3–4）。
     5. 预览图是**游戏风格的效果图**（目标游戏的画面风格），不是最终画面；卡片里别承诺做得一模一样。
     6. 改了文字方案（用户在「方案」页改了条目）要重新问：旧的预览图作废还是保留；不要悄悄沿用。
     7. 改编作品（小说 / 影视 / 动漫）也一样：场景方案确认 → 预览图 → 确认 → 开工。原文引用、版权规则见改编模式的文档。
6. **形象**
   - 你做：画头像和行走图，先自己把每张和照片并排看一遍。
   - 请用户：发 `task` 卡请用户去"人物"确认形象（`#people`）。每次重画之前，先说明会发什么、大概多少钱。
7. **每一版**
   - **沙箱（`lab`，用户自己的 Linux 机器上的 Docker）**：只用 `gameanything lab sandbox`（up / tool / build / shot / input / look / fetch / down）
     和游戏自己的沙箱工具（doctor / layer / run / shot / rec / log / stop）；进世界、开局用 `input` 加截图来做，改了 mod 就 stop、build、run 重来。
     见 setups/linux-sandbox.md「Building in the user's own sandbox」。
   - **先看在哪里做**：读 `config/project.yaml` 的 `build_mode`（用户在新建向导「在哪里做」或项目菜单里选的）。`lab`：上一条的沙箱。`native`：用户自己的游戏，**不碰 docker、实验室和沙箱**，用 `gameanything native backup / build / install / log --game <游戏>`（先备份存档，只改 Mods 文件夹）。**本机模式少打扰**（规矩见 `docs/cross-platform.md`「本机模式少打扰」）：
     - 开游戏只能用 `gameanything native launch --project "$P" --round <这一轮> --reason "要测什么"`。它会在对话里发卡「要开游戏测一下，现在可以吗？」，她点了「现在可以」才开（或者按她在项目菜单「什么时候开游戏」里选的时间段 / 随时可以）。退出码 2 = 还在等她，先做别的，不要在对话里再催；3 = 游戏已经开着（可能是她在玩），不开也不关。
     - 关游戏只能用 `gameanything native close --project "$P"`：只关 gameanything 自己开的那次，她自己开的游戏从来不关。
     - **她在用电脑时绝不把游戏拉到前面、绝不动她的鼠标键盘。** 看游戏只用 `gameanything native shot --project "$P"`（只截游戏窗口），按键只用 `gameanything native drive --project "$P" "key escape" "click 640 360"`（只发给 gameanything 开的游戏窗口，不抢焦点）。不要用 `osascript activate`、`open -a`、`xdotool windowactivate`、`SetForegroundWindow` 之类的东西。
       - `drive` 退出码 2 = 她在用电脑（60 秒内有输入）或游戏不在前面（Windows）：停下，先做别的，过一会儿再试；不要在对话里催她。3 = 不是 gameanything 开的游戏 / 看不出她在不在（不要硬来）。
       - 她选了「我没在用电脑时」：`launch` 返回 2（code `busy`）就是她还在用，放到后台 `--wait` 等，不发卡、不问她。
       - 第一次在 Mac 上用 shot / drive 前跑 `gameanything native permissions`；没有权限就照它打印的话告诉她去系统设置里打开（不要自己猜路径）。
     - **能不能操作屏幕（2026-11-01 起）**：本机模式第一次 `native launch` 之前、以及项目换了 agent / 模型以后，你自己跑
       `gameanything native ready --project "$P" --if-needed --card-file "$TMPDIR/ready.yaml"`（查的是**你这个 agent** 的沙箱和它所在的 app；退出码 0 能看能点，1 只能看，3 都不行；`native launch` 没查过会提醒）。看它最后一行 `next:`：
       - `ok`：照常用 shot / drive。
       - `card`：用 `gameanything chat card --project "$P" --file "$TMPDIR/ready.yaml" --text "一句话说明"` 发**一张**卡（key `native-ready`，两个选择「我打开了，再查一次」/「不给，我自己点」，卡里有她要做的每一步，写着要给哪个 app 权限）。她点了以后再跑一次 `native ready`（不用 --if-needed）。
       - `wait`：卡已经发了、她还没点：不要再发，也不要在对话里催。
       - `self`：她选了自己点（`native_hands: self`，她可以在项目菜单「什么时候开游戏」→「谁来点游戏」里改）。不调用 drive（会被拒绝，code `self`）；每一轮的进度卡写清楚要她点的地方（「点主菜单的 Load」「按 Esc 关掉对话框」），等她说「好了」再看结果；shot 也不行时请她发截图或说说看到了什么。
       - 不要为了能截图 / 按键去关掉或放宽任何 agent 的沙箱（Codex 的 workspace-write 也一样）。
     - Windows：drive 只在游戏已经在最前面时按键。她勾了「测试时允许把游戏切到前面」（`native_front: away`），而且她离开电脑 1 分钟以上，drive 会把 gameanything 自己开的游戏切到前面再按（最小化的先还原），结果里有 `fronted`；她在用电脑或看不出时从来不切。
     - 每一轮先把改动全部做完、编译，再跑 `gameanything native check --project "$P" --src <构建好的 mod>`（对照游戏的程序集 / jar 查引用；我的世界加 `--server` 用无界面服务器试加载），查出的错先改；然后**一轮只开一次游戏**，把所有改动一起测。游戏能热重载的（胡闹厨房 2 装了 ScriptEngine、城市：天际线）用 `gameanything native reload` 换新版本，不重开。
     - 进度卡写明这一轮开了几次游戏（`gameanything native launches --project "$P"`），例如「这一轮开了 1 次游戏」。
     - 没有 `build_mode` 的老项目：按 `gameanything native doctor --project "$P"` 的自动规则。选的那种这台电脑做不了（`gameanything project set-mode <id> --show`），照实告诉用户，请她在「在哪里做」里换。`go` 卡的跑法和估算只写这一种。
   - **录下构建过程**：开工前跑 `gameanything project settings`，`record_builds` 为 true（默认，用户在网页「设置」里可关）就带 `--record` 启动实验室（`mclab_rt.py up … --record` / `sdlab_rt.py up … --record` / `cslab_rt.py up … --record`）：游戏画面录进 `<run>/work/recordings/`，代码每 2 分钟快照进 `<run>/history.git`。为 false 就不录。构建结束 `down` 会停掉录制；**最后一轮做完但实验室要留着（给用户逛）时，马上跑 `mclab_rt.py record-stop <name>`**（2026-10-21：录制空转了 9 小时，多出 1.26 GB 空画面）；把子 agent 的操作记录也复制进 run 目录保存。
   - 开工前发 `go` 卡（每条写明出自用户哪句话）；用户点了开工，再启动构建，同时开着磁盘看门狗。
   - `go` 卡一定要带 `estimate`：先跑 `gameanything estimate --project P --size small|medium|large --account subscription|api --yaml`（不写 --agent / --model 就按项目的构建模型估）
     （功能用 small，婚礼那样的一整期用 large），把输出并进卡片文件。API 用户看到金额，订阅用户看到额度提醒；用户点开工之前什么都不启动（D18）。
   - **构建只用项目的构建模型**（2026-10-28 起，代替 D21 的 runners）：config/project.yaml `build_model`（`gameanything project set-model "$P"`；她在输入框旁的「构建」里换）。
     `chat card` 会在开工卡上写明 `build_model`（只读）并去掉 `runners`；卡上不能再选跑法。估算要按这个模型（`--project`）。她开工前换了模型，就用同一个 key 重发一张带新估算的卡。
     那个模型项目所有者跑不了（没登录 / 没 key），构建不会换成别的模型，而是停着并发一条通知给你：照实告诉她去「我的 agent」登录或在「构建」里换。Fable 非常贵，是构建模型时要提醒她一句。
   - `go` 卡还要写 `playtest_rounds`（试玩评审最多几轮，默认 6）和 `wall_hours`（最多几小时，默认 5）（D22）。用户可以在卡上改轮数；回答里带
     `playtest_rounds` 时，用 `bench run … --playtest-rounds N` 启动，并在 BRIEF 里写一句「你最多有 N 轮试玩」。
   - 启动时加 `--keep-going 0.8`：构建 agent 在用满 80% 的时间之前停下，实验室会用剩下的时间再启动它一次，让它照最新的评审意见接着改
     （2026-10-17 UCSD 两版都提前收工：3 小时 17 分、2 小时 39 分，上限 5 小时；BRIEF 里写「用满时间」没用）。
   - 启动后马上在后台挂 `gameanything build watch --project P --session S --key <进度卡 key> --milestone … --trial <trial 目录> --steps … "current:构建中：{round_text} · {time_text}" …`，
     进度卡会自动显示「试玩第几轮（最多几轮）· 已跑多久（最多几小时）」，构建结束它自己退出。
   - **每一轮的经验和开发状态（硬规则，2026-10-25 起；dev-status.md、lessons.md）**：
     - 第一次开工前没有 `5_build/STATUS.yaml` 就 `gameanything status init --project P`（从 go 卡、world_plan、她还没处理的话播种），recheck 清单写进去（`gameanything status recheck --project P --add "…"`）。
     - 给构建 agent 和试玩 / 评审 agent 的 BRIEF 都要写这几句（他们读不到这份文档）：
       「开工前先读 `gameanything lessons show --game <g> --role builder`（评审：`--role playtester`）和 `gameanything status show --project P`。」
       「构建 agent：每做完一条要求就 `gameanything status set-item --project P --id rN --state done|partial --build <m> --by builder --evidence "<第几轮 + 时间 / 帧>"`。」
       「试玩 agent：不信构建 agent 的结论，自己验证每条 `--by playtester`；跑完复查清单 `gameanything status recheck --project P --build <m> --pass … --fail … --note …`；
        以前 done 的现在坏了就 `--state regressed`，`gameanything status add-regression --id gN --cause …` 写原因。」
       「一轮结束时，新坑和新做法各记一条 `gameanything lessons add --game <g> --role builder|playtester --symptom … --cause … --fix … --evidence …`
        （只对这台电脑成立的加 `--local`；不写她的照片、人名、存档细节）。」
     - 主会话 / 协调员每期结束 `gameanything lessons review`：确认、合并或删掉候选。
   - 构建完做独立回放，要用真实输入；仪式这类长场景要回放到底。然后派一个独立的审阅（REVIEW.md、checks.yaml），生成试玩页（`make_play.py`），补上英文（`gameanything i18n missing / add`）。
   - **每次交最终结果，「试玩」页必须有 agent 的试玩录像（硬规则，用户 2026-10-21：大观园第 1 版交付时试玩区没有录像）。** 没有 `5_build/<m>/play/play.yaml` + `video.mp4`，就不算交付，不发 `result` 卡。
     - 录像要在**干净的最终构建**上录（不是开发过程的录屏，也不是截图拼起来），按用户会走的路线完整走一遍，带游戏声音（新沙箱带 `CUDA_DISABLE_CONTROL=true`；Minecraft 用 `mc-run` 启动，它会设好 PulseAudio）。录完先自己查：`volumedetect` 的 max 不能是 -91 dB（静音），再抽几帧看画面对不对、有没有黑边。
     - `play.yaml`：`video`、按地点 / 时刻分的 `chapters`（标题 + 秒数）、`scenes`（用户选的目标图 / 预览图）、`checks`（每处一条：像不像、还差什么，来自独立评审）。录像确实是独立回放、或确实用真实键盘输入录的，才写 `independent_replay: true` / `real_input: true`（试玩页只按这两项显示「独立回放 · 真实键盘输入」，不写就不显示）。
     - **交付的最后一步（硬规则，2026-10-24：feature m3 / m3b、sims4-flying-car round2 只交了文件夹，没登记里程碑、没有 play.yaml，试玩页看不到）**：
       构建 agent（或代它收尾的主会话）在报告「做完了」之前跑
       `gameanything build deliver --project P --m <m> --name "第 N 版 …" [--what "一句话"] [--chapters <章节文件，例 final.chapters.yaml>]`：
       查录像能放（ffprobe）、没有 `play.yaml` 就写一个（一章「完整录像」，或用 `--chapters`）、校验 `play.yaml`（chapters 每章 moment / title / t，
       引用的截图 / 场景图 / 声音文件都在）、在 `4_design/world_plan.yaml` 登记里程碑（status built、at、name / what，原有字段和注释保留）。
       退出码 1 = 没交付好：照它列的修好再跑；重复跑没有副作用。
     - 发 `result` 卡之前：`gameanything build check --project P --m <m>` 必须是 OK（只读；不带 `--m` 列出所有 5_build 文件夹缺什么）。没 OK 不发 `result` 卡。
     - `gameanything build deliver` 会按 STATUS 提醒（不拦）：还有 broken / regressed、回归没修好、这一版的复查没做完、done 只有构建 agent 自己说的。
       `result` 卡用 `gameanything status card --project P --m <m> --image /build/<m>/… --out "$F"` (`F=$(mktemp "$TMPDIR/card-XXXXXX.yaml")`) 生成（统计行来自 STATUS），提醒里的问题在总结里照实说。
     - 发卡前 curl 一遍 `/build/<m>/video.mp4` 要 200；页面左侧这一版要显示「等你看录像」。
     - **剧情在原地演（2026-10-22，用户：「为什么那几个情节不是在已经做好的场景发生？而是又加了额外的时长？…到了那个场景就能看到对应的人物」）**：游览路线走到哪个景点，就在那个景点的停留里演那里的剧情（人物出场、字幕），不要把剧情集中放到片尾单独一段。路线按地点排，剧情跟着地点；一个景点有戏就把停留时间拉长到戏演完。
     - **录法（2026-10-22，用户：「视角不对，好多地方没看到好的效果」）**：
       - 机位用评审调过的取景点（`shot gNN` 那组），不要用玩家的落脚点 / 瞬移点（会贴墙、钻树叶、对着台阶）；每个机位前方约 3 格内不能有树叶和方块。
       - 运镜在游戏里做（mod 的 `tour` 命令按 tick 插值位置和朝向，缓入缓出）：每处先远景再慢慢推近、停 3–4 秒、可微转向第二个看点；片头从空中降到入口，片尾升到鸟瞰。不要从外面一条条发命令转镜头（又慢又卡，只会原地横扫）。
       - 地名字幕由录像流程按时显示（标题 + 一句短引文，放下方），录像时关掉「走进区域就弹字幕」，否则瞬移会串台。
       - 节奏：每处 10–12 秒，全片 4–5 分钟；录前清屏（关命令回显、隐藏 HUD、正午、晴天）。
       - 录完按章节每章抽 3 帧拼成总览图，自己逐章看：主体清楚、字幕对得上，才放进试玩页。
     - 改编项目（Minecraft 等）也一样：用地点代替回忆时刻做章节，例：大观园第 1 版 `5_build/m1/play/`（13 处游园，126 秒，带声音）。
8. **用户的意见**
   - 试玩页、形象页、方案页上的留言和选择都会进对话。
   - 你要逐条回应：记进 `feedback/next_round_notes.md`；要用户选做法的，发方案卡。
9. **带回家**（收尾那一期）：先备份用户的存档，再装进用户自己的游戏；说清存档里会多什么、怎么卸载。卸载的影响要实际测过再写。
10. **备份**：每一版做完，备份到用户指定的地方（D16，要用户同意过）。用户的歌、受版权保护的文件不进第三方的备份。

