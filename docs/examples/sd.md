# Example: My San Diego Memory

**Mode:** Memory · **Game:** Cities: Skylines
**What came in:** my photos from my years in San Diego, plus a few sentences about the places that mattered to me.
**What came out:** a city built on the real San Diego coastline, delivered over 7 versions. Versions 1–3 built five places along the coast, and versions 4–7 added the UCSD campus. The later versions come with a walkthrough video.

---

## Getting started: material in, places out

🧑 **You:** Please sort through the photos I just uploaded.

🤖 **Agent:** All your photos are here. I've sorted them on this machine and nothing has been sent anywhere. Can I look at what's in them? I'll look at scenes and places only. I won't try to identify anyone.

🃏 **Card — Can I look at your photos?**
Yes · No
→ picked: **Yes**

🤖 **Agent:** Done. Going by the pictures, they group into a few places: a harbor with a giant statue and an aircraft carrier, a seaside park, rocky cliffs with sea lions and a small cove, a sunset over a shopping-center parking lot, and a park with domed buildings and a long reflecting pool. A few things I can't tell from the photos: where these are, what kind of city you want, and which places matter most.

🧑 **You:** The sea lions and cliffs are La Jolla Cove. The seaside park is La Jolla Shores, and the domes are Balboa Park. The coast matters most to me: the ocean at sunset, on sunny days and at sunrise. I want a "my San Diego" I can walk around in, with the harbor, the coast and the park.

🤖 **Agent:** Got it. And the parking-lot sunset?

🧑 **You:** That's UTC, the shopping mall nearby. Put it in too.

🤖 **Agent:** That gives five places: **the Harbor**, **La Jolla Cove**, **UTC**, **Balboa Park**, and **a drive along the coast**. You marked all five as must-keep. La Jolla Shores is skipped. Next come three design choices.

🃏 **Card — What should the city look like?**
A: Follow the real coastline (recommended) · B: A small town with the places close together
→ picked: **A**

🃏 **Card — How do you explore it?**
A: One "memory camera" per place that flies there and slowly circles (recommended) · B: Only the built-in camera
→ picked: **A**

🃏 **Card — How should time of day work?** *(multi-choice)*
A: Follow the game's day/night cycle · B: One click to switch to sunset / sunrise / clear day · C: Always sunset
→ picked: **A + B**

🃏 **Card — Here's my understanding, edit anything that's wrong**
A city on the real coastline: the Harbor in the south, La Jolla to the north, UTC inland, Balboa Park next to downtown, with real roads between them. Harbor: aircraft carrier, the big statue, benches facing the bay. Cove: cliffs, sea lions on the rocks, a small bay at dusk. UTC: shops along an open-air street. Balboa Park: domes, reflecting pool, white balustrade bridge, shell fountain, white colonnade. One memory camera per place. Day/night cycle plus quick time switches.
→ **Looks right**

## Planning: references, trade-offs, targets

🤖 **Agent:** Some places aren't well covered by your photos. Should I find public reference photos of the landmarks? I'll take buildings and scenery only, no people, and use them only to check shapes.

🃏 **Card — Search for public reference photos?** *(multi-choice)*
UTC · Harbor · Balboa Park · La Jolla Cove · None
→ picked: **all four**. I then unticked a few of the photos it found and kept 14.

🃏 **Card — Scale?**
A: Shrink the whole coast (about 22 km) to fit the map, with buildings at normal size (recommended) · B: 1:1, but some places get cut off · C: Ignore scale, move places closer together
→ picked: **A**

🃏 **Card — The game has no aircraft carrier or Balboa domes. Where do landmark models come from?**
Built-in assets only · Ready-made Steam Workshop models · A mix of both
→ picked: **Workshop**, with a note: *"Why can't you build them yourself, or subscribe for me? I want this to be fully automatic."*

🤖 **Agent:** Both can be automatic. Our mod can subscribe through Steam, so you only approve the list once. I can also generate 3D models for anything the Workshop doesn't have.

🃏 **Card — Subscribe for you, or build it myself?**
A: I subscribe for you · B: I build it myself · C: Mix (recommended)
→ picked: **Mix, and you do the subscribing**

🤖 **Agent:** Honestly, the Workshop has no actual USS Midway, California Tower or kissing-sailor statue. I found close stand-ins: a similar US carrier, Spanish Revival shops and houses, a domed botanical building and a lifeguard tower. They're models only, no code. I'll build the rest myself: the statue, the tower, the sea lions and the UTC mall.

🃏 **Card — Workshop list: tick what I should subscribe to**
7 candidates
→ picked: **5**. The agent subscribed and confirmed every item installed.

🃏 **Card — La Jolla Shores was skipped, but the coast road runs past it. How should I handle it?**
A: Keep the real terrain, no memory camera (recommended) · B: Plain coastline · C: Add a memory camera after all
→ picked: **A**

🤖 **Agent:** Next I'll draw a "target picture" for each place, showing what it should look like in the game. I'll only send public reference photos and a few of your landscape shots, never photos with people in them.

🃏 **Card — Target picture per place (2 options each)**
Harbor A/B · Cove A/B · UTC A/B · Balboa A/B · Coast drive A/B
→ picked: Harbor **A**, Cove **B** (looking along the cliffs at sea lions), UTC **A**, Balboa **B** (from the end of the pool), Drive **A** (road curving around the bay at sunset).

🧑 **You** *(on UTC)*: Why are there no shop names or logos? Look up which stores are actually at UTC and add them. Otherwise it doesn't feel real.

🤖 **Agent:** Will do, as plain text signs with no copied logos. I checked the mall's official directory.

🃏 **Card — Which UTC stores should get signs?**
16 stores from the mall directory
→ picked: **15**

🃏 **Card — Go: Phase 1 build**
Terrain from public elevation data · roads from OpenStreetMap · all 5 places · memory cameras · time switches · store signs · a new save that overwrites nothing · side-by-side comparison with the target pictures
→ **Start**

## Version 1: the first city

🎬 **Version 1 delivered.** Terrain, sea, the road network, all five places, memory-camera buttons and 15 UTC store signs, saved as a new city. No video this time, only side-by-side comparisons against the target pictures. The agent graded each place against its target picture (out of 10): Harbor 7, Cove 5, UTC 5, Balboa 5, Drive 5.

🤖 **Agent:** Honestly, it's still far from the targets. One mid-build fix helped: the starting map was desert-themed, so the ground looked like sand. I rebuilt on a temperate map. The remaining gaps: grey water, no paving, no pale sandstone on the cliffs, and placeholders for the sea lions and the tower.

🧑 **You:** Fix the water colour and paving, even if it means changing the mod code. And why are the buildings so dull? It doesn't feel busy at all. UTC is grey and sparse, nothing like a shopping district. Why are there no sea lions at the Cove? Overall it's still ugly, and the whole image looks hazy and grey.

🤖 **Agent:** Three causes. The buildings are the game's plain grey-beige models, there are only about 1,000 of them, and colour grading is off. UTC has only 24 shops. The game has no sea-lion model. The haze can be fixed with a more vivid colour grade and warmer sunlight.

🃏 **Card — How should Phase 2 go?** *(multi-choice)*
A: Mod code for paving, sand, water colour and colour grading · B: Several times more buildings, with UTC as a continuous shopping street · C: Real 3D models for the sea lions, the tower and the statue · D: Leave it, I'll play the save first
→ picked: **A + B + C**

🧑 **You:** I have an account with a 3D-model generator. You can use that.

🃏 **Card — Which 3D models should I generate?**
Sea lion · California Tower · kissing-sailor statue · Balboa botanical building · None
→ picked: **all four**. The agent sent text descriptions only, no photos.

## Version 2: colour, density, first 3D models

🎬 **Version 2 delivered.** The sea is now blue. There are about 2,400 buildings (up from about 900). UTC is two continuous rows of about 60 shops. The Cove has a sea-lion colony, and Balboa has a recognisable tiled-dome tower. Still no video. Grades: Harbor 6, Cove 4, UTC 5, Balboa 5, Drive 4.

🤖 **Agent:** The image is still too dark, the walkways look like asphalt, and the sea lions are tiny in the shot. I tried two more rounds of brightening, but they scored lower, so I kept the best version.

🧑 **You:** Why can't I see the sea lions at the Cove? UTC looks busy now but it has no landmark, so you can't tell at a glance that it's UTC. Balboa Park looks nothing like it. Where's the domed botanical building? The white balustrade by the pool? The buildings look like a row of bungalows, not the ornate Spanish-style buildings in the park, and there's no fountain. Once the scenery is better, put people in too: surfers and sunbathers by the sea, shoppers with cold drinks and ice cream at UTC. And add more buildings and props so the scenes feel fuller.

🤖 **Agent:** Here's the plan. Move the sea lions closer and make them larger. Add a UTC entrance tower and main mall building. Add the botanical dome, white railings, a fountain and ornate arcade buildings at Balboa. Generate several kinds of people: surfers, sunbathers, shoppers with tea or ice cream, and a family.

🧑 **You:** Go.

## Version 3: the walkthrough video

This version went through several cuts based on my notes on the video.

**Rounds 1–2.** Balboa improved the most: blue pool, white railings, the domed botanical building, and the ornate arcades. The sea lions now lie in groups on the rocks.

🃏 **Card — Kissing-sailor statue: 3 untextured previews, pick one**
A: Realistic bronze, white dress · B: Classic pose on a granite plinth · C: Low-poly
→ picked: **A**. From here on, the agent shows previews before finishing any 3D model.

🧑 **You:** Why is the Balboa fountain *in* the pool?! Search the web for more photos of these places. Right now none of them look right!

🤖 **Agent:** You're right, I placed it wrong. The fountain belongs on the plaza next to the pool. I found more public photos and re-laid out every place from them. Balboa now matches: a long north–south pool, the botanical building at the north end, arcades on the west side, the fountain on the south plaza, and the tower.

🧑 **You:** The beach looks stiff. Polish everything you've noticed yourself, and next time give me a **video** on the playtest page!

🎬 **Cut 1:** a 55-second fly-through of the five places, with one chapter per place. The Cove beach was rebuilt along the real shoreline with a white foam line.

🧑 **You** *(at 0:15, Cove)*: Why is the beach so empty? Not enough sea lions, hardly any people.
🧑 **You** *(at 0:33, UTC)*: Where's the UTC landmark? It's two bungalows next to a street. UTC doesn't look like this at all, and the anchor stores are missing.
🧑 **You:** The video is too fast and rough to see any detail. I want a highlight shot for every place.

🤖 **Agent:** Agreed. Each place got only 8 seconds and the recording was choppy. I'll render frame by frame at a smooth 24 fps, slowly push in on each place, and then hold on a highlight shot. The Cove now has about 190 sea lions, around 100 people, gulls, rocks and lifeguard towers. Other places got more people too.

🃏 **Card — UTC buildings (previews)**
Two department stores · glass-box store · row of two-storey shops · ice rink · cinema
→ picked: **everything except the ice rink**

🎬 **Cut 2:** a 130-second "cinematic" version with a slow push-in and a highlight hold for each place.

🧑 **You** *(0:48)*: Why are the sea lions white? They should be dark grey.
🧑 **You** *(1:40, Balboa)*: What's in the pool? Is someone standing in it?
🧑 **You** *(2:06, Drive)*: Can the coast drive follow a car the whole way?
🧑 **You:** Why is everyone standing still? And why does the camera keep shaking?
🧑 **You** *(0:55, UTC)*: This is completely wrong and ugly. Where are Macy's, Nordstrom, Apple, the hotpot and tea shops? Find UTC's real layout from above and what each store looks like, then build from that.

🤖 **Agent:** I fixed the sea-lion colour and moved the visitors out of the pool. I also built UTC from its real footprint in OpenStreetMap: Nordstrom in the northwest, Macy's at the south end, the parking structures, and the open-air street that splits in two. The shake came from timing, so recording is now fully frame-locked.

🧑 **You:** It's still ugly! Stores are recognised by their **buildings and signs**. Do you really think a huge word floating over every building looks good?
🧑 **You:** And the aircraft carrier deck is bare. Look at real photos, it's full of aircraft. Redo it.

🤖 **Agent:** Fair. I'm replacing the floating words with storefront signs in each brand's colours. I tried generating store buildings from text, but the results were generic.

🧑 **You:** Completely wrong! Find real photos online first, *then* generate.

🤖 **Agent:** I gathered openly licensed photos of each store and of the real aircraft on the Midway's deck. First attempt: the aircraft came out great, but most stores failed. The generator picked up whatever stood out in each photo, like a parked car or a tree. I cropped every photo down to the facade and re-ran it, and 9 stores came out usable. For the failures I'm using procedural facades with brand signs. The carrier deck now holds 30 aircraft of 7 real types, plus vehicles and crew.

🎬 **Cut 3:** 134 seconds. Real-looking storefronts at UTC, a full carrier deck, and a car-follow camera on the coast road.

🧑 **You:** It's getting good, only a few small things left. 1) People still don't walk, especially at the harbor. 2) Don't caption what I said about each place. Place names are enough. 3) UTC ends before I can see anything. I never saw the stores. 4) The coast drive is very shaky.

🤖 **Agent:** All four are fixed. About 600 people now walk, and surfers bob in the waves. Captions show only place names. UTC is a 69-second street-level walk past each store. To stop the flicker on the drive, I record at 2× resolution and scale down.

🎬 **Cut 4:** 177 seconds.

🧑 **You** *(1:01)*: Macy's flashed past before I saw the front.
🧑 **You** *(1:07)*: What is this place?
🧑 **You** *(1:13)*: The hotpot place is filmed crooked, and it doesn't look like the real one. Look up what the one at UTC actually looks like.
🧑 **You** *(1:25)*: Why is the tea shop's sign full of gaps? Something's wrong with the model.
🧑 **You** *(1:49)*: Look at this Apple store yourself. It doesn't feel like a glass building at all.
🧑 **You** *(1:53)*: I can't see the Nordstrom sign. Which one is the department store?
🧑 **You** *(2:36, 2:46)*: What's this, is it clipping? The cars are clipping too, and the camera is still shaky.

🤖 **Agent:** 1:07 is the ice rink, and nothing in the shot explained it. I'll label it **UTC Ice** and pave the empty grass. The clipping at 2:36 was my mistake: the closer camera I added for UTC also applied to the drive and flipped the camera. Now each chapter uses its own camera. I found photos of the hotpot restaurant at UTC itself and rebuilt it from them. The Apple store is now a real glass box with thin white frames. I put a big sign over the Nordstrom entrance, and the camera holds on the Macy's and Nordstrom facades.

🃏 **Card — Rebuild from these real UTC photos?**
A: Yes · B: Find clearer photos first
→ picked: **A**

🧑 **You:** Show me the preview first. Why is the rink roof a grey-and-white grid? And write the rink name in English.

🤖 **Agent:** Fixed: plain white roof, and the sign reads only "UTC Ice".

🎬 **Version 3 delivered.** This is the final cut: **198 s** with chapters Harbor 0:00 · Cove 0:26 · UTC 0:52 · Balboa 2:22 · Coast drive 2:48. All six checks in the playtest are marked *partial*. The coast drive camera is stable again. The agent was upfront that the grass under the plaza and rink still shows through in this cut.

🖼️ *Harbor highlight:* a sunny waterfront promenade lined with palms. A grey aircraft carrier with aircraft on deck is moored on the right, the big statue stands on a round base, and towers rise across the bay.
🖼️ *Cove highlight:* a curved sandy beach under a dark cliff, dozens of dark sea lions on the sand, beach umbrellas, gulls over bright turquoise water, and a white line of surf.

## Version 4: adding the UCSD campus

🧑 **You:** Now I want the UCSD campus built into this city. Plan it, and search for real pictures.

🤖 **Agent:** The campus sits right next to UTC, so it goes into the existing map. I suggest starting with Geisel Library, Price Center and Warren Mall. I found 14 openly licensed photos.

🃏 **Card — UCSD reference photos: pick the most representative**
14 photos
→ picked: **6** (Geisel, Price Center, Warren)

🃏 **Card — Target pictures (2 each)**
Geisel A/B · Price Center A/B · Warren Mall A/B
→ picked: Geisel **A**, Price Center **B** (overhead plaza), Warren **B** (long lawn walk)

🃏 **Card — 3D model previews: tick what to keep**
Geisel · Price Center · Warren Mall
→ picked: **Geisel + Warren**. I asked for Price Center to be redone, and the second try kept the curved glass front, steps and blue umbrellas.

🧑 **You:** There's a yellow patch above the road here. Can that be fixed?

🤖 **Agent:** It's a sand layer that didn't sit on the terrain. One piece floats above the road and one pokes out into the sea. I'll fix it in the next round.

🃏 **Card — Go: Version 4**
Remove the yellow sand sheets · put Geisel, Price Center and Warren into the city · light-blue water · paving instead of grass · fix blank memory-button labels · comparisons and video
→ **Start**

🎬 **Version 4 delivered.** The sand sheets are gone and the water is light blue. The three UCSD buildings are in the game but rough. Requirements done: **4/15** (3 partial). Video **88 s**, with eight chapters: the five places plus Geisel, Price Center and Warren.

🖼️ *Geisel highlight:* a pale, layered library on angled concrete legs, standing on a thin slab above a green lawn, with blue sea at the top right.

🧑 **You:** Focus on making UCSD good now. The buildings are the wrong colour, washed-out white like raw 3D models. All three are in the wrong places too. Look up the UCSD layout online and confirm their positions and relative sizes. And add students, pedestrians and plants this round, it's too empty.

## Version 5: real positions and scale

🤖 **Agent:** From OpenStreetMap: Price Center is about 210 m south-southeast of Geisel, and Warren is about 290 m east. The whole city is scaled to 0.41, so Geisel should be about 35 m wide, but it's currently 90 m. That's why they're crowded together.

🃏 **Card — Here's my understanding of Version 5**
Real positions · real relative sizes · concrete grey and green-blue glass · grounded on the terrain, no floating slabs · students, trees, benches
→ **Looks right**, then **Start**

🎬 **Version 5 delivered.** Positions and sizes now match the map. Geisel is concrete grey with green-blue glass and is the closest to its target picture. Price Center and Warren textures have broken up into flat triangles. Requirements done: **4/16** (4 partial). Video **88 s**.

🖼️ *Geisel:* a tiered grey-and-teal library on a grass clearing, surrounded by dense trees and palms, with hills and the sea in the distance.

🧑 **You:** The blotchy triangles on Price Center and Warren must be fixed. And there's nothing in front of the library. Search for photos: there should be a wide walkway, concrete bollards, campus banners, and students.

🃏 **Card — Real photos of the walkway in front of Geisel (Library Walk)**
3 photos
→ picked: **2**

## Version 6: Library Walk and sharper textures

🎬 **Version 6 delivered.** It has a striped brick Library Walk with bollards, blue-and-gold banners, rows of trees, crowds of students and Geisel at the end. Price Center is noticeably sharper, and Warren is still dark and rough. Requirements done: **4/17** (5 partial). Video **44 s** (Library Walk · Geisel · Price Center · Warren).

🃏 **Card — Version 7: fix the lighting, align to the map, connect the campus, reshoot**
Smooth shading (no dark jagged triangles) · top-down comparison against OpenStreetMap, then correct positions and orientation · remove the models' built-in bases and connect them with paths · new camera shots: walk north up Library Walk, Geisel head-on, a north-up overview
→ **Start**

## Version 7: a campus that matches the map

🎬 **Version 7 delivered.** The buildings no longer go dark, all three sit where they are on the real map, the bases are gone and paths connect them. This round rebuilt only the campus. Requirements done: **5/21** (8 partial). Video **65 s**: Library Walk looking north · Geisel front · Price Center · Warren Mall · campus overview, north up.

🖼️ *Map check:* on the left, OpenStreetMap of the campus with Geisel, Price Center and Warren highlighted; on the right, the game from straight above, north up, with the three buildings, paths and trees in the same arrangement.

🃏 **Card — What next?**
Bring back the other places · brighten Geisel's front · add sound to the video · install in my own game
→ *(left open)*

---

**What this example shows:** you bring photos and a few sentences, the agent turns them into places, and you steer every choice through cards. Each version comes back with a video you can comment on at exact timestamps. My notes ("the fountain is in the pool", "find real photos first", "the camera is shaking") turned directly into the next version's plan.
