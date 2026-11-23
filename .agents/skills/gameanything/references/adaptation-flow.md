# 改编项目的流程（`kind: adaptation`，2026-10-21 起）

> 2026-10-26 起 agent 按状态机做：`gameanything flow next` / `gameanything flow check`，文档是 `core.md` + `modes/adaptation.md` + `steps/adaptation/<步骤>.md`。这份长文件留作参考。

用户把喜欢的作品（小说、电影、剧集、动漫）做进游戏（第一个目标：红楼梦·大观园，Minecraft）。和回忆项目的区别：素材是**作品**，不是用户的照片；没有「真人」，但有版权。
依据：`hlm/spike/REPORT.md` 里对第十七回、第二十七回的抽取试验（189 条引文全部逐字核对通过；约 12% 的元素是发明的）。

## 0. 版权先问清楚（先于一切）
- 只有**公有领域底本**可以逐字引用和放进提示词（例如 Project Gutenberg 的《紅樓夢》）。记下 `source_license`。
- 现代白话译本、注释本、影视剧本、动漫台词、字幕：用户上传时**先警告**，不进引文栏位，不整段放进任何提示词；要用的话只保留极短摘录并改写。
- 不下载受版权保护的媒体。用户自己上传的文件，只在本机处理；要发给模型之前走 `permission` 卡（发什么、发给谁）。
- 用户说清楚「底本是哪一版」（译本也算），写进 `config/project.yaml`（`source`、`source_license`）。

## 0b. 一律用简体中文（用户 2026-10-21 要求：「繁体字我看不懂」）
- 作品是繁体的，**自动转成简体**再做一切事情：`gameanything ingest` 在改编项目里会自动转换文档（`1_ingest/.../text.txt` 是简体，pack.yaml 里标 `simplified: true`；原文件原样留在 `0_inbox`）。
  没走 ingest 的文本用 `gameanything text simplify <文件> -o <输出>`；YAML 用 `--yaml`（只转值，不动键和 id）。
- 抽取、引文、场景表、角色、方案、卡片、对话，全部用简体。引文的「逐字」校验对照的是**转换后的简体文本**。
- 告诉用户一句：原文是繁体，已转成简体显示，原文件保留着。

## 1. 步骤
1. **收作品**：先问清是哪种作品，再按类型收：
   - **文字作品（小说等）**：txt / md / pdf / **epub** 都能直接上传（epub 按章拆成一页一章，有 DRM 加密的读不出，请用户换无加密版本或复制成 txt；只收用户自己合法拥有的文件，不替用户下载电子书）。让用户选章节（先少量，例如两章）。预处理：繁体转简体（见 0b）、异体字归一（只用于比对）、清掉误插字符、标记缺字（□）、去掉硬折行。
   - **电影 / 剧集 / 动漫**：用户自己提供的字幕文件、剧本、设定资料、截图或剧照，以及用户自己的描述（「第几集第几分钟的那条街」）。不下载视频或任何媒体。
     出处用「第几集 / 时间点」代替页码；截图只当参考（和地标参考图一样：不放进游戏、不提交、不公开），要发给模型看图之前走 `permission` 卡。
     受版权保护的作品：台词不整段引用，只记很短的摘录或改写，并标出处。
2. **抽取**（按章，输出 YAML，放 `3_remember/`）：场景（地点、发生什么、在场人物、时间 / 季节 / 天气、1–2 条**逐字**引文）；地点（原文怎么描写它、原文**没**描写什么）；人物；可建造元素（建筑 / 植物 / 水 / 路），每个标 `grounding: explicit | implied | invented` 并带 `quote_ids`。引文必须通过「去空白后的子串校验」，不通过就丢弃，不许自己「修正」引文。
   网页上「场景」「角色」两页读的是 `3_remember/adaptation.yaml`（只由你写；用户的选择在 `feedback/adaptation_review.yaml`，键 `scene:<id>` / `place:<id>` / `char:<id>`，choice keep / skip / change + note；用户的 note 也会原话进对话）。格式：
   ```yaml
   work: {title: 红楼梦, type: novel|film|series|anime, source: Project Gutenberg #24264, source_license: public domain, units: [第十七回, 第二十七回]}
   scenes:     [{id: s17-02, unit: 第十七回, title: 园门, place: 大觀園園門, what: ..., characters: [賈政, 寶玉], time: ..., quotes: [{text: 逐字引文, where: 第十七回}]}]
   places:     [{id: p1, name: 大觀園園門, aliases: [園門], described: [逐字引文], not_described: [門前廣場, 圍牆高度],
                 build: [{name: 園門五間桶瓦泥鰍脊, kind: structure|plant|water|path|decor, grounding: explicit|implied|invented, quote: 逐字引文, note: ...}]}]
   characters: [{name: 寶玉, aliases: [], role: ..., looks: [{text, where}], lines: [{text, where}], image: 2_perceive/refs/x.png}]
   ```
   （也接受抽取试验的写法：`buildables` 单独列出、带 `place` 和 `status: grounded|invented`。）用户点了「确认场景、地点和角色」才进文字方案。确认之前先发一张 `task` 卡，请用户把「场景」和「角色」两页都看一遍（角色没有单独的确认按钮，和场景一起确认）。
   隐私账本 `privacy_ledger.yaml` 必须是 `requests:` 下的列表（和回忆项目一样），不要写成顶层列表。
3. **跨章地点登记表**（别名、后文正名、匾名）：先建表再抽取，最后自动检查「提到了但没抽」。否则同一地方会被当成两个。
4. **向用户提问，不悄悄发明**：按影响排序（全园比例、各处方位、游戏里没有的植物 / 动物怎么对应、季节、是否采用后文名字）；每题附原文证据和默认选项（默认：按游览路线排成环形，水系贯穿）。
5. **文字方案**：`world_plan.yaml`（场景 → 地点 → 要建什么、哪些是原文有的、哪些是发明的、每一版做哪几处）。发明的内容单独列出，在地图里也要看得见（告示牌或元数据）。发明时优先借同一本书别处的描写，其次才是风格化发明，且不得和原文冲突（例如原文写「一株花木也无」的院子不能种树）。用户确认后才进下一步。
   再写 `5_build/<这一版>/plan.yaml` 的 `items:`（每条 `n`、`title`、`title_en`、`desc`、`desc_en`，可选 `quote`、`quote_en` 放原文引文）。「方案」页只显示这份清单，没写就是空的：写好之前不要请她去看方案，也不要说「方案写好了」。
6. **预览图**：见 `memory-project-flow.md` 第 5 步的「预览图」：许可卡 → 每处 1–2 张游戏风格效果图 → 候选卡让用户选 / 提改 → 选定的进构建包 `targets/`。
7. **构建**：`go` 卡、构建、独立回放和评审、交付（`gameanything build deliver` / 发 `result` 卡前 `gameanything build check`）、每轮读经验和开发状态并更新 `5_build/STATUS.yaml`（`dev-status.md`、`lessons.md`），和回忆项目一样（`memory-project-flow.md` 第 7 步，先看 `build_mode`：`lab` 服务器沙箱 / `native` 用户自己的游戏，native 不碰 docker）。第一批只在 **Minecraft** 里做（实验室见 `/opt/docker-rt/GUIDE.md` 10a）；其他游戏接入后再开放。
8. **用户的意见、带回家、备份**：同回忆项目。

## 2. 对话里要说清楚的
- 抽取给的是「路线、命名和少量结构细节」，不是设计图：很多尺寸、屋顶、材质原文没写，必须靠发明或问用户。每一版开始前，把「原文有的 / 发明的」比例告诉用户。
- 游戏里没有的东西（杏花、海棠、鹤……）怎么对应，要先问。
- 引文一律逐字；任何台词都要能指回出处（文字作品：章节和原文位置；影视 / 动漫：第几集、时间点）。
