# Mode: feature (one new thing added to her game: a dish, a tool, a mini game)

She says 「想加一个 X」. You ask until it is clear, write a requirements sheet she confirms, then a small plan, then build.
The flow is a state machine (`gameanything flow next`):

| # | step | who | done when |
|---|---|---|---|
| 1 | gather 说想加什么 | her | she said it in the chat (or put files in 素材) |
| 2 | ingest 整理素材 | you | only if files are in the inbox: `gameanything ingest` |
| 3 | questions 问清楚 | you → her | questions card (key `feature-questions`, every item with a hint) answered |
| 4 | spec 写需求单 | you | 3_remember/feature.yaml (items: what / how / done_when / saves) + understanding / task card `#spec` |
| 5 | confirm_spec 确认需求 | her | 「确认需求」 (feedback/feature_review.yaml state confirmed) |
| 6 | plan 方案 | you | world_plan.yaml milestone for this version; 5_build/<m>/plan.yaml items (what the 方案 page lists); options card for the size of a big feature; plan card |
| 7 | confirm_plan 确认方案 | her | 「就按这个做」 on 方案 or 「按这个做」 on the plan card |
| 8 | go 开工 | you → her | build go card (estimate of the build model, size small) started |
| 9 | build 构建 | you, background | build_start request; delivered; result card after `gameanything build check` |
| 10 | feedback 试玩和意见 | her | result + task + 「下一步」 options card (key `next-round`) answered |
| 11 | next_round 下一版 | you | next milestone (status next) → back to plan |
| 12 | keep 带回家 | her | installed in her own game (final accepted) |

How the steps connect:
- One step per run, in order. A step with a card: send it in the same run with `gameanything chat card`; plain-text questions do not count.
- Her 保留 / 要改 / 不要 on 需求 arrive in the chat: change feature.yaml (keep the ids) and ask her to confirm again.
- New 3D objects (Meshy): 2D reference first, permission card (`to: Meshy`, `files`), a drawing go card (key `meshy-…`, `gameanything gen estimate --tool meshy:image-to-3d`), `gameanything gen request --tool meshy:image-to-3d`; show the
  preview pictures in a candidates / result card before anything goes into the game. A drawing go card is not the build's go card.
- Things to try by hand (mini games, feel): offer 带回家 already after the first version.
- Every card has `en:`; to her: short simplified Chinese.
