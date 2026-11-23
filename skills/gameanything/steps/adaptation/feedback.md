# Step feedback — 试玩和意见 (her)
Entry: the result card is out; she watches on 试玩.
Do: her comments become items in 5_build/STATUS.yaml (`gameanything status set-item` / `feedback --add-event`); answer each; changes to a running build go as `build_change` requests. In the run that posts the result card, also send an `options` card (key `next-round`): what the next version does (more chapters, characters and story, polish; each with its cost, one recommended; `en:` too).
Exit: she picked on the card (or wrote what she wants), or the milestone is accepted.
Mistakes: promising changes without recording them; starting the next round without her choice.
Records (references/feedback-records.md): each comment of hers is one `gameanything feedback` record with your reading, linked to its STATUS item; unsure readings go to her on the confirm card first. In the run that posts the result card, also send the verify card (`gameanything feedback card --kind-of-card verify --m <m>`) when the version has before / after pairs, and record her answers (`gameanything feedback verdict`, `gameanything feedback accept` when she accepts the version).
