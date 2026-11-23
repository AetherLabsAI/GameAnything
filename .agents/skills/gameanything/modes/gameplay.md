# Mode: gameplay (an abstract life experience translated into a game's own mechanics)

Not a rebuild of a place or a day: the meaning of the experience becomes mechanics (a resource, cards, enemies, a loop). The mapping
is agreed with her first, then the content. Example: 「PhD: The Spire」 for Slay the Spire.
Subject rules: obstacles are things (Bug, The Deadline), never real people or a role standing for one; humour is universal, no names
of real labs, schools or people (replace them and say so); version 1 is small (StS: 1 character, 25–35 cards, 8–10 relics, 6–8 events,
5–6 enemies, 1 act, 1 boss). The flow is a state machine (`gameanything flow next`):

| # | step | who | done when |
|---|---|---|---|
| 1 | gather 说说经历 | her | words in the chat or files in 经历 |
| 2 | ingest 整理经历 | you | only if files are in the inbox |
| 3 | questions 问关键问题 | you → her | core tension retold; questions card (key `gameplay-questions`, hints) answered |
| 4 | mapping 机制映射 | you | gameplay.yaml mapping + core (loop, resources, ≥3 archetypes); task card `#mechanics` |
| 5 | confirm_mapping 确认机制映射 | her | 「确认机制映射」 (gameplay_review.yaml mapping confirmed) |
| 6 | scope 第一版范围 | you → her | understanding card of the scope answered; `scope` written |
| 7 | content 内容表 | you | content (cards, relics, enemies, events, bosses); task card `#content` |
| 8 | confirm_content 确认内容 | her | 「确认内容」 |
| 9 | go 开工 | you → her | (art: permission + drawing go card → `gameanything gen request`), world_plan milestone, 4_design/BRIEF.md, build go card started |
| 10 | build 构建 | you, background | build_start request; delivered (play / balance); result card after `gameanything build check` |
| 11 | feedback 试玩和意见 | her | result + task + 「下一步」 options card answered |
| 12 | next_round 下一版 | you | next milestone (status next) → back to go (with an understanding card of the changes) |

How the steps connect:
- One step per run, in order. No content before the mapping is confirmed; no art and no build before the content is confirmed.
- A step with a card: send it in the same run with `gameanything chat card`; plain-text questions do not count. Every card has `en:`.
- A good mapping is isomorphic (failed experiments give Insight), not a reskin (Strike renamed Experiment).
- Balance numbers come from a simulator that plays worse than a person: always report them next to the critic's own runs.
- Her notes on 机制映射 / 内容 arrive in the chat: change gameplay.yaml (keep the ids) and say what changed.
