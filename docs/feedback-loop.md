# The feedback loop: feedback → polish → experience

How GameAnything turns a user's feedback into fixes and lasting experience: the design (sections 1–6), what study mode records
(section 7), decisions taken while building (section 8) and a map of the code (section 9). Section 0 says which parts are the product
(always on) and which exist only for a study (behind study mode, off by default).

The loop has two parts. The **inner loop** polishes one project: every piece of her feedback becomes one structured record, the agent
confirms with her what it means when that is unclear, the fix is linked to the development status, and the fix is checked again at the
same anchor (the same video moment or the same part of the picture) before the record closes on her confirmation. The **outer loop**
turns resolved records into experience at the right scope (her personal taste, a game, a mode, general craft, the system itself), feeds
back only what is relevant into the next build, and a critic predicts before delivery what she would say again. The question the
evaluation answers is whether the loop makes her **say the same thing less often**.

Status (2026-10-27):

| Part | State |
|---|---|
| Record store, records from every channel, links to STATUS items, backfill, metrics log | phase 1, implemented (`gameanything feedback …`, `gameanything/feedback.py`) |
| Verification at the same anchor (before/after pairs, builder step, deliver check, confirm card) | phase 2, implemented (`gameanything feedback verify / pairs / confirm`) |
| Preference profile (store + page) and the metrics panel on the 开发状态 page | phase 3, implemented (`gameanything profile …`, `gameanything/profile.py`, `#prefs`) |
| Retrieval at build start | minimal version implemented (`gameanything feedback brief`, budgeted, logged); the ranking of section 2.3 is a follow-up |
| Retrospective step, critic | implemented as agent steps (`gameanything feedback retro / critic`, `gameanything/retro.py`), wired into the builder (2.1, 2.4) |
| LLM judge, agreement | implemented behind her per-project permission card (`gameanything feedback judge`, `gameanything/judge.py`, 7.4); no run yet |
| Blind conditions (online evaluation) | implemented: ABBA C1 / C4 per project, fixed per version at build start, logged, never shown (7.8) |
| Backfill from old projects, logging completeness | implemented (`gameanything feedback backfill`, `gameanything feedback datacheck`, 7.5) |
| Study mode (product / study split, section 0) | implemented 2026-10-27: off by default in every project (`gameanything/study.py`) |

Terms used below: **version** = a delivered milestone (`5_build/<m>/` with `play/`, registered in `4_design/world_plan.yaml`; `m1`,
`m2`, …, also `p3`); **record** = one feedback record; **item** = a requirement in `5_build/STATUS.yaml`; **lesson** = an entry of the
lessons layers (`references/lessons.md`); **preference** = an entry of her preference profile; **kind** = the complaint category of a
record (section 7.2), the unit of "the same thing again".

---

## 0. Product and study: the study-mode switch

The rule (2026-10-27): the parts that collect data for the evaluation are behind a switch that is **off by default**, turned on only
while we run a study, and never change what she experiences. Everything that improves the experience is the **product** and is always on.

| | Product (always on) | Study (only with study mode on for that project) |
|---|---|---|
| Records | a record per point of her words (`chat read`, `feedback add / set / link`), her words verbatim, the reading, STATUS links (1.1–1.4) | label sheets (`feedback label --export / --import / --human-sheet`), agreement (`feedback agreement`) |
| Uncertain readings | the confirm card `fbc-…` before anything changes (1.5) | — |
| Verification | same-anchor before / after pairs, the re-shoot list, the 「改好了吗？」 card `verify-<m>`, her verdict (1.6) — in **every** version | — |
| Experience | 我的偏好 page and profile, the budgeted brief at build start, the retrospective (builder step 0), the critic before delivery (builder step 1c) | — |
| Conditions | every version runs the full loop (what section 7.6 calls C4); nothing is withheld from her | blind ABBA assignment C1 / C4 (7.8), `condition` events, `feedback condition --set` |
| LLM judge | — | the permission card `feedback-judge`, judge runs, the ledger entry (3.2, 7.4) |
| Logging | each record's own `history`, `confirm`, `resolution`, `verification`, `her_verdict` in `records.yaml`; `critic.yaml`, `retro/<m>/applied.yaml`; profile `history` and last-used | every line of `feedback/metrics.jsonl` (7.5: `retrieval`, `build_start` / `build_end`, `critic` predictions, `retro`, `record_*`, `delivered`, `accepted`, …), `feedback metrics`, `feedback match` (critic prediction matching), `feedback datacheck` |
| Page | 开发状态 with 「你说过的话」 and a 「我的偏好」 button | the 「反馈和改进」 panel (records, repeat rate, bars); with it a small 「研究模式开着」 badge that only the project owner sees |
| Resident | records, confirm cards, verify cards, the 我的偏好 hint | sending the judge card; any talk about a study, conditions or experiments (never, unless study mode is on; conditions never even then) |

**Off** (the default): `feedback.assign / peek / uses` give C4 without writing anything (a version assigned C1 during an earlier study
also gets the full loop once study mode is off), `feedback.log_event` writes nothing, `judge.*` refuses (`consent` is no), `gameanything chat card`
refuses a card with the key `feedback-judge`, the study commands (`feedback metrics / label / condition / judge / agreement / match /
datacheck`) refuse with 「研究模式没开」, and `/api/feedback` returns only `{study: false, exists, profile_on}` (no records, no metrics).
**On**: everything in sections 6 and 7 as written.

The switch:

```
gameanything project set-study <project id> on | off | default     # config/project.yaml `study: true|false`; default = remove it, follow the global default
gameanything project set-study <project id>                         # print it (and where it comes from)
gameanything project settings --study on | off                      # the global default (<home>/settings.yaml `study:`) for every project without its own
```

It is read fresh on every call (agentd's build start, the builder's `feedback brief / critic / pairs`, `build deliver`, the page), so a
build that is already running obeys a change at once; no restart is needed. The browser's Settings cannot change it (CLI only). Each
change of a project's effective state is a `study` event in its `feedback/metrics.jsonl` (`{at, ev: study, on, scope: project|global,
by}`): `on: true` opens a study period, `on: false` closes it and is the last line until the next period (the dataset stops there). A
project that never had study mode on gets no log file at all. Analyses use only events inside on-periods (7.5).

---

## 1. Inner loop: polish this project

### 1.1 The feedback record

One record per piece of feedback. A message that says two different things ("而且文字要改成英文。另外我们的场景能不能做的更丰富宏大？")
is two records sharing one `event`. Records live in `<project>/feedback/records.yaml` (section 1.2). Schema:

```yaml
- id: f7                         # f<N>, numbered per project, never reused
  project: adaptation-3          # the project id (registry), for the profile's links back
  created: 2026-10-27T03:40:00   # when she said it (the thread event's time)
  event: e_20261027T034000_21f7  # the conversation event (conversation/thread.jsonl); the page jumps there
  source: playtest               # chat | playtest | picture | card | verdict | backfill
  milestone: m3                  # the version she was looking at (the anchor's version; else the newest delivered version at that time)
  modality: video_moment         # text | video_moment | image | image_region
  anchor:                        # where exactly; every field optional, as much as the channel gives
    video: {m: m3, t: 235.7}     # the version's video and the second she paused at
    chapter: {moment: full, title: 完整录像, t: 0}   # the play.yaml chapter that contains t (play.yaml chapters)
    frame: feedback/frames/m3_2026-10-27T034000.png  # the frame the page grabbed at t (project-relative)
    image: 0_inbox/581793075405_.pic.jpg            # a picture she attached / a still of the play page
    region: [0.12, 0.30, 0.48, 0.71]                 # a box on the frame or the image, x0 y0 x1 y1 as fractions
    target: 客厅                 # the scene / place / object the words name (from the project's places, moments, chapters)
    moment: m_cove               # a board moment / adaptation scene id when the channel gives one
  words: 这里周围飘着的那些珠子 白色方块 黄色方块是啥   # HER WORDS, VERBATIM, never edited
  interpretation: 客厅里有白色、黄色的方块浮在空中，她以为是掉落物（实际是水晶吊灯从这个角度看像浮块）
  interpretation_en: White and yellow cubes floating in the drawing room look like item drops (they are the chandelier seen from this angle)
  certainty: low                 # high | low: low = must be confirmed with her before anything changes (1.5)
  confirm: {card: fbc-f7, state: corrected, at: 2026-10-27T03:44:08, event: e_20261027T034408_1b2f}   # pending | confirmed | corrected
  class: question                # bug | taste | request | question
  kind: unreadable_object        # complaint category (taxonomy, 7.2); `other` when none fits
  scope: craft                   # project | user | game | mode | craft | system: where the experience goes (section 3)
  status_item: r16               # the STATUS item it became (gameanything status set-item --source feedback:<event>)
  state: closed                  # the lifecycle state (1.4)
  resolution: {m: m4, what: 吊灯改成挂在天花板上的链条 + 灯罩，从门口机位看是一盏灯, by: builder, at: …}
  verification:                  # the same anchor in the new version (1.6)
    m: m4
    before: feedback/frames/m3_2026-10-27T034000.png
    after: 5_build/m4/play/verify/f7_after.png
    pair: 5_build/m4/play/verify/f7_pair.png
    method: reshoot              # reshoot (builder re-shot the same camera) | chapter_offset (frame of the new video at the mapped time) | listed (no picture yet)
  her_verdict: {verdict: ok, at: …, event: …}   # ok | not_ok: the record closes only on ok
  repeat_of: [f2]                # earlier records of the same kind (and target) on an earlier version: this record is a repeat
  labelled_by: resident          # who set class / kind / scope: resident | heuristic | judge | human
  history:                       # every state change, for the metrics
  - {at: …, state: new, by: chat-read}
  - {at: …, state: confirming, by: resident}
```

Rules: `words` is copied from the event and never edited (AGENTS.md hard rule). Her photos and frames are referenced by path inside her
project, never copied elsewhere. `interpretation` is the agent's reading and is always shown as the agent's, next to her words.

### 1.2 Where things live in a project

| Path | What | Written by |
|---|---|---|
| `feedback/records.yaml` | the records (one YAML list, atomic writes under a lock file `feedback/.records.lock`) | `gameanything feedback …` (resident, builder, `chat read`, backfill) |
| `feedback/frames/` | frames the 试玩 page grabbed at a video moment (exists) | the UI |
| `conversation/files/` | frames from 「在对话里说」 and attachments (exists) | the UI |
| `5_build/<m>/play/verify/` | after-frames and before/after pairs of this version (`<rid>_after.png`, `<rid>_pair.png`) | builder (`gameanything feedback verify`), `gameanything build deliver` |
| `5_build/<m>/play/verify.yaml` | the verification list of this version: record, before, after, pair, method | `gameanything feedback pairs` / `build deliver` |
| `feedback/metrics.jsonl` | the append-only event log the metrics are computed from (7.5); study mode only (section 0) | every command of the loop, agentd builds |
| `feedback/labels/` | labelling sheets for the LLM judge and the human check (7.4); study mode only | `gameanything feedback label` |
| `<home>/profiles/<owner>.yaml` | her preference profile, outside every project and every repo (section 4) | `gameanything profile …`, the 我的偏好 page |

### 1.3 Channels → records

| Channel | What arrives | Record |
|---|---|---|
| Chat text | a `text` event from the UI | the resident decides whether it is feedback; if so `gameanything feedback add --event E` (one per point) |
| Playtest moment (试玩 page 「在 X 留言」) | `build_feedback.jsonl` + `user_review.yaml` note `{kind: time, t, frame}` and a thread event with context `video {m, t, frame}` | created automatically by `gameanything chat read` (`modality: video_moment`, anchor `video`, `chapter` from play.yaml, `frame`) |
| 「在对话里说」 from the player | thread event with context `moment` + `video {m, t, frame}` (frame in `conversation/files/`) | automatic, as above |
| A box on a still (试玩 page 「框出」) | note `{kind: box, box, id: <still>}`; the thread event now carries a `region` context (new, phase 1) | automatic (`modality: image_region`, anchor `image` + `region`) |
| A picture she attached | thread event with context `file` (in `0_inbox/`) | automatic (`modality: image`, anchor `image`) |
| A moment / check / sound verdict with a note | thread event with context `moment` / `check` / `file` | automatic (`source: verdict`, `anchor.moment`) |
| An answer on a card | `answer` event | only when the answer itself is feedback on the work (the resident adds it with `--event`) |

Automatic records start in state `new` without an interpretation; the resident's run fills `interpretation`, `class`, `kind`, `scope`,
`certainty` (`gameanything feedback set`). Page-generated lines (`auto: true`, e.g. 「把《X》标成了满意」) are never records: they are not her words
(but an "all ok" is logged as a verdict for the metrics).

### 1.4 Lifecycle

```
new ──interpret──▶ interpreted ──(certainty low)──▶ confirming ──her answer──▶ interpreted (confirmed / corrected)
                        │                                                     │
                        ├── class question, answered, nothing to change ──▶ answered (terminal)
                        ├── she withdraws / out of scope, she agreed ──▶ dropped (terminal)
                        ▼
                      open  (linked to a STATUS item)  ──builder starts──▶ in_progress ──item done──▶ fixed
                                                                                                │
                              verification pair made at the same anchor (before/after) ◀────────┘
                                                                ▼
                                                            verifying ──her ok──▶ closed (terminal)
                                                                │
                                                                └──her not ok / the same kind again──▶ reopened ──▶ open
```

| Transition | Who | Command |
|---|---|---|
| → new | `gameanything chat read` (anchored channels), resident (`add`), backfill | automatic / `gameanything feedback add` |
| new → interpreted / confirming | resident | `gameanything feedback set --id f7 --interpretation … --class … --kind … --scope … --certainty high\|low` |
| confirming → interpreted | resident after her answer on the confirm card | `gameanything feedback confirm --id f7 --as confirmed\|corrected [--interpretation …] --event E` |
| interpreted → open | resident (creates / links the STATUS item) | `gameanything feedback link --id f7 --item r16` (or `--new-item "…"`: `status set-item` with `source: feedback:<event>`) |
| open → in_progress → fixed | builder (follows the STATUS item) | `gameanything status set-item --id r16 --state done …` moves linked records to `fixed` and fills `resolution` |
| fixed → verifying | builder / `gameanything build deliver` | `gameanything feedback verify --id f7 --m m4 --after <png>` or the automatic chapter-offset frame |
| verifying → closed / reopened | resident, from her answer on the verify card | `gameanything feedback verdict --id f7 --ok\|--not-ok --event E` |
| any → reopened | `add` of a new record with the same kind + target on a later version (it becomes a repeat; the old one reopens if it was fixed) | automatic |

A record is never deleted. `dropped` needs her agreement (the reason is kept).

### 1.5 Confirming an uncertain interpretation

Real case (adaptation-3, m3, 3:55): 「这里周围飘着的那些珠子 白色方块 黄色方块是啥」. The obvious reading ("item drops floating around,
remove them") was wrong: four minutes later she found herself that they were the crystal chandelier seen from below. Had the builder
"removed the floating cubes", it would have deleted the chandelier she had asked for in m2.

Rule (resident, `core.md`): set `certainty: low` when any of these holds, and then send ONE `questions` card (key `fbc-<record ids>`,
the anchored frame as the item's `image`) with the reading in plain words and the options before changing anything:
- her words are a question about what something is (是什么 / 是啥 / 这是哪), or name no object;
- the frame shows several candidate objects, or the reading would remove or replace something she asked for before;
- the reading needs a fact only she knows (a real place, a person, the reference she means).

Records with `certainty: high` go straight to `open`. The card answer is recorded with `gameanything feedback confirm`; `corrected` keeps the old
interpretation in `history` (a study needs the error rate of first readings, 7.3 M6).

### 1.6 Verification at the same anchor

When a version is delivered, every record whose STATUS item was fixed in it gets a before/after pair from the same anchor:

1. **reshoot** (preferred): the builder puts the camera where the anchor was and takes the after picture in the game. The lab tools of
   Cities: Skylines (`cine` camera keys), Minecraft (teleport + look) and Stardew (`warp` + screenshot) can do this; the builder's role
   doc lists the anchors to re-shoot (`gameanything feedback pairs --project P --m <m> --todo`) and registers each after picture with
   `gameanything feedback verify --id f7 --m <m> --after 5_build/<m>/play/verify/f7_after.png`.
2. **chapter_offset** (automatic, at `gameanything build deliver`): when the old and the new video both have a chapter with the same `moment`
   id that is not `full`, the after frame is taken from the new video at `new_chapter.t + (t_old − old_chapter.t)` (clamped to the
   chapter), with PyAV. Good for scripted tours (cine), wrong when the camera path changed; marked as such.
3. **listed**: when neither is possible, the record is listed in `verify.yaml` without an after picture and `gameanything build deliver` warns
   「N 条她的意见没有在同一个画面复拍」. The builder must re-shoot or say why in the end note.

`gameanything feedback pairs` writes the side-by-side pictures (`<rid>_pair.png`, before left, after right, the region box drawn on both) and
`5_build/<m>/play/verify.yaml`; `gameanything status card` adds a line 「你的 N 条意见：同一画面复拍 X 条」 and the first pair as the picture;
`gameanything feedback card --kind-of-card verify --m <m>` makes the `questions` card (key `verify-<m>`, one item per record, the pair as `image`, her words as the
question) that she answers. A record closes only on her `ok` (`gameanything feedback verdict`). No answer within the version = stays `verifying`
(counted as "unconfirmed" in the metrics, not as fixed).

---

## 2. Outer loop: experience

### 2.1 Retrospective step (implemented 2026-10-27)

When: after each delivered version, once her feedback on it is in: in practice at the start of the next build. agentd computes the
versions before the new one that have records and no applied retrospective (`retro.retro_todo`, the newest two) and the builder's first
message says 「FIRST … the retrospective of m3」; `roles/builder.md` step 0 does it. The last version of a project (no next build) is
the resident's (`gameanything feedback retro --todo`). It runs in every condition (it gathers experience; conditions only change what is
*retrieved*), and the `retro` event records the version's condition.
How: like perceive's agent-native mode. `gameanything feedback retro --project P --m <m> --emit` writes `feedback/retro/<m>/request.md`: the
rules below and the data (`retro.retro_input`: the version's resolved records with their fix, pair and her verdict, her complaints on the
version, the repeats with the earlier records and their fixes, the brief's retrievals, her profile entries). An agent on her login
answers it in a fresh context (a sub-agent given only that file) into `feedback/retro/<m>/proposals.yaml`; `--collect` validates
(scope, kind, evidence ids that exist), applies and writes `applied.yaml` + a `retro` event (proposals with their result or the reason
they were refused, the repeats, the repeats no proposal covers).
What it produces, each with evidence (record ids, the fix, the pair):
- for each `repeat` record: why the earlier fix did not hold, and a lesson at the record's scope (a repeat always yields a candidate);
- for each resolved record whose fix generalises (it does not depend on her content): a candidate at its scope (section 3);
- for her taste (`scope: user`): a preference candidate in her profile (`gameanything profile add … --from <project>:<record>`), off until she or
  the second-project rule confirms it;
- for system bugs (`scope: system`): an issue for the code, never prompt text (the coordinator turns it into a fix + test).
It never writes her words, photos or names into a shared layer (the `lessons add` guard applies; section 3.2).
Routing at `--collect`: `user` → `profile.add(by=retrospective)` (candidate, off) or, with `merge_into: p1`, the evidence added to that
entry; `game` → a candidate lesson in the game's LESSONS (`lessons.add`, the privacy guard sees the project's names); `mode` / `craft` →
a candidate in the builder role file (`mode` prefixed with the mode, 8.1); `system` → a coordinator request (`agentd.write_request`, kind
`other`, `details.type: system_issue`, the record ids); `project` → nothing. A candidate preference is confirmed when **she** switches it
on on the 我的偏好 page (the switch is her yes; an agent's `profile on` does not confirm); every change of an entry is in its `history`.

### 2.2 Promotion ladder

| Rung | Where | Enters when | Leaves when |
|---|---|---|---|
| project item | `5_build/STATUS.yaml` + the record | every interpreted record (1.4) | closed |
| candidate lesson / preference | lessons layers (`status: candidate`) / profile (`status: candidate`, `on: false`) | the retrospective proposes it: (a) any repeat, or (b) a resolved record whose fix generalises | confirmed, merged or dropped |
| confirmed rule | lessons (`status: confirmed`) / profile (`status: confirmed`, `on: true`) | **held in a second project**: retrieved in a build of another project and that version had no record of its kind there, OR the same kind recurred in a second project (evidence from ≥ 2 projects); plus the coordinator's review (lessons) or her yes on the page (preferences). A preference she states as a rule (「以后都…」) is confirmed at once | dormant (below) |
| automatic check | a lint / test / gate in code (`gameanything build check`, a lab tool check, a unit test) | a confirmed rule that is machine-checkable (a predicate over files, frames or logs) AND (≥ 3 hits or ≥ 1 repeat despite the rule) | — (the prose rule then shrinks to a pointer to the check) |
| dormant | stays in the file, not retrieved by default | retrieved in ≥ 8 builds with 0 hits and no record of its kind in the last 90 days | a new record of its kind wakes it |

Confidence of a preference: `low` (one record), `medium` (two records, or one explicit statement), `high` (≥ 3 records in ≥ 2
projects, or she confirmed it). System bugs skip the ladder: a code fix + a regression test the same day (example: the "cards show no
pictures" complaints of 2026-10-17, 10-21, 10-26 became the `_pictures_ok` check in `conversation.py`).

### 2.3 Retrieval at build start (budgeted)

At build start the builder gets only what is relevant to this game, mode (project kind) and step: `gameanything feedback brief --project P
--role builder [--budget 12]` (implemented minimally) prints, within the budget (number of entries; about 1 500 characters):
1. her preference profile entries that are `on` and apply to this project (kind / game / project filter), by confidence then last use (≤ 4);
2. this project's repeat-prone kinds: kinds with ≥ 1 record on an earlier version, most repeated first (≤ 3), as one line each
   「她已经 2 次说过：场景简陋（客厅、房子）」;
3. the records to re-verify this version (anchors to re-shoot, 1.6);
4. confirmed lessons of the game and role whose text matches the open items' kinds (≤ 5; the full `gameanything lessons show` stays available).
Every brief is logged (`retrieval` event: which ids were shown, 7.5) so the rule hit rate can be computed. Planned ranking (follow-up):
score = kind overlap with the open records + 1 for confirmed + recency decay, ties by confidence.

### 2.4 Critic before delivery (implemented 2026-10-27)

Before `gameanything build deliver`, a critic run (role `roles/critic.md`, to be written) gets the new version's frames per chapter, her
preference profile (applicable, `on`), this project's records (kinds, targets, her words) and the craft checklist, and predicts
"would she say this again?": a list `5_build/<m>/critic.yaml` of predictions `{kind, target, frame, t, p (0–1), text}`. Predictions
with `p ≥ 0.5` go back to the builder as a last round (bounded: one round); all predictions are logged (`critic` event) so that they can be
matched with her actual records on that version (same kind, and for the strict match the same target or chapter): precision, recall and
calibration (7.3 M7). Seam: `feedback.critic_input(root, m)` returns exactly what the critic sees; `feedback.match_predictions(root, m)`
scores a `critic.yaml` against the records.
Implementation: `roles/builder.md` step 1c, after the final video and before `build deliver`: `gameanything feedback critic --project P --m <m>
--emit` (under a condition without the critic it says 「不用」 and logs `critic_skip`) writes `5_build/<m>/critic/request.md` with
`retro.critic_input` (her complaints before m with her words, her applicable preferences, the STATUS recheck list) and a frame per
chapter (`5_build/<m>/critic/frames/`, the middle of each chapter; six frames over the video when it has only `full`). A fresh context
answers into `5_build/<m>/critic.yaml`; `--collect` validates and logs every prediction (`critic` event, also low-p ones for
calibration) and lists the `p ≥ 0.5` ones for ONE last fix round. `build deliver` warns the builder when the critic was due and not
collected. `gameanything feedback match --m <m>` (= `retro.match`): precision / recall / F1 loose (kind) and strict (kind + target or chapter),
Brier score; run it after her feedback on m is in (`her_records` says how many).

---

## 3. Scopes, routing, privacy

### 3.1 Routing table

| Scope | Example (real) | Goes to | Shared? |
|---|---|---|---|
| `project` | 「海狮为什么是白色的？应该是黑灰色」 | the STATUS item only | no |
| `user` (her taste) | 「这里有点简陋」(adaptation-3), 「海边为什么这么空」(SD): she wants dense, detailed scenes | her preference profile | **never** (private) |
| `game` | Cities: the map's height-data terrain needs smoothing at the coast | `<game package>/LESSONS.md` | yes, abstracted |
| `mode` | adaptation: rooms must read as the genre (悬疑 / 恐怖大宅) | mode craft notes `skills/gameanything/references/lessons/<mode>.md` (new layer, follow-up; today: the role file) | yes |
| `craft` | characters clip into furniture; an object unreadable from the camera | builder self-check list (`references/lessons/builder.md`, later a check) | yes |
| `system` | 「卡片里看不到图」, 「那个卡片在哪？」 | code fix + test (an issue for the coordinator) | yes (code) |

The default scope of a kind is in the taxonomy (7.2); the resident's guess can override it, the retrospective step decides.

### 3.2 Privacy rules
- Her photos, frames, words and anything naming her people stay in her project (`feedback/`, `5_build/`). Records are never copied out of
  the project; the profile links to them by `project:record` id and shows her words only on her own page.
- The preference profile is per user, in `<home>/profiles/`, never in a repository, never in a shared lesson, never sent to another
  user (hub: only the project owner sees and edits it; collaborators get 403).
- Shared layers (game, mode, craft) get only abstracted, non-personal text; `gameanything lessons add` keeps refusing photo names, project paths,
  e-mails and the project's vocab / people names.
- Labelling her words with an LLM judge (7.4) sends her words to a model: that is a `permission` card and a `privacy_ledger.yaml` entry
  like any other model call. It exists only in study mode (section 0): with it off the card cannot be sent and nothing runs. She agreed
  to this on 2026-10-27 **per project**: in a project with study mode on, the resident sends the card `feedback-judge` (zh + `en:`)
  once per project; no yes on the current card of that key = no judge for that project (`judge.emit` refuses, nothing is written for a
  model). The frames go only when the card listed them (`--card --frames` adds them and a `files` list). The offline numbers in this
  document were labelled locally (keyword heuristic, no model).
- Published study results may report counts, kinds and agreement; quotes of her words and her frames only with her explicit consent per quote / figure.

---

## 4. The preference profile

Store: `<home>/profiles/<owner>.yaml` (`<home>` = the project list folder, `~/.config/gameanything`; `<owner>` = `owner:` of the
project, `local` when there is none). File mode 0600.

```yaml
entries:
- id: p1
  text: 场景要丰富、精致：房间和外景都要有足够的陈设和细节，不要空、不要简陋
  text_en: Scenes must be rich and detailed (enough furniture and props indoors and out); never bare or plain
  kind: sparse_plain # the complaint kind it prevents (7.2; for the rule hit rate)
  modes: []          # project kinds it applies to (memory / adaptation / feature / gameplay); empty = all
  games: []          # game ids; empty = all
  projects: []       # project ids; empty = all
  from:              # links back to the records
  - {project: adaptation-3, record: f1}
  - {project: beach-trip, record: f3}
  confidence: high   # low | medium | high (2.2)
  status: confirmed  # candidate | confirmed
  on: true           # her switch: off = never retrieved
  created: …
  updated: …
  last_used: …       # the last brief that showed it (retrieval)
  used: 4            # how many briefs showed it
  hits: 1            # builds where it was shown and no record of its kind followed
  by: retrospective  # retrospective | resident | her
```

Page 「我的偏好」 (`#prefs`, linked from the 开发状态 page): every entry with its text (zh / en), where it came from (links to the
records: same project → the record on the 开发状态 page; another project → its id and her words), the projects / kinds / games it applies
to (modes / games / projects), confidence, last used, the on/off switch, edit (text, scope) and delete; she can also add one herself (`by: her`, confirmed). All
labels through `t()` (zh / en like the rest of the UI). API: `GET /api/profile`, `POST /api/profile {op: add|set|toggle|remove, …}`
(hub: owner only).

---

## 5. Who writes what

| Who | Writes |
|---|---|
| UI server | thread events with anchor context (video / region / file), frames (exists); nothing in `records.yaml` |
| `gameanything chat read` (resident run) | `new` records for anchored events, `record_created` metrics events |
| resident | interpretation, class, kind, scope, certainty; confirm cards and their outcome; links to STATUS items; her verdicts; text records |
| builder | STATUS items (exists); after pictures (`feedback verify`); `retrieval` event via `feedback brief` |
| `gameanything build deliver` | automatic chapter-offset after frames, `verify.yaml`, pairs, `delivered` event, the warning about unverified records |
| agentd (builds.py) | `build_start` / `build_end` events with wall time, rounds, provider, tokens / cost from the run's log |
| retrospective step (builder step 0 / resident) | `feedback/retro/<m>/`, candidate lessons, preference candidates, system-issue requests, `retro` event |
| critic (builder step 1c) | `5_build/<m>/critic/`, `5_build/<m>/critic.yaml`, `critic` / `critic_skip` events |
| judge (resident, after her yes) | `feedback/labels/judge/<run>/`, `labels.judge` / `labels.judge_b` on the records, a ledger entry, `judge` event |
| her (page) | profile entries (on/off, edit, add, delete) |

---

## 6. Metrics shown on the project page

Study mode only (section 0); with it off the page shows just the 「我的偏好」 button. The 开发状态 page gets a panel 「反馈和改进」: records by class and state; complaints per version (bars); the repeat-feedback rate
(headline, strict and loose, with n); rounds until she accepted a version; how many fixes were checked at the same anchor and how many
she confirmed; the rule hit rate when retrievals are logged (`—` until then). And the list of records (her words, the anchor frame, the
reading, the linked item, the state). Definitions are in 7.3; the page computes them with `feedback.metrics(root)`, the same function a
study's numbers come from.

---

## 7. Study instrumentation (study mode only)

What a study records and how labels, metrics and conditions are defined in code. Everything here is behind study mode (section 0).
The research design itself (questions, offline replay, statistics, threats to validity) is kept outside this repository.

### 7.2 Units and labels
- **Version** `v`: a delivered milestone of a project, ordered by delivery time (world_plan `at`, else the `result` card time, else the
  folder time). The first version of a project with feedback is `v₁`.
- **Record** `r`: section 1.1. `ver(r)` = the version she was looking at.
- **Complaint**: a record that asks for a change or reveals a defect: `class ∈ {bug, taste, request}`, or `class = question` with a
  kind other than `other` (a question that exposed a defect, like the chandelier). `C` = the complaints; `C_v` those on version `v`.
  Logistics ("进度如何", "开始吧") are not records at all.
- **Kind** `κ(r)`: the complaint category, one per record (the primary one), from this taxonomy (default scope in brackets):

| kind | meaning | example | scope |
|---|---|---|---|
| `sparse_plain` | the scene is bare, plain, empty, not detailed | 这里有点简陋；海边为什么这么空 | user |
| `not_like_reference` | does not look like the real place / the reference | 跟我给你的参考图不一样；Balboa park 也完全不像 | craft |
| `mood` | the feeling / genre is not there (hotel luxury, horror, bustling) | 没有那种侦探小说里很悬疑恐怖的感觉 | user |
| `color_light` | colours, light, dull or washed out | 整体画面颜色也灰蒙蒙的不鲜亮 | user |
| `clipping` | things or people intersect | 这里穿模了 | craft |
| `unreadable_object` | she cannot tell what something is | 这里背后那片白色建筑是什么？ | craft |
| `layout_scale` | position, orientation, proportion, map layout wrong | 喷泉怎么跑到水池里了 | craft |
| `model_quality` | a model / texture is broken (gaps, triangles) | 喜茶的牌子怎么全是缝隙 | craft |
| `missing_content` | something she expects is not there | 海狮呢；UTC 标志性的建筑呢 | project |
| `npc_life` | people static, too few, not alive | 为什么人都是站着不动的 | craft |
| `camera` | the video: shaky, too fast, misses the subject, wrong angle | 镜头还是很抖；Macy 这块没录到正面 | mode |
| `text_language` | in-game text: language, signs, labels | 文字要改成英文；每个建筑上写一个大字 | project |
| `ui_delivery` | the product: cards / pictures not visible, page bugs, progress reporting | 卡片里看不到图 | system |
| `game_error` | the game shows an error / crashes | 游戏界面又报错了 | game |
| `other` | none of the above | | project |

- **Target** `τ(r)`: the scene / place / object, normalised to the project's place registry (adaptation `3_remember/adaptation.yaml`
  places), board moments (memory), play.yaml chapter moments, or a small room / landscape lexicon (客厅, 走廊, 房子, 海边 …); `null` when
  the words and the anchor give none.
- **Repeat.** `r ∈ C` is a *strict repeat* if there is `r' ∈ C` of the same project with `κ(r') = κ(r)`, `τ(r') = τ(r) ≠ null` and
  `ver(r') < ver(r)`; a *loose repeat* if the same holds without the target condition. A record on `v₁` can never be a repeat.
  Explicit markers in her words (还是, 又, 仍然, still, again) are recorded (`marker: true`) and used to validate the labels, not to define
  repeats.

### 7.3 Metrics (formulas, units)
- **M1 repeat-feedback rate (headline).** `RFR = |{r ∈ C : r is a repeat, ver(r) ≠ v₁}| / |{r ∈ C : ver(r) ≠ v₁}|`, a proportion
  (reported as %), per project and pooled; strict (`RFR_s`) and loose (`RFR_l`). Per version: `RFR_v = repeats_v / |C_v|`. Lower is
  better. A cross-project variant `RFR_x` counts `r` as a repeat when the same kind was complained about in any *earlier project* of the
  same user (what the profile should prevent).
- **M2 feedback load.** `F_v = |C_v|` complaints per version (count), by class; and `F̄` its mean over versions ≥ 2.
- **M3 rounds to acceptance.** `A = ` the index of the first version she accepts (all moments ok on the 试玩 page, 「这一版可以了」,
  「带回家」 chosen, or an explicit acceptance recorded with `gameanything feedback accept --m`), counted from the first version of the
  milestone line; right-censored when the project ends without acceptance (report Kaplan–Meier style or as `>k`).
- **M4 rule hit rate.** For a build `b` that retrieved the set `R_b` of lessons / preferences, a retrieved entry `ℓ` is a *hit* when its
  kind `κ(ℓ)` had at least one complaint in that project on an earlier version (or, for preferences, in an earlier project) and no
  complaint of `κ(ℓ)` on `b`'s version. `HR = Σ_b hits_b / Σ_b |R_b ∩ applicable|` (applicable = `ℓ` whose kind occurred before); also
  the *use rate* (entries whose fix the builder cites in its evidence) and the *expiry count* (2.2 dormant).
- **M5 verification coverage.** Share of fixed complaints of a version that got a same-anchor pair (`reshoot`, `chapter_offset`), and
  the share she confirmed (`her_verdict: ok`) — the "closed on her confirmation" rate. False fixes = `not_ok` / verdicts.
- **M6 interpretation error rate.** Share of confirmed-or-corrected records that were `corrected` (first reading wrong), split by
  `certainty`; the ideal is errors only among `low`. Also the share of `high` records that later turned out wrong (reopened with a new
  reading).
- **M7 critic quality.** Predictions with `p ≥ θ` vs her complaints on the same version, matched on kind (loose) or kind + target
  (strict): precision, recall, F1; Brier score and a reliability diagram of `p` (calibration).
- **M8 cost.** Agent wall time per version (build start → delivered), builder tokens (input, output, cache), cost in USD where the
  account is metered, playtest rounds; her time per version (first record → last record on that version, an upper bound of effort).

### 7.4 Labelling: class, kind, target, repeat
1. **Live labels** come from the resident (`labelled_by: resident`). They are used by the system but not trusted for a study.
2. **LLM judge** (offline, after her consent; 3.2): for each record the judge gets the words, the anchor's chapter / target and the
   frame (optional; ablate with and without the frame), the taxonomy table above with one positive and one negative example per kind,
   and the project's place list; it returns `{class, kind, target, explanation}` as JSON. For repeat pairs it gets two records and
   answers "is the second the same complaint as the first, on the same thing?" (yes / no / partly with a reason). The rubric: *same
   kind* = the change she wants belongs to the same row of the taxonomy; *same target* = the same place, room or object (a different
   room of the same house is a different target). Run with temperature 0, two prompts orders, keep both.
   Implementation (`gameanything/judge.py`, rubric `taxonomy-7.2-v1`, prompt version 1): `gameanything feedback judge --emit --model M` writes
   `feedback/labels/judge/<run>/req_{a,b}_<n>.md` (order a: taxonomy and records as listed; b: both reversed; batches of 40) and
   `pairs_{a,b}.md` (every loose-repeat pair; b swaps the two records), plus `run.yaml` (model, rubric, prompt version, record ids,
   pairs, the consent card). No model is called from code and no paid key is used: the agent CLI on her own login answers each file in
   a fresh context (a sub-agent given only that file), like perceive's agent-native mode. The temperature is the harness's (not
   settable there): the two orders are the robustness check, and their agreement is logged. `--collect` stores `labels.judge` /
   `labels.judge_b` (class, kind, scope, target, explanation, model, rubric, prompt_version, run, order; the pair answers under
   `labels.judge.pairs`) next to `labels.heuristic` / `labels.resident`; the live class / kind do not change.
   `gameanything feedback label --export` writes the sheet (`feedback/labels/<date>.jsonl`, one line per record, ids only plus words), `--import`
   merges the judge's or a human's labels into `labels.<judge|human:<name>>` (`--name`; `--apply` also makes them live).
   `label --human-sheet [--seed N]` writes a blind, shuffled sheet (ids, words, chapter; no labels) for a human labeller.
3. **Human labels and agreement.** `label --human-sheet` gives a blind sheet for human labellers; their labels are imported as
   `labels.human:<name>`. `gameanything feedback agreement --a judge --b human:<name> --field kind|class|target` reports
   `judge.agreement` (Cohen's κ, raw agreement, confusion matrix) and `judge.alpha` (Krippendorff's α nominal over the judge and every
   `human:*`). `feedback.relabel(recs, who)` recomputes every metric with one labeller's labels.
4. **The keyword heuristic** (`feedback.heuristic_label`) is the reproducible zero-cost baseline used for backfilled records (it is a
   lower bound for an automatic labeller).

### 7.5 What is logged from now on (`feedback/metrics.jsonl`)
Only while study mode is on for the project (section 0); the `study` event marks where each study period starts and stops. One JSON
object per line, `{at, ev, …}`; never her photos, only ids and paths inside the project. Events:

| ev | fields | by |
|---|---|---|
| `record_created` | id, m, source, modality, class, kind | `chat read`, `feedback add`, backfill (`backfill: true`) |
| `record_state` | id, from, to, by | every state change |
| `record_labels` | id, class, kind, scope, certainty, labelled_by | `feedback set`, `label --import` |
| `confirm` | id, card, outcome (confirmed / corrected) | `feedback confirm` |
| `retrieval` | m, role, condition, entries [{type, id, kind}], n, chars, budget | `feedback brief` (a plain `lessons show` is not logged; follow-up) |
| `build_start` | m, provider, run_id, playtest_rounds, wall_hours, condition | agentd |
| `build_end` | m, rc, wall_s, rounds, delivered, usage {input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens}, cost_usd, num_turns | agentd (from the run's stream log) |
| `delivered` | m, records_to_verify, pairs (by method) | `build deliver` |
| `verify` | id, m, method | `feedback verify` / deliver |
| `verdict` | id, m, verdict | `feedback verdict` |
| `accepted` | m, how | `feedback accept`, 「这一版可以了」 |
| `critic` | m, model, prompt_version, theta, collect (n-th), predictions [{kind, target, chapter, t, p}] | `feedback critic --collect` |
| `critic_emit` / `critic_skip` | m, frames, records, preferences / m | `feedback critic --emit` |
| `retro_emit` / `retro` | m, prompt_version, condition; proposals [{scope, kind, evidence, why, result \| refused}], repeats, uncovered_repeats | `feedback retro` |
| `judge_emit` / `judge` | run, model, rubric, prompt_version, n, pairs / labelled {a, b}, missing, order_agreement | `feedback judge` |
| `condition` | m, name, how (schedule \| manual \| manual_project), schedule, index, project (7.8); without m: a project-wide manual setting | agentd build start, `feedback brief`, `feedback condition --set` |
| `backfill` | run, added, ids, already_recorded, skipped_not_feedback, backup | `feedback backfill` (its `record_created` / `record_state` events carry `backfill: true`) |
| `study` | on, scope (project \| global), by | `project set-study`, `project settings --study` (also written when it turns off: the end of the period) |

Also logged: `build_start` has `model`, `go_card`, `log` (the run's stream log) and `condition`; `build_end` adds `models` (from the
run's `system init` events); `delivered` has `verify_step` (false under a condition without it); `record_labels` has `target`,
`labelled_by` (`human:<name>` too) and `live`. Outside the log: every record keeps `labels.<labeller>` with a time, `history` of
states, `confirm`, `resolution`, `verification`, `her_verdict`; every profile entry keeps `history` (add / confirm / on / off /
evidence / edit, by whom); `feedback/retro/<m>/applied.yaml`, `5_build/<m>/critic.yaml`, `feedback/labels/judge/<run>/run.yaml`.
Logging completeness: `gameanything feedback datacheck --project P` (`feedback.datacheck`) lists every datum of this section and 7.3 per unit
(record, version, delivery, profile entry, judge run) as ✓ / ~ partial / ✗ missing / · not applicable yet (or from before live logging
began, `feedback.logging_since`); exit 1 when something is missing. It never assigns a condition. Metrics are derived later from these
raw data (no final metric is fixed yet, by her decision of 2026-10-27).

Timestamps are local ISO seconds (the rest of the project uses them). The model and the harness of each run are logged (`provider`; the
model from the go card's runner) because models change during a study.

### 7.6 Conditions: baselines and ablations
| Condition | Lessons at build start | Profile | Critic | Same-anchor verification |
|---|---|---|---|---|
| C0 no experience | none (builder reads only STATUS) | no | no | no |
| C1 game lessons (the system before 2026-10-27) | game + role lessons (`lessons show`) | no | no | no |
| C2 + profile | as C1 + her profile entries | yes | no | no |
| C3 + critic | as C2 | yes | yes | no |
| C4 full loop | budgeted brief (2.3) | yes | yes | yes |

Extra ablations: C4 without the budget (everything retrieved: does more context hurt?); C4 without confirmation of uncertain readings
(M6); verification by chapter offset only vs reshoot. The condition is a per-version switch (`gameanything feedback condition --set C2`,
logged; the builder brief obeys it) so that versions of one project can be compared.
What each condition switches (`feedback.USES`): the profile in the brief (C2–C4), the critic (C3, C4), same-anchor verification and the
repeat-kind / re-shoot lines of the brief (C4); lessons (C1–C4). Under a condition without verification `build deliver` makes no pairs,
`pairs --todo` lists nothing, the result card has no pair line and no verify card goes out; the records simply stay `fixed`. C0 is not
enforceable (the builder reads lessons by its role doc) and is not in the online schedule.

### 7.8 Blind conditions (online study)
Projects with study mode on (section 0), from the time it was turned on, with full logging (7.5). Projects with it off are not in the
study: every version gets C4 and nothing is assigned or logged. Design: within-project, alternating
blocks of versions (ABBA: C1, C4, C4, C1 …) when a project has ≥ 4 versions, otherwise between projects matched on kind and game; she is
not told the condition (she agreed to this on 2026-10-27). Primary outcome: RFR (M1, strict) per version; secondary: F_v, A, M8.
**Assignment (implemented, schedule `abba-C1C4-v1`).** `feedback.scheduled(project, i)` gives the arm of the i-th version of a project
(0-based, in the order versions get their **first** build): positions `i mod 4 ∈ {0, 3}` get the first arm, `{1, 2}` the second (A B B A
A B B A …); the first arm is C1 or C4 by `sha256(project id + ":" + schedule) mod 2`, so about half the projects start with each. The arm
is fixed once per version by `feedback.assign(root, m)`: agentd calls it when it starts the builder (`build_start` logs it), the
builder's `feedback brief` calls it when someone else started the build; everything else (deliver, the result card, the critic,
datacheck) only peeks (`feedback.peek`) and never assigns. A re-build or re-delivery of a version keeps its arm. A project-wide
`gameanything feedback condition --set C4` (no `--m`) takes a project out of the schedule (its next versions get C4, `how: manual_project`); a
per-version `--set X --m mN` before the version is assigned overrides one version. Versions built before 2026-10-27 have no assignment and
are treated as C4 by `peek` (what the code did then; for the analysis they are pre-study). Blinding: the condition is never in the page
data (`metrics()` no longer returns it), the brief's output does not name it, the commands say only 「不用」 to the builder, and core.md /
`feedback-records.md` / `roles/builder.md` forbid naming it in chat, cards or notes. Residual unblinding: a C1 version has no
before/after card, which she may notice.

---

## 8. Deviations from the approved design and decisions taken while building

### 8.1 Decisions
- **Records are created by `gameanything chat read`, not by the UI server.** The UI already writes the anchors (frames, `build_feedback.jsonl`,
  thread context); making the records there would put two writers on `records.yaml` and records without an interpretation would appear
  for words the resident has not read. `chat read` runs at the start of every resident run, so no anchored feedback is missed. Text-only
  messages need the resident's judgement (most are logistics), so they become records with `gameanything feedback add`.
- **One kind per record.** The design said "the same kind of complaint"; a primary kind per record keeps repeat detection simple and the
  labelling cheap; multi-label is a sensitivity analysis.
- **Mode craft notes** are a new lessons layer that does not exist yet; until it does, mode-scope experience goes into the role file
  with the mode in its text.
- **The profile page is a workspace screen (`#prefs`) linked from 开发状态**, not a new tab: the profile belongs to the user, not to one
  project, and the tab lists are per project kind.

- **Two units: version and delivery.** A milestone is often delivered several times (one project had result cards
  「电影版 2 / 3 / 4 / 5」 under one milestone). Repeats are computed per version (the unit of 7.2) and per
  delivery (each `result` card of a version; `feedback.deliveries`); both are logged. Result-card `milestone` labels that are
  free text (「第 3 期第 4 轮」) are mapped to the milestone by their number (`_ms_key`); labels that name none (「雕像 A」) are ignored.
- **Targets** come from her words first (project places, board moments, chapter titles, a small lexicon), then from the linked STATUS
  item's text, then from the anchor's chapter. In the backfill the chapter comes from the version's *final* play.yaml, which may be a
  later cut than the one she watched (a threat for anchored offline records; live records store the chapter at the time she spoke).
- **Profile filters.** The profile field for project kinds is `modes` (memory / adaptation / feature / gameplay); `kind` on a profile
  entry is the complaint kind it prevents (needed for the rule hit rate).
- **The keyword labeller** is a baseline only: one record per message (a message with two points keeps one kind), clarifications by her
  (「我发现…好像是水晶吊灯」) are filtered by a rule, logistics are skipped by a pattern.

- **Backfill is merge-only (2026-10-27, second pass).** The first version refused a project with records and `--force` replaced them;
  on a live project `chat read` keeps creating records, so the backfill now adds only the events that have no record (by event id),
  never changes an existing record (her confirmations, verdicts, the resident's readings), backs up `feedback/` first (without
  `frames/`, which nothing bulk writes) and is idempotent. `--force` is gone; `--dry-run` counts. Records are never deleted (1.4).
- **Labels side by side.** The approved design had one `labelled_by`; for agreement every labeller's labels must survive, so a record
  keeps `labels.<heuristic|resident|judge|judge_b|human:<name>>` and the live `class` / `kind` stay the resident's. Judge and human
  labels do not drive the system (they are for a study) unless imported with `--apply`.
- **The judge, the retrospective and the critic are agent steps, not headless model calls.** "Through the agent CLI / an approved path"
  (her rule) = request files answered by the agent on her own login, like perceive `--emit / --collect`; nothing in code calls a model
  or uses a key. The design's `roles/retrospective.md` / `roles/critic.md` became steps of `roles/builder.md` (step 0, step 1c) with
  the instruction to answer in a fresh context (a sub-agent), because the builder is already running with the right seat, data and
  login; a separate agentd run per step can replace it later without changing the files.
- **Independence of the critic.** The critic should not be the builder that made the version; a sub-agent given only the request file
  is the approximation. Whether the builder used one is not checked (a threat for M7).
- **No final metric (her decision, 2026-10-27).** Section 7.3 lists candidates; what is guaranteed is the raw data of 7.5 for both units
  (version and delivery), checked by `gameanything feedback datacheck`.
- **Study mode (2026-10-27, her rule).** The loop shipped first with the evaluation always on (blind conditions in every project, the
  judge card due once per project, the metrics log and panel everywhere). She asked for the study parts behind a switch, off by default,
  that does not change her experience. The split is section 0. Decisions: the switch is per project with a global default (a study can
  include some projects only); off means C4 for every version (not "no loop"), so the default product is the full loop; with it off the
  whole metrics log is silent rather than a subset (nothing the product reads comes from it: records, critic.yaml, retro/applied.yaml and
  the profile keep their own state), so a dataset never has half-logged versions; turning it off writes one closing `study` event; the
  panel is hidden rather than emptied, and the 「我的偏好」 button stays on the page; the judge card is refused by `chat card` itself so a
  resident following an old doc cannot send it. At the time of the change no live project had a `condition` event or a judge card.
- **The condition was removed from the 开发状态 page data** (`metrics()` returned it, the page did not show it, but it reached the
  browser). It is now only in `feedback/metrics.jsonl`.

---

## 9. Code map
| What | Where |
|---|---|
| study mode (the switch, its boundary events) | `gameanything/study.py`, CLI `gameanything project set-study / settings --study`; gates in `feedback.log_event / assign / peek / condition`, `judge`, `conversation.Thread.card`, `ui/screens.feedback_state` |
| records, channels, backfill, metrics, verification, brief, conditions, datacheck | `gameanything/feedback.py`, CLI `gameanything feedback …` (`cli.py`) |
| LLM judge (consent card, requests, collect), agreement (κ, α), human sheet | `gameanything/judge.py`, `gameanything feedback judge / agreement / label --human-sheet` |
| retrospective, critic, prediction matching | `gameanything/retro.py`, `gameanything feedback retro / critic / match`; agentd's retro note (`builds.Builds.retro_note`) |
| preference profile | `gameanything/profile.py`, CLI `gameanything profile …` |
| page data | `gameanything/ui/screens.py` (`feedback_state`, `profile_state`), routes in `gameanything/ui/__init__.py` |
| pages | `gameanything/ui/static/app.js` (`SCREENS.status` panel, `SCREENS.prefs`), `i18n.js` |
| logging hooks | `feedback.log_event`; agentd builds (`builds.py`), `build deliver` (`delivery.py`), `chat read` (`cli.py`) |
| agent docs | `skills/gameanything/core.md` (resident rule), `references/feedback-records.md`, `roles/builder.md` (verification), steps `*/feedback.md` |
| tests | `tests/test_feedback.py`, `tests/test_profile.py`, `tests/test_judge.py`, `tests/test_retro.py` (study mode on), `tests/test_study.py` (both states) |
