# Minecraft：经验（lessons）

做过的人留下的做法。格式和规则见 skills/gameanything/references/lessons.md：一条 = 一个 `### <id>` 小块，
不写她的照片、人名、存档细节。`gameanything lessons add` 追加候选（candidate），协调员 `gameanything lessons review` 确认 / 合并 / 删除。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 开发

### minecraft-001
- date: 2026-10-24
- game: minecraft
- role: builder
- 现象: `gameanything native doctor` 里 Minecraft 的 running 一直是 unknown，restore 在游戏开着时照样执行，游戏退出时又把世界写回去。
- 原因: Java 进程名都是 java，按进程名找不到；而每个启动器都会传 `--gameDir <.minecraft>`。
- 做法: Linux / macOS 在进程参数里找 `--gameDir <这个 .minecraft>`；Windows 的 tasklist 看不到参数，仍是 unknown，要请她先关游戏再 restore。
- 证据: repo commit e709614；_agent/logs/2026-10-24/native-linux/minecraft-doctor-1.txt
- 可信度: tried once
- status: confirmed

### minecraft-002
- date: 2026-10-24
- game: minecraft
- role: builder
- 现象: `native install` 把 `build/libs/*-sources.jar`（或一个文件夹）装进了 mods/，Fabric 不加载，没有报错。
- 原因: `./gradlew build` 在 build/libs 里同时留下 mod jar 和 sources jar，两者都有 fabric.mod.json，sources jar 里没有 class。
- 做法: 只装带 fabric.mod.json 且有编译好的 class 的那个 jar（install 现在会检查）；拷文件时用 `modlab-1.0.0.jar` 这样的确切名字，不要 `*.jar`。
- 证据: repo commit e709614；_agent/logs/2026-10-24/native-linux/minecraft-takehome-0-before-fix-sources-jar.txt
- 可信度: tried once
- status: confirmed

### minecraft-003
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 26.3 改了很多名字：`Blocks.RED_WOOL` / `PINK_STAINED_GLASS` 不存在，`ServerPlayer.hurtMarked` 没了，`TextDisplay.getText/setText` 是 private。
- 原因: 26.3 是新版本（Mojang 原名、未混淆），旧教程和记忆里的写法大多过时。
- 做法: 在 `/lab/mc-sources/` 用 rg 查真实代码再写；有颜色的方块用 `Blocks.WOOL.pick(DyeColor.X)` 这类写法；只在容器里能读源码，宿主机看不到。
- 证据: mc-runs/hlm-m1/work/MODLOG.md、mc-runs/hp-m1/work/MODLOG.md（v1、v3 round 1）
- 可信度: verified repeatedly
- status: confirmed

### minecraft-004
- date: 2026-10-21
- game: minecraft
- role: builder
- 现象: `mc reset` / `mc-run` 总是生成普通地形世界（种子 2024），没有超平坦选项，大场景被山和树打乱。
- 原因: 实验室的启动脚本固定这样建世界。
- 做法: mod 里放一个 data-pack 维度（flat 生成器），用自己的命令在那里建并把玩家传过去；在这个维度里 tp 要写 `execute in modlab:<维度> as @p run tp @s ...`，否则会回到主世界。
- 证据: mc-runs/hlm-m1 MODLOG round 1；mc-runs/hp-m1 MODLOG v1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-005
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 戏里人物被埋进地下、站到屋顶或井棚上、在桥上消失。
- 原因: 建造时直接写方块不更新 heightmap，heightmap 返回的是下面的水面或泥土；MOTION_BLOCKING 也看不到没有碰撞的自制树叶。
- 做法: 站立高度从上方往下扫描第一个实心面（跳过树叶）；亭子、桥、楼上用固定高度；扫描前先 `getChunk` 把区块加载好（未加载的区块返回空气）。
- 证据: mc-runs/hlm-m1 MODLOG（LAB FACT big）、m3 ITERATIONS round 3
- 可信度: verified repeatedly
- status: confirmed

### minecraft-006
- date: 2026-10-23
- game: minecraft
- role: builder
- 现象: 她在录像 7:26 看到元妃和宫女悬在水面上；独立评审没发现。
- 原因: 人物关了重力（免得被挤开），站位落在石台边缘外或桥的空洞上；固定高度的戏会把这类洞藏起来。
- 做法: 做一个对所有人物、每段走位取样检查脚下实地的命令（第一次查出 83 处，修到 0），每版交付前跑一遍；给坐着的人都放真正的座位；补光方块不要放进楼梯等已有结构的格子。
- 证据: adaptation m4 批注 e_20261023T021648_d757；mc-runs/hlm-m1 m5 ITERATIONS round 1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-007
- date: 2026-10-23
- game: minecraft
- role: builder
- 现象: 第二条船连续两版不出现：一条船被拆散，另一条停在出生点。
- 原因: 两条船的 block_display 零件用了相同的 tag，每 tick 的 `tp @e[tag=..,limit=1]` 只移动其中一个。
- 做法: tag 写成 `<零件><实例 id>`；用 block_display 拼的东西（船、人物）都用唯一 tag 或固定 UUID 去找。
- 证据: mc-runs/hlm-m1 MODLOG（second boat）、m5 ITERATIONS round 1
- 可信度: tried once
- status: confirmed

### minecraft-008
- date: 2026-10-23
- game: minecraft
- role: builder
- 现象: 花冢、树篱、楼梯、墙面一片黑，同样的命令上一次是亮的；扁平植物显示成黑剪影。
- 原因: 建造时放下的 light 方块有时不会计算光照；重复放一个已存在的 light 方块不会改变什么。
- 做法: 建完约 30 s 后强制加载这些区块，把所有 light 方块删掉再放一次；扁平装饰方块给 `lightLevel`。
- 证据: mc-runs/hlm-m1 MODLOG（LAB FACT light, again）
- 可信度: verified repeatedly
- status: confirmed

### minecraft-009
- date: 2026-10-23
- game: minecraft
- role: builder
- 现象: 方块状态解析失败；用草、蕨、橡树叶做的显示实体是黑的；粉色方块悬在空中。
- 原因: 26.3 要 `block_state:{id:"..",properties:{..}}`（旧的 `"name[k=v]"` 不认）；受生物群系染色的方块在 display 里渲染成黑色；没有支撑的装饰方块看着像飘着。
- 做法: 按新格式写；显示用的绿植换不染色的方块（杜鹃叶、苔藓、花）；装饰放完从镜头看一遍有没有悬空。
- 证据: mc-runs/hlm-m1 MODLOG（display state / display tint）；adaptation m5 批注 e_20261023T185905_6531
- 可信度: verified repeatedly
- status: confirmed

### minecraft-010
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 客户端加载模型时死掉，日志 `PartDefinition parent is null`。
- 原因: 模型 json 里子零件出现在父零件之前。
- 做法: 生成模型的脚本按父链排序；手臂、肢体的旋转方向先拿一个姿势截图验证正负号（右臂 yRot 负数才是向内，弄反就成了 T 字姿势）。
- 证据: mc-runs/hlm-m1 MODLOG（crash、arm yRot）；mc-runs/hp-m1 MODLOG v4 round 1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-011
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 字幕盖住画面中间的人物；一段戏的台词在镜头离开后还在别的房间的画面里出现；长句被截断。
- 原因: 标题通道在屏幕中央；场景没有在玩家离开后停止；1152-1280 px 宽的窗口一行只放得下约 16 个汉字或 34 个英文字符。
- 做法: 用自己的 HUD 元素或动作栏放在下方一条；玩家离开范围约 1.5 s 后中止这段戏并清掉字幕；按窗口宽度拆短句。mod 自己永远不写聊天栏。
- 证据: mc-runs/hp-m1 MODLOG v4 round 2；mc-runs/hlm-m1 MODLOG（Titles）
- 可信度: verified repeatedly
- status: confirmed

### minecraft-012
- date: 2026-10-23
- game: minecraft
- role: builder
- 现象: gradle 说 UP-TO-DATE，jar 里还是旧代码；build.done 在但其实编译报错。
- 原因: 宿主机写的文件在容器里要 1-4 分钟才更新；root 拥有的文件容器用户覆盖不了；build.done 只表示脚本结束。
- 做法: 编译前在容器里确认新文字已经到了（`unzip -p jar X.class | grep`）；每次都看 build.log 有没有 `error:`；两个 gradle 不要同时跑。
- 证据: mc-runs/hlm-m1 MODLOG（LAB FACT workflow）；mc-runs/hp-m1 MODLOG v3 round 1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-013
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 在 `while read` 循环里批量跑 `mc cmd`，后面几行的开头字母丢了（房间名变成 `engwu`）。
- 原因: `mc cmd` 读取了标准输入。
- 做法: 循环里一律 `mc cmd "..." < /dev/null`。
- 证据: mc-runs/hlm-m1 MODLOG
- 可信度: tried once
- status: confirmed

### minecraft-014
- date: 2026-10-21
- game: minecraft
- role: builder
- 现象: 生成蝴蝶、牌匾的命令把聊天栏刷满，进了截图和录像。
- 原因: 服务器控制台命令源不理 `withSuppressedOutput()`。
- 做法: 用 `CommandSource.NULL` 建 CommandSourceStack 执行；拍摄期间关 `send_command_feedback`、`command_block_output`。
- 证据: mc-runs/hlm-m1 MODLOG round 5 lab facts
- 可信度: verified repeatedly
- status: confirmed

### minecraft-015
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 评审说礼堂没有改动、某处是「黑色的板」，其实改动都在：镜头站在旧门楼的实心方块里、露台栏杆里或书架里。
- 原因: 旁观者镜头在方块里面时整屏是那个方块；旧版留下的结构会挡住新东西。
- 做法: 评审和自己看到的不一致时，先用 `mc blocks` 查镜头所在格和视线上的方块；镜头周围 2 格内不留柱子、13 格内不留树；只给登记过的机位清树。
- 证据: mc-runs/hp-m1 MODLOG v2 round 2、v3 round 2；mc-runs/hlm-m1 m5 ITERATIONS round 1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-016
- date: 2026-10-22
- game: minecraft
- role: builder
- 现象: 鸟瞰只拍到天空和雾、远处只有光秃的柱子；改完室内后截图还是旧样子；远跳后连拍 12 张都是第一张。
- 原因: 客户端重新生成网格很慢（方块 30-60 s，display 实体立即出现），远处区块还没渲染。
- 做法: 远跳后至少等 12 s；大量改方块后等 30 s 以上；远景最后拍并加长等待。
- 证据: mc-runs/hp-m1 MODLOG v2 round 3、v3 round 2；mc-runs/hlm-m1 MODLOG（screenshots）
- 可信度: verified repeatedly
- status: confirmed

### minecraft-022
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: 用命令生成的 block_display 全是空气(看不见),命令也没报错。
- 原因: 26.3 的 block_state 要写 {id:"minecraft:x",properties:{k:"v"}};写成 {Name:"minecraft:x"} 会被读成空气。
- 做法: summon block_display 时一律用 id / properties;生成后用 data get entity @e[tag=..,limit=1] block_state 检查一次不是 minecraft:air。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

### minecraft-023
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: 用固定 UUID(名字哈希)生成的人物,第二次游览时有的出现、有的没有。
- 原因: 上一次游览留在已卸载区块里的同 UUID 实体和新生成的撞了 UUID,新的被丢掉;kill 命令只杀得到已加载的实体。
- 做法: 每次生成都用随机 UUID(表里记住 id 到 UUID);游览开始先 forceload 戏用到的区块再 kill;人物 tag 统一方便清理。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

### minecraft-024
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: 想要带皮肤、能摆姿势的人形:自己拼 block_display 太费劲,换装也难。
- 原因: 26.3 有原版 minecraft:mannequin 实体,profile:{name:"Steve"} 能联网取默认皮肤。
- 做法: 用 mannequin + equipment 里染色皮革头盔/胸甲/护腿/靴子换装(dyed_color 整数 RGB),pose 用 crouching(坐)、swimming(倒地),immovable:1b、hide_description:1b、CustomName 做名牌;走动用 Java 里每 tick teleportTo。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

### minecraft-025
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: Glowing 的绿色描边透过墙壁和山体能从外面看到,俯拍岛上出现一团绿点。
- 原因: 发光描边不被方块遮挡。
- 做法: 描边只在镜头进餐厅那几章打开(data merge Glowing:1b),其他章节、静态截图前关掉。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

### minecraft-026
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: 共享沙箱的 2-4 号位直接 mc-run 时画面是 Mesa llvmpipe(软件渲染),很卡,截图总是旧的一帧。
- 原因: 非 1 号位的 Xvfb 屏没有走 GPU;mc-run 里 VGL=1 才会加 vglrun -d egl;另外 lab-display.sh N up 要先开。
- 做法: 导出 VGL=1 MC_N=N DISPLAY=:104+N 再启动;日志里应是 NVIDIA L40S;每次 mc-run 都新建世界,mod 里的维度要重新 /build;docker-rt 的 exec 流配额(8)是全服务器共享的,收到 EXEC_STREAM_QUOTA_EXCEEDED 就等几秒重试。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

### minecraft-027
- date: 2026-10-26
- game: minecraft
- role: builder
- 现象: 光方块摆好了房间还是黑的;循环里的 mc-shot 把后面的循环输入吃光。
- 原因: 建造时区块还没算过光(同旧经验 minecraft-008);ffmpeg 会读标准输入。
- 做法: 把光方块位置记下来,拍摄/游览前整体换成空气、40 tick 后再放回(/soldier relight);循环里每条命令都写 </dev/null;传送后等 25 秒再截图,第二张才可靠。
- 证据: adaptation-3 m1 第 1 轮 2026-10-26
- 可信度: tried once
- status: candidate

## 试玩

### minecraft-017
- date: 2026-10-21
- game: minecraft
- role: playtester
- 现象: 第一次补录的试玩录像是静音的。
- 原因: 游戏启动时没有 PulseAudio socket 的路径（XDG_RUNTIME_DIR），OpenAL 打不开声音设备。
- 做法: `mc-run` 现在总是设置它；每段录像录完用 `ffmpeg -af volumedetect` 查有没有声音再交。
- 证据: skills/gameanything/references/pitfalls.md（2026-10-21）；adaptation m1
- 可信度: verified repeatedly
- status: confirmed

### minecraft-018
- date: 2026-10-22
- game: minecraft
- role: playtester
- 现象: 瞬移落脚点再原地横扫的录像，镜头贴墙、钻进树叶、字幕串台。
- 原因: 瞬移和横扫不看周围的方块。
- 做法: 用 mod 里的游览命令：每处一个取景点（从机位往后、往上一点起步），三次缓动移动再停留；两点之间按地表高度抬成弧线，抬升太大或进室内就直接切；沿路每 2 tick 清掉镜头前的树叶；字幕按时间发。
- 证据: skills/gameanything/references/pitfalls.md（2026-10-22）；mc-runs/hlm-m1 MODLOG（Tour command、Glide fix）
- 可信度: verified repeatedly
- status: confirmed

### minecraft-019
- date: 2026-10-22
- game: minecraft
- role: playtester
- 现象: 她以为剧情是另外加的地方、拉长了时长，问为什么不在已做好的景点里发生。
- 原因: 第 3 版录像先游完全部地点，再在片尾单独放 4 段戏。
- 做法: 游览按地点走，走到哪处就在停留时演那里的戏（有戏的地方停久一点），不集中放片尾。
- 证据: adaptation e_20261022T171844_3a5a 的备注；adaptation m4 方案
- 可信度: verified repeatedly
- status: confirmed

### minecraft-020
- date: 2026-10-22
- game: minecraft
- role: playtester
- 现象: 截图里有「Saved screenshot as …」聊天字、飘着的掉落物、夜里加雨的天气。
- 原因: 聊天行停留约 10 s；覆盖植物时掉出物品；长时间运行后时间和天气自己走了。
- 做法: 拍前清掉 item 实体，固定时间和天气（advance_time / advance_weather 关），两张截图之间等 8 s 以上；结束后恢复规则。
- 证据: mc-runs/hlm-m1 MODLOG round 5、Tour command；mc-runs/hp-m1 MODLOG v4 round 2
- 可信度: verified repeatedly
- status: confirmed

### minecraft-021
- date: 2026-10-22
- game: minecraft
- role: playtester
- 现象: 拍别处的截图时触发了旁边的戏；海格小屋里牙牙跑向镜头而不是玩家该坐的位置。
- 原因: 剧情按玩家位置触发，旁观模式的镜头也算玩家。
- 做法: 拍景点时排除旁观者，或在剧情里区分 spectator；要验证「走进去会开始」就用真的生存玩家走一遍（`mc act move_to`，门要先 `open_block`）。
- 证据: mc-runs/hlm-m1 m3 ITERATIONS round 1 第 6 条；mc-runs/hp-m1 MODLOG v4 round 1-2
- 可信度: verified repeatedly
- status: confirmed

## macOS（2026-10-29 实机）

### minecraft-028
- date: 2026-10-29
- game: minecraft
- role: builder
- 现象: macOS 上用 Fabric 安装器装好加载器后，启动器里没有 Fabric 配置。
- 原因: 启动器开着时运行安装器，启动器退出时用内存里的 launcher_profiles.json 盖掉了新配置。
- 做法: 先关启动器再跑 `java -jar fabric-installer.jar client -mcversion <版本> -dir <.minecraft>`；已经开着就重启启动器。Fabric API 从 maven.fabricmc.net 下到 mods/。启动器登录要她自己做（不输她的密码）。
- 证据: native-test MacCraft 测试
- 可信度: tried once
- status: candidate

### minecraft-029
- date: 2026-10-29
- game: minecraft
- role: builder
- 现象: Minecraft 26.x 的 Fabric mod 怎么在 Mac 上编译。
- 原因: 官方 example 模板要 Java 25（release = 25）；Homebrew 的 JDK 在 macOS 14 要装 Xcode。
- 做法: Adoptium Temurin 25 的 tar.gz 解到 ~/.local/jdk，JAVA_HOME 指向它跑 `./gradlew build`；装 build/libs 里不带 -sources 的 jar（install 会拒绝 -sources.jar）。gradlew 会下载并运行外部代码，要她同意。
- 证据: native-test MacCraft 测试（26.3 + Fabric 0.20.1）
- 可信度: tried once
- status: candidate

### minecraft-030
- date: 2026-10-29
- game: minecraft
- role: playtester
- 现象: 从启动器开的 Minecraft，`native shot / drive` 拒绝（不是 GameAnything 开的）。
- 原因: Minecraft 没有能开指定配置的启动链接，只能在启动器里点 Play；改过的版本会弹「安全功能可能不支持」要确认；第一次进游戏有无障碍提示。
- 做法: 按规矩 m2w 不操作；要截图 / 点击就用桌面操控工具；进单人世界后用聊天行和 logs/latest.log 核对 mod 效果。
- 证据: native-test MacCraft 测试
- 可信度: tried once
- status: candidate

### minecraft-031
- date: 2026-10-29
- game: minecraft
- role: playtester
- 现象: 关掉 Minecraft 后启动器显示「游戏崩溃 Exit code: 143」。
- 原因: 143 = 128 + 15（SIGTERM）：关 JVM 游戏发的是 SIGTERM，启动器把非正常退出都报成崩溃。
- 做法: 不是崩溃：没有 crash-reports，latest.log 最后是 Stopping server / Saving players。要跟她说清楚；以后可以改成让游戏从菜单退出。
- 证据: native-test MacCraft 测试
- 可信度: tried once
- status: candidate

### minecraft-032
- date: 2026-10-30
- game: minecraft
- role: builder
- 现象: Mac 上 `native launch` 打不开 Minecraft（「请她自己打开启动器」），新用户每次都要自己开启动器、选 Fabric、点 PLAY；`close` 用 SIGTERM 关，下次开启动器先弹崩溃报告（Exit code 143），挡在 PLAY 前面。
- 原因: 启动器没有能指定配置启动的链接；关 JVM 发的是 SIGTERM，启动器把它算成崩溃。
- 做法: Mac 上 `launch` 用 `open -g` 打开 /Applications/Minecraft.app，after_launch 在后台：先看 launcher_profiles.json 里最近用过（lastUsed）的配置是不是 Fabric（不是就停下，让她自己选），等启动器窗口，把它拉到前面（它只在前台才画页面），8 秒后真实点击 PLAY（窗口宽高的 0.54 / 0.763），等游戏的 java 进程出现再记下来。关：先发 macOS 的退出请求（NSRunningApplication terminate），游戏写「Stopping!」约 2 秒退出，不再弹崩溃报告；SIGTERM 只作后备。
- 证据: fresh_mac_user 2026-10-30：两次 launch 14–15 秒到游戏进程，[M2W-smoke] loaded，close 后启动器没有崩溃框
- 可信度: tried once
- status: candidate
