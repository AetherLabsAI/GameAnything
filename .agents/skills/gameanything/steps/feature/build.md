# Step build — 构建 (you, then the background builder)
Entry: she pressed 开工.
Do first: `gameanything status init --project "$P"` if 5_build/STATUS.yaml is missing, then `gameanything agentd request --project "$P" --kind build_start --text "…" --details '{"go_key": …, "milestone": "m1", "build_mode": …, "runner": …, "playtest_rounds": …, "items": […], "status": "5_build/STATUS.yaml"}'`. Tell her 「已经交给后台开工」. agentd checks the card and starts a builder; you never start or stop anything.
While it builds: pass each builder note on in one short line; her changes → `build_change` request.
When a note says done:
1. `gameanything build check --project "$P" --m <m>` (missing play.yaml / registration: `gameanything build deliver --project "$P" --m <m> --name "第 N 版 …"`, check again).
2. `gameanything status card --project "$P" --m <m> --image /build/<m>/… --out "$F"` (`F=$(mktemp)`) → `gameanything chat card`; then a task card `open: "#play/<m>"`.
Exit: delivered and the result card is out.
Mistakes: a result card while build check fails or without a play video; claiming 「检查通过」 before the check passed.
