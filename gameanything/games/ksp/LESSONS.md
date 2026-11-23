# Kerbal Space Program：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。

## 开发

### ksp-001
- date: 2026-10-25
- game: ksp
- role: builder
- 现象: 游戏开着时换掉 GameData 里的插件 DLL，不生效。
- 原因: KSP 1 只在启动时加载 GameData 里的插件，没有官方重载。
- 做法: 改了插件就关游戏、install、重开（到主菜单约一两分钟）；把一轮改动攒在一起开一次测完。
- 证据: ksp-native-linux 测试 08b-reload；ksp-game 分支 ed6f881
- 可信度: tried once
- status: candidate

## 试玩

### ksp-002
- date: 2026-10-25
- game: ksp
- role: playtester
- 现象: 测试 mod 时容易直接进到用户已有的存档。
- 原因: KSP 的存档按档案（saves/<名字>）分，默认停在上次用的那个。
- 做法: Start Game > New Game 新建一个测试专用档案再测；开游戏可能先出 Steam 启动器，要按它的 Play；窗口模式在 设置 > 图形 里关全屏。
- 证据: ksp-native-linux 测试 05-launch-2
- 可信度: tried once
- status: candidate

## 实验室（服务器沙箱）

### ksp-003
- date: 2026-10-28
- game: ksp
- role: builder
- 现象: 实验室里游戏一直停在加载画面，Player.log 里成百上千条 UnauthorizedAccessException（GameData/Squad/...model.mu）。
- 原因: KSP 用读写方式打开 GameData 里的资源文件；只读的硬链接打不开。
- 做法: 每个运行目录自己拷一份 GameData（约 1.1 GB），其余程序文件才用只读硬链接（kslab_rt.py 已经这样做）；卡在 LOADING 先 `ks log --grep Exception`。
- 证据: _agent/logs/2026-10-28/ksp-lab（第一次 start）
- 可信度: tried once
- status: candidate

### ksp-004
- date: 2026-10-28
- game: ksp
- role: builder
- 现象: 截图上盖着「Breaking Ground」资料片广告弹窗，主菜单和飞行里都有。
- 原因: settings.cfg 里 MISSION_SHOW_EXPANSION_INFO / SERENITY_SHOW_EXPANSION_INFO 默认 True。
- 做法: 实验室启动前把这两项设成 False（`ks start` 自动做）；还有弹窗就 `ks cmd dismiss` 再截图。
- 证据: ksp-lab 01-main-menu（修之前 / 之后）
- 可信度: tried once
- status: candidate

### ksp-005
- date: 2026-10-28
- game: ksp
- role: playtester
- 现象: 场景截图一片黑，飞船看不清。
- 原因: 现成场景（Mun Orbit）的飞船在背光 / 夜面；镜头默认对着太阳反方向。
- 做法: `ks cmd camera <朝向> <俯仰> <距离>` 转到向阳的一边（朝向加 180 度试试），或用 Space Station 1（近地轨道、有阳光）；干净画面先 `ks cmd ui hide`；录像用 `ks clip <秒> <名字> --orbit <度>` 让镜头慢慢转。
- 证据: ksp-lab 02-flight-mun-orbit、03-flight-station、05-station-orbit.mp4
- 可信度: tried once
- status: candidate

### ksp-006
- date: 2026-10-28
- game: ksp
- role: builder
- 现象: 录像录完了工具还一直等，「进程还活着」。
- 原因: 沙箱里从 docker exec 脱离出去的进程结束后没人回收，变成僵尸进程，`kill -0` 仍然算它活着。
- 做法: 判断进程活着要看状态不是 Z（kslab_rt.py 的 alive()）；不要自己用 kill -0 等。
- 证据: ksp-lab clip-1.log（第一次 clip 等满 115 秒）
- 可信度: tried once
- status: candidate

## macOS（2026-10-29 实机）

### ksp-007
- date: 2026-10-29
- game: ksp
- role: builder
- 现象: macOS 上 `native launch`（steam://rungameid/220200）后 KSP 进程起来但 0% CPU、没有窗口、没有日志。
- 原因: Steam 在 Mac 上的启动流程卡住（多启动项的游戏会弹一个 agent 看不到的选择框；第一次从外置盘启动还有 macOS 验证）。
- 做法: macOS 直接 `open -g KSP.app`（KSP 1 不需要 Steam）：adapter.launch_url 已改。
- 证据: docs/cross-platform.md macOS 9；48f3855
- 可信度: tried once
- status: candidate

### ksp-008
- date: 2026-10-29
- game: ksp
- role: builder
- 现象: macOS 上 `native log --game ksp` 打出了别的游戏（城市：天际线）的日志。
- 原因: 候选里有 ~/Library/Logs/Unity/Player.log：所有 Unity 游戏共用，log() 取最新改动的那个。KSP 自己的在 ~/Library/Logs/Squad/KSP/Player.log（产品名 KSP）和游戏目录的 KSP.log。
- 做法: game.yaml 只留 KSP.log 和 Squad/KSP/Player.log（已改）；看日志前先确认路径属于这个游戏。
- 证据: docs/cross-platform.md macOS 10；48f3855
- 可信度: tried once
- status: candidate

### ksp-009
- date: 2026-10-29
- game: ksp
- role: playtester
- 现象: macOS 上 `drive` 发 F8：4 次只到 1 次；第一下按键常丢。
- 原因: 按住只有 20 ms，KSP（Rosetta、窗口不在前面时帧率低）每帧轮询键盘，按下落在两帧之间；刚拉到前台的 Unity 游戏丢第一下。
- 做法: 按住 MAC_KEY_HOLD 80 ms，拉到前台后等 1 s（已改）：5/5。测按键时让 mod 写日志计数，用日志核对收到几次。
- 证据: docs/cross-platform.md macOS 11；48f3855
- 可信度: tried once
- status: candidate
