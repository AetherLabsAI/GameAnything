# Cities: Skylines：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### cities_skylines-001
- date: 2026-10-25
- game: cities_skylines
- role: builder
- 现象: 游戏开着时替换已装 mod 的 DLL（城市里、主菜单里，改名替换或原地写），一分钟内都没有重新加载。
- 原因: Linux 版没有触发重载（inotify 正常，不是文件系统的问题）；Windows / macOS 没验证。
- 做法: 改了 C# 就关游戏、install、重开（3–5 分钟），把改动攒在一起一次测；只改数据文件时用 `cmd` 同步，不用重开。
- 证据: repo 981cfeb；_agent/logs/2026-10-24/wc-cities-tests/cs-9、cs-12*、cs-13
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-002
- date: 2026-10-25
- game: cities_skylines
- role: builder
- 现象: restore + uninstall 后，她的 `userGameState.cgs` 和备份不再一样（多了 `...enabled = False`）。
- 原因: uninstall 把 mod 开关写成 false，而不是删掉这个键；没有键的 mod 本来就是关的。
- 做法: 关 mod = 删除键；卸载后对比设置文件和备份应逐字节相同。
- 证据: repo 981cfeb；wc-cities-tests/cs-16-restore-uninstall.txt
- 可信度: tried once
- status: confirmed

### cities_skylines-003
- date: 2026-10-24
- game: cities_skylines
- role: builder
- 现象: 新装的 mod 不生效。
- 原因: 开关存在 `userGameState.cgs`，键名按游戏写的 mod 文件夹路径算；游戏开着时它会用内存里的设置覆盖。
- 做法: 游戏关着时先 `install` 一次（写开关），再开游戏；菜单里看到「N/M mods enabled」再继续。
- 证据: wc-cities-tests/cs-3、cs-5c、cs-14；docs/cross-platform.md 第 5 节
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-004
- date: 2026-10-23
- game: cities_skylines
- role: builder
- 现象: 每次开游戏 mod 开关和法律声明的同意都丢了。
- 原因: 游戏先写 `/tmp/.../*.cgs.tmp` 再移动到 home（JuiceFS，另一个文件系统），移动失败（`UnauthorizedAccessException`）。
- 做法: 给游戏设 TMPDIR 到 home 同一文件系统（`--same-fs-tmp`）；在那之前 `cs install` 每次开游戏前重写开关。
- 证据: modlab/cities/m2w/CLAUDE.md §6 第 1 条；wc-cities-tests README（TMPDIR in the home）
- 可信度: tried once
- status: candidate

### cities_skylines-005
- date: 2026-10-24
- game: cities_skylines
- role: builder
- 现象: 新 home 首次开游戏弹出 Legal Disclaimer（隐私政策、使用条款），不点就进不了城市；预写 `legal.*` 键也挡不住。
- 原因: 这是用户和 Paradox 之间的协议，agent 无权替她同意。
- 做法: 没有她书面同意绝不点、不绕过；挡住了就停下报告。她同意过的只限这份 Cities 文件，新的法律文本要再问。
- 证据: wc-cities-tests/cs-2c-disclaimer.txt；docs/cross-platform.md（Linux Cities 行）；modlab/cities/m2w/CLAUDE.md §1
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-006
- date: 2026-10-20
- game: cities_skylines
- role: builder
- 现象: 停车场的车、长凳、商店放下后就不见了。
- 原因: 游戏模拟会删掉压在道路或步行铺装段上的 prop/tree（无论路先建还是后建）。
- 做法: 道具放在草地上，铺装用别的方式表现（见 007）；放完用截图确认还在。
- 证据: cities 回忆项目 5_build/rounds_log（r2_dev 附近，"The game DELETES every prop/tree placed on a road or pavement segment (verified)"）
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-007
- date: 2026-10-23
- game: cities_skylines
- role: builder
- 现象: `surface.txt` / `pave` 日志说已更新，截图里什么都没有；PavementA/B 看起来一样。
- 原因: Linux 版地表数据写进去了但不渲染（原因未查）。
- 做法: 广场、步道、沙滩用带贴图的平面 OBJ 或游戏道具/建筑表现。
- 证据: modlab/cities/m2w/CLAUDE.md §6 第 2 条；cities 回忆项目 p2r1_dev.md
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-008
- date: 2026-10-23
- game: cities_skylines
- role: builder
- 现象: 重开游戏后之前用命令建的东西没了。
- 原因: 建的东西只活在正在运行的城市里。
- 做法: 全部建城步骤写进 `onload.txt`（地形、水、道路、物件、模型、色调、天空）；交付前干净 `install` 一次，确认只靠 `onload.txt` 能重建全部。
- 证据: modlab/cities/m2w/CLAUDE.md §3、§4
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-009
- date: 2026-10-20
- game: cities_skylines
- role: builder
- 现象: 海水慢慢退掉；码头被涨上来的水淹了。
- 原因: 游戏的水模拟会流失海水，海面上下浮动约 3 m。
- 做法: mod 每 20 秒补一次海水（`water.txt` 的海平面）；码头/岸边比海面高出 3 m 以上，做硬质岸线。
- 证据: cities 回忆项目 HANDOFF_NEXT_MACHINE.md §2；rounds_log（quay raised to 46.4 m）
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-010
- date: 2026-10-23
- game: cities_skylines
- role: builder
- 现象: 刚跑的命令在 Player.log 里看不到结果。
- 原因: 游戏带缓冲写 Player.log，最后几行能晚几分钟。
- 做法: 看 mod 自己即时写的 `m2w.log`（`cs log`）；编译错误和异常再看 Player.log。
- 证据: repo 91ca094；modlab/cities/m2w/CLAUDE.md §6 第 3 条
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-011
- date: 2026-10-22
- game: cities_skylines
- role: builder
- 现象: 生成的建筑模型从斜角看是空心、破碎的。
- 原因: 网格是单面的，背面被剔除。
- 做法: 导入前把网格改成双面或补上背面；从记忆镜头的角度截图检查。
- 证据: cities 回忆项目 rounds_log p3r4_dev.md
- 可信度: tried once
- status: candidate

### cities_skylines-017
- date: 2026-10-26
- game: cities_skylines
- role: builder
- 现象: Linux 版 Cities 里中文按钮和回忆文字空白；字体放进用户字体目录没用，整份 8 MB CJK OTF 还让游戏启动卡死
- 原因: Unity 5.6 只列出系统字体（只有 DejaVu 8 个），不扫用户字体目录
- 做法: 不用字体：用 PIL 加 Noto 把文字预渲染成图片放进 mod 的 data/ui，Memories.cs 在没有 CJK 系统字体时画图片
- 证据: my-san-diego-memory m7 build, screenshot of the memory buttons
- 可信度: tried once
- status: candidate

### cities_skylines-018
- date: 2026-10-26
- game: cities_skylines
- role: builder
- 现象: 载入存档后一次建全部模型（约 2800 个，1.3 GB 贴图）后沙盒 pod 重启（Failed/Dead），游戏和 Steam 全丢
- 原因: 游戏常驻约 10.8 GB，pod 上限 12 GB；多次重建或二次 models 更容易触发
- 做法: 分阶段重建（clearall、只放海面、路、建筑树道具、全部模型），一个会话里 models 只跑一次；pod 重启后重跑 entrypoint.sh、steam-then-game.sh、cs install
- 证据: my-san-diego-memory m7 stage.sh; promo agent handover
- 可信度: verified repeatedly
- status: candidate

### cities_skylines-019
- date: 2026-10-26
- game: cities_skylines
- role: builder
- 现象: Cove 悬在公路上方的沙黄斜面和伸进海里的沙色圆环
- 原因: 来源是 cliff_cove 贴面（按坡度和高度带切出的平面，沙岩色），在游戏坡面上悬空
- 做法: 把 cliff_cover 从 models 去掉；定位方法：从 models.txt 去掉某一行，只重跑 models，再拍同角度对比
- 证据: my-san-diego-memory m7 before/after screenshots
- 可信度: tried once
- status: candidate

### cities_skylines-020
- date: 2026-10-26
- game: cities_skylines
- role: builder
- 现象: terrain 重设后地面在截图里消失，只剩蓝色海面
- 原因: 渲染 patch 没刷新
- 做法: 按 terrain、waterclear、waterfill、terrain 的顺序，再等 10 秒
- 证据: my-san-diego-memory m7 stage.sh
- 可信度: tried once
- status: candidate

### cities_skylines-021
- date: 2026-10-26
- game: cities_skylines
- role: builder
- 现象: cs stop 之后 cs install 有时提示 Legal Disclaimer，有时启动卡在编译前
- 原因: 不确定：同样参数有时过有时不过，全新 pod 的第一次启动总是过
- 做法: 多试一两次 stop 加 install；提示出现后先别点，常常自己消失；只有 city loaded 才算成功
- 证据: my-san-diego-memory m7 install logs
- 可信度: tried once
- status: candidate

### cities_skylines-022
- date: 2026-10-27
- game: cities_skylines
- role: builder
- 现象: 自建的平面步道/铺地上长出一丛丛草叶（只在镜头近时画），抬高 0.45 m、pave、nograss、decoration._Color 透明都没用
- 原因: 草叶是 TerrainProperties 的 grass/fertile decoration，按地形画，不管上面有没有模型
- 做法: field TerrainProperties m_useGrassDecorations false 和 m_useFertileDecorations false（写进 onload.txt）；草坪远看不变
- 证据: my-san-diego-memory m11 r6_close → r7_close
- 可信度: verified repeatedly
- status: candidate

### cities_skylines-023
- date: 2026-10-27
- game: cities_skylines
- role: builder
- 现象: 种了约 3500 棵树后弹出 IndexOutOfRange（TreeInstance.PopulateGroupData）
- 原因: 一个渲染分组里的树太多
- 做法: 同一片区域控制在 ~1300 棵、间距 ≥6.5 m（网格查重）；先少后多
- 证据: my-san-diego-memory m11 Player.log 04:45
- 可信度: tried once
- status: candidate

### cities_skylines-024
- date: 2026-10-27
- game: cities_skylines
- role: builder
- 现象: macOS 上 native reload 换了 DLL，新命令仍是 unknown command
- 原因: Unity/Mono 不卸载已加载的程序集，旧的 Host 继续处理 cmd.txt
- 做法: C# 改动攒在一起，close → 复制 DLL → launch；只改数据（models.txt、OBJ、look.txt、objects）时用 models / objects / tint 命令，不用重启
- 证据: my-san-diego-memory m11 04:27 log
- 可信度: verified repeatedly
- status: candidate

### cities_skylines-025
- date: 2026-10-27
- game: cities_skylines
- role: builder
- 现象: 画面里所有朝南的墙都在阴影里、发深蓝；对着正面拍（往北看）永远背光
- 原因: 地图的 DayNightProperties.m_Latitude 是 66，而且这个游戏里纬度符号和南北是反的：设 32.8 太阳仍在北边
- 做法: dnp m_Latitude -32.8（负值）让太阳到南边；录像要稳定时再用 sunfix <pitch> <yaw> <强度> 固定太阳（48 22 2.6 在 LUTVibrant 下颜色最好）
- 证据: my-san-diego-memory m11 第 3 轮截图对比
- 可信度: verified repeatedly
- status: candidate

### cities_skylines-026
- date: 2026-10-27
- game: cities_skylines
- role: builder
- 现象: Meshy 生成的整栋楼（带树、地面）怎么加面数都糊，减面烘焙更糊
- 原因: 生成模型是一团扫描式网格，没有干净的平面和直线
- 做法: 地标和校园楼按真实结构用代码建几何（OSM 外轮廓拉伸 + 每层立面贴图重复；Geisel 这类拆成楼板、玻璃带、斜柱），面数低、线条干净；OBJ 旁的 txt 写 raw=1 保留坐标
- 证据: my-san-diego-memory m11 gen_campus 脚本和目标图对比
- 可信度: tried once
- status: candidate

## 试玩

### cities_skylines-012
- date: 2026-10-24
- game: cities_skylines
- role: playtester
- 现象: `native drive` 发的按键（XSendEvent）Cities 没反应；普通 `xdotool click` 也点不准。
- 原因: Unity 读相对鼠标移动，不认 XSendEvent。
- 做法: 尽量用 citybuilder mod 的命令（`cmd`）操作；非点不可时用小步移动 + 慢点击（`cs click` / uclick.py），并截图确认。
- 证据: wc-cities-tests/cs-10、cs-11；modlab/cities/m2w/CLAUDE.md §6 第 4 条
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-013
- date: 2026-10-20
- game: cities_skylines
- role: playtester
- 现象: 重建后马上截图，港口是空的、河是蓝的。
- 原因: 模型和贴图还在流式加载；道具只在镜头 100–150 m 内绘制。
- 做法: 重建后多等一会儿再截；近景道具用近镜头确认；看过的截图才算数。
- 证据: cities 回忆项目 rounds_log p2r1_dev.md
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-014
- date: 2026-10-20
- game: cities_skylines
- role: playtester
- 现象: 换 LUT / 水色等全局外观后，5 个地点总分从 27 掉到 20，几轮都没超过最好的一版。
- 原因: 全局改动同时影响所有地点，变暗变灰，恰好是用户抱怨的方向。
- 做法: 每轮按地点打分，和「历史最好」比，不只和上一轮比；变差就回退那一项，交付最好的状态。
- 证据: cities 回忆项目 rounds_log r6_play.md、p2r3_play.md
- 可信度: verified repeatedly
- status: confirmed

### cities_skylines-015
- date: 2026-10-23
- game: cities_skylines
- role: playtester
- 现象: 屏幕录像有卡顿和界面，不适合放试玩页。
- 原因: 屏幕录像是构建日志；`cine` 逐帧捕获镜头，回放平滑，但没有音轨。
- 做法: 最终录像用 `cs cine`，章节写进 play.yaml；每章看 3 张抽帧确认地标在画面里；在 RESULT 里写明无声音。
- 证据: repo e37b402；modlab/cities/m2w/CLAUDE.md §5
- 可信度: tried once
- status: candidate

### cities_skylines-016
- date: 2026-10-20
- game: cities_skylines
- role: playtester
- 现象: 在 Mac 上点了 Paradox 启动器欢迎页的 CONTINUE 后账号被登出，游戏开不了。
- 原因: 启动器要用户本人的账号登录。
- 做法: 不替她登录；先在网页里说明，请她自己登录后再继续；能不用鼠标就不用。
- 证据: cities 回忆项目 HANDOFF_NEXT_MACHINE.md §2
- 可信度: tried once
- status: candidate

### cities_skylines-027
- date: 2026-10-31
- game: cities_skylines
- role: builder
- 现象: Mac 上 `native launch` 后先出来的是 Paradox 启动器（Cities.app/Contents/Launcher/dowser），不是游戏，要点 PLAY；进游戏后主菜单弹 Paradox 的「Legal Disclaimer」（隐私政策，2 页 Agree）；游戏全屏后进了自己的桌面空间，`native shot` 说「找不到窗口」。
- 原因: 启动器不是游戏进程，m2w 不认它；协议是发行商的；全屏窗口不在当前桌面，CGWindowList 的「只列屏幕上的」查不到。
- 做法: 截图看到启动器就点 PLAY（drive(launcher=[启动器 pid])，窗口 1280x670 里 PLAY 约在 (861,259)）；协议只在她说「同意，帮我点」后点 Agree；shot 现在也找不在当前桌面上的窗口（screencapture -l 照样能截）；要点击时先把游戏拉到前面（它会切到那个桌面空间）。同一天加上了：Mac 上 after_launch 等 Paradox Launcher 窗口（最多 30 分钟，首次验证），拉到前面点 PLAY（窗口宽高的 0.673 / 0.387），实测 38 秒到游戏；close 先把游戏拉到前面再请求退出，7 秒正常退出，不再 SIGTERM。
- 证据: fresh_mac_user 2026-10-31：smoke 日志 starting a new city on Black Woods / city loaded (LoadGame), money 597268077
- 可信度: tried once
- status: candidate
