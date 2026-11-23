# Step questions — 问清楚 (you, then her)
Entry: she said what she wants.
Do: first one line 「收到」, then ONE `questions` card in this run: where it goes in the game, how the player uses it, where the pictures / models come from, how we know it works, what the save gains. Each item with a default in `hint`; partial answers are fine.
```yaml
kind: questions
key: feature-questions
title: 做之前想问你 4 件事（不答的按默认）
items:
  - {n: 1, text: 放在哪一关？, hint: 默认：新加一关「茶餐厅」}
  - {n: 2, text: 菜的样子照什么做？, hint: 默认：照你放进素材的照片}
en: {title: "4 questions before I start (unanswered ones use the default)"}
```
Exit: card sent, every item has a hint, she answered.
Mistakes: asking in plain text; questions without defaults; asking what she already said.
