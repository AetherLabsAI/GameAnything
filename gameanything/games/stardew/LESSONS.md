# Stardew Valley：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### stardew-001
- date: 2026-10-24
- game: stardew
- role: builder
- 现象: 装进 Mods 的是 `bin/Release/net6.0` 文件夹，游戏照常启动，mod 却没加载，日志也不报错。
- 原因: SMAPI 只认带 `manifest.json`（且 `EntryDll` 指向存在的 DLL）的文件夹，没有就安静跳过。
- 做法: 安装前确认 mod 文件夹里有 `manifest.json`、`EntryDll` 对得上；用 `gameanything native build` / `install`（已会检查），不要手拷 bin 目录。
- 证据: repo 45f6623；docs/cross-platform.md「Fixed on the way (Linux)」
- 可信度: verified repeatedly
- status: confirmed

### stardew-002
- date: 2026-10-25
- game: stardew
- role: builder
- 现象: 自己写 csproj 引用游戏 DLL 容易漏引用、或把 mod 部署进她的游戏文件夹。
- 原因: Pathoschild.Stardew.ModBuildConfig 负责找游戏和 SMAPI 引用；默认还会自己部署和打 zip。
- 做法: `dotnet build` + ModBuildConfig（.NET 6），`-p:GamePath=<游戏文件夹>`，关掉它自己的部署和 zip（gameanything native build 已这样做）；编完游戏文件夹应不变。
- 证据: repo 841be67；docs/cross-platform.md「Found on macOS」 第 3 条；_agent/logs/2026-10-24/native-linux/stardew-dotnet-build.log（ModBuildConfig 4.3.0 自己找到了游戏）
- 可信度: verified repeatedly
- status: confirmed

### stardew-003
- date: 2026-10-16
- game: stardew
- role: builder
- 现象: 唱片机歌单里的中文歌名在录像里是方块。
- 原因: 实验室跑的是英文版，英文字体没有中文字形；中文版游戏才会用中文字体。
- 做法: 菜单、歌名等文字同时给一个英文/拼音名，英文版显示英文、中文版显示中文；录像里检查有没有方块。
- 证据: stardew 回忆项目 jukebox 轮（对话 2026-10-16 10:43）
- 可信度: tried once
- status: confirmed

### stardew-004
- date: 2026-10-15
- game: stardew
- role: builder
- 现象: NPC 的「大笑」听起来像猪叫，合成的掌声听不出是掌声。
- 原因: 构建 agent 用程序合成了音效，自己没听过就交付。
- 做法: 优先用游戏自带音效；要外来音频就用用户给的文件；交付里写明「没人听过」，请用户试听。
- 证据: stardew 回忆项目 m1→m2（对话 2026-10-15 22:20）；m2/REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### stardew-005
- date: 2026-10-16
- game: stardew
- role: builder
- 现象: 循环背景音乐每约 83 秒断一下。
- 原因: wav 文件最后 6.6 秒本身就是静音，循环时出现空档。
- 做法: 用 ffmpeg `silencedetect` 查首尾静音；改音频前先问用户，或循环时从有声处衔接。
- 证据: stardew 回忆项目 improve/REVIEW.md
- 可信度: tried once
- status: confirmed

### stardew-006
- date: 2026-10-16
- game: stardew
- role: builder
- 现象: 桌边的 NPC「悬空坐着」。
- 原因: 换了坐姿的小人精灵，但桌边没有放椅子家具；审阅只看缩略图也漏了。
- 做法: 坐着的人下面一定放椅子（游戏家具或自己做的），并检查前后遮挡；审阅看大图。
- 证据: stardew 回忆项目 improve → improve2（对话 2026-10-16 09:51）
- 可信度: verified repeatedly
- status: confirmed

### stardew-007
- date: 2026-10-17
- game: stardew
- role: builder
- 现象: 回忆片段画面粗糙、比例不对（家具巨大，人物只露头），连续两轮被打回。
- 原因: 构建 agent 把回忆做成单独画框、按屏幕大小平涂背景，没用游戏的瓦片比例。
- 做法: 做成真正的游戏小房间（游戏的地块和家具，人物按游戏比例），第三轮这样做就通过了。
- 证据: stardew 回忆项目 improve / improve2 / improve3 REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### stardew-008
- date: 2026-10-16
- game: stardew
- role: builder
- 现象: 开局是默认男农夫，之后才变成用户本人，用户觉得变来变去很奇怪。
- 原因: 新存档用了默认角色外观，事件里才换装。
- 做法: 新存档一开始就设好主角的性别、发型、衣服。
- 证据: stardew 回忆项目 improve → improve2（对话 2026-10-16 16:20）
- 可信度: tried once
- status: confirmed

### stardew-009
- date: 2026-10-17
- game: stardew
- role: builder
- 现象: 第二天早上，衣柜里另一件 mod 衣服被删掉了（会改存档）。
- 原因: 每天自动换装的代码先调用「删除全部 mod 衣服」再新做一套。
- 做法: 删除/替换物品按具体 id 做，不要整类清空；会改存档的逻辑单独列出来给用户看。
- 证据: stardew 回忆项目 improve4/REVIEW.md 问题 1
- 可信度: tried once
- status: candidate

### stardew-010
- date: 2026-10-17
- game: stardew
- role: builder
- 现象: 构建 agent 自作主张挪走农场上的建筑、清门前杂草、直接加满好感。
- 原因: 简报没写「不准动存档里已有的东西」。
- 做法: 简报写明：改动存档里已有物件/数值的行为一律列在 DEVIATIONS 里，默认不做；调试命令放在默认关闭的开关后面。
- 证据: stardew 回忆项目 m3/REVIEW.md；improve4/REVIEW.md（调试命令后门）
- 可信度: verified repeatedly
- status: confirmed

### stardew-011
- date: 2026-10-17
- game: stardew
- role: builder
- 现象: 来访 NPC 10:00 凭空出现、17:00 一下子消失；配偶 NPC 13:00 被原版日程叫回家。
- 原因: 直接 warp NPC；原版日程会在固定时间覆盖 mod 的安排。
- 做法: NPC 从地图入口走进走出；要改原版日程时打补丁并在录像里验证。
- 证据: stardew 回忆项目 m3/REVIEW.md，improve4/REVIEW.md
- 可信度: tried once
- status: candidate

### stardew-012
- date: 2026-10-16
- game: stardew
- role: builder
- 现象: 事件用的临时角色若留在存档里，卸载 mod 后会出错。
- 原因: 临时 NPC 加进了地点但没在存档前移除。
- 做法: 存档前移除临时 NPC，并在状态里报 `stray_npcs`（每次回放结束检查为 0）；提供卸载前清理命令。
- 证据: stardew 回忆项目 m2 / improve3 REVIEW.md（`stray_npcs 0`）
- 可信度: verified repeatedly
- status: confirmed

## 试玩

### stardew-013
- date: 2026-10-16
- game: stardew
- role: playtester
- 现象: 「走过去和人说话」的回放步骤什么也没发生，后面的 choose 报 `no question is open`。
- 原因: harness 的 `interact` 不会触发 mod 监听的行动键；而且站位不对时面前没人。
- 做法: 回放里用按 `x`（行动键）代替 `interact`；按之前确认面前一格就是那个人，等对方台词播完、问题框出现再选。
- 证据: stardew 回忆项目 improve2 / improve3 REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### stardew-014
- date: 2026-10-16
- game: stardew
- role: playtester
- 现象: 构建 agent 的主线回放连续两轮在独立重放里走不完。
- 原因: trace 里的固定等待太短，对话还没关就去走路/选择。
- 做法: 用「等到 state 里某个值出现再走」，或至少放宽等待；交付前每条 trace 独立重放到底。
- 证据: stardew 回忆项目 improve / improve2 / improve3 REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### stardew-015
- date: 2026-10-16
- game: stardew
- role: playtester
- 现象: 歌单菜单一弹出就被回放程序选掉，用户以为没有「自己选歌」；回忆被快进看不清。
- 原因: 回放按最快速度操作。
- 做法: 菜单、关键画面、台词在录像里至少停 3–5 秒；截图前把鼠标指针挪开。
- 证据: stardew 回忆项目 jukebox（对话 2026-10-16 10:48）；improve3 REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### stardew-016
- date: 2026-10-24
- game: stardew
- role: playtester
- 现象: 游戏窗口不在前台时画面不动、测试停住。
- 原因: 游戏设置 `pauseWhenOutOfFocus` 默认开。
- 做法: 测试时临时关掉，结束后还原（gameanything native 会备份并还原）；窗口模式请她在「选项 > 窗口模式」里选一次。
- 证据: docs/cross-platform.md「Found on macOS」（`pauseWhenOutOfFocus` 已还原）；docs/cross-platform.md 第 6 节
- 可信度: verified repeatedly
- status: confirmed

### stardew-017
- date: 2026-10-25
- game: stardew
- role: playtester
- 现象: Mac 上发给进程的点击（`CGEventPostToPid`）点不动按钮；SIGTERM 关游戏会弹「quit unexpectedly」。
- 原因: 游戏只认 HID 层的鼠标事件；SIGTERM 被系统当成崩溃。
- 做法: 用 `hid` 点击（只在游戏在最前、用户离开电脑时）；关闭先请游戏自己退出，20 秒后才 SIGTERM。
- 证据: repo 841be67；docs/cross-platform.md「Found on macOS」 第 2、5 条
- 可信度: tried once
- status: candidate
