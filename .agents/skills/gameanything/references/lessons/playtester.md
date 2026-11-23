# playtester：经验（和游戏无关）

格式和规则见 skills/gameanything/references/lessons.md。只写对每个游戏都成立的做法；某个游戏的写进它游戏包里的 LESSONS.md。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

### playtester-001
- date: 2026-10-16
- game: any
- role: playtester
- 现象: 构建 agent 写的回放在独立重放里连续两轮没走完，它的报告却说通过。
- 原因: 回放里的等待写得太紧，构建 agent 没有每条都重放到底。
- 做法: 用真实输入独立重放每一条 trace，看最后的截图和 state；走不完先查 trace 本身（等待、按键、站位）再判功能。不信 builder 的结论。
- 证据: pitfalls.md；stardew 回忆项目 improve / improve2 REVIEW.md
- 可信度: verified repeatedly
- status: confirmed

### playtester-002
- date: 2026-10-16
- game: any
- role: playtester
- 现象: 修了一处文字后，录像前半段还是旧版的样子。
- 原因: 只重录了一部分，旧素材没全换。
- 做法: 改了东西后，相关截图和录像整段重做；发卡前逐段核对是不是当前版本。
- 证据: pitfalls.md（唱片机歌名）；stardew 回忆项目 jukebox 轮
- 可信度: verified repeatedly
- status: confirmed

### playtester-003
- date: 2026-10-21
- game: any
- role: playtester
- 现象: 交付只发了对比图，试玩页没有录像；补录的那次又是静音的。
- 原因: 交付清单里没有强制录像和声音检查。
- 做法: 每次交付都有试玩录像；录完用 `ffmpeg -af volumedetect` 查音量；本来就没声音的（如 Cities 的 cine、没有声卡的服务器）在结果里写明。
- 证据: pitfalls.md 2026-10-21；adaptation m1
- 可信度: verified repeatedly
- status: confirmed

### playtester-004
- date: 2026-10-22
- game: any
- role: playtester
- 现象: 瞬移到落脚点再原地横扫的录像里，镜头贴墙、钻进树叶、字幕串台。
- 原因: 没事先挑视角，也没用游戏自己的平滑镜头。
- 做法: 先挑好每章的取景点，用游戏内平滑运镜，字幕按时间出现；画面干净（无调试界面、鼠标挪开）；每章抽帧检查。
- 证据: pitfalls.md 2026-10-22；adaptation m2 → m3
- 可信度: verified repeatedly
- status: confirmed

### playtester-005
- date: 2026-10-16
- game: any
- role: playtester
- 现象: 人悬空坐着、画面比例不对，审阅都没发现，用户一眼看出。
- 原因: 审阅只看了缩略图。
- 做法: 关键画面用原尺寸截图检查比例、遮挡、有没有缺的物件。
- 证据: stardew 回忆项目 improve（对话 2026-10-16 09:51、10:01）
- 可信度: verified repeatedly
- status: confirmed

### playtester-006
- date: 2026-10-23
- game: any
- role: playtester
- 现象: 打算拿真实项目做新实验室 / 新游戏的验收，开销很大，被叫停。
- 原因: 真实项目复杂、慢、要花钱。
- 做法: 新接入的验收用便宜的小测试（一条路、一个模型、一张截图、一小段录像）；用测试专用的 home 和存档。
- 证据: docs/cross-platform.md 各游戏实测行
- 可信度: verified repeatedly
- status: confirmed

### playtester-007
- date: 2026-10-25
- game: any
- role: playtester
- 现象: 卸载 / 还原后，设置文件和测试前的备份不完全一样。
- 原因: 卸载逻辑写了新值，而不是恢复原状。
- 做法: 每次 backup → install → 玩 → restore → uninstall 后，对比存档、设置和游戏文件夹（哈希、大小、mtime），要逐字节相同；游戏开着时 restore / uninstall / install 应被拒绝。
- 证据: docs/cross-platform.md（各游戏 byte-identical）；repo 981cfeb
- 可信度: verified repeatedly
- status: confirmed

### playtester-008
- date: 2026-10-25
- game: any
- role: playtester
- 现象: drive 显示按键 / 点击已发，游戏没反应（Linux 上 XSendEvent、Mac 上发给进程的事件、读原始输入的游戏）。
- 原因: 有的游戏只认真实的 HID 输入，或按每帧光标位置判断悬停。
- 做法: 每次操作后截图确认；不认就改用 mod 里的命令；Mac 上用真实光标，点击前确认游戏窗口在最前、没被盖住。
- 证据: docs/cross-platform.md（drive 老实话）；repo 841be67；wc-cities-tests cs-10、cs-11
- 可信度: verified repeatedly
- status: confirmed

### playtester-009
- date: 2026-10-25
- game: any
- role: playtester
- 现象: Mac 上往 Steam 启动选项框里模拟打字，空格、`!`、`_` 丢了，引号变成弯引号。
- 原因: 模拟键入经过输入法 / 自动替换。
- 做法: 用剪贴板粘贴（`gameanything native doctor --game <游戏> --copy`）；填完截图核对。
- 证据: repo 841be67；docs/cross-platform.md「Found on macOS」
- 可信度: tried once
- status: confirmed

### playtester-010
- date: 2026-10-24
- game: any
- role: playtester
- 现象: 她按时间点留言问画面里的东西，画面里有两个可能的对象；成片又剪过、加速过，时间对不上原始录像。
- 原因: 留言只有时间点，没有圈出位置。
- 做法: 用剪辑区间把成片时间换回原始录像时间，对照日志；先列出看到的候选、各是什么，再请她确认或圈出；回复时每个候选都解释，区分「是 bug」和「游戏本来的样子」。
- 证据: feature m3 QA_0052_0406.md；feature 对话 2026-10-24 19:05-19:20
- 可信度: tried once
- status: confirmed

### playtester-011
- date: 2026-10-25
- game: any
- role: playtester
- 现象: 对她指出的问题先凭画面猜了一个原因，猜错了。
- 原因: 没对照这一版的改动和日志。
- 做法: 看她指的那一帧，同时查这一版改过的代码和日志；没查实就明说是推断，查实后再给结论和修法。
- 证据: sims4-flying-car round4 ITERATIONS.md 第 2 轮
- 可信度: tried once
- status: candidate

### playtester-012
- date: 2026-10-23
- game: any
- role: playtester
- 现象: 评审说「没有改」的其实改了；评审又漏掉了悬空的人、大块纯色、拿反的道具，都是她在录像里看到的。
- 原因: 评审只看少量截图，看不出物理问题和录像里的细节。
- 做法: 交付前自己看一遍录像里每段的主画面；物理问题（脚下有没有地、悬空、穿模）用自动检查，不靠评审肉眼。
- 证据: adaptation m4、m5 的批注；mc-runs hp-m1 MODLOG v2 round 2
- 可信度: verified repeatedly
- status: confirmed
