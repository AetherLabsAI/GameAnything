# Step go — 开工 (you, then her)
Entry: previews picked (or skipped).
Do:
0. `gameanything setup guide --project "$P"`: read the WHOLE guide it prints (prerequisites, verdict, what to tell her), then `--read <mark1>-<mark2>-<mark3>` (its 3 read marks). Criterion `setup_guide`.
1. Re-read config/project.yaml `build_mode`. `gameanything estimate --project "$P" --size small|medium|large --yaml` (the build model's estimate) → a `go` card: milestone, items (the final list), estimate, playtest_rounds.
2. Tell her in one line that the card shows time and cost and nothing starts before she presses 开工.
A preview / drawing go card (key `preview-go`) is not this card.
Exit: she pressed 开工 on the build go card (the build_start request is the next step, build).
Model: builds run ONLY on the build model (`gameanything project set-model "$P"`; she changes it with the 「构建」 chip). `chat card` puts it on the card read only and drops `runners`. Chip changed after the card: resend it (same key, new estimate). Fable is very expensive: say so.
Mistakes: a go card without the build model's estimate; runners to pick; starting anything yourself; native mode plans that use docker.
