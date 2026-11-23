# Civilization VI：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。

2026-10-26 第一次 Linux 往返（Aspyr 1.0.12.9，暂停前的 WIP）和 2026-10-28 的真机往返（wc-cities 当 Linux 电脑，真 Steam）留下的。

## 开发

### civ6-001
- date: 2026-10-26
- game: civ6
- role: builder
- 现象: mod 被扫描进 Mods.sqlite，但每次启动都被游戏改回禁用；官方 Additional Content > Mods 页显示 `Not compatible`。
- 原因: `.modinfo` 的 `<Properties>` 少了 `<CompatibleVersions>2.0</CompatibleVersions>`。
- 做法: 每个 `.modinfo` 都写 `CompatibleVersions 2.0`（游戏自带的 DLC 都写）；`native check` / `build` 没有它就拒绝。不要让她勾「忽略兼容性警告」来掩盖。
- 证据: _agent/logs/2026-10-25/civ6-native-linux/civ6-mod-not-compatible-detail.png
- 可信度: tried once
- status: candidate

### civ6-002
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 10-26 的冒烟 mod 在 Modding.log 里已加载，但世界追踪面板仍写着「Choose Research」，没有任何可见变化。
- 原因: 两处错：文字文件放在 `.modinfo` 顶层的 `<LocalizedText><File>` 里（那里只放 mod 自己名字的文字，文件不会被加载）；世界追踪面板用的是 `LOC_WORLD_TRACKER_CHOOSE_RESEARCH`，不是 `LOC_HUD_CHOOSE_RESEARCH`。
- 做法: 文字一律走动作：`<FrontEndActions>` / `<InGameActions>` 里的 `<UpdateText><File>Text/x.xml</File></UpdateText>`，文件内容 `<GameData><LocalizedText><Replace Tag="LOC_..." Language="en_US"><Text>…</Text></Replace></LocalizedText></GameData>`（照游戏自带 DLC）。改界面上的字先在 `steamassets/base/assets/ui/**.lua` 里找它真正用的 LOC 标签。`native check` 会对顶层 `<LocalizedText><File>` 报警告。
- 证据: _agent/logs/2026-10-28/civ6-smoke/13-PROOF-frontend-main-menu.png、17-PROOF-in-game-world-tracker.png、18-logs-in-game.txt
- 可信度: tried once
- status: candidate

### civ6-003
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 10-26 记的是「新 mod 只有 Mods 行、没有 ModGroupItems 行，所以没启用」；10-28 同一版本里，合格的新 mod 第一次启动被扫描后，游戏自己在当前组加了一行 `Disabled = 0`，主菜单马上出现 mod 的前端文字。
- 原因: 当前 Linux 版的开关在当前选中的 `ModGroups` 的 `ModGroupItems.Disabled`（`Mods` 表没有 `Disabled` 列）；10-26 那次 manifest 不兼容（civ6-001），所以没被加进组。
- 做法: 第一次 install 后正常启动游戏即可；之后再 install 一次只是确认开关（「Mods.sqlite already enabled」）。GameAnything 只改游戏自己建的行，游戏开着时不改 Mods.sqlite。
- 证据: _agent/logs/2026-10-28/civ6-smoke/22-p2-reinstall.txt
- 可信度: tried once
- status: candidate

### civ6-004
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 测试用户的 `HOME` 和 `XDG_DATA_HOME` 都指向测试目录，游戏仍然把日志、Mods.sqlite、存档写到系统账户自己的 `~/.local/share/aspyr-media/Sid Meier's Civilization VI`。
- 原因: Aspyr 的 Linux 版用 passwd 里的家目录（getpwuid），不看这两个环境变量。
- 做法: game.yaml 的 Linux 用户目录写死 `{home}/.local/share/aspyr-media/...`，不用 `{xdg_data}`；同一台机器上要隔离数据只能换系统账户（实验室就是直接用沙箱账户的这个文件夹）。
- 证据: _agent/logs/2026-10-28/civ6-smoke/05-r1-close-wrong-folder.txt（/proc/<pid>/fd 指向 /home/player/.local/share/aspyr-media）
- 可信度: tried once
- status: candidate

## 试玩

### civ6-005
- date: 2026-10-28
- game: civ6
- role: playtester
- 现象: 启动后先是长达数分钟的开场动画和初始化（窗口像卡住），然后弹「2K Games Online Policies, Agreements and Terms」。
- 做法: 只要进程还在、日志（Startup.log、Modding.log）在前进就继续等；点一下画面跳过动画。2K 条款我们没有她的同意，点「I Disagree to All」，单人离线照样能玩。进局前还有领袖介绍页，要点「Begin Game」。
- 证据: _agent/logs/2026-10-28/civ6-smoke/09-r1-menu.png、11-r1-after-click.png、12-r1-after-decline.png、15-loading.png
- 可信度: tried once
- status: candidate

### civ6-006
- date: 2026-10-28
- game: civ6
- role: playtester
- 现象: `native close` 发 SIGTERM 后游戏没退，而是弹「Are you sure you wish to quit your game?」；`close` 回答「还开着，没有强制关，告诉她」。
- 做法: 告诉她点「Yes」（或者在游戏菜单里 Exit to Desktop），然后再 `native close` 记成已关。不要强杀：她可能还没存档。
- 证据: _agent/logs/2026-10-28/civ6-smoke/19-close.txt、20-after-sigterm.png、21-user-clicked-yes-close.txt
- 可信度: tried once
- status: candidate

### civ6-007
- date: 2026-10-28
- game: civ6
- role: playtester
- 现象: 冒烟 mod 的 gameplay 脚本 `print(...)` 找不到输出：默认设置下 Logs/ 里没有 Lua.log。
- 原因: AppOptions.txt 的 `EnableTuner 0`（默认）时不写 Lua.log。
- 做法: 本机测试的可见证据用界面上的文字（主菜单按钮、世界追踪面板的标签），日志只看 Modding.log 里的 `Applying Component` / `Loading Text`；不要为了日志去改她的 AppOptions.txt。
- 证据: _agent/logs/2026-10-28/civ6-smoke/18-logs-in-game.txt
- 可信度: tried once
- status: candidate

## 实验室（服务器沙箱）

### civ6-008
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 打开 `EnableTuner 1` 后 Linux 版仍然不写 Lua.log；gameplay 脚本的 `print()` 在哪里都看不到。
- 做法: 实验室里用 `c6-log mods` 看 Modding.log 的 `Applying Component` / `Registering`（证明脚本被加载），效果一律在屏幕上证明（标签、通知、单位、建筑）；`c6-log errors` 里 `table Colors / DiplomacyStatements / LeaderAnimations already exists` 和 CivRoyale 的 `_China.xml` 警告是游戏自己的噪音。
- 证据: _agent/logs/2026-10-28/civ6-lab/09-logs.txt
- 可信度: tried once
- status: candidate

### civ6-009
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 每次启动都会弹 2K 在线条款框；之后进局前还有领袖介绍页要点「Begin Game」；一次启动到主菜单要 2–4 分钟，超过 docker exec 的约 120 秒上限。
- 做法: 用 `c6-game start`（立刻返回）+ 反复 `c6-game wait menu`（每次 ≤100 秒；它自己点「I Disagree to All」），`c6-game play` + `c6-game wait ingame`（自己点 Begin Game，约 1 分钟）。不认识的画面 `c6-ui state` 会说 `other`：先 `c6-shot` 看。
- 证据: _agent/logs/2026-10-28/civ6-lab/05-wait-menu.txt、07-play-ingame.txt、06-menu.png、08-ingame.png
- 可信度: tried once
- status: candidate

### civ6-010
- date: 2026-10-28
- game: civ6
- role: builder
- 现象: 世界追踪面板的标签框会截断长文字（「[M2W-SMOKE] LOADED - CHO…」）。
- 做法: 可见证据的文字短一点（模板用「[LabMod] Research」）；长内容放到描述、提示框或百科里。
- 证据: _agent/logs/2026-10-28/civ6-smoke/17-PROOF-in-game-world-tracker.png、civ6-lab/08-ingame.png
- 可信度: tried once
- status: candidate

## macOS（2026-10-29 实机）

### civ6-011
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: macOS 上 mod 装好了，游戏却没扫到（Modding.log 里只有自带地图和剧本）；`native close` 说游戏已经关了。
- 原因: Mac 版（Aspyr，Steam build 15296837）的文件夹是嵌套的：mod 在 ~/Library/Application Support/Sid Meier's Civilization VI/Sid Meier's Civilization VI/Mods，Logs/ 和 Mods.sqlite 在 …/Firaxis Games/Sid Meier's Civilization VI/；进程名是 Civ6_Exe / Civ6_Exe_Child，不是 Civ6。
- 做法: game.yaml 已改（mac user、logs、extra_files、process_names）；装完看 Modding.log 的 `Loading Mod - …/<mod>.modinfo` 和 `Target Mods`。
- 证据: civ6 game.yaml；Modding.log 2026-10-29
- 可信度: tried once
- status: candidate

### civ6-012
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: macOS 14 打开文明 6：「Civilization VI is damaged and can't be opened」。
- 原因: Civ6.app 的签名登记了所有 DLC 剧本文件，Steam 不下载没买的 DLC，签名不完整；macOS 第一次打开时严格检查就判损坏。手工拷贝 / rsync 的副本还带 provenance 标记，xattr -cr 也删不掉（Operation not permitted）。
- 做法: 按 Aspyr 官方说明：Steam 里点开始 → 损坏提示点「取消」→ 系统设置 › 隐私与安全性 › 「仍要打开」（她自己点）→ 再从 Steam 开。不要手工搬 Steam 游戏：用 Steam 重新下载或「移动安装文件夹」。
- 证据: support.aspyr.com 22917046701453；codesign -vvv 列出缺的 DLC 文件
- 可信度: tried once
- status: candidate

### civ6-013
- date: 2026-10-29
- game: civ6
- role: playtester
- 现象: Mac 上从 Steam 开文明 6 停在 2K LaunchPad；从「仍要打开」直接开则 Steam 报「Game configuration unavailable」；开场动画按 Esc / 点击（发给进程）都跳不过。
- 原因: Steam 先开 LaunchPad，要点 Play；直接开 Civ6.app 时游戏用内部编号 560070 请 Steam 重启它，Steam 不认识；发给进程的按键 / 点击文明 6 不收。
- 做法: 从 Steam 开、在 LaunchPad 点 Play（m2w 目前点不到：要她点或用桌面操控）；动画等它播完（约 2 分钟）；菜单里用真实点击。关游戏时会弹 Are You Sure，要点 Yes。
- 证据: Steam console_log 2026-10-29 12:09
- 可信度: tried once
- status: candidate

### civ6-014
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: MacCiv 的主菜单标记没出现，但对局里规则、文字、脚本都生效了。
- 原因: 主菜单「Single Player」的文字标签是 LOC_SINGLE_PLAYER，不是 LOC_MAIN_MENU_SINGLE_PLAYER；前端文字只在游戏启动时读。Lua.log 默认不写，print 看不到。
- 做法: 改文字前在游戏自带的 Text/en_US/*.xml 里查真正的 Tag；在画面上核对效果（单位名 Mac Warrior、近战 99、金币 10 → 510：Play Now 第 1 回合 PlayerTurnStarted 会触发）。
- 证据: native-test MacCiv 截图 2026-10-29
- 可信度: tried once
- status: candidate

### civ6-015
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: 文明 6 装在外置 USB 硬盘上，第一次打开「验证」了半个多小时，期间别的新程序（Minecraft 启动器、tModLoader 的 .NET）都「没有响应」。
- 原因: macOS 第一次打开新应用要扫一遍；25 GB 在 USB 上只有约 7 MB/s；扫描排队，后面的新程序都等着。
- 做法: 大游戏装本机盘；必须用外置盘就先单独打开一次让它验证完，别同时开别的新程序；卡住就先关正在验证的那个。
- 证据: native-test 2026-10-29（iostat、XprotectService）
- 可信度: tried once
- status: candidate

### civ6-016
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: m2w 用 Steam 链接开文明 6 后停在 2K LaunchPad 窗口，要她手动点 Play；`drive` 不碰它（不是游戏本身的窗口）。
- 原因: 规则写的是「只操作 GameAnything 开的游戏窗口」，没考虑启动器：它是开游戏流程的一部分，但属于另一个程序。
- 做法: 规则（她 2026-10-29 同意）：游戏自带的启动器（2K LaunchPad 这类，点一下 Play 才进游戏）算 `launch` 的一部分，由 m2w 在开游戏时自己点掉，不让她手动点；只点启动器的 Play，不碰启动器里的别的东西（账号、新闻、商店）；Mac 上要真实点击时照「少打扰」规则：她离开电脑，或项目选了「我在用电脑时也可以」。
- 证据: native-test 2026-10-29（她两次手动点 LaunchPad 的 Play；之后 13:20 一次完整启动 51 秒到主菜单，没有人点）
- 可信度: tried once
- status: candidate

### civ6-017
- date: 2026-10-29
- game: civ6
- role: builder
- 现象: 自动开文明 6 时连着出了四个问题：① 一次 Esc（启动后 10 秒）没跳过开场动画；② 拿焦点的点击点在窗口左上角 (40,60)，游戏全屏时正好是屏幕触发角，弹出了调度中心；③ 启动器的 PLAY 被 Claude 的浮动面板盖住，把启动器拉到前面也没用，`covered`；④ 调用 `launch` 的 agent 会话断开时，launch 命令连同还没发的 Esc 一起被杀掉，动画一直播。另外 `close` 后游戏弹「Are you sure you want to exit the game?」，一次点 OK 不总是生效。
- 原因: 开场是好几段视频（Aspyr、2K、Firaxis 标志，然后片头），一次 Esc 只能跳一段或者太早；浮动窗口（layer > 0）永远在普通窗口前面；after_launch 是 launch 命令里的同步步骤。
- 做法: Esc 每 6 秒按一次，共 5 次（主菜单上按 Esc 没有反应，验证过）；拿焦点的点击放在窗口上方正中（主菜单上是标题，没有按钮）；`drive` 在 `native_drive: always` 下拉到前面仍被盖住时，把游戏窗口挪到左上角再看；after_launch 放进独立的后台进程（`native/afterlaunch.py`）；`Game.confirm_quit` 点确认框的 OK，最多 3 次、每次隔 3 秒。截图时不要在同一个工具调用里等待：只截一张就看。
- 证据: native-test 2026-10-29（launch 13:20:08 → 13:20:59 PLAY pressed、Escape sent 5x、主菜单；close 自动点 OK 退出）
- 可信度: tried once
- status: candidate
