# 公开地标的参考图，和开工前的「目标图」

谁读这份：要在游戏里还原真实地点的 agent（任何游戏）。2026-10-17 UCSD 第 1 版的教训：用户只拍了 Geisel 图书馆的正面，
构建 agent 没有别的参考，也没用生图，搭出来认不出来；试玩评审也没拿照片对照。用户说：「这些经典地点可以去用 search 功能先搜参考图，
这个技能也要记下来方便之后复用」。

## 0. 什么时候想到要搜（先问用户，用卡）
用户原话（2026-10-17）：「这个上网搜图可以做成一个 skill 在相关任务 比如图像信息不全 又是公共场景的情况下询问用户是否需要搜索」；
后来又说「多上网搜一些这几个景点的照片」——照片不够时**主动问**，不要等她提。
- 只要一个要还原的地方**照片不够**（只有一个角度、太暗、被人挡住、或者根本没拍），而它是**公共场所**（地标、校园楼、教室、会议厅、
  商场、共享办公室、公园、街景……），就发一张许可卡问她要不要上网搜几张参考图。卡的 **key 以 `websearch` 开头**
  （每个地点一张：`websearch-<地点>`；一张卡问几个地点就用 `websearch-<这一批>`），写明搜哪几个地点、用什么搜索词、只拿来做参照：
  ```yaml
  kind: permission
  key: websearch-geisel
  title: 要不要我上网搜几张 Geisel 图书馆的参考图？
  will_send: ["搜索词：Geisel Library UCSD exterior / aerial（只有这个公共地点的名字）"]
  will_not_send: ["你的照片、名字、家人朋友的信息、你的住址"]
  to: 网页搜索（只搜公开的图片，存在项目里只当参照，不放进游戏）
  en: {title: "Shall I search the web for a few reference pictures of Geisel Library?", will_send: ["Search words: Geisel Library UCSD exterior / aerial (only the public place)"], will_not_send: ["Your photos, names, family and friends, your address"], to: "Web search (public pictures only, kept in the project as references, never in the game)"}
  ```
  也可以用 `options` 卡（同样的 key 前缀，选项 key `yes` = 搜、`no` = 不搜）。只有她在网页上点了同意 / 选了 `yes` 才算。
- 用户也可以直接告诉你地址或名字（比如「实验室在 University Center Lane 的 WeWork」），用它来搜；地址只用来搜那个公共地方的图，
  不写进游戏、不和用户的其他信息放在一起。她在对话里直接说「去搜吧」也要再发一张卡让她点（`gameanything refs fetch` 只认卡）。
- 用户说不要，就只用用户自己的照片。

## 1. 什么能搜，什么不能（搜索词卫生）
- **能搜**：公开的地标和建筑（校园里的标志建筑、博物馆、航母、公园、雕像、街景），只为了看清形状、比例、材质、各个角度。
- **不能搜**：任何人（用户、家人、朋友的照片或信息）、用户的家和私人地点、会暴露用户住址或日常路线的东西。
- **搜索词只写地点本身**：「Geisel Library UCSD exterior」可以；「Alice Geisel Library」「林小雨 毕业照 Geisel」不行。不带人名
  （3_remember/people.yaml、board.yaml、config/vocab.txt 里的名字，她的登录名 / 显示名）、邮箱、文件名或路径，也不带她的事
  （「我们的婚礼」「她的宿舍」）。WebSearch / WebFetch / Codex 的搜索都会把搜索词发到外面，这条每次都要守；
  `gameanything refs fetch` 会拒绝带这些名字的 `--query` / `--place`。
- 网页只拿来看（WebFetch 读页面找图片地址和许可）；**不要用 curl / wget / python 自己下图**。

## 2. 怎么搜、怎么存
1. 用搜索工具（Claude：WebSearch、WebFetch；Codex：自带的 web search）找每个地标 3–6 张：正面、侧面、远景 / 航拍、关键细节
   （比如 Geisel 一层层外伸的楼板和斜柱）。优先维基共享资源、官方网站、有明确来源的图；在原页上看作者和许可。
2. 每张图用一条命令存：
   ```
   gameanything refs fetch --project "$P" --place "Geisel Library" --url <图片本身的网址> --query "<你用的搜索词>" \
       --consent websearch-geisel --page <图所在的网页> --license "CC BY-SA 4.0" --author "<作者>" --side front
   ```
   它先核对许可卡（她点了同意）、搜索词（没有私人名字）、网址（公网 http(s)、真的是图片、不超过 15 MB），再存到
   `2_perceive/landmark_refs/<地点>/web-NN-<hash>.<ext>`，同目录 `sources.yaml` 记下每张的 url、page、query、license、author、side、
   consent（卡的 id）、fetched、sha256。在 agent 运行里它只排队，由后台（agentd）在本机下载（Codex 的沙盒没有网络），一般几秒内
   打印结果；超时会说「已排队」，下好后后台给你留言。看 `gameanything refs status --project "$P"`。
3. 她自己给的地标图也可以放进 `landmark_refs/<地点>/`，在 sources.yaml 里写 `{file: …, source: user}`。
4. `gameanything flow check` 每一步都会查 landmark_refs（`web_refs_consent`；也可以 `gameanything refs check --project "$P"`）：有没登记的图、
   网图没有她同意的 websearch 卡、缺 url / query / license，都算不通过：删掉那张图，或先发卡问她。
5. 这些图**只用来看和当生图参照**：不放进游戏、不放进相册、不公开、不提交到 git；HF 备份可以带上（私有），但注明来源。
   要发给生图模型当参照，许可卡的 will_send 里要写出这些参考图。
6. 和用户自己的照片分开：回忆板、像素画、人物只用用户的照片；参考图只帮着还原建筑的样子。

## 3. 目标图（开工前先给用户看）
（时机：文字方案确认之后；完整步骤见 memory-project-flow.md 第 5 步的「预览图」。）
1. 每个要还原的地方画 1–2 张「游戏风格的效果图」（比如 Minecraft 方块风格、Stardew 像素风），参照 = 用户的照片 + 地标参考图。
   要发给生图模型之前，先发许可卡：写清发哪些照片、哪些参考图、发给谁、大概多少钱。每次调用记进 `privacy_ledger.yaml`。
2. 把目标图发给用户确认（一张 `questions` 或 `candidates` 卡，带图），满意了才进构建包。
3. 构建包里放 `targets/`（目标图）和 `landmark_refs/`，BRIEF 里写明：照着目标图搭，搭完从同一角度截图并排对比。

## 4. 试玩评审要对照
- 试玩评审每一轮都要拿到用户的照片和目标图，问「这一处和照片 / 目标图像不像」，像不像要单独给结论，不像就打回去改。
- 评审输出坏掉（不是 JSON）时要重来，不能当成没有意见。

## 5. 人物
- 人物（皮肤、行走图、头像）只照用户的照片和用户标的框：发型、发色、衣服；不搜网上的任何人。
- 要把照片里的人发给生图模型画皮肤或头像，先发许可卡，说清楚是谁的照片。
