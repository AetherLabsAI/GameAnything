# Step preview — 预览图和形象 (you, then her)
Entry: plan confirmed. Every version gets preview pictures before the build.
Do:
1. Jobs in 4_design/gen/previews.yaml (`out: previews`, `jobs: [{name, prompt, images}]`); `gameanything gen estimate --project "$P" --tool openrouter:edit --inputs …` (`gameanything gen list`).
   `permission` card (key `preview-permission`): what is sent, `to` the service, `files` = pictures it may send (her photos only if she ticks them). A drawing `go` card (key `preview-go`, `estimate` + `cost_usd` from the estimate, `max_images` ≤ 20). No faces of her family unless ticked.
2. Both yes: `gameanything gen request --project "$P" --tool <tool> --inputs 4_design/gen/previews.yaml --permission preview-permission --go preview-go`. Never run gen_*.py; say 「已经开始画了」.
3. The note says done: look at each picture yourself (logos, shop names, real faces, garbled text), then one `candidates` card per scene (A/B, media: image, /media/4_design/previews/…); she picks the look to build.
Landmark refs (2_perceive/landmark_refs, only after her websearch yes) may go to the drawing only if the permission card lists them.
4. Avatars / walking sprites (looks.yaml): a task card `open: "#people"` to check them.
Exit: she picked (or declined: skipped), and every look is seen.
Mistakes: pictures in an options card; drawing before the plan was confirmed; promising the game will look exactly like the picture.
