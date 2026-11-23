# Step people — 标记人物 (you, then her)
Entry: photos looked at. The people list decides who appears in the game and how they are called.
Do: one `task` card in this run: open `#people/tag`, key `people-tag`. Say why (who is in the game, their names) and how long (many photos: ten-odd minutes). She boxes each person, names them, drags them into groups, picks how much each appears in the game.
```yaml
kind: task
key: people-tag
title: 给照片里的人起名字
body: 框出每个人、起名字、分组；这决定谁出现在游戏里、怎么称呼。大概 10 分钟。
open: "#people/tag"
en: {title: "Name the people in your photos", body: "Box each person, name them, group them. About 10 minutes."}
```
No photo detection (she declined it, or there are no photos): write the people she named in the chat into 3_remember/people.yaml (`id`, `name`, `role`, `source: her words`) and open `#people` instead; she can also add someone there herself (「加一个人」, `source: user`: keep those entries as she wrote them).
While she tags: unsure about someone → a `questions` card. Never guess names, relations or habits.
Exit: she pressed 做好了 on the card (or 3_remember/tags.yaml / confirmed people exist).
Mistakes: inventing who someone is; skipping the why; sending faces to a model without a permission card naming them.
