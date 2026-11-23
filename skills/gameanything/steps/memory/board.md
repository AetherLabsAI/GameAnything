# Step board — 整理这一天 (you)
Entry: people tagged (or no photos).
Do:
1. 3_remember/board.yaml (the 「这一天」 page reads exactly these fields):
   ```yaml
   experience_board:
     title: …
     skeleton: [{id: morning, what: 上午：出门和接亲}, {id: ceremony, what: 仪式}]     # the parts of the day, in order
     moments:                                                                       # in order
       - {id: m1, title: …, title_en: …, when: …, where: …, what_happened: …, quotes: [her words verbatim], source_refs: [pack ids],
          importance: must_preserve | important | optional | skip, segment: morning}  # segment = a skeleton id
   ```
   Every moment has `id`, `importance` and `segment` (not `weight`) and `source_refs` (the pack ids of its photos / videos: the page shows the first photo); every moment says where it comes from (a photo, her words, a transcript).
   Write the file with the file tools as ONE YAML document (never `cat >>`); `gameanything flow check` validates it.
2. What only she knows (who said what, why a moment matters, the order of the day): one `questions` card, partial answers are fine, every item with a `hint`.
3. One `task` card: open `#board`, key `board-review`: 「请到「这一天」确认时刻、顺序和每个时刻有多重要」.
Exit: board.yaml has moments and the task card is out (then she confirms: next step).
Mistakes: inventing quotes or facts about real people; editing her words (quotes are verbatim; your reading is a separate line); asking in plain text.
