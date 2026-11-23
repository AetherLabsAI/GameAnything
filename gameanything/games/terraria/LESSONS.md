# Terraria (tModLoader)：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。

2026-10-28 第一次真机往返（Linux，真 Steam 的 tModLoader v2026.8.3.0）留下的。

## 开发

### terraria-001
- date: 2026-10-28
- game: terraria
- role: builder
- 现象: `native check` 对刚构建的 mod 报「用 tModLoader 2026.8.3.0 打包的，她装的是 1.4.4.9」，其实是同一个 tModLoader。
- 原因: tModLoader.dll 的 AssemblyVersion 是泰拉瑞亚的版本（1.4.4.9）；tModLoader 自己的版本在 AssemblyInformationalVersion 里（`1.4.4.9+2026.08.3.0|2026.08|stable|...`），.tmod 头里记的是后者。
- 做法: 用 informational version 里 `+` 后面那段比较（adapter.tml_version）。
- 证据: _agent/logs/2026-10-28/terraria-smoke/run-p1.log、check-after-fix.txt
- 可信度: tried once
- status: candidate

### terraria-002
- date: 2026-10-28
- game: terraria
- role: builder
- 现象: 新装的 tModLoader 第一次启动要先选语言、点欢迎框，而且没有角色和世界；第一次启动还会在安装文件夹里下载自带的 .NET 运行时（dotnet/，约 30 MB）。
- 原因: 全新安装。
- 做法: 先不带 mod 开一次，建一个本地小角色和小世界（Small，Classic），退出后再 backup → install；之后进世界时 `[M2W-smoke] entered world` 和黄色聊天行就是可见证据（聊天行几秒后淡出，进世界后马上截图）。
- 证据: _agent/logs/2026-10-28/terraria-smoke/04-first-launch.png … 14-worldlist.png、32-proof-chat-line.png
- 可信度: tried once
- status: candidate

## 试玩

### terraria-003
- date: 2026-10-28
- game: terraria
- role: builder
- 现象: 测试角色进世界后没人操作，晚上被僵尸一直打死；窗口没有焦点时游戏照样全速跑（冒烟 mod 设了 InactiveSleepTime = 0）。
- 原因: 冒烟测试只需要进世界那一下。
- 做法: 截到聊天行后就 `native close`；测试世界用 Classic/Small，别留着跑；关游戏前的自动存档会改存档，restore 会还原成备份那一刻（逐字节一致）。
- 证据: _agent/logs/2026-10-28/terraria-smoke/23-in-world.png、40-close-restore-uninstall.txt
- 可信度: tried once
- status: candidate

### terraria-004
- date: 2026-10-28
- game: terraria
- role: builder
- 现象: 实验室用新的存档文件夹（`-tmlsavedirectory`）第一次启动时停在「选择语言」和欢迎框，`-skipselect` 进不了世界，`tr-game start` 等到超时。
- 原因: 新存档文件夹没有 config.json，游戏当作第一次运行。
- 做法: `tr-game start` 先在 `save/config.json` 补上 Language、LastLaunchedVersion、LastLaunchedTModLoaderVersion（和 1280x720 窗口）再启动；之后直接进世界，约 30 秒。
- 证据: gamebench hosting/modlab/terraria/rt/bin/tr-game；_agent/logs/2026-10-28/terraria-lab/03-state.png、04-restart.txt
- 可信度: tried once
- status: candidate

### terraria-005
- date: 2026-10-28
- game: terraria
- role: builder
- 现象: 聊天行（`Main.NewText`）几秒就淡出，截图常常拍不到。
- 原因: 泰拉瑞亚的聊天行本来就会消失。
- 做法: 要可见证据就在 `ModSystem.ModifyInterfaceLayers` 里加一个 `LegacyGameInterfaceLayer`，每帧 `Utils.DrawBorderString` 画横幅（实验室模板 LabMod 有）；聊天行只当辅助。
- 证据: _agent/logs/2026-10-28/terraria-lab/05-in-world.png、06-recording.mp4
- 可信度: tried once
- status: candidate

## macOS（2026-10-29 实机）

### terraria-006
- date: 2026-10-29
- game: terraria
- role: builder
- 现象: macOS 第一次启动 tModLoader：十几分钟没有进程，之后 `shot` 说「游戏已经关了」。
- 原因: 第一次启动先等 macOS 验证、再下载 tModLoader 自带的 .NET（几分钟）；进程比 launch 晚 13 分钟出现，超过了按「现在」算的 15 分钟收养窗口。
- 做法: quiet._adopt 改成按进程自己的启动时间判断（已改）。第一次启动要多等，看 tModLoader-Logs/Launch.log 的 dotnet-install。
- 证据: docs/cross-platform.md macOS 12；48f3855
- 可信度: tried once
- status: candidate

### terraria-007
- date: 2026-10-29
- game: terraria
- role: playtester
- 现象: macOS 上 `drive` 点 tModLoader 的按钮（第一次启动的语言选择、欢迎框、建角色、建世界）没反应。
- 原因: FNA/SDL 不收发给进程的点击；真实点击每步 50 ms 太快（游戏每帧轮询鼠标）；游戏不是前台 app 时第一下只激活窗口。
- 做法: mac_click: hid（真实光标，只在她离开 60 秒后）；MAC_HID_STEP 120 ms；点之前先把游戏拉到前台（都已改）。每点一下都会重置空闲计时，下一下要再等 60 秒。
- 证据: docs/cross-platform.md macOS 14；48f3855
- 可信度: tried once
- status: candidate

### terraria-008
- date: 2026-10-29
- game: terraria
- role: playtester
- 现象: macOS 上在世界里按 Esc、数字键没反应，打字（角色名）却能进。
- 原因: 发给进程的按键 FNA 不收（文字输入事件能到）；真实按键也要窗口先有键盘焦点：拉到前台、点标题栏都不够。
- 做法: mac_keys: hid（已改）；按键前先在游戏画面里真实点一下（step 里先 click 再 key）。
- 证据: docs/cross-platform.md macOS 15；48f3855
- 可信度: tried once
- status: candidate

### terraria-009
- date: 2026-10-29
- game: terraria
- role: playtester
- 现象: 测完 restore 后测试角色还在；测试世界不在本地 Worlds/ 里。
- 原因: restore 只放回备份里的文件，不删备份之后新建的存档；tModLoader 新建世界默认存 Steam 云，backup 只备本地。
- 做法: 测试前在角色 / 世界列表里关掉云图标；测完把测试角色、世界挪进 .trash。
- 证据: native-test 项目 MacTerra 测试
- 可信度: tried once
- status: candidate
