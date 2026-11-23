# Step copyright — 版权和底本 (you)
Entry: the work is ingested. Before any quote or extraction.
Do:
1. Say the copyright note in the chat, in one or two lines: public domain → word-for-word quotes are fine; copyrighted (modern novels, translations, films, anime, subtitles) → private use, only very short quotes, never whole passages in any prompt.
2. Write both fields into config/project.yaml:
```yaml
source: 《无人生还》(And Then There Were None)，阿加莎·克里斯蒂，1939（她自己的英文原著文件）
source_license: copyrighted（私人自用；原文只做很短引文）
```
3. If the edition is unclear (which translation? which cut?), ask with a `questions` card, key `source`, each item with a `hint` default.
Exit: `gameanything flow check --project "$P" --step copyright` passes.
Mistakes: skipping the note because she did not ask; writing source_license only in adaptation.yaml (the flow reads config/project.yaml).
