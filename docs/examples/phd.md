# PhD: The Spire — doing a PhD as a Slay the Spire character

**Mode:** Gameplay · **Game:** Slay the Spire (character mod)
**What came in:** my design notes about what a PhD feels like: long effort, uncertain feedback, and a few well-known jokes from research life.
**What came out:** four versions. Version 1 was a playable character with a full deck but felt "just like normal Slay the Spire". I asked for a redesign, and from version 2 on one run is one paper submission, from the first experiment to the reviews, the rebuttal and the decision.

---

## Material in: what the agent understood

🧑 **You:** *(uploads my design notes)*

🤖 **Agent:** Hi, I'm this project's agent. Gameplay mode turns the *meaning* of an experience into the game's own mechanics, in three steps: (1) we agree on the experience → mechanic mapping; (2) we fix a small first scope and a content list (cards, relics, enemies, events, boss); (3) I build it as a Slay the Spire character mod, play it myself and run balance simulations.
I read your notes. The core tension as I see it: long investment versus uncertain feedback. Failed experiments still build understanding, but the value only pays out once you go all the way from idea → experiment → evidence → writing → submission.

🃏 **Card — 6 questions only you can answer** (answer any)
What fills a typical day? · The hardest moments? · The best moments? · Inside jokes you want in? · What should a player feel at the end? · Anything to keep out?
→ answered:
- *Day:* reading papers, running experiments and waiting for results, fixing bugs, writing, group meetings. Also chatting with labmates, and recharging with sport, TV shows and crafts.
- *Hardest:* rejections, long stretches with no progress, a low score from an AI reviewer.
- *Best:* an acceptance, GitHub stars and citations going up, someone saying "great work".
- *Jokes:* Reviewer 2, getting scooped on arXiv, AI reviewers, running out of tokens again.

🤖 **Agent:** These map well:
- chatting with labmates → discussion cards that give **Insight**; sport, shows and crafts → cards and a rest-site option that lower **Stress** (the core of a sustainable play style)
- rejection → if **Submit** falls short it's *Rejected*, but you keep part of the progress and can resubmit; no progress → an enemy called **Plateau**; the low-scoring AI reviewer → an enemy **AI Reviewer** (a tool, not a person)
- acceptance, stars, citations → **Citations** that build up during a run and make later submissions stronger
- out of tokens → a cheap "Ask an LLM" card with a per-fight quota

Enemies and bosses are always *things* (Bug, Scope Creep, The Deadline), never people.

🃏 **Card — Mechanics page: confirm each mapping** (23 experience → mechanic rows, 4 resources: Insight / Evidence / Paper Progress / Stress, 5 play styles)
→ kept **23/23**

🃏 **Card — Version 1 scope, as I understand it**
1 character, *The Researcher* (72 HP, starting relic Lab Notebook) · about 30 cards across Theory / Experiment / Collaboration / Engineering · 9 relics · 7 events (3:17 AM, scooped on arXiv, "one small change", "this should be easy", "great work!", out of tokens, a vacation) · 5 enemies + elite Scope Creep · 1 act, boss **The Deadline** with a turn countdown · later: qualifying exam, committee, graduation, acts 2–3
→ **OK**

🤖 **Agent:** The heart of it is the paper pipeline: **Run Experiment** (success gives Evidence, failure gives Insight) → **Write Draft** (Evidence becomes Progress) → **Submit** (8+ Progress is *Accepted*; less is *Rejected* and you keep half). Against The Deadline, one acceptance inside the countdown weakens it; miss it and you enter *Crunch*.

🃏 **Card — Content page: review every item** (33 cards + 5 status cards, 10 relics, 7 events, 6 enemies, boss)
→ kept **62/62**

🃏 **Card — Permission: generate the card art, relic icons and enemy portraits** (text prompts only; hand-painted watercolour with bold outlines; no real people, labs, schools or logos; about 51 images)
→ **Yes**

🃏 **Card — Art picks (4 cards: basic & common cards · uncommon & rare · relics · enemies, boss and character)**
→ 🧑 **You:** These all look fine, use them directly.

🃏 **Card — Go: version 1** (character, 33 cards, 10 relics, 7 events, 6 enemies, The Deadline; the agent plays full runs and runs balance simulations; up to 3 rounds with an independent playtest review between rounds)
→ **Start**

## Version 1

🤖 **Agent:** Round 1: the whole act is playable, but balance is bad: 0 wins out of 20 simulated runs, dying around floor 6. Part of that is the simple bot submitting with no Progress, but Plateau and Scope Creep really are too strong.
The independent reviewer then played two full runs by hand. Good: the Experiment → Evidence → Draft → Progress → Submit chain works and the first *Accepted* (40 damage, +1 Citation) feels great; the PhD flavour reads through every name. Stuck: Scope Creep ends runs, and 5 turns is too short for The Deadline.
Round 2 fixed those (Deadline countdown 8, more Evidence sources, gentler rejection, a "Take a vacation" rest option): win rate 25%, and the reviewer beat The Deadline twice. Round 3 made it a little harder again, made Stress carry over between fights (so vacations and the "sustainable" style matter), and added our own **"You graduated!"** ending.

🎬 **Version 1 delivered.** One playable act with The Researcher, all confirmed content in (62/62 content items), our own graduation screen. Simulated: 10% win rate over 20 runs. Video **3:48**, a bot playing a full run.

🖼️ *The graduation screen:* a gift-wrapped thesis on a desk next to a laptop and a server rack, with the line "The Deadline ticks to zero and nothing explodes. Your paper is out…"

🧑 **You:** This video doesn't work at all. It's just cards being played one after another. I have no idea what's going on, and there's no sense of story or strategy. Watch it yourself, how does it feel?

🤖 **Agent:** You're right, it feels like that to me too. It's just a bot playing fast and nothing explains what a card does, why it's played, or which PhD moment it stands for.

🃏 **Card — Re-make the playtest video like this?**
A: slower pace, one caption per key decision, PhD-story chapter cards, event text shown, cut to about 3 minutes · B: I also want…
→ picked: **A**

🎬 **Narrated video delivered.** **3:20** highlight (plus an 18-minute full run), 5 chapters: *finding a problem → experiments and writing → reviewers → the deadline → graduation*. Each key move has a caption like "Run Experiment → Evidence +2: the experiment worked".

🧑 **You** *(0:23)*: The card text has far too little contrast. I can't read it.
🧑 **You** *(1:17)*: I can't really tell what this enemy is supposed to be.

🤖 **Agent:** The card frame we drew made the text box off-white, and the game writes off-white text on it. I'll switch to a dark translucent box. The enemy is Scope Creep (a vine monster made of sticky notes): no face, no clear outline, and nothing on screen says its name.
→ I picked the dark text box; the enemy art waits until the redesign.

🧑 **You:** Honestly, the design itself is boring.

🤖 **Agent:** I see it too: every fight is "collect resources → deal damage", the paper and the story stay off the table, and there are few real trade-offs.

🃏 **Card — What feels most boring?** (multi)
No real decisions · cards all feel alike · fights drag · it doesn't feel like a PhD · enemies have no character
→ picked: **doesn't feel like a PhD, enemies have no character, cards all feel alike**

🃏 **Card — Which direction?** (multi)
A run is writing one paper · real dilemmas · memorable big moments and combos · events that form a storyline · I'll explain
→ picked: **real dilemmas + memorable moments and combos**

*(The agent drafted a redesign. I wrote my own redesign notes on top of it and asked the agent to work out what has to change.)*

## Version 2: one run = one paper submission

🃏 **Card — Version 2 change list, from your notes**
- A run is one submission: map → **Deadline 11:59 AoE** (replaces the old boss) → *Reviews are out* → **3 turns of Rebuttal** → *Accept* / *Reject & Resubmit* / *Desk Reject*
- **Submit** is no longer a damage card: the fight stops, the screen dims, "Under Review", then three reviewer scores pop up
- **Rebuttal**: no monsters, only response cards (Clarify, Cite Section, Run Additional Experiment, Add Ablation, Admit Limitation…); Reviewer 2 might add three new concerns, or there's radio silence
- *Accepted* comes with a light "72-hour camera-ready" event before the final screen
- Resources: Evidence, **Paper** (four sections: Intro / Method / Experiments / Analysis) and Stress; Citations removed
- An always-visible paper panel (title, venue, countdown, section progress, Stress bar); the background shifts from day office → late-night lab → 3 AM screen glow → red countdown
→ **OK**

🃏 **Card — 5 things to decide**
→ use a real venue name (NeurIPS) · hide Insight inside card conditions · draw 4 new backgrounds · drop "Ask an LLM" · Desk Reject only as a small chance when figures or page limits weren't fixed

🃏 **Card — Mechanics page (15 rows) and Content page (23 cards + 8 rebuttal cards + status cards, 6 relics, 5 enemies, 10 events + 5 story moments)**
→ kept **15/15** and **69/69**

🃏 **Card — New art picks** (after a permission card: 4 backgrounds, 2 new enemies *Unexpected Baseline* and *Dependency Hell*, a redrawn Scope Creep with a face, a group of three reviewers, 12 new cards like *rm -rf results/*, *Works on My Machine*, *Future Work*)
→ kept **all 20**

🃏 **Card — Go: version 2** → **Start**

🤖 **Agent:** Round 1: the whole submission flow runs, and all three endings were reached. The reviewer found 2 serious and 9 larger problems; round 2 fixed them all, made every play style able to get accepted, and turned *Accepted*, Reviewer 2's "18 hours left" and *Radio Silence* into full-screen moments.

🎬 **Version 2 delivered.** One run = one submission, with the paper panel, the deadline, reviews, rebuttal and three endings. Requirements done **4/4**. Simulated 32 runs: 41% accepted, and all four play styles can get accepted. Video **3:52** highlight (6 chapters) + **19:48** full run, captioned.

🖼️ *Accepted screen:* a dark panel under an "ACCEPTED" banner with the paper title, "NeurIPS – Accepted (poster)", three reviewer scores and the advisor's reply "Great. The next deadline is in 11 weeks."

🃏 **Card — What next?**
Polish feel and visuals · add content · tune balance · take it home
→ picked: **polish**

🃏 **Card — Version 3 polish list** (multi)
Bigger hand · status-card text hidden by the hand · hit / block / Stress / Evidence feedback · paper panel and clock animation · phase transitions and ending scenes · unified card frames (needs new art) · enemy idle and attack motion · event layout · test rarely-seen relics
→ picked: **everything except new card frames** (no new art this time)

🧑 **You:** Also, NeurIPS uses a 6-point scale. Your scores are wrong.

🤖 **Agent:** You're right, it's out of 10 now. I'll switch to the 6-point scale and convert the thresholds so the odds of each ending stay about the same.

## Version 3: polish

🎬 **Version 3 delivered.** Scores on the NeurIPS 6-point scale (accept line: average 4.5). Bigger cards that lift on hover; a separate slot for "Major Concern"; red flash and damage numbers on hits, blue for block, purple for Stress, gold for Evidence, each with a sound; the paper panel fills section by section and the deadline clock runs smoothly; step bars for submit → review → rebuttal; enemies breathe and lunge. Requirements done **5/8** (3 partial: a few hand-layout edge cases, sound only checked for volume). Video **3:54** highlight + **18:52** full. In the recorded run the paper is accepted with 5.5 / 3.5 / 6.

🃏 **Card — What next?**
→ picked: **keep polishing**, with a note: *make all the text English*.

🃏 **Card — What exactly goes English?**
→ picked: video captions and chapter cards · playtest and balance page notes · in-game text stays English · fix the last line of *Write Draft* touching the next card · show more of the side cards when the hand has 8–10 cards

## Version 4: English and layout fixes

🎬 **Version 4 delivered.** Captions, chapter cards and page notes in English; the in-game text stays English; with 5 cards, *Write Draft* is fully readable, and with 8–10 cards the side cards show much more. A small follow-up fix starts the hand to the right of the energy orb so nothing is covered. Requirements done **6/7** (one layout check not re-captured). Video **3:55** highlight + **18:52** full.

---

**What this example shows:** in Gameplay mode you first agree on *what the experience means* and how that becomes a mechanic, then on the content. The first version was technically complete but felt like a reskin; saying "this is boring" plus two short choice cards led to a redesign where the game's structure itself tells the story: a run is one paper, from the first experiment to the reviewers' verdict.
