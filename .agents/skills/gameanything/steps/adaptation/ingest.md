# Step ingest — 整理作品 (you)
Entry: files in 0_inbox; feedback/ingest_request.yaml state pending.
Do:
1. `gameanything ingest "$P/0_inbox" --project "$P"` (local only: text, traditional → simplified, video frames + local transcript). Long: tell her one line first.
   Optional features: when its output says one is not installed (`transcribe` (speech in videos)), run `gameanything extras install <name> --project "$P"` once: it posts the card that asks her (what it is for, how big; exit 2 = waiting, carry on without it). After her 「装吧」 run it again (exit 0 = installed), then run the ingest line again: it fills in only what was skipped. Exit 3 = she said not now (carry on, do not ask again) or the install failed (tell her in one line what it printed, carry on).
2. Set feedback/ingest_request.yaml `state: done`.
3. Tell her what was found (chapters, a video of N s) in one line. A video gets more later (keyframes in extract).
Exit: pack.yaml has the items; ingest_request state done.
Mistakes: sending anything to a model here; leaving ingest_request pending (the page keeps saying 「agent 正在整理」); fixing a tool by installing system packages yourself (ask the coordinator with a `question` request); `pip install` / `uv pip install` of an optional feature yourself (only `gameanything extras install`, after her card).
