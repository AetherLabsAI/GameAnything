# Step next_round — 下一版 (you)
Entry: she picked what the next version does (or wrote it).
Do:
1. Add the next milestone to 4_design/world_plan.yaml (`m2: {status: next, name: 第 2 版 …, what, what_en}`; keep the other milestones, their status and comments). She picked 带回家: set `final: {status: next}` instead.
2. Say in one line what the next version will do; the flow then starts again at design (plan → confirm → preview → go → build) for this milestone only.
Exit: the next milestone is in world_plan.yaml.
Mistakes: building again with the old go card (each go card builds once); skipping the plan confirmation for the new version.
