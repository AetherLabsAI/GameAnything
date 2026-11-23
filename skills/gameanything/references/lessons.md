# 经验（lessons）：做过的人留下的做法

谁读这份：构建 agent（builder）、试玩 / 评审 agent（playtester、critic）、协调员（coordinator）、写游戏包的人。
经验是**跨项目**的：「tModLoader 构建报某个错时这样修」「Stardew 回放第一帧总是黑的，等 2 秒再截」。
项目自己的进度不放这里，放 `5_build/STATUS.yaml`（见 dev-status.md）。

## 1. 三层，`gameanything lessons show` 合在一起看
| 层 | 文件 | 写什么 | 进仓库 |
|---|---|---|---|
| 每个游戏 | `gameanything/games/<id>/LESSONS.md`（游戏包里；插件游戏在插件包里；还没有游戏包的游戏先放 `docs/lessons/games/<id>.md`，游戏包做好后搬进去） | 这个游戏的做法，分两节：`## 开发`（builder）和 `## 试玩`（playtester） | 是 |
| 每个角色 | `skills/gameanything/references/lessons/builder.md`、`playtester.md` | 和游戏无关的做法（怎么交付、怎么截图对比、怎么写检查项） | 是 |
| 本机私有 | `<项目列表文件夹>/lessons/<id>.md`（`~/.config/gameanything/lessons/`，Windows `%APPDATA%\gameanything\lessons\`），和游戏无关的写进 `general.md` | 只对这台电脑 / 这个账号成立的（某个路径、某个显卡驱动、这台机器的 Steam 账号） | **否**，永远不提交 |

## 2. 一条经验的格式
一条 = 一个 `### <id>` 小块，下面每行一个 `- 字段: 值`（值可以接着下一行，缩进两格）：

```markdown
### terraria-003
- date: 2026-10-25
- game: terraria
- role: builder
- 现象: `tModLoader.dll` 构建时报 "Could not find a part of the path .../ModSources"
- 原因: 第一次运行 tModLoader 之前没有 ModSources 文件夹
- 做法: 构建前 `mkdir -p "<user>/ModSources"`；或者先让 tModLoader 开一次到主菜单
- 证据: m2 第 1 轮 14:05，client.log 第 212 行
- 可信度: tried once
- status: candidate
```

- `id`：游戏层 `<game>-NNN`，角色层 `<role>-NNN`，本机层 `local-<game>-NNN`；`gameanything lessons add` 自动编号，不要手改。
- `game`：游戏 id（角色层写 `any`）；`role`：`builder` 或 `playtester`。
- `现象`（symptom）、`原因`（cause）、`做法`（fix）：各一两句；`做法` 写成下一个人能照做的步骤。
- `证据`（evidence）：哪一版 / 哪一轮 + 时间或录像帧，能让人回去核对。同一条再遇到一次就多一行证据。
- `可信度`（confidence）：`tried once`（试过一次）或 `verified repeatedly`（多次验证）。
- `status`：`candidate`（agent 刚写的，未审）或 `confirmed`（协调员确认过）。
- 英文字段名（`symptom` / `cause` / `fix` / `evidence` / `confidence`）也认，写的时候用中文名。

## 3. 硬规则：共享层里不放她的东西
游戏层和角色层会进公开仓库：**不写她的照片、文件名、人名、对话原话、存档细节（角色名、世界名、农场名）、账号、路径里的用户名**。
要写「这张婚礼照的光线」这类只对她的项目成立的话，写进本机层（`--local`），或干脆不写。`gameanything lessons add` 会拦下明显的照片
文件名、项目素材路径、邮箱，以及（给了 `--project` 时）项目 vocab / 人物名单里的名字；拦不下的要你自己守住。

## 4. 什么时候读、什么时候写
- **每一轮开工前（builder 和 playtester 都要）**：`gameanything lessons show --game <g> --role builder|playtester`，再 `gameanything status show --project P`。
  先读 confirmed 的；candidate 是别人试过一次的，参考但要自己验证。
- **一轮结束时**：遇到的新坑、找到的新做法，每条一次 `gameanything lessons add`：

      gameanything lessons add --game terraria --role builder --symptom "…" --cause "…" --fix "…" --evidence "m2 第 1 轮 14:05" [--local] [--project P]

  和已有的一条很像（现象 / 原因相似）时不会新加，而是给那一条加一行证据、可信度升成 `verified repeatedly`，输出里说并进了哪条。
  真的不一样再加 `--force`。和游戏无关的写 `--general`（进角色层）。
- **协调员**：每天或每期结束 `gameanything lessons review`：列出所有 candidate；`--confirm ID` 确认、`--drop ID` 删掉、`--merge A B`（把 B 并进 A，
  证据合在一起，删掉 B）。确认前看证据是否真能核对、有没有她的私人内容。
- 新游戏的游戏包要带一份 `LESSONS.md`（`gameanything game new` 会生成空的两节；`gameanything game check` 检查格式）。
