# Mode: memory (one real day or period of her life made into a game world)

Her photos, videos and words are private and about real people. Nothing goes to a model before a `permission` card she said yes to
(log it in `privacy_ledger.yaml`). Never invent facts about real people: drafted lines are `source: draft` and she confirms them.
The flow is a state machine (`gameanything flow next`):

| # | step | who | done when |
|---|---|---|---|
| 1 | gather 放进素材 | her | files in 素材 |
| 2 | ingest 整理素材 | you | `gameanything ingest` done, ingest_request state done |
| 3 | perceive 看图 | you → her | photos: permission card (key `perceive`) yes, `gameanything perceive --emit/--collect` → 2_perceive/cards |
| 4 | people 标记人物 | you → her | photos: task card `#people/tag`, she tagged / pressed 做好了 |
| 5 | board 整理这一天 | you | 3_remember/board.yaml moments; questions card for what only she knows; task card `#board` |
| 6 | confirm_day 确认这一天 | her | 「这一天」 confirmed (board_review.yaml) |
| 7 | design 写方案 | you | options cards for design choices; 4_design/world_plan.yaml with a milestone; 5_build/<m>/plan.yaml items (what the 方案 page lists); understanding / task card `#plan` |
| 8 | confirm_plan 确认方案 | her | 「就按这个做」 on 方案 (plan_review.yaml), or 「按这个做」 on a plan card |
| 9 | preview 预览图和形象 | you → her | permission + preview go card → `gameanything gen request`; candidates picked; looks seen on 人物 |
| 10 | go 开工 | you → her | build go card (estimate of the build model) started |
| 11 | build 构建 | you, background | build_start request; delivered; result card after `gameanything build check` |
| 12 | feedback 试玩和意见 | her | result + task + 「下一步」 options card (key `next-round`) answered, or accepted |
| 13 | next_round 下一版 | you | next milestone in world_plan.yaml (status next) → back to design |
| 14 | keep 带回家 | her | final accepted (her saves backed up first) |

How the steps connect:
- One step per run, in order; never skip her steps (no plan before 这一天 is confirmed, no drawing before the plan is confirmed).
- A step with a card: send it in the SAME run (`gameanything chat card`), then say in one line where it is. Text questions do not count.
- Cards carry the step (`flow_step`); use the keys the step docs give. Every card has `en:`.
- Her words on 这一天 / 方案 / 人物 / 试玩 come into the chat as her lines: apply them in that run and say what changed.
- 「先补这一步」 (a gap): fix the earlier step's files first.
- Versions: after a result she picks what next; you write the next milestone; the round restarts at design (plan → go → build).
- Public places with too few pictures: ask her first (options card, key `websearch-<place>`), then search public names only.
- Build mode: read config/project.yaml `build_mode` (lab / native) before the go card; native never touches docker or a sandbox.
