# Overcooked! 2：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### overcooked2-001
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 从别的关卡资源包加载的道具（没切的面包）在本关是纯洋红 RGB(255,1,255)，没有明暗；切开后又正常。
- 原因: prefab 的材质用的 shader 在本关没加载，变成 `Hidden/InternalErrorShader`（`shader.isSupported == false`），Unity 画错误色。
- 做法: `LoadPrefab` 后遍历所有 Renderer，凡 shader 不支持的换成本关同类材质的副本（`Resources.FindObjectsOfTypeAll<Material>` 找，找不到用纯色 Standard）；在 prefab 上改一次，箱子里、手里、生成的都覆盖。加一个扫描命令（如 `hkshaders`），关卡开始、拿在手里、回合结束各扫一次，`bad=0` 再录。
- 证据: feature m3 QA_0052_0406.md；m3b README「Fix 1」（日志 FixShaders ... -> mat_ingredients_bun_01，三次扫描 bad=0）
- 可信度: tried once
- status: confirmed

### overcooked2-002
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 煎蛋在灶上看得到，厨师端起锅就像空锅；锅的食材气泡也显示错的图标。逻辑上蛋还在（日志 `utensil_frying_pan_01[DLC05_Egg] (cooked)`）。
- 原因: DLC 借来的蛋只登记了 `FryableObjectsLookup`，本关没有它在锅里的模型，也没配食材图标。
- 做法: mod 定时检查每个锅的内容，含该食材就在锅本身下挂一个子模型（按生/熟/焦变色），倒空就删；气泡 `IngredientContentsUIContainer` 改成真实内容的图标。凡是借来的食材，都要检查「放在工位上 / 端在手里 / 装盘后」三种状态都有画面。
- 证据: feature m3 QA_0052_0406.md Q2；m3b README「Fix 2」
- 可信度: tried once
- status: confirmed

### overcooked2-003
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 右下角台面装盘的一下被倒计时 HUD 挡住，观众以为菜丢了。
- 原因: 屏幕下方左右是金币和倒计时 HUD，上方是订单栏；台面格子落在这些区域里。
- 做法: 用回合内镜头把所有台面格子投影到屏幕坐标（如 `hkscreen`），列出 HUD 区域，机器人只用不被挡的中间台面（`SAFE_PLATES`），需要的话多放几个干净盘子。关键步骤（倒进盘子）加一张特写。
- 证据: feature m3 QA_0052_0406.md；m3b README「Fix 3」
- 可信度: tried once
- status: confirmed

### overcooked2-004
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 自定义关卡里订单栏越来越长，交过的菜票还留着（v2 时以为是「引擎不清除票」）。
- 原因: 客户端同一个订单被 `ClientOrderControllerBase.AddNewOrder` 加了两次，第二张 RecipeUI 交付后不消失。
- 做法: Harmony prefix 跳过同一 OrderID 的第二次添加（每关重置；留一个开关文件可关掉）。每版录像每 25 秒截一次订单栏，确认票和真实订单一致。
- 证据: hkfood MODLOG m3（Hk5.cs CoAddPre）；m3、m3b README「Regressions checked」
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-005
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 屏幕上的时钟改成 10 分钟，回合到 4:00 时游戏突然退回世界地图。
- 原因: 只改了客户端订单控制器的计时，服务端回合计时器还是 240 秒。
- 做法: 时长同时写到订单控制器（BuildOrderController prefix）和服务端回合计时器（postfix），录像里确认时钟连续倒数、不回地图。
- 证据: hkfood MODLOG m3（ROUNDTIME）；m3b README「Round clock」复查
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-006
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 有一局食物被放进了本该换成砂锅/平底锅的蒸笼里。
- 原因: 很早暂停时，关卡的两个蒸笼还没挂到灶上，按挂载查找没找到，替换跳过了。
- 做法: 替换工位时按格子位置找并销毁，再放新工具；录像第一帧检查灶上是不是新工具。
- 证据: hkfood MODLOG m3（Hk3.cs steamers）；m3b README 复查
- 可信度: tried once
- status: confirmed

### overcooked2-007
- date: 2026-10-23
- game: overcooked2
- role: builder
- 现象: 第一版把现有菜谱换成新菜的图标，做法还是原关卡的（蒸鱼当煲仔饭、蒸胡萝卜当菠萝包），被指出只是换了图。
- 原因: 为了快，菜的做法沿用原关卡菜谱。
- 做法: 每道菜先写「真实做法 → 游戏里的工具链」，缺工具就从别的关卡借（烤箱 `ServerSpawnPrefab` + `GridManager.OccupyGrid`），做不到的先说清再商量，不偷偷换成别的做法。
- 证据: feature thread（v1 选项卡备注，2026-10-23）；hkfood ITERATIONS v2
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-008
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 杨枝甘露改成芒果柚子西米，但食材柜盖子上还是西瓜和葡萄，被问为什么有西瓜和葡萄。
- 原因: 只换了食材的颜色和订单图标，没换箱子盖的图。
- 做法: 换一个食材时列清单：箱盖图、订单票图标、气泡图标、手里的 3D 样子、装盘样子。手里的形状改不了（重新上色的蜜瓜/葡萄）要在交付里写明。
- 证据: feature thread 2026-10-24 05:57；m3 README「What changed」第 4 条
- 可信度: tried once
- status: confirmed

### overcooked2-009
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 新加的查表项不生效；面包盘拒收煎蛋；搅拌好的东西放不上盘子。
- 原因: `OrderToPrefabLookup` 有缓存标志，用过后追加的条目不匹配；面包盘只收 `BurgerCosmeticPrefabs` 里的配料；Mixed 节点要有 `m_platingStep=Plate` 和装盘 prefab 才能直接装盘；放进工具要工具查表和食材烹饪步骤两边都有。
- 做法: 追加查表前把 `m_cachedAssembledOrderNodes` 设回 false；新配料加进 `BurgerCosmeticPrefabs`（照抄 FriedMeat 的限制）；Mixed 节点配好装盘步骤。改之前用 IL 列表/诊断命令确认规则（IL 列表遇到泛型 token 要跳过，否则游戏崩）。
- 证据: hkfood RESULT.md v2 research、v2 round 2；MODLOG
- 可信度: tried once
- status: confirmed

### overcooked2-010
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 餐蛋治的中间状态（面包 + 煎蛋）盘子上是空的，没有报错。
- 原因: 蛋进来时引擎丢掉了汉堡外观，组合没有对应的 3D。
- 做法: 中间状态画一个替身，凑齐后换成真模型；先蛋后肉的顺序不要改（反过来会叠出猪扒包模型）。交付里写明替身。
- 证据: feature m3b README「Engine finding」
- 可信度: tried once
- status: candidate

### overcooked2-011
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: Meshy 模型放上真实盘子后，四个是「盘子叠盘子」；玻璃杯碗不透明；正常镜头下很小。
- 原因: 生成的模型自带盘子；只用了基础色贴图（Standard shader，无透明）；一格一个盘子。
- 做法: 生成时要求「不带盘子/碗底」、≤20k 面（减面会糊贴图接缝）；OBJ 转换后 1024 贴图足够；玻璃要单独做透明材质；放置按包围盒调 fit/高度。先用一个 CC0 模型打通加载（Avocado 测试）。
- 证据: feature m3 README「Per dish」「Honest problems」；hkfood RESULT.md m3 preview
- 可信度: tried once
- status: confirmed

### overcooked2-012
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 写了一半的 cmd.txt 被执行了两次；沙盒写完马上在主机读，读到空文件，`Hk3.cs` 两次被空文件覆盖。
- 原因: 文件桥没有完成标记；JuiceFS 挂载的可见性有延迟。
- 做法: 命令文件以 `# nonce` 行结尾才执行；源码在 scratchpad 留主副本、用推送脚本单向推，推完不要立刻从主机读回；数据文件用新名字。超过约 70 KB 的单条命令会被拒。
- 证据: hkfood MODLOG m3（Plugin.cs nonce）；RESULT.md v2 round1 friction
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-013
- date: 2026-10-23
- game: overcooked2
- role: builder
- 现象: 加载后先闪一下原版唐人街厨房，再换成茶餐厅。
- 原因: 布置脚本在加载后 2 秒才跑。
- 做法: 布置延迟降到 0.5 秒，布置完成前画黑幕再淡入；关掉粒子系统；加载前的关卡卡片还是原图，录像里剪掉。
- 证据: hkfood ITERATIONS v1 round 3；MODLOG round 3
- 可信度: tried once
- status: confirmed

### overcooked2-014
- date: 2026-10-25
- game: overcooked2
- role: builder
- 现象: Mac 上直接在终端跑 `run_bepinex.sh` 游戏退出；ScriptEngine 下 `scripts/*.dll` 没加载（SymbolsNotFoundException）。
- 原因: 游戏要 Steamworks，必须由 Steam 启动；ScriptEngine r11.2 要求 dll 带 `.pdb`，且会读所有 `*.dll`。
- 做法: Mac 用启动选项 `"<游戏目录>/run_bepinex.sh" %command%`（`executable_name="Overcooked2.app"`，Rosetta 下能注入）；热加载时 `.pdb` 一起放，临时文件名不要以 `.dll` 结尾；ScriptEngine 设置只在游戏启动时读。插件 `Awake` 里设 `Application.runInBackground = true`，否则失焦就暂停。
- 证据: docs/cross-platform.md「Found on macOS」；docs/cross-platform.md（Overcooked! 2 段、§9）
- 可信度: tried once
- status: confirmed

### overcooked2-015
- date: 2026-10-24
- game: overcooked2
- role: builder
- 现象: 开工时 Steam 没在跑、只剩僵尸进程；容器被平台重启后没有 X、PulseAudio，Steam 一启动就死；`hkgo` 后桥的暂停标志是旧的。
- 原因: 平台重启不跑 entrypoint；桥的状态没刷新。
- 做法: 开工先检查 Steam 是否登录（`oc2-steam start` 等待），缺 X/声音先重跑 `/usr/local/bin/entrypoint.sh`；`hkgo` 后 `oc2 resume` + `oc2 pause` 才算真暂停。收工卸载 mod（只留 OC2Bridge.dll）、`overcooked2.sh down`，在对话里告诉她 Steam 可以登录了。
- 证据: hkfood RESULT.md m3 / m3b「Ops」「State left」
- 可信度: verified repeatedly
- status: confirmed

## 试玩

### overcooked2-016
- date: 2026-10-23
- game: overcooked2
- role: playtester
- 现象: 等搅拌机、等烤箱用 `time.sleep` 没用；搅拌过头变 OverMixed。
- 原因: 机器人跑时游戏只在动作和 `oc2 advance` 里走时间；搅拌机 12 秒 Mixed、24 秒 OverMixed，只在工位上搅。
- 做法: 所有等待用 `oc2 advance`；Mixed 后立刻取。录像里的冻结段用「画面不变就剪掉」自动剪，交付里写明剪辑和倍速。
- 证据: hkfood RESULT.md v2 research「Other findings」、friction；m3 README「Editing」
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-017
- date: 2026-10-24
- game: overcooked2
- role: playtester
- 现象: 4 分钟真实关卡里单机器人只交 2-3 道菜；没有订单的菜交了不得分；开头就堆满订单的录像不被接受。
- 原因: 一道菜 45-90 秒，远慢于阶段节奏。
- 做法: 录全菜一局时用一个阶段、关自动订单、机器人每交一道加一单（`hkorder`），回合时长放到 600 秒；多放干净盘子免洗；从关卡第一秒录（幕布、Go、标题），订单栏从空开始。
- 证据: hkfood RESULT.md v2 round 2「Full real-phase run」；m3 README；feature thread 2026-10-24 03:48
- 可信度: verified repeatedly
- status: confirmed

### overcooked2-018
- date: 2026-10-24
- game: overcooked2
- role: playtester
- 现象: 一次从台面拿冰块没拿到，搅拌机只有牛奶，冻饮没交出（7/8）。
- 原因: 拿取动作不报错。
- 做法: 每次拿取后读状态确认手里的东西，不对就重试并在日志写 RETRY；交付前数一遍交付数。
- 证据: feature m3b README「Honest problems」
- 可信度: tried once
- status: confirmed

### overcooked2-019
- date: 2026-10-24
- game: overcooked2
- role: playtester
- 现象: 她在成片 0:52、4:06 留言，画面里有两处可能的东西，回答前不确定她指哪个。
- 原因: 成片剪过冻结帧、又加速，时间和原始录像对不上。
- 做法: 用剪辑区间文件把成片时间换回原始录像时间，再对机器人日志里的状态；取色（纯洋红 = 丢 shader）；把每个候选都解释清楚并给图，区分「是 bug」和「游戏原本的样子」（搅拌机的「+」是正常提示）；「看起来空」先查日志是逻辑丢了还是只是没画。
- 证据: feature m3 QA_0052_0406.md；thread 2026-10-24 19:05-19:20
- 可信度: tried once
- status: confirmed

### overcooked2-020
- date: 2026-10-24
- game: overcooked2
- role: playtester
- 现象: 修一处时容易把之前修好的鬼票、回合时钟、蒸笼替换弄坏。
- 原因: 这些都在同一个 mod 的同一段初始化里。
- 做法: 每版录像固定检查：订单栏与订单一致（每 25 秒）、时钟连续倒数不回地图、第一帧灶上工具对、全场 shader 扫描 bad=0、所有菜的 3D 模型都在、关键步骤不被 HUD 挡。
- 证据: feature m3b README「Regressions checked」
- 可信度: tried once
- status: confirmed

### overcooked2-021
- date: 2026-10-24
- game: overcooked2
- role: playtester
- 现象: 回合内特写常拍到别的盘子，或者被厨师和气泡挡住。
- 原因: 镜头 rig 脚本会拉回镜头；刚装好的盘子被厨师挡。
- 做法: 拍特写先禁用 rig 脚本、隐藏字幕条，游戏暂停时拍；按格子位置选盘子；拍不到的写「未在游戏盘子上验证」。
- 证据: hkfood RESULT.md v2 round 2「Verified / not verified」、friction
- 可信度: tried once
- status: candidate

### overcooked2-022
- date: 2026-10-31
- game: overcooked2
- role: builder
- 现象: 重新下载后游戏文件夹里没有 BepInEx 的日志更新，但旧的 LogOutput.log 里有 [M2W-smoke] loaded（10-25 留下的，跟着 BepInEx 一起拷回来），差点当成这次的结果；第一次启动后 Steam 弹「Overcooked! 2」小窗（Steam Helper 的启动提示），游戏 15 分钟后才开始跑（USB 盘首次验证）。
- 原因: 日志是旧的；Steam 的启动提示不是游戏窗口。
- 做法: 看日志第一行的 BepInEx 时间戳和文件修改时间，确认是这次启动写的；以截图为准（开始画面上的「M2W smoke: plugin loaded」）。Steam 启动选项让她用 `native doctor --game overcooked2 --copy` 复制后粘贴。
- 证据: fresh_mac_user 2026-10-31：BepInEx 5.4.23.4 - Overcooked2 (10/30/2026 11:49:07 PM)，开始画面截图
- 可信度: tried once
- status: candidate
