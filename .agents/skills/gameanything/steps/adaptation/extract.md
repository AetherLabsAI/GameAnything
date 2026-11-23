# Step extract — 抽取场景 (you)
Entry: she picked the units; read only those.
Do:
1. Write 3_remember/adaptation.yaml (only you). Shown fields in both languages (`title`+`title_en`, `what`+`what_en`, `name`+`name_en`); quotes: original word for word in `text`, plus `text_zh` / `text_en`:
```yaml
work: {title: 无人生还, title_en: And Then There Were None, type: novel, units: [第二章, 第三章]}
scenes:
  - {id: s02-01, unit: 第二章, title: 奥克桥站, title_en: Oakbridge station, place: p-station, what: …, what_en: …, characters: [薇拉],
     quotes: [{text: "I haven't even seen my employer yet.", text_zh: 我连雇主都还没见过。, where: 第二章}],
     frames: [{file: 2_perceive/keyframes/<video>/k003.jpg, t: 6.2}]}
places:
  - {id: p-station, name: 奥克桥站, name_en: Oakbridge station, aliases: [], described: […], not_described: [站台长度],
     build: [{name: 站台, name_en: Platform, kind: structure, grounding: explicit, quote: …}]}
```
2. Quotes must be in the text; not found → delete, never "fix".
3. Video in the work: `gameanything visuals --project "$P"`, read 2_perceive/keyframes/index.yaml (shots + `said`), link `frames` to scenes, then a `questions` card, items with `image: /media/2_perceive/keyframes/…`.
4. `gameanything flow check --project "$P" --step registry`: fix places.
5. Send a task card: `kind: task, key: scenes-review, open: "#home"`, body: what to review on 场景.
Exit: `gameanything flow check --step extract` passes (english is a warning).
Mistakes: only Chinese; frames in an options card (no pictures there).
