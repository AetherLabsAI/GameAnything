# Step go — 开工 (you, then her)
Entry: plan confirmed (and previews of new objects picked).
Do:
0. `gameanything setup guide --project "$P"`: read the WHOLE guide it prints (prerequisites, verdict, what to tell her), then `--read <mark1>-<mark2>-<mark3>` (its 3 read marks). Criterion `setup_guide`.
1. Read config/project.yaml `build_mode`. `gameanything estimate --project "$P" --size small --yaml` (the build model's estimate) → one `go` card: milestone, items (each from her words), estimate, playtest_rounds.
2. Tell her in one line that nothing starts before she presses 开工.
A drawing / Meshy go card (`gameanything gen request`) is separate and does not count as this card.
Exit: she pressed 开工 (the build_start request is the next step).
Model: builds run ONLY on the build model (`gameanything project set-model "$P"`; she changes it with the 「构建」 chip). `chat card` puts it on the card read only and drops `runners`. Chip changed after the card: resend it (same key, new estimate). Fable is very expensive: say so.
Mistakes: a go card without the build model's estimate; runners to pick; starting anything yourself; native plans that use docker.
