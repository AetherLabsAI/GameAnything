# Step ingest — 整理素材 (you)
Entry: files in 0_inbox (only then; a feature from her words alone skips this step).
Do:
1. `gameanything ingest "$P/0_inbox" --project "$P"` (local only), then feedback/ingest_request.yaml `state: done`.
   Optional features: when its output says one is not installed (`transcribe` (speech in videos)), run `gameanything extras install <name> --project "$P"` once: it posts the card that asks her (what it is for, how big; exit 2 = waiting, carry on without it). After her 「装吧」 run it again (exit 0 = installed), then run the ingest line again: it fills in only what was skipped. Exit 3 = she said not now (carry on, do not ask again) or the install failed (tell her in one line what it printed, carry on).
2. One line to her: what was found (N photos of dishes, a recipe page).
Looking at photos with a model needs a `permission` card first (what is sent, to whom), logged in privacy_ledger.yaml.
Exit: pack.yaml has the items; ingest_request state done.
Mistakes: sending anything to a model here; leaving ingest_request pending; `pip install` / `uv pip install` of an optional feature yourself (only `gameanything extras install`, after her card).
