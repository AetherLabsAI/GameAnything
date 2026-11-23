# 卡片：每种情况用哪种

| 情况 | 卡片 | 例子 |
|---|---|---|
| 要发内容给模型之前 | `permission` | 看图之前："会发：缩小的照片……不会发：原图、视频" |
| 有事实只有用户知道 | `questions`（可以只答一部分） | "穿蓝紫碎花裙的两位是谁？" |
| 有几种做法要用户挑 | `options`（写明代价，标出建议，可以多选） | 对话改法 A–E；领证地图留不留 |
| 有声音、图片要用户试听试看 | `candidates`（可以都不要） | 两首背景音乐；掌声 |
| 你复述了理解，要用户确认 | `understanding`（每条可以直接改） | 设计选择的理解；功能的需求单 |
| 要用户在工作区里做一件事 | `task`（"去做 / 做好了 / 稍后"）；`open:` 是这个项目有的页面：回忆 `#home` `#board` `#people`(`/tag`)，改编 `#scenes` `#characters`，功能 `#spec`，玩法 `#mechanics` `#content` `#balance`，都有 `#gather` `#plan` `#play` `#status` `#keep`（别的页面 `chat card` 会拒绝） | 标记照片里的人；确认形象；看录像 |
| `options` 卡标 `recommended: true` 的项 | 页面上默认已勾好（标题里可以写「默认已勾好」） | 先改编哪几章 |
| 一版做好了 | `result`（截图、统计、"打开试玩页"）；发之前 `gameanything build check --project P --m <m>` 必须 OK，没 OK 先 `gameanything build deliver` 修好；统计行用 `gameanything status card --project P --m <m>` 从 `5_build/STATUS.yaml` 生成（做到 / 部分 / 没做 / 回归 / 已知问题 / 复查），不凭记忆写 | 第 2 版的成果 |
| 下一版要开工 | `go`（做什么、用哪个构建模型（只读，项目的「构建」）、多久、多少钱） | 整天改进的 14 条 |
| 要付费生成（图、3D、声音） | `permission`（`to` 写服务名，如 fal.ai / Meshy / OpenRouter；`files` 列出会发的图，通配符）+ 生成用的 `go`（`estimate` 和 `cost_usd` 抄 `gameanything gen estimate` 的输出，`max_images`）；两张都点了才 `gameanything gen request --tool <adapter>:<cap> --inputs …`。后台会核对：服务名对得上、每张图都在 `files` 里、估价不超过开工卡 | 预览图、Meshy 3D 菜 |
| 正在做 | `progress`（同一个 key 原地更新） | 构建 → 回放 → 审阅 → 备份 |
| 后台构建在跑 | 不用自己发：agentd 自己发一张 `live-<m>` 进度卡（gameanything 署名），从构建 agent 的工具调用看出它现在在做什么、开发状态的条目、试玩轮次、最新截图，卡住 / 用量到上限 / 结束时还会在对话里说一行（live.py）。开工后它还会问一次她要不要看游戏的实时画面（`permission` 卡，key `live-view-<m>`，同意后在「工作台」里只能看、不能点）。开 lab / 本机构建时 agentd 还会发一张 `live-view-<m>` 许可卡（要不要在「工作台」里看游戏实时画面 / 游戏窗口截图），她的回答由后台自己处理，你不用管也不要替她回答。不要发 key 以 `live-` 开头的卡；她问「在干嘛」时先看这张卡和「开发状态」页 | 「后台构建 · 现在：在改剧情镜头的代码 Story.java」 |
| 本机模式要开她的游戏测试 | 不用自己发：`gameanything native launch --project P` 会发 `options` 卡（key `native-launch`：现在可以 / 等我说 / 今晚 HH:MM 后），只认她在网页上点的回答；她选了「我没在用电脑时」/「只在这个时间段」/「随时可以」时不发卡 | 「要开游戏测一下，现在可以吗？」 |

**卡片的 key**：同一个 key 再发一张，旧卡留在原处变成只读（标「已更新，见下方」，旧回答还在），新卡出现在对话最下面、等她回答；旧卡上的回答不算新卡的回答。所以新一轮的 `questions` / `options` 卡要在 key 里带上这一版（如 `plan-questions-m4`、`plan-options-m4`），不要沿用上一版的 key；只有想替换一张还没答的卡（改错字、补一项）时才用同一个 key。

用户随时可能直接说一句话（补充、纠正、新要求），这是最常见的。先回应，再决定要不要发卡片。新要求进 `5_build/STATUS.yaml` 的 items（`gameanything status set-item --text …`），还没处理的话进 open_feedback（`gameanything status feedback --event <事件 id> --add-event`），处理 / 回答后改成 handled / answered（dev-status.md）。

## 卡片里的图片必须让用户真的看得到（硬规则，用户 2026-10-17 和 2026-10-21 两次遇到「卡片里看不到图」）
- 网页能给工作文件夹（`1_ingest/`、`2_perceive/`、`3_remember/`、`4_design/`、`5_build/`、`feedback/`）下面任何子文件夹里的图片/视频/声音（`layout.media_file`）；不给 `0_inbox/`、`config/`、`conversation/` 和 `.` 开头的文件夹。卡片里的 `/media/…`、`/art/…`、`/build/…` 链接发卡时会检查，文件不存在或网页打不开就拒绝发卡并说明原因。视频关键画面和人物截图在 `2_perceive/keyframes/`、`2_perceive/people/`（`gameanything visuals`）。
  卡片里的图**必须**放在其中之一，`url` 写成 `/media/<项目内相对路径>`（例如 `/media/4_design/targets/g01_A.png`）。放在别处的图，网页一律 404。
- 发卡**之前**自己验证：对每个 `url` 跑 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<端口>/media/...`，要 200。端口看 `gameanything project list` / 用户正在用的那个网页服务；
  网页服务当前打开的必须是这个项目（否则 `/media` 指向别的项目）。拿不到 200 就不要发卡，先修。
- 发完卡在对话里说一句「图在卡片里，点一下可以放大」；用户说看不到，先自己 curl 一遍再回答，不要猜。
- **`options` 卡不显示图片**（2026-10-23，用户在 Sims 4 项目里问「图呢？？」：飞车 3D 预览放在选项卡的 `image` 字段里，页面上只有文字）。所有预览图（Meshy 的 3D 预览、候选模组截图、建模参考图）一律用会显示图片的卡发：`result` 或 `candidates`；要让用户做选择，再另发一张 `options`/`permission` 卡，文字里写「图在上一张卡」。**预览图必须展示给用户，用户没看到图就不能往下做。**

