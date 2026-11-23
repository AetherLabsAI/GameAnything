# Slay the Spire：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### slay_the_spire-001
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: GitHub 上的 ModTheSpire / BaseMod 发布版装上后游戏崩溃。
- 原因: 那些发布版是 2018 年的，不兼容游戏 2.3.4（12-18-2022）。
- 做法: 用 Steam 创意工坊的文件：ModTheSpire 1605060445（放游戏目录）、BaseMod 1605833019（放 `mods/`）；本机模式让她订阅创意工坊。
- 证据: modlab/sts/README.md、CLAUDE.md「Versions」；docs/cross-platform.md Linux / Mac 实测用的都是工坊文件
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-002
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 新版 Java 写法（`var`、record、switch 表达式、`List.of`）编不过，或者编出来游戏加载不了。
- 原因: 游戏自带 Java 8 的 JRE。
- 做法: `javac --release 8`（`sts-build` / `gameanything native build` 已经这样编）；写代码只用 Java 8 语法。
- 证据: modlab/sts/CLAUDE.md；docs/cross-platform.md（`--release 8`，和实验室的读博 jar 逐字节一致）
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-003
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 打完第一场战斗，画面停在死掉的怪上不动，`sts do` 超时。
- 原因: `AbstractDungeon.getRewardCards` 凑不够不重复的卡，死循环。
- 做法: COMMON / UNCOMMON / RARE 各至少 3 张。卡死时 `kill -3 <pid>` 打线程栈再看日志。
- 证据: modlab/sts/CLAUDE.md「Pitfalls found in this lab」
- 可信度: tried once
- status: confirmed

### slay_the_spire-004
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 把第一幕的怪物池全换成 mod 怪后，生成怪物列表时卡死。
- 原因: `populateMonsterList` 要不重复的种类：普通 / 强敌至少 3 种，精英至少 2 种。
- 做法: 种类不够就用组合遭遇凑（例：2 只 Bug、AI Reviewer + Bug），精英留 1 种原版、权重调低。
- 证据: gameplay m1 第 3 轮 MODLOG（ExordiumPatches）
- 可信度: tried once
- status: confirmed

### slay_the_spire-005
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 评审打了两局，10 件 mod 遗物只见到 1 件，原版事件和怪物占了大半。
- 原因: BaseMod 在它自己的 postfix 里才加自定义遗物，在 initializeRelicList 里过滤太早。
- 做法: 在 `receivePostDungeonInitialize` 里把遗物池过滤到 `modid:` 开头的；事件池、怪物池、商店无色卡位用 patch 换掉；看日志里的池大小确认。
- 证据: gameplay m1 第 2 次评审意见 → 第 3 轮 MODLOG
- 可信度: tried once
- status: confirmed

### slay_the_spire-006
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 启动时 ModTheSpire 停在「Missing Mod ID」对话框，游戏进不了菜单。
- 原因: 命令行 / 配置里的 mod id 要和 `ModTheSpire.json` 完全一致（`CommunicationMod` 不是 `communicationmod`）。
- 做法: 照抄 `ModTheSpire.json` 的 `modid`；所有字符串 id 都加 `modid:` 前缀。
- 证据: modlab/sts/CLAUDE.md「Pitfalls」
- 可信度: tried once
- status: confirmed

### slay_the_spire-007
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 类找不到（`EnergyDownPower` 在 `powers.watcher`，`LoseEnergyAction` 在 `actions.unique`）；反射读 `showingStats` 用错类，日志刷了 156 行 NoSuchFieldException，Reject 画面的分数没画出来。
- 原因: 凭印象写包名和字段；`showingStats` 是 `GameOverScreen` 的 protected 字段，不是 `DeathScreen` 的。
- 做法: 写之前在反编译的游戏 / BaseMod 源码里 grep；`ReflectionHacks.getPrivate(obj, 声明它的类, 名字)`；改完看 `sts-log errors` 有没有新异常。
- 证据: gameplay m2 MODLOG「Pitfalls」、m3 第 2 轮 MODLOG
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-008
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 还没进地图时 `AbstractDungeon.getCurrRoom()` 抛异常。
- 原因: BaseMod 的 PostUpdate / PostRender 在主菜单就开始调用。
- 做法: 钩子开头检查「是不是这个 mod 的角色」和 `currMapNode != null`。
- 证据: gameplay m2 MODLOG「Pitfalls」
- 可信度: tried once
- status: confirmed

### slay_the_spire-009
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 她看录像说卡牌上的字对比度太低，完全看不清。
- 原因: 自绘卡框把描述区填成米白色，游戏的卡面文字本来就是米白字 + 金色关键词。
- 做法: 描述区用深色半透明底（和原版一样）；新卡框进游戏后，手牌和放大图都截图看字。
- 证据: gameplay m1 试玩留言（0:23）→ 当天改深色底重新打包
- 可信度: tried once
- status: confirmed

### slay_the_spire-010
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 中文卡面上 `phd:Prepared` 原样显示，`点 Block` 变成 `5lock`，`Deadline` 变成 `0eadline`；中文事件正文里的英文句子空格全丢（`Ithinkweshouldstepback`）。
- 原因: 游戏的中文排版不解析 mod 关键词标记，还会吞掉英文；`#y` 只有前面有空格才生效。
- 做法: zhs 字符串里只写中文词，`#y` 前加空格。语言在游戏关着时改 `preferences/STSGameplaySettings` 的 `LANGUAGE`（ZHS / ENG），测完改回原来的。
- 证据: gameplay m3 第 1、2 轮 MODLOG / ITERATIONS
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-011
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 放大后的手牌，悬停那张升起来又落下（闪烁）；牌叠在一起时最左边那张永远选不中。
- 原因: 游戏每帧在 `AbstractPlayer.updateInput` 里把悬停卡的 drawScale 重置成 1.0；`isHoveredInHand` 按未缩放的尺寸判断；`getHoveredCard` 取手牌顺序里第一张，但最后一张画在最上面。
- 做法: Postfix `updateInput` 重新设缩放；Prefix `isHoveredInHand` 用放大后的范围；`getHoveredCard` 倒着找。注意 `Settings.scale` 只用来换算 1080p 设计单位，`target_x` 这类已经是像素，不要混用。
- 证据: gameplay m3 第 1、2 轮 MODLOG / ITERATIONS（HandLook）
- 可信度: tried once
- status: confirmed

### slay_the_spire-012
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: m3 放大手牌后，先是盖住审稿人分数和血条，后来 5 张时 Write Draft 最后一行被邻牌压住、8–10 张时两侧只露 70%，m4 又发现 10 张时第一张盖住能量球。
- 原因: 每次只看一种手牌张数；状态 / 分数标签放在手牌会伸到的位置。
- 做法: 改手牌布局后固定截 5、8、10 张、10 张 + 状态牌格、悬停各一张，核对能量球、结束回合、血条、状态牌全文；分数标签画在头顶（手牌碰不到）。
- 证据: gameplay m3 第 1–3 轮、m4 第 1–2 轮 ITERATIONS
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-013
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 链式事件的文字被清空；每点一次选项，正文就重新播放逐字弹入（清单文字乱跳）。
- 原因: `AbstractImageEvent` 构造时会清空共享的对话框；`updateBodyText` 会重放弹入动画。
- 做法: 下一个事件用 Supplier 在点 Continue 时再构造，`waitTimer=0.1`；改选项用 `updateDialogOption(i, text, disabled)`，正文不动。
- 证据: gameplay m2 第 2 轮 MODLOG
- 可信度: tried once
- status: confirmed

### slay_the_spire-014
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: Rebuttal 第一回合手里没牌（评审列为阻断问题）；打出的牌还悬在审稿人头上。
- 原因: 排队的 DrawCardAction 要等阻塞队列的阶段切换动作结束才跑；打出的牌还在 `cardInUse` / limbo 里。
- 做法: 在切换动作里直接 `p.draw(n)`；切换开始时清掉 `cardInUse` 和 limbo；要消失的牌设 `purgeOnUse`。
- 证据: gameplay m2 第 2 轮 ITERATIONS #1、#3
- 可信度: tried once
- status: confirmed

### slay_the_spire-015
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 每回合加一张 Major Concern，10 张手牌被塞满、抽不到牌；会复制的 Bug 让战斗打了 21 回合。
- 原因: 每次新建一张卡；复制没有上限。
- 做法: 同类状态牌合成一张（`x3` 计数）或限制手里最多 2 张；复制每场最多 2 次。
- 证据: gameplay m1 第 2 轮、m2 第 2 轮 MODLOG / ITERATIONS
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-016
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: `sts lab console fight <怪>` 测不了精英专属逻辑、Boss 打完后的毕业画面。
- 原因: 控制台总是建 MonsterRoom，不是 Elite / Boss 房间。
- 做法: 在 mod 里加文件开关（例：`/tmp/phd_beats` 强制剧情时刻、`/tmp/phd_force_accept` 直达结局），让 `fight` 不重置结局状态；交付前把开关文件删掉。
- 证据: gameplay m1 第 1–2 轮 MODLOG，m2 第 3 轮 #6，m3 第 3 轮 #4
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-017
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 第 1 轮模拟胜率 0%（主要是机器人太笨）；第 3 版报 59% 接收、第 2 版报 45%，看起来像变简单了，查下来是噪声。
- 原因: 实验室的贪心机器人不读卡面；同一种子每次重放结果会变，换了 jar 更不一样；22 局的误差约 ±20 个百分点。
- 做法: 给角色写专门的出牌策略（自己的 sim 副本）；比较时用同一批种子看总体，再用「同一 jar 关掉改动」做对照组；给她看时同时报模拟结果和评审亲手打的结果，说明误差。
- 证据: gameplay m1 第 1–2 轮 ITERATIONS；m3 RESULT「J: why 59% and not 45%」；skill 提交 671f923
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-018
- date: 2026-10-23
- game: slay_the_spire
- role: builder
- 现象: 改评分取整后，同一批种子的结果整体变了（第一批 15/22，修好后 13/22）。
- 原因: 取整用了 `cardRandomRng`，把游戏后面的随机抽取全打乱了。
- 做法: mod 自己的随机用单独的 `java.util.Random`（用种子 + 层数做种子）。
- 证据: gameplay m3 第 1 轮 MODLOG、ITERATIONS J
- 可信度: tried once
- status: confirmed

### slay_the_spire-019
- date: 2026-10-22
- game: slay_the_spire
- role: builder
- 现象: 尺寸不对的图在游戏里偏移或被裁；抠图后怪物腿上留白边、白洞，她看不懂敌人是什么。
- 原因: 游戏对每种图有固定尺寸（卡图 250x190 / 500x380，遗物 128x128 等）；白底抠图留了边。
- 做法: 按 modlab/sts/CLAUDE.md 的尺寸表缩放（保留透明）；抠图后腐蚀 2 px，封闭的纯白块也去掉；敌人要有清楚的轮廓，第一次出场显示名字。进游戏截图看手牌、放大卡、遗物栏、战斗。
- 证据: modlab/sts/CLAUDE.md「Image sizes」；gameplay m1 试玩留言（1:17）、m2 第 2 轮 #9
- 可信度: verified repeatedly
- status: confirmed

## 试玩

### slay_the_spire-020
- date: 2026-10-25
- game: slay_the_spire
- role: playtester
- 现象: 点击没反应：Mac 上 `CGEventPostToPid` 的点击按不动按钮；实验室里不聚焦就 `xdotool mousemove` 也没用；软件渲染下截图时悬停的卡还没长大。
- 原因: 游戏按每帧的光标位置算按钮的悬停状态，按下时没处在悬停状态就不算点击；软件渲染只有几帧每秒。
- 做法: 先聚焦窗口，把光标移到按钮上，停 ≥0.2 s 再按下、松开（实验室 `ui.sh click` 就是这样）；Mac 上用真实光标（`mac_click = "hid"`）；截悬停效果前等 6–8 s。
- 证据: modlab/sts/ui.sh；gameplay m3 第 1 轮 MODLOG（sim/mv.sh）；提交 841be67（Mac）
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-021
- date: 2026-10-24
- game: slay_the_spire
- role: playtester
- 现象: `native shot` / `drive` 截到、点到的是 ModTheSpire 的启动窗口，不是游戏。
- 原因: LWJGL 2 的游戏窗口不设 `_NET_WM_PID`，`xdotool search --pid` 看不到它。
- 做法: 按游戏的准确窗口标题找（`Game.window_titles`：先是「ModTheSpire 3.30.3」，勾好 mod 点 Play 后是「Modded Slay the Spire」），并确认这个窗口不属于别的进程。
- 证据: 提交 19429ca；_agent/logs/2026-10-24/native-linux-sts（native-shot-1 / -2）
- 可信度: tried once
- status: confirmed

### slay_the_spire-022
- date: 2026-10-24
- game: slay_the_spire
- role: playtester
- 现象: 启动后先出来的是 ModTheSpire 的 mod 列表，不是游戏。
- 原因: Steam 的「Play With Mods」跑的是 `jre/bin/java -jar ModTheSpire.jar`。
- 做法: 用 `gameanything native drive` 勾 BaseMod + 自己的 mod，点 Play；进局后看日志里有 mod 的 loaded 行。Mac 上 Steam 也有「Play With Mods」。
- 证据: docs/cross-platform.md（Linux 2026-10-24）、docs/cross-platform.md「Found on macOS」
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-023
- date: 2026-10-22
- game: slay_the_spire
- role: playtester
- 现象: 教程弹窗挡住命令；战斗第一帧怪物意图是 `DEBUG`；手牌满时脚本打错了牌；营火新选项在界面里不消耗营火，用 `choose` 却结束了营火。
- 原因: 弹窗不归 CommunicationMod 管；意图还没掷出；手牌从 1 编号、每打一张都会变；CommunicationMod 选完选项会自己设 `somethingSelected`。
- 做法: 用 stslab 关教程；每条命令后重新读 state 再选下标；CommunicationMod 点不了的界面截图 + `ui.sh click X Y`；新加的界面行为在真界面点一次。
- 证据: modlab/sts/CLAUDE.md；gameplay m1 MODLOG（第 1–2 轮）
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-024
- date: 2026-10-22
- game: slay_the_spire
- role: playtester
- 现象: 第一版录像是机器人快速出牌，她反馈看不懂在干什么，没有故事和策略的乐趣。
- 原因: 没讲每张牌在做什么、为什么打、对应经历里的哪一刻。
- 做法: speed 1 录完整一局，带游戏声音；每个关键决策一行字幕（从决策日志生成）；按经历的故事线插章节卡；事件画面停下让人读字；剪 3–4 分钟精华 + 完整版。说明里写清是程序在打。
- 证据: gameplay m1 对话（2026-10-22 17:35）→ 讲解版被接受，m2–m4 沿用
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-025
- date: 2026-10-23
- game: slay_the_spire
- role: playtester
- 现象: 同一个种子重放，一次赢一次输；第 2 版录 Accept 的种子 VID11 在第 3 版 jar 上是 Reject，多花了一局 18 分钟。
- 原因: 有些随机没被种子固定，或者和时序有关；改了代码随机序列也变。
- 做法: 录像脚本循环录到出现想要的结局为止（`rec.sh` / `vid.sh`）；剧情时刻用测试开关强制触发，并在说明里写「录像时强制触发」。
- 证据: gameplay m1 第 3 轮 MODLOG；m3 RESULT「FRICTION LOG」
- 可信度: verified repeatedly
- status: confirmed

### slay_the_spire-026
- date: 2026-10-23
- game: slay_the_spire
- role: playtester
- 现象: 前两次截结局淡出画面都晚了，只截到「Proceed」。
- 原因: 最后的结算和祝贺画面都在第三次 `end` 里跑完，命令返回时已经结束。
- 做法: 在第二次 `end` 之前就开截图循环（约 70 帧、每秒 1 帧）。
- 证据: gameplay m3 第 3 轮 MODLOG / RESULT
- 可信度: tried once
- status: confirmed

### slay_the_spire-027
- date: 2026-10-22
- game: slay_the_spire
- role: playtester
- 现象: x264 veryfast 24 fps 只有 0.6 倍速，录像变慢；录出来没声音。
- 原因: 软件 GL 下 CPU 不够；ffmpeg 所在的 shell 找不到 PulseAudio；游戏只有用 `sts-start` 启动时才把声音放进 game2 声道。
- 做法: ultrafast / 20 fps；ffmpeg 的 shell 里设 `XDG_RUNTIME_DIR` 和 `PULSE_STATE_PATH`，录 `game2.monitor`；录完 `volumedetect`。只测了音量就写「没人听过」。
- 证据: gameplay m1 第 3 轮、m3 第 2 轮 MODLOG；m3 / m4 结果卡
- 可信度: verified repeatedly
- status: confirmed
