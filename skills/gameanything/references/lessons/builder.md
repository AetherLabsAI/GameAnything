# builder：经验（和游戏无关）

格式和规则见 skills/gameanything/references/lessons.md。只写对每个游戏都成立的做法；某个游戏的写进它游戏包里的 LESSONS.md。
2026-10-25 从过去的项目记录整理出的第一批：历史里明确验证过的标 confirmed，其余 candidate。

## 实验室和进程

### builder-001
- date: 2026-10-24
- game: any
- role: builder
- 现象: 在游戏沙盒里用 ffmpeg 编码最后的视频，内存不够，容器直接挂掉，同一沙盒里的游戏也一起没了。
- 原因: 沙盒内存配额小，编码很吃内存。
- 做法: 沙盒里只录原始素材（mkv / 帧），拷到宿主机再剪辑、编码。
- 证据: feature（Overcooked 2）m3 hkfood RESULT.md「Cleanup」「Friction」；2026-10-24 wc-cities 沙盒事故；valheim-native-linux 测试里没在沙盒编码
- 可信度: verified repeatedly
- status: confirmed

### builder-002
- date: 2026-10-22
- game: any
- role: builder
- 现象: 等游戏启动、编译、重建 + 截图的命令跑到一半被切断，回显晚到，下一轮在 jar 还没好时就开始了。
- 原因: 实验室的 `docker exec` 有 120 s 上限。
- 做法: 长步骤用 `setsid nohup …` 放后台看日志，或用实验室自带的分段等待工具（`vh-game wait`、`cs` 等）；不要 `docker exec -i`；开新一轮前确认产物已更新、没有残留的 `.tmp`。超过一两分钟的等待不要挡住对用户的回复。
- 证据: mc-runs hp-m1 MODLOG v2 round 1-2、round 4；modlab cities / valheim CLAUDE.md
- 可信度: verified repeatedly
- status: confirmed

### builder-003
- date: 2026-10-24
- game: any
- role: builder
- 现象: `pkill -f` / `pgrep -f` 匹配到了自己的 shell（exit 144），或误杀别的实验室的游戏、Steam、网页服务。
- 原因: `-f` 匹配整条命令行，包括当前这条命令本身。
- 做法: 先单独一次调用列出 PID（`ps -eo pid,comm,args | awk`，排除 bash / sh / awk），再 kill 这些确切的数字；游戏只用实验室工具起停（它们记着自己的 PID）。
- 证据: modlab valheim CLAUDE.md「Rules」；valheim-native-linux 16-cleanup-procs；重启网页时的多次误杀
- 可信度: verified repeatedly
- status: confirmed

### builder-004
- date: 2026-10-24
- game: any
- role: builder
- 现象: 后台沙盒在跑游戏时，她在自己电脑上登录同一个 Steam 账号，后台的游戏被顶掉；反过来沙盒开 Steam 也会踢掉她正在玩的会话。
- 原因: 同一 Steam 账号同时只能有一个游戏会话。
- 做法: 文件、构建先准备好不启动；开 Steam / 游戏前先问她，一次同意只开一次；开工时提醒她别登录，收工关掉游戏和 Steam 后明确告诉她可以登录了。
- 证据: feature 对话 2026-10-24 05:49、08:17、21:24；valheim-native-linux 13-launch-r2（one yes = one launch）
- 可信度: verified repeatedly
- status: confirmed

### builder-005
- date: 2026-10-22
- game: any
- role: builder
- 现象: 宿主机上改了源码马上在沙盒里编译，编的还是旧版本；或报 Permission denied。
- 原因: 实验室共享盘是 JuiceFS，宿主机写入要 1–4 分钟才在容器里可见；宿主机建的文件属 root，容器用户写不了。
- 做法: 在容器里编辑，或用 tar / base64 推进去；编译前在容器里 `sha256sum` / grep 确认看到的是新内容；宿主机建的目录 `chmod -R a+rwX`；正在跑的脚本不要改。
- 证据: gameplay m1、m2 MODLOG；mc-runs hlm-m1 MODLOG（LAB FACT workflow）；modlab cities CLAUDE.md §0
- 可信度: verified repeatedly
- status: confirmed

### builder-006
- date: 2026-10-24
- game: any
- role: builder
- 现象: 在她的存档里测功能，游戏时钟被跑了约 9 个游戏小时；或调试时拨钟让存档里的人物状态、剧情往前走。
- 原因: 测试期间游戏一直在走（有的游戏还会自动加速）；退出时保存就把变化写进存档。
- 做法: 不拨游戏时钟；不用时暂停游戏；用复制的测试存档；退出选不保存，测完对比存档和备份。
- 证据: sims4-flying-car round2、round4 ITERATIONS.md；sims4-flying-car 对话（测试后时钟被跑了约 9 小时）
- 可信度: verified repeatedly
- status: confirmed

### builder-007
- date: 2026-10-23
- game: any
- role: builder
- 现象: 构建 agent 用 `gameanything chat claim` 发进度卡，把驻守会话踢掉，她的消息没人回。
- 原因: 构建 agent 照抄了驻守会话的命令。
- 做法: 构建 / 评审不运行 `gameanything chat claim / say / card / progress`，只向协调者报告；进度由驻守会话发。
- 证据: 2026-10-23 驻守会话被踢掉的事故
- 可信度: tried once
- status: confirmed

### builder-008
- date: 2026-10-17
- game: any
- role: builder
- 现象: 构建 agent 跑满时间上限被停，最后一条消息是空的，结果和花费都没记下。
- 原因: 到上限前没有收尾。
- 做法: 离时间上限至少 30 分钟时写好 RESULT / NOTES / DEVIATIONS；源码打包成能离线重建的样子。
- 证据: stardew 回忆项目 m3 REVIEW.md（agent_timeout）
- 可信度: tried once
- status: confirmed

### builder-009
- date: 2026-10-22
- game: any
- role: builder
- 现象: 一个问题来回改了几十次（同一个机位一直被柱子、树挡住）。
- 原因: 只在同一个方向上改参数，没有换思路。
- 做法: 同一种失败重复 3 次就停下，写下已知原因，换方向（例如拆掉挡路的东西，而不是继续挪镜头）。
- 证据: mc-runs hlm-m1 MODLOG（Camera work is most of the time）；实验室 CLAUDE.md 的 circuit breaker
- 可信度: tried once
- status: candidate

## 交付

### builder-010
- date: 2026-10-24
- game: any
- role: builder
- 现象: 只交了 `5_build/<m>/play/` 文件夹，试玩页不列出这一版，或打开报错；网页的场景 / 方案 / 预览页也是空的。
- 原因: 试玩页的版本来自 world_plan.yaml 的 milestones，章节来自 play.yaml。
- 做法: 报告做完前最后一步 `gameanything build deliver --project P --m <m> --name …`；发 result 卡前 `gameanything build check --project P --m <m>` 必须 OK；交付前打开试玩页确认这一版在。
- 证据: feature m3 / m3b 和 sims4-flying-car round2 的事故（pitfalls.md 2026-10-24）
- 可信度: verified repeatedly
- status: confirmed

### builder-011
- date: 2026-10-24
- game: any
- role: builder
- 现象: 交付录像开头已经是关卡后段，看不出是新内容，被要求重录。
- 原因: 把几段测试拼起来，开场被剪掉了。
- 做法: 先开录再进关卡，一整局连续录，从加载、开场标题录起；剪掉的冻结帧、加速都写在 README 里，「没有摆拍、没有拼接」要属实；录完看第一帧。
- 证据: feature 对话 2026-10-24 03:48；feature m3 README「Editing (honest)」
- 可信度: verified repeatedly
- status: confirmed

### builder-012
- date: 2026-10-16
- game: any
- role: builder
- 现象: 构建报告写「做到了」，独立重放却对不上（回放走不完、声音没人听过、动作只看了有没有）。
- 原因: 用推断或数值代替了实测；agent 只能量音量、看不出好不好看。
- 做法: 每条结论附证据（截图、state、日志）；没看到 / 没听到就写「没验证」；结果卡最后一条列出没验证的项，并请她自己看 / 听；会改存档或和简报不同的做法写进 DEVIATIONS。
- 证据: stardew 回忆项目 m3 / improve REVIEW.md；gameplay m3、m4 结果卡
- 可信度: verified repeatedly
- status: confirmed

### builder-013
- date: 2026-10-23
- game: any
- role: builder
- 现象: 交付后又补修了游戏，但试玩页上的录像还是修之前录的。
- 原因: 小改只改了 mod，没重录。
- 做法: 结果卡里写明「录像是修之前录的」，下一版重录；或者小改也重录关键片段。
- 证据: gameplay m4 结果卡
- 可信度: tried once
- status: candidate

### builder-014
- date: 2026-10-25
- game: any
- role: builder
- 现象: 游戏里的对话框标题、台词用了构建记录里的内部代号，她问为什么叫这个名字。
- 原因: 内部角色名直接进了用户可见文字。
- 做法: 交付前全文搜一遍用户可见的文字（对话框、台词、通知、字幕），只用她的叫法。
- 证据: sims4-flying-car round5b 后的反馈、第 17 版开工卡
- 可信度: tried once
- status: candidate

## 图和素材

### builder-015
- date: 2026-10-17
- game: any
- role: builder
- 现象: 画面被说粗糙、人物丑；构建 agent 一张目标图都没有就直接搭，评审也只对着文字打分。
- 原因: 没有「每个地方应该长什么样」的目标图，评审没拿照片和目标图对照。
- 做法: 先出预览 / 目标图请她挑，评审每轮拿她选的图对比截图；公开地标先问要不要上网找参考图（只做参照，记下来源和许可）。
- 证据: minecraft 回忆项目 m1 → m2 的反馈
- 可信度: verified repeatedly
- status: confirmed

### builder-016
- date: 2026-10-22
- game: any
- role: builder
- 现象: 生图给不戴眼镜的人画上眼镜；3 个人画成 5 个；道具画错（花锄成了锤子）；表情不对。
- 原因: 模型会自己补常见特征，提示词里没写死人数、道具和表情。
- 做法: 提示词只写照片里确有的特征，写明人数、手里拿什么、表情；发卡前自己逐张看，和原照片并排检查；重画只改她指出的部分。
- 证据: pitfalls.md；minecraft 回忆项目 m1；adaptation、adaptation-2 角色图
- 可信度: verified repeatedly
- status: confirmed

### builder-017
- date: 2026-10-23
- game: any
- role: builder
- 现象: 预览图她看不到：一次放进了 options 卡（不显示图），一次 result 卡格式错没发出去，却说已发。
- 原因: 只有 result / candidates 卡显示图；没检查发送结果。
- 做法: 预览图一律走 result / candidates 卡；发卡后看返回结果并 curl 图片地址，确认后再说已发。
- 证据: sims4-flying-car 对话（Meshy 预览两次）；pitfalls.md 2026-10-23
- 可信度: verified repeatedly
- status: confirmed

### builder-018
- date: 2026-10-17
- game: any
- role: builder
- 现象: 换了图，网页上还是旧图。
- 原因: 新图和旧图同一个地址，网页用了缓存。
- 做法: 每次改图换文件名或带 `?v=` 版本号；卡里的图要能点开看大图。
- 证据: minecraft 回忆项目 m1 的反馈
- 可信度: tried once
- status: confirmed

### builder-019
- date: 2026-10-24
- game: any
- role: builder
- 现象: 要俯视角的菜品，用俯视参考图去生成 3D，出来一个不规则的白碗；预览卡是固定侧面，她看不出是不是俯视。
- 原因: 图生 3D 对俯视参考图效果差；预览角度和游戏镜头不同。
- 做法: 用斜视角参考图生成；预览时说明角度，最好补一张游戏镜头角度的渲染；透明杯碗、冰块这类大概率做不好，先说。
- 证据: feature 对话 2026-10-24 05:17-05:47
- 可信度: tried once
- status: confirmed

### builder-020
- date: 2026-10-21
- game: any
- role: builder
- 现象: 用户给的小说文本来自免费下载站，不是授权版本。
- 原因: 不能逐字抽取或引用来源不明的受版权保护文本。
- 做法: 不用这份文件；场景和人物用自己的话转述，每条标「书里大致写过 / 推测」；游戏台词自己写；生图提示词不写真人演员。
- 证据: adaptation-2 m1 开工前的决定；adaptation-2 m4 plan.yaml 头注
- 可信度: tried once
- status: confirmed

### builder-021
- date: 2026-10-23
- game: any
- role: builder
- 现象: 外部 mod 的下载页被人机验证拦住；网页上传不收 .rar。
- 原因: 人机验证不能绕过；上传入口只收常见格式。
- 做法: 给直链请她自己下载，再去她的下载文件夹找；先检查压缩包内容（只含资源、没有脚本才装）；第三方 mod 只私下用，不发布。
- 证据: sims4-flying-car round4 前的 mod 下载
- 可信度: tried once
- status: confirmed

### builder-022
- date: 2026-10-23
- game: any
- role: builder
- 现象: 题材里的真实规则凭印象写错了（审稿分数用了 10 分制，实际是 6 分制）。
- 原因: 没查官方说明。
- 做法: 真实世界的规则（评分制、流程、术语）先查官方说明再写；换算时保持原来的难度，用对照组验证。
- 证据: gameplay 对话 2026-10-23 → m3 第 1 轮
- 可信度: tried once
- status: candidate
