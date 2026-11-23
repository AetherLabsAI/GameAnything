# No Man's Sky：经验（lessons）

## 开发

### nms-001
- date: 2026-10-26
- game: nms
- role: builder
- scope: 版本与 mod 布局
- 现象: 原始接入提交把实现写死为“5.58+”，但接手时服务器安装的已经是 build 25732212、游戏 7.06。
- 原因: NMS 更新频繁，旧版本号很快失效；仅靠旧说明不能证明当前 loader 仍兼容。
- 做法: 先检查真实安装。7.06 的 `NMS.exe` 同时包含 `GAMEDATA/MODS`、`PCBANKS/MODS`、`.EXML`、`.MBIN`、`_id`、`_index` 与 `GCMODSETTINGS.MXML` 字符串；这支持松散文件 loader 仍存在，但最终仍须用可见 smoke 做实机验证。
- 证据: wc-cities appmanifest_275850.acf（buildid 25732212）；2026-10-26 对真实 `Binaries/NMS.exe` 的只读字符串检查；Hello Games 官方 7.06 release log。
- 可信度: tried once
- status: candidate

### nms-002
- date: 2026-10-26
- game: nms
- role: builder
- scope: 两种 mod 路径
- 现象: 当前二进制同时引用 `GAMEDATA/MODS` 和 `PCBANKS/MODS`。
- 原因: 松散 EXML/MBIN loader 与传统 `.pak` bank loader 是不同安装布局。
- 做法: 第一版适配只接 `GAMEDATA/MODS/<ModName>/` 松散文件；拒绝 `.pak` 是为了避免把它装进错误目录，并不宣称当前游戏不再支持 `.pak`。未来若接 `.pak`，应作为明确的第二种 package/install 模式写入 `PCBANKS/MODS`。
- 证据: 7.06 `NMS.exe` 路径字符串；适配器 `check_installable` 与 `game.yaml`。
- 可信度: tried once
- status: candidate

## 试玩

尚未完成 7.06 实机 smoke（见 nms-003）；验证后在这里记录可见证据、离线设置、启动时间和恢复结果。

### nms-003
- date: 2026-10-29
- game: nms
- role: builder
- scope: Linux 首次启动 / 内存
- 现象: wc-cities（12 GB、64 核）里第一次从 Steam 开 7.06：选启动项（「Play No Man's Sky」/ VR 两项，要点 Play）→ Proton 安装脚本（约 1.5 分钟）→「处理 Vulkan 着色器」时 Steam 用 fossilize_replay 回放 NMS 的预编译缓存（shadercache/275850 约 7.7 GB、569 439 条管线），开始后十几秒沙箱内存从 8.2 GB 跳到 11 GB，整个 pod 变成 Failed。NMS.exe 根本没启动。10-26 那次被记成「机器重启」的失败，日志里也停在同一步（ProcessingShaderCache）。
- 原因: 着色器预缓存的回放按核数开工作进程，又要读 7.7 GB 的缓存文件；小内存、多核的机器（尤其是有内存上限的容器）撑不住。和 mod 无关。
- 做法: 在内存 ≤16 GB 的机器上，先在 Steam > 设置 > 下载 里关掉「着色器预缓存」（或限制后台处理 Vulkan 着色器），或者弹出处理着色器的窗口时马上点「跳过」，再开游戏。沙箱里重试前先确认关掉了，否则会再次把 wc-cities 弄成 Failed。安装、备份、还原这几步没问题：游戏没跑起来，存档和 SETTINGS 前后逐字节一致。
- 证据: GameAnything 实验日志 `_agent/logs/2026-10-29/nms-smoke/`（11-steam-logs-and-memory.txt：console_log / shader_log / 每 20 秒的内存记录）；10-26 和 10-29 两次都停在同一步。
- 可信度: verified repeatedly
- status: candidate
