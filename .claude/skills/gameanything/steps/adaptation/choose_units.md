# Step choose_units — 选章节 (you, then her)
Entry: copyright recorded. Do NOT extract yet.
Do: read the table of contents (pack text), then send ONE card in this run listing the units (chapters / episodes) with a default (2–3 units to start), and tell her it is in the chat.
```yaml
kind: options
key: units
title: 先改编哪几章？（可多选，默认已勾好）
multi: true
items:
  - {key: ch2, title: 第二章 抵达士兵岛, desc: "换船登岛，管家夫妇迎接", recommended: true}
  - {key: ch3, title: 第三章 晚宴与留声机, desc: "录音逐个指控十位客人", recommended: true}
  - {key: ch5, title: 第五章 第一个人死去, desc: "马斯顿喝下毒酒"}
en: {title: "Which chapters first? (pick several; defaults are ticked)"}
```
Quote every `desc` ("…"): a colon or comma-colon inside an unquoted desc breaks the yaml into extra keys.
Exit: the card is sent (`units_card`), valid (`units_card_valid`), and she answered (`units_answered`). Until she answers, the step waits: say in one line what she should pick; do not start extracting on «no reply in 10 minutes».
Mistakes (2026-10-26, adaptation-3): asking 「你想先选哪几章？」 as plain text — the page then said 「agent 正在抽取」 while nothing happened.
