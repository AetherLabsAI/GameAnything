# Step go — 开工 (you, then her)
Entry: content confirmed. A later version: her pick on the 「下一步」 card; send an `understanding` card of the change list first.
Do:
0. `gameanything setup guide --project "$P"`: read the WHOLE guide it prints, then `--read <mark1>-<mark2>-<mark3>` (its 3 read marks). Criterion `setup_guide`.
1. Art (cards, relics, enemies): a `permission` card (what is sent: names, card text, style; no photos of her; these pictures ship inside the mod) and a drawing go card (key `art-go`), `estimate` + `cost_usd` from `gameanything gen estimate`), then `gameanything gen request --tool <adapter>:image --inputs 4_design/gen/art.yaml …` (`out: art/<group>`); picks in candidates cards.
2. 4_design/world_plan.yaml milestone (`m1: {name: 第一版, status: next, what}`) and 4_design/BRIEF.md (mapping, scope, content, subject rules, balance targets, her words).
3. Read `build_mode`; `gameanything estimate --project "$P" --size medium --yaml` (the build model's estimate) → the build `go` card (milestone, items, estimate, playtest_rounds).
Exit: she pressed 开工 on the build go card.
Model: builds run ONLY on the build model (`gameanything project set-model "$P"`; she changes it with the 「构建」 chip). `chat card` puts it on the card read only and drops `runners`. Chip changed after the card: resend it (same key, new estimate). Fable is very expensive: say so.
Mistakes: the art go card counted as the build's; no milestone (the 试玩 page breaks); starting the lab yourself.
