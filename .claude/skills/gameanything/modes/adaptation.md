# Mode: adaptation (a novel / film / series / anime made into a game world)

The work is hers to choose, not her memories; there are no real people, but there is copyright. Everything she sees is in simplified
Chinese (`gameanything ingest` converts traditional text; the original file stays in 0_inbox). The flow is a state machine (`gameanything flow next`):

| # | step | who | done when |
|---|---|---|---|
| 1 | gather 放进作品 | her | files in 作品 page |
| 2 | ingest 整理 | you | `gameanything ingest` done, ingest_request state done |
| 3 | copyright 版权和底本 | you | `source`, `source_license` in config/project.yaml, copyright said in chat |
| 4 | choose_units 选章节 | you → her | options/questions card (key `units`, a default) answered |
| 5 | extract 抽取场景 | you | 3_remember/adaptation.yaml valid, quotes verbatim, zh+en, video → keyframes linked, task card to 场景 |
| 6 | registry 地点登记表 | you | one place per real place (aliases, later names), every scene's place listed |
| 7 | confirm_scenes 确认场景 | her | 「确认场景和地点」 (feedback/adaptation_review.yaml `state: confirmed`) |
| 8 | characters 整理人物 | you | characters with role / looks / lines + where, zh+en, video → people linked, task card to 角色 |
| 9 | confirm_characters 确认人物 | her | 「确认人物」 (`state_characters: confirmed`) |
| 10 | questions 问关键问题 | you → her | questions card (key `plan-questions`), each with evidence + default, answered |
| 11 | plan 文字方案 | you → her | 4_design/world_plan.yaml + 5_build/<m>/plan.yaml items (what the 方案 page lists) + understanding/task card; she confirms on 方案 |
| 12 | preview 预览图 | you → her | permission + go card → `gameanything gen request`; candidates card picked |
| 13 | go 开工 | you → her | build go card (estimate of the build model) started (a preview go card is not it) |
| 14 | build 构建 | you, background | `build_start` request; delivered; result card after `gameanything build check` |
| 15 | feedback 试玩和意见 | her | comments into 5_build/STATUS.yaml; 「下一步」 options card (key `next-round`) answered, or accepted |
| 16 | next_round 下一版 | you | next milestone (status next) in world_plan.yaml → back to questions |

How the steps connect:
- One step per run, in order. Never skip her steps: do not extract before she picked the units, do not plan before both confirmations.
- A step with a card: send the card in the SAME run, then tell her where it is. Text questions do not count (the flow cannot see them).
- Cards you send carry the step automatically (`flow_step`). Use the keys the step docs give (`units`, `scenes-review`, …).
- Her 「要改」 notes on 场景 / 角色 arrive as chat lines: apply them to adaptation.yaml in that run and say what changed.
- `gameanything flow next` may say 「先补这一步」 (a gap): an earlier step's files are missing (e.g. video but no keyframes). Fix it first.
- While she has to act, use the run for 「等她的时候可以先做」 items (e.g. English fields) and say in one line what she should do.
- Invented content is always marked (grounding: invented) and listed apart; borrow from the same work first; never contradict the text.
- Video in the work: frames are reference only (never shipped, never published); showing them to a model needs a permission card.
- Versions: after a result she picks what next; you write the next milestone; the round restarts at questions (only this milestone's cards count).
