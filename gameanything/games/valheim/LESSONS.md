# Valheim：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### valheim-001
- date: 2026-10-25
- game: valheim
- role: builder
- 现象: Mac 上用 Steam 启动选项 `".../start_game_bepinex.sh" %command%` 开游戏，进程起来了但 BepInEx 没出现（没有 LogOutput.log）；`arch -x86_64 ... %command%` 则 Steam 报 `Failed to spawn process`。
- 原因: doorstop 只有 x86_64 dylib，游戏是 universal，要在 Rosetta 下起；Steam 的启动包装疑似改写了注入用的环境变量（没查完）。不是 hardened runtime（游戏带 allow-dyld-environment-variables）。
- 做法: 脚本里 `executable_name="valheim.app"`，开头加「arm64 时 `arch -x86_64` 重新执行自己」，由 gameanything 在游戏文件夹里直接运行（Steam 客户端开着即可）；Linux / Windows 仍走 Steam 启动选项。
- 证据: repo 0845c3f、175c4f2、a89408e；docs/cross-platform.md「Found on macOS」（Valheim 行、更新）
- 可信度: verified repeatedly
- status: confirmed

### valheim-002
- date: 2026-10-25
- game: valheim
- role: builder
- 现象: ScriptEngine 热重载时报 `SymbolsNotFoundException`，什么都没加载。
- 原因: ScriptEngine 读 DLL 一定要符号文件；另外插件必须是 .NET Framework 4.x / netstandard，不能是 .NET 5+。
- 做法: 目标 `net462`，`native build` 产出 DLL + `.pdb` 一起装；同一插件不要同时留在 `plugins/` 和 `scripts/`；`OnDestroy` 里 `harmony.UnpatchSelf()`。
- 证据: repo 981cfeb；docs/cross-platform.md 第 5 节；_agent/logs/2026-10-25/valheim-native-linux/14-reload-v2.txt
- 可信度: verified repeatedly
- status: confirmed

### valheim-003
- date: 2026-10-24
- game: valheim
- role: builder
- 现象: 加的物品进世界后不见了。
- 原因: 每次进世界游戏都会重建 `ZNetScene` / `ObjectDB`。
- 做法: 在这两个 `Awake` 的 Postfix 补丁里注册（实验室 `mod/Lib/PrefabKit.cs` 有示例）。
- 证据: modlab/valheim/rt/CLAUDE.md「Writing the mod」
- 可信度: tried once
- status: candidate

### valheim-004
- date: 2026-10-24
- game: valheim
- role: builder
- 现象: `vh-build examples/hello` 报 CS0012 FontStyle。
- 原因: HelloMod.csproj 少引用 `UnityEngine.TextRenderingModule`（实验室的 bug，未修）。
- 做法: 从 `mod/` 模板开始；需要别的游戏模块就在 csproj 里加带 HintPath 的 `<Reference>`。
- 证据: _agent/logs/2026-10-24/wc-cities-tests/README.txt（vh-5-build.txt）
- 可信度: tried once
- status: confirmed

## 试玩

### valheim-005
- date: 2026-10-25
- game: valheim
- role: playtester
- 现象: 新建的测试角色和世界都成了 Steam Cloud 存档。
- 原因: Valheim 在 Steam 上默认用云存档；gameanything 只备份本地 `worlds_local/` + `characters_local/`。
- 做法: 测试前用「Manage saves > Move to local」把测试角色/世界挪到本地；绝不选中或改动她自己的云存档角色。
  Valheim 1.0 新建角色/世界时没有「Cloud save」勾选框（2026-10-31），建好立刻挪；挪完角色后它的 `_backup_auto` 备份还在云端：展开那一行，选中备份，Remove。
- 证据: repo 51329ea；docs/cross-platform.md（Linux Valheim 行）；valheim-native-linux/README.txt
- 可信度: tried once
- status: confirmed

### valheim-006
- date: 2026-10-25
- game: valheim
- role: playtester
- 现象: Valheim 有联机，误开服务器或加入别人会影响别人。
- 原因: 游戏菜单默认可开服务器。
- 做法: 每次测试用测试专用的本地世界，「Start server」关掉，不加入任何服务器。
- 证据: docs/cross-platform.md（Valheim has online play）；valheim-native-linux/README.txt
- 可信度: verified repeatedly
- status: confirmed

### valheim-007
- date: 2026-10-24
- game: valheim
- role: playtester
- 现象: 游戏到了菜单、插件也加载了，桥接却不回应，日志也没有新内容，等多久都没用。
- 原因: 启动挂起（原因未知），约每三次一次。
- 做法: 每次重启后先 `timeout 12 vh ping`，超时就 `vh-game restart`；`vh-game start` 检测到 25 s 静默会自己重启。
- 证据: modlab/valheim/rt/CLAUDE.md「Boot hang」
- 可信度: verified repeatedly
- status: confirmed

### valheim-008
- date: 2026-10-24
- game: valheim
- role: playtester
- 现象: 在同一沙盒里动 Steam 会把另一个实验室的游戏踢掉。
- 原因: wc-cities 沙盒里 Valheim 和 Overcooked 2 共用一个登录的 Steam。
- 做法: 不自己启停 Steam；只用 `vh-game` 起停自己的游戏（确切 PID），不碰 oc2lab。
- 证据: modlab/valheim/rt/CLAUDE.md「Rules」
- 可信度: verified repeatedly
- status: confirmed

### valheim-009
- date: 2026-10-31
- game: valheim
- role: builder
- 现象: 游戏装在外置 USB 盘上，第一次 `native launch` 后 start_game_bepinex.sh 和游戏进程过一会儿都没了，没有日志也没有崩溃报告；第二次启动等了约 5 分钟后正常进到菜单，屏幕上有「M2W smoke: plugin loaded」。
- 原因: 脚本最后 `exec` 游戏程序；macOS 第一次验证 USB 盘上的程序时，这样直接起的进程会悄悄结束（打开 app 时那种验证窗口也会出现）。
- 做法: 第一次启动时告诉她要等，截图盯着；进程没了、BepInEx/LogOutput.log 也没有，就再 `native launch` 一次。新装的 Valheim 要先装 BepInExPack_Valheim（Thunderstore，denikson，5.4.2351），把包里 BepInExPack_Valheim/ 的内容解到游戏文件夹。
- 证据: fresh_mac_user 2026-10-31：00:18 第二次启动，00:23 进程开始跑，LogOutput.log [M2W-smoke] loaded
- 可信度: tried once
- status: candidate
