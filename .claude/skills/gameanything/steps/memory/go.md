# Step go — 开工 (you, then her)
Entry: previews picked (or skipped).
Do:
0. `gameanything setup guide --project "$P"`: read the WHOLE guide it prints (prerequisites, verdict, what to tell her), then `--read <mark1>-<mark2>-<mark3>` (its 3 read marks). Criterion `setup_guide`.
1. Read config/project.yaml `build_mode` (lab / native). `gameanything estimate --project "$P" --size medium|large --yaml` (the build model's estimate) → one `go` card: milestone, items (each says which of her words it comes from), estimate, playtest_rounds (default 6), wall_hours (default 5).
```yaml
kind: go
key: m1-go
milestone: m1
title: 「婚礼那天」第 1 版：仪式和晚宴
items: [仪式草坪（你说：要有那道花拱门）, 晚宴长桌]
en: {title: "Wedding day, version 1: ceremony and dinner"}
```
2. Tell her in one line: the card shows time and cost; nothing starts before she presses 开工.
Exit: she pressed 开工 (the build_start request is the next step).
Model: builds run ONLY on the build model (`gameanything project set-model "$P"`; she changes it with the 「构建」 chip). `chat card` puts it on the card read only and drops `runners`. Chip changed after the card: resend it (same key, new estimate). Fable is very expensive: say so.
Mistakes: a go card without the build model's estimate; runners to pick; using a drawing go card as the build's; starting anything yourself; native plans that use docker.
