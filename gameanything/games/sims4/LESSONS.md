# The Sims 4：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### sims4-001
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 演出中台上的角色突然不见，右上角弹「I should really get going now」；一次完整运行里主角 NPC 在第 64 秒、主持人在第 103 秒被移除。
- 原因: 脚本生成的 NPC 挂的是「拜访」情境；情境到期或被游戏结束后 Sim 实例被删除。每秒延长拜访时长也没拦住（清理时情境数量变多，说明旧的已被结束）。没有 situation 的路人几秒内就会自己走掉消失。
- 做法: 生成 NPC 时必须挂情境（`create_visit_situation` + `change_duration_by_minutes`）；另外每秒做在场检查（PRESENCE/TRACE 日志），人没了 1 秒内重新生成、重建情境、放回原位、重新拿起道具。根治方法仍未找到，交付时如实说明。
- 证据: sims4-flying-car round5b ITERATIONS.md / README（3 次完整运行：1 次触发补救，2 次全程在场）；sims4-flying-car 项目 5_build/story/ACT1_NOTES.md；commit c9e3de1
- 可信度: verified repeatedly
- status: confirmed

### sims4-002
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 台上的角色都变胖，衣服变成随机的旧棕色衣服。
- 原因: `set_all_commodities_to_best_value()` 把体型相关的 commodity（胖度 Fitness_Fat）也拉满，游戏随之重新生成随机服装。
- 做法: 只补 `motive_*`（饥饿、膀胱、精力等动机）；体型用 0–100 刻度显式设置（fat/fit），并每秒检查体型，跑偏就改回。
- 证据: sims4-flying-car round4 ITERATIONS.md 第 2 轮；commit 034f69c
- 可信度: verified repeatedly
- status: confirmed

### sims4-003
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 换好的服装在 Sim 出生或被传送后变回随机衣服；从随机来源 Sim 复制服装时还会带上帽子、眼镜、首饰。
- 原因: spawn 会重置当前服装；传送后游戏也会把衣服重置成随机的；复制服装是按来源 Sim 的全部部件复制。
- 做法: spawn 之后再调一次 `set_current_outfit`；每秒检查服装，不对就重新套上（日志记 `outfit_fixes`）；`dress()` 一律去掉帽子和配饰部件。
- 证据: sims4-flying-car round4 ITERATIONS.md 第 3–4 轮，round5 README；sims4-flying-car 项目 5_build/story/ACT1_NOTES.md
- 可信度: verified repeatedly
- status: confirmed

### sims4-004
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 录到一半画面停住，整轮作废（例如游戏弹出的剧情提问对话框、我们自己第二幕的选择框）。
- 原因: 模态对话框会把游戏暂停，直到有人点选。
- 做法: 每秒关闭所有不是我们发出的对话框；我们自己的对话框在自动录制时用 `dialog_respond` 自动答。成就、新生儿这类通知（非模态）关不掉，会出现在画面里，交付时说明。
- 证据: sims4-flying-car round5b ITERATIONS.md（u2 作废，u3 通过）；thread 中 2:12 画面被对话框暂停的反馈（第 17 版开工卡）
- 可信度: verified repeatedly
- status: confirmed

### sims4-005
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 测试会改变存档里的游戏时间、人物状态；保存一次就污染了用户的真实存档。
- 原因: Alt+F4 或菜单退出会弹「Save Game?」，「Save and Exit」会覆盖存档；游戏内 Python 没有退出/回主菜单的函数。
- 做法: 退出时选「Exit Game」（不保存）；把用户存档复制成新存档位（如 Slot_00000002 → Slot_00000003）再加载，只在内存里改状态；每轮前后比对原存档 sha256，并保留只读原样副本。
- 证据: sims4-flying-car server_repro/README.md，round5 README（sha256 前后一致）；_agent sims4-spike NOTES.md Phase D
- 可信度: verified repeatedly
- status: confirmed

### sims4-006
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: `terrain.get_terrain_height` 在部分区域返回 -100；物件悬空约 1 米（地块中心比周围高 1 米）；生成在这种区域的 Sim 几秒内被游戏「请走」。
- 原因: 地块和周边只有部分区域有可读的地形高度（该地块只有 z<198 或 x>=200 等范围有效），且地块本身有台阶。
- 做法: 每个锚点逐点取地形高度；读不出时用周围的地面高度并在交付里写明；Sim 一实例化就放到有效的位置（如舞台上），不要先站在读不出的地面上。
- 证据: sims4-flying-car 项目 5_build/story/ACT2_NOTES.md（Clock/terrain）；round4 README 第 3 条；round5 ITERATIONS.md（飞入的角色在这种区域消失）
- 可信度: verified repeatedly
- status: confirmed

### sims4-007
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: EA app 安装报 `Error 0x80070643 INST-14-1603`（MSI 自定义动作 JunoInitializeSession 返回 1603）；失败后的下一次运行会立即退出；安装末尾报 D0-4A8E。
- 原因: 安装器的自定义动作依赖 .NET，禁用 mscoree 或 Wine 包不带 wine-mono 就会失败；Wine 没正确建出 `EA Desktop\EA Desktop` 目录联接。
- 做法: 用不需要 i386 库的纯 wow64 Wine 版本；装 wine-mono + wine-gecko，不要禁用 mscoree/mshtml；DXVK 拷进 system32/syswow64 并设 native,builtin；从带版本号的目录启动 EALauncher.exe；立即退出就再运行一次；D0-4A8E 点确定即可。
- 证据: _agent/logs/2026-10-24/sims4-spike/NOTES.md；之后 round2–round5b 都在这套环境里构建和录制
- 可信度: verified repeatedly
- status: confirmed

### sims4-008
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 录像抖动、第二幕重影。
- 原因: 游戏镜头自带缓动；每个 tick 都发镜头命令会不断重置缓动。实测帧差变异 cv：每 tick 0.64，每 0.08 s 0.29，每 0.04 s 0.19。
- 做法: 镜头更新用固定 0.04 s 网格，在同一帧物体移动之后再动镜头，不重复发同一条命令；先写分镜表，每个镜头只下一次「从 A 滑到 B」。分镜重写后第二幕 cv 只从 0.53 降到 0.49，重影没解决，「不要和游戏缓动打架」仍是待验证的假设。
- 证据: sims4-flying-car round5 ITERATIONS.md（抖动测试），round5b README 第 3 条，round5b/ACT2_SHOTLIST.md；commit 710ac4c、c9e3de1
- 可信度: tried once
- status: candidate

### sims4-009
- date: 2026-10-23
- game: sims4
- role: builder
- 现象: 自制 .package 被游戏挂上，模型、贴图、名字都读得到，但物件定义（OBJD）和目录条目（COBJ）「资源不存在」。
- 原因: 游戏把 OBJD/COBJ 中 instance 第 63 位为 1 的资源映射到 group 0x80000000；我们写的是 group 0。
- 做法: OBJD/COBJ 用高位 ID 时 group 写 0x80000000（或用小于 2^63 的 ID 配 group 0）；先用 `sims4.resources.get_normalized_key` 在游戏里查。
- 证据: sims4-flying-car 5_build/sims4_car/CONVERTER_NOTES.md（v1 → v2a）
- 可信度: tried once
- status: confirmed

### sims4-010
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 近景时舞台平台和坡道「消失」，只剩影子。
- 原因: 转换器把包围盒写成模型原尺寸，游戏按缩放后的尺寸渲染，按旧包围盒做视锥裁剪。
- 做法: 用 `obj2package --render-bbox` 写渲染后的包围盒；运行时缩放（object scale）后也要保证包围盒覆盖实际大小。
- 证据: sims4-flying-car round2 ITERATIONS.md 第 2 轮；commit 5b02140
- 可信度: tried once
- status: confirmed

### sims4-011
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 车先是只有 1/3 大小并悬空，后来又被放大到约 12 米（被反馈太大）。
- 原因: 游戏没有按我们的量化除数解码顶点（渲染约 1/7.6）；运行时缩放 7.6 又叠加在已缩小的模型上；放车时没贴地。
- 做法: 一次放几个不同缩放的版本，旁边放长凳 / Sim 量；以真车约 4.2–4.8 米、Sim 约 1.8 米为准；放物件按地形高度贴地。
- 证据: CONVERTER_NOTES.md Update 2；round2 README 第 6 条
- 可信度: verified repeatedly
- status: confirmed

### sims4-012
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 玩家 Sim 上台一直 TRANSITION_FAILURE；NPC 有时第一次也失败。传送后的活动 Sim 几帧后又被自主行为拉回沙发。
- 原因: 活动 Sim 的交互路径失败；自主行为（autonomy）在传送后重新选择行动。
- 做法: 失败 2 次就直接放上台，镜头先拍起身再切到台上；需要固定位置时关掉活动 Sim 的 autonomy 闹钟，结束时恢复。
- 证据: round2 ITERATIONS.md 第 3–4 轮，round3 README；sims4-flying-car 项目 5_build/story/ACT2_NOTES.md（Hide + teleport）
- 可信度: verified repeatedly
- status: confirmed

### sims4-013
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 调试时推进时钟让存档里人物的状态往前走（触发了剧情事件）；测试时游戏自己提速到 5 档，跑掉十几个游戏小时；后几轮全在夜里，黑衣服和深色台面看不见。
- 原因: 一场 3–4 分钟的演出在游戏里会过 3–9 小时；活动 Sim 睡觉时游戏会自动加速。
- 做法: 不拨钟、演出一结束就暂停（speed 0）；最终录像前重启游戏回到中午；颜色设计考虑傍晚光线（台面用浅色）。
- 证据: round2 ITERATIONS.md 第 4 轮；round4 ITERATIONS.md 第 4–5 轮；sims4-flying-car 项目 5_build/story/ACT2_NOTES.md（Game state）
- 可信度: verified repeatedly
- status: confirmed

### sims4-014
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 在 macOS 上从 ~/Documents 直接 import 开发中的模块，弹出「The Sims 4 想访问文档文件夹」授权框，游戏被卡住；游戏退出时会重写 Options.ini。
- 原因: 系统权限框（TCC）阻塞游戏；游戏只认 Python 3.7 字节码；Options.ini 在退出时写回。
- 做法: 用 `gameanything native build --game sims4` 打成 .ts4script 装进 Mods（Options.ini 的 scriptmodsenabled=1）；只在游戏关闭时安装；开发热加载用改名的副本（命令前缀不同，避免和已安装模组冲突）；桥的 dev 开关文件用完就删。
- 证据: sims4-flying-car 项目 5_build/story/ACT1_NOTES.md（BLOCKER），ACT2_NOTES.md（Live method）；交接笔记 Gotchas（已移出仓库）
- 可信度: verified repeatedly
- status: confirmed

### sims4-015
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 脚本对话框点了按钮，回调从不执行。
- 原因: tunable 键是 `ui_responses`（不是 dialog_responses）；构建后 `loots_for_response=()` 被变成 None，`respond()` 返回 False。
- 做法: 构建对话框后 `for r in d.ui_responses: r.loots_for_response = ()`；自动模式用 `dialog_respond(id, n)` 回答。
- 证据: sims4-flying-car 项目 5_build/story/ACT1_NOTES.md (d)
- 可信度: tried once
- status: confirmed

### sims4-016
- date: 2026-10-24
- game: sims4
- role: builder
- 现象: 每帧 move_to 一个 Sim 时游戏报错「QuaternionImmutable ... is not a rotation around y」。
- 原因: Sim 的朝向只接受绕竖轴的旋转；物件可以倾斜。
- 做法: Sim 只给 yaw（`util.yaw_only`）；需要「飞行姿态」用物件（车）表现，倾斜轴按机身侧轴算，测试里验证车顶不侧翻。
- 证据: sims4-flying-car 项目 5_build/story/ACT2_NOTES.md（Iron Man）；round3 README 第 6 条
- 可信度: tried once
- status: confirmed

### sims4-017
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: `vfx.PlayEffect` 播 s40_fire、olympus_fire_long、s40_Sim_smoke 都没有画面；`object_laserLightShow` 创建失败。
- 原因: 这个游戏版本里这些特效名不能单独播放；部分物件属于未安装的资料片。
- 做法: 火用篝火物件 + 物件状态（FireIntensity_High / High_VFX_Normal），水柱用喷泉发射器物件；先单件逐个放进游戏看，再进整套。没有真正的烟和舞台灯，交付时说明。
- 证据: round3 ITERATIONS.md 第 0 轮，round3 README 第 2 条
- 可信度: tried once
- status: confirmed

### sims4-018
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 第二幕开头多出一个角色站在邻居门廊旁。
- 原因: Sim 被创建在默认出生点，游戏淡入显示后才被脚本移走。
- 做法: 一创建就隐藏（VisibilityState(False)）并移到目标位置（高空 / 台上），轮到他时再显示。
- 证据: round5 README 第 4 条；commit 710ac4c
- 可信度: tried once
- status: confirmed

### sims4-019
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 场地贴着房子像「家门口的小表演」；搬走后又被大树和邻居房子挡住开场镜头。
- 原因: 只按地块坐标估位置，没有看镜头方向上的遮挡；家庭地块只有约 20x30 米。
- 做法: 先俯拍扫描全图多处，选够大的无树无房空地（如 42x18 米），再把阵型、观众朝向、镜头、车和飞行路线都改成「舞台坐标系」，换场地只改原点。
- 证据: round3 ITERATIONS.md 第 2–3 轮；round4 ITERATIONS.md 第 1 轮、README「我看过的地方」
- 可信度: verified repeatedly
- status: confirmed

### sims4-020
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 录像开头 30–48 秒是全景等观众走来坐下，很闷。
- 原因: 让 NPC 自己走路、找座位要很久。
- 做法: 主要角色直接放到台上；观众到约 45% 入座就开始，或直接放到座位上；静止的段落要有镜头运动。
- 证据: round3 ITERATIONS.md 第 1–2 轮；round5 README 老实说
- 可信度: verified repeatedly
- status: confirmed

### sims4-021
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 用人脸关键点黑盒搜索 67–72 个脸部滑杆约 160 次，分数 0.241 → 0.078，但肉眼前后几乎一样；用户反馈五官不像，至少发型要像。
- 原因: 脸部滑杆名字是哈希、粒度粗，没有发际线、眼窝这类单独控制。
- 做法: 先扫描全部自带发型做对比图，选最接近的短发型并给 3 个候选；体型、服装、发型优先；开工前就说清脸做不像，需要更像就请用户自己下载发型 CC。
- 证据: round5 ITERATIONS.md / README 第 1 条；round5b README 第 2 条；对话里的同一条反馈
- 可信度: verified repeatedly
- status: confirmed

### sims4-022
- date: 2026-10-25
- game: sims4
- role: builder
- 现象: 车落在台前时车身穿进坡道边和篝火，离观众长椅很近。
- 原因: 落点和转身朝向只按舞台位置算，没避开后来加的篝火和坡道边。
- 做法: 加道具后重新算车的落点和转身半径，留出净空；落地和转身段逐帧检查。
- 证据: sims4-flying-car 对话（她指出穿模的那一帧）、第 17 版开工卡（round6，进行中）
- 可信度: tried once
- status: candidate

## 试玩

### sims4-023
- date: 2026-10-24
- game: sims4
- role: playtester
- 现象: 脚本状态全部「通过」，但实际画面是舞台像笼子、车太大、人物胖。
- 原因: Sims 4 脚本只能读写数据，碰不到渲染，没有截图命令；只看状态和数字会漏掉所有视觉问题。
- 做法: 每轮都要截游戏窗口 / 录屏看画面（服务器用 x11grab，Mac 按窗口截图需要屏幕录制权限）；每项改动配一张截图，并对照用户指出的那一帧。
- 证据: sims4-flying-car 对话（她问为什么不自己看游戏画面）；sims4-flying-car 项目 5_build/story/ACT2_NOTES.md「No visual confirmation of anything」
- 可信度: verified repeatedly
- status: confirmed

### sims4-024
- date: 2026-10-25
- game: sims4
- role: playtester
- 现象: 用户说录像抖；第 14、15 版录像只有 15 fps。实时查看页（远程转发）也抖。
- 原因: 15 fps 录制本身不顺；实时查看页的抖来自抓屏、压缩和转发，不是游戏帧率（x11grab 4 秒抓到 121 帧全不同）。
- 做法: 录制 30 fps，用「不同帧数」确认游戏真画到 30 帧；用帧差变异系数 cv 给改前改后的数字；先分清抖在游戏、录制还是查看器。
- 证据: 对话（她反馈录像和实时查看页都抖）；round5 README 第 6 条
- 可信度: verified repeatedly
- status: confirmed

### sims4-025
- date: 2026-10-25
- game: sims4
- role: playtester
- 现象: 构建报告说完成，用户在 1:08 看到话筒前没人；之前也看到台上是穿旧棕衣的胖子。
- 原因: 游戏会删 Sim、重置服装和体型，单看最后结果发现不了中途的缺席。
- 做法: 回放时用 PRESENCE/TRACE 日志按秒核对位置，关键时刻截图（如 52/62/68/74 秒）；逐帧核对台上是谁、穿什么；看到「我该走了」通知就查是否触发了补救。
- 证据: round5b README 第 1 条；round4 README 第 2 条
- 可信度: verified repeatedly
- status: confirmed

### sims4-026
- date: 2026-10-24
- game: sims4
- role: playtester
- 现象: 读档后停在世界地图，桥的 health 一直是 "menu"，等了约 13 分钟以为还在加载。
- 原因: 那是正常的地图界面；只点住户标记没反应，要点地块本身再按 Play / 前往。
- 做法: 读档后点地块进入，等 health 不再是 "menu" 再跑；启动时先关全屏广告和 Mods 对话框。
- 证据: sims4-flying-car server_repro/README.md；sims4-spike NOTES.md Phase D
- 可信度: tried once
- status: candidate

### sims4-027
- date: 2026-10-25
- game: sims4
- role: playtester
- 现象: 服务器录像里没有游戏自带音乐和音效。
- 原因: 服务器上的游戏没有声卡。
- 做法: 按日志时间点（MARK）生成配乐混进录像；交付时说明她自己玩时听到的是游戏原声，听不到这段配乐。
- 证据: round3 README 第 7 条；gameanything/worlds/sims4/soundtrack.py
- 可信度: verified repeatedly
- status: confirmed

### sims4-100
- date: 2026-10-26
- game: sims4
- role: builder
- 现象: 车落地后转身压进红色边条、篝火和长椅。
- 原因: 特效物件（篝火）放在车的落车区里，落地点和出场路线没按周边物件留空。
- 做法: 先把会占地的特效物件放到平台上，落车区只留车；出场路线沿空的一端走；逐帧看落地和转身。
- 证据: sims4-flying-car round6 stills/01–03
- 可信度: tried once
- status: candidate

### sims4-101
- date: 2026-10-26
- game: sims4
- role: builder
- 现象: 游戏自己的「I should really get going now」通知一直挂在右上角，关了又出现；Elon 仍在约 50 秒被移除。
- 原因: 拜访情境到期，游戏发的是持续通知；每秒延长情境、取消对话框都没拦住。
- 做法: 在场守卫（1 秒内重新生成）是目前唯一有效的补救；交付里如实说明通知还在。
- 证据: sims4-flying-car round6 日志（PRESENCE 53.0 / 58.0 respawned）
- 可信度: tried once
- status: candidate


### sims4-028
- date: 2026-10-30
- game: sims4
- role: builder
- 现象: Mac 新用户流程里 Sims 4：① 游戏在外置 USB 盘上，第一次启动卡了约 20 分钟（进程 0% CPU）；② 直接 `open "The Sims 4.app"` 一直不动，要从 EA App 点 PLAY；③ 主菜单前后各弹一个促销页，电脑操作工具的点击点不掉，Esc 能关；④ 新装的 smoke mod 没写日志，因为 Mods 里还有一个旧的 m2w_smoke/，两个 .ts4script 里是同名模块 m2w_smoke，游戏只导入第一个；⑤ 退出时弹「Exit Game – Are you sure?」。
- 原因: macOS 对 USB 盘上的大 app 做首次验证；Sims 要 EA App 先认证；促销页只认真实按键；脚本模组按模块名导入，同名就被挡掉。
- 做法: 先告诉她第一次启动会等很久，每几秒截图看状态（不要只等日志）；从 EA App 的 PLAY 启动；促销页按 Esc（m2w native drive "key escape"），每按一次截一次图；装脚本 mod 前看 Mods 里有没有同名模块的旧 mod；退出的确认框点 ✓（主菜单上没有存档问题，绝不在游戏里存档）。2026-10-31 起：launch 打开 EA App，after_launch 点侧栏的 The Sims 4 再点 PLAY（实测 20 秒到游戏）；install 发现 Mods 里别的 .ts4script 有同名模块就拒绝并说怎么办。close 在主菜单上请求退出没反应，20 秒后 SIGTERM（主菜单没东西可存）。
- 证据: fresh_mac_user 2026-10-30：23:18 点 PLAY，23:38 进程开始跑；旧 m2w_smoke.log 23:39:25 [M2W-smoke] loaded；Mods 对话框列出 m2w_smoke 和 sims4 两个脚本模组
- 可信度: tried once
- status: candidate
