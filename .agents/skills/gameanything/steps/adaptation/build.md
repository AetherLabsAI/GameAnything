# Step build — 构建 (background builder)
Entry: she pressed 开工. First: `gameanything status init --project "$P"` if needed, then `gameanything agentd request --project "$P" --kind build_start --text "…" --details '{"go_key": …, "milestone": "m1", "build_mode": …, "runner": …, "items": […], "status": "5_build/STATUS.yaml"}'`; tell her 「已经交给后台开工」. agentd checks the card and starts a builder; you never start or stop anything.
Then: answer her questions from `gameanything status show --project "$P"` and the building banner. Builder / background notes: tell her in one short
line (started, round N, waiting for a sandbox seat and why, blocked and why). Her changes while it builds: `build_change` request (details
`milestone`, `change`; more rounds: `playtest_rounds`). When a note says the build is done:
1. `gameanything build check --project "$P" --m <m>`; if only play.yaml / registration is missing: `gameanything build deliver --project "$P" --m <m> --name "第 N 版 …"`, check again.
2. `gameanything status card --project "$P" --m <m> --image /build/<m>/… --out "$F"` (`F=$(mktemp)`) → `gameanything chat card`.
3. Video missing or broken: no result card; send a `question` request and tell her plainly.
4. A note says it was interrupted / stopped / not delivered: say so plainly; a new round needs a new go card (each go card builds once).
Exit: delivered and the result card is out.
Mistakes: a result card from memory; posting while build check fails.
