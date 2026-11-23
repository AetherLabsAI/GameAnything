# Step preview — 预览图 (you, then her)
Entry: plan confirmed.
Do:
1. Jobs in 4_design/gen/previews.yaml (`out: previews`, text prompts only), `gameanything gen estimate --project "$P" --tool <adapter>:image --inputs …`. `permission` card (key `preview-permission`): what is sent (text descriptions only, no copyrighted passages), `to` the service, cost. And a `go` card for the drawing round (key `preview-go`, `estimate` + `cost_usd` from the estimate).
2. When she said yes on both: `gameanything gen request --project "$P" --tool <adapter>:image --inputs 4_design/gen/previews.yaml --permission <key> --go <key>`. Never run a gen_*.py yourself.
3. agentd sends you a note when done: look at 4_design/previews/, send one `candidates` card per place (media: image, key `preview-<place>`, urls /media/4_design/previews/…).
Real public places in the work with too few pictures: ask first (`websearch-<place>` card), then `gameanything refs fetch` (references/landmark-references.md); refs may go to the drawing only if the permission card lists them.
Exit: she picked (or declined the permission: the step is skipped).
Mistakes: pictures in an options card; asking for API keys; running gen_*.py.
