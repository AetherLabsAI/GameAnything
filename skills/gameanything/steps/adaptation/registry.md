# Step registry — 地点登记表 (you)
Entry: adaptation.yaml exists. Usually fixed in the same run as extract.
Do: one entry in `places` per real place across all units: later names, plaque names and short names go into `aliases`; every scene's `place` is a place id (or a name / alias); buildables point at a listed place. Merge duplicates, keep the ids the scenes use.
```yaml
places:
  - {id: p03, name: 沁芳亭, name_en: Qinfang Pavilion, aliases: [沁芳桥, 沁芳泉]}
```
Then list what the text mentions but you did not extract (「提到了但没抽」) in the chat summary, so she can ask for it.
Exit: `gameanything flow check --project "$P" --step registry` passes.
Mistakes: the same place under two ids (the plan then builds it twice); a scene pointing at a place name that is not in the table.
