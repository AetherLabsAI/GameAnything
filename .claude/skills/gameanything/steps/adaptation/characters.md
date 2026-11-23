# Step characters — 整理人物 (you)
Entry: scenes confirmed.
Do:
1. `characters` in adaptation.yaml: `name`/`name_en`, `role`/`role_en`, `looks` and `lines` as quotes with `where` (or `grounding: invented` for what the text does not say), `aliases`. Every quote has `text` (the original line, or your invented description; never only `text_zh` / `text_en`).
```yaml
characters:
  - {name: 薇拉, name_en: Vera Claythorne, role: 年轻的家庭女教师, role_en: young governess,
     looks: [{text: "…", text_zh: …, where: 第一章}], lines: [{text: "…", text_zh: …, where: 第二章}],
     image: 2_perceive/people/c03/001.jpg, frames: [{file: 2_perceive/keyframes/<video>/k011.jpg, t: 21.5}]}
```
2. Video in the work: `gameanything visuals` made 2_perceive/people/index.yaml (clusters by look; nobody is identified). Match clusters to characters by the transcript near their frames and her naming; send a `questions` card with `image: /media/2_perceive/people/cNN/001.jpg` per item («这是谁？»).
3. Task card: `kind: task, key: characters-review, open: "#people"` — she reviews 角色 and clicks 「确认人物」.
Exit: `gameanything flow check --step characters` passes.
Mistakes: names only; a character picture sent in an options card; guessing who a face is without asking her.
