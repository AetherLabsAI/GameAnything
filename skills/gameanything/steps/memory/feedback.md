# Step feedback — 试玩和意见 (her)
Entry: the result card and the task card to 试玩 are out.
Do: in the same run as the result, one `options` card (key `next-round`): what the next version does, from her notes and the review (each with its cost, one recommended; add 「带回家：装进你自己的游戏」 when it is ready).
```yaml
kind: options
key: next-round
title: 下一版做什么？（可以多选，也可以写一句）
multi: true
items:
  - {key: fix, title: 先修你说的三处, desc: "花拱门、灯光、对白", recommended: true}
  - {key: keep, title: 带回家, desc: "装进你自己的游戏"}
en: {title: "What should the next version do?"}
```
Her comments: answer each; record them (`gameanything status set-item` / `feedback --add-event`, next_round_notes.md).
Exit: she picked on the card (or wrote what she wants), or accepted the version.
Mistakes: saying 「都完成了」 while she has not chosen; promising changes without recording them.
Records (references/feedback-records.md): each comment of hers is one `gameanything feedback` record with your reading, linked to its STATUS item; unsure readings go to her on the confirm card first. In the run that posts the result card, also send the verify card (`gameanything feedback card --kind-of-card verify --m <m>`) when the version has before / after pairs, and record her answers (`gameanything feedback verdict`, `gameanything feedback accept` when she accepts the version).
