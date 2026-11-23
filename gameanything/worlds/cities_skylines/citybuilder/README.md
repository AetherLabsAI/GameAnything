# citybuilder: a generic "build a city from data files" mod for Cities: Skylines 1 (native mode, D19)

Source/ is generic. Everything personal (heightmap, roads, objects, the words shown on the memory buttons) lives in the mod's `data/`
folder next to the DLL and is never committed here. The mod is driven by commands (`cmd.txt` in the mod folder, one command per line,
picked up every second while a city is loaded; `onload.txt` runs once after a city loads; results go to the game log with the prefix
`[M2WCity]`). Every `[M2WCity]` line is also appended to `m2w.log` in the mod folder (emptied at each game start, written and closed per line), because
Unity's Player.log on Linux is buffered and can lag minutes behind; lab tools read `m2w.log`.

Data files (all optional): `terrain.raw` (1081x1081 uint16 LE, height_m*64, first row = north), `roads.txt` (`R|NetInfo|x,z x,z ...`),
`objects.txt` (`B|prefab|x|z|angleDeg[|y]`, `P|prop|...`, `T|tree|x|z`), `signs.txt` (`S|text|x|z|y|size`),
`memories.txt` (`H|title`, `M|id|title|titleEn|x|z|dist|yaw|pitch|text`), `water.txt` (`S|seaLevel`, `P|cx|cz|w|l|level` pools).

Commands: pave, surface, grade, tint, models, dump, terrain, clearall, cleartrees, waterclear, waterfill, sealevel, nosources, paint, cleansurface, unlock, money, roads,
objects, signs, shot, cam, time, hold, weather, speed, wait, name, save, findb, wateri, watermap.

What was learned the hard way (macOS, game 1.21.1-f9):
- Map = 17280 m, heightmap 1081x1081 at 16 m; `TerrainManager.SetRawHeightMap(byte[])` (file row 0 = north) replaces the terrain.
- Starting from a coastal base map, the old map's water and its render textures stay. Clear them (`waterclear` zeroes the water buffers and
  calls `UpdatePatch` on all 81 patches), then write the sea yourself (`waterfill`: cells whose ground is under the level get water up
  to it), then re-apply the terrain so the render patches refresh; the water mesh shows up ~30 s later.
- The game's own sea leaks about 0.5 m per minute and natural water sources overshoot, so the mod tops the sea up every 20 s (`water.txt`).
- The simulation is paused at first (`speed 3` also clears the forced pause); `Application.runInBackground` is switched on.
- Camera: `CameraController.m_current/targetPosition/Size/Angle` (angle.x = yaw, angle.y = pitch); beyond `m_maxTiltDistance` the camera
  is forced top-down. Screenshots without UI: render the camera into a RenderTexture.
- Building/prop angle: the front looks along (sin a, -cos a) in (x, z).
- All 25 map tiles: `UnlockManager.UnlockAllProgressionMilestones()` on the simulation thread, then fill `GameAreaManager.m_areaGrid`.

## Surfaces, look and props (data-driven; re-read on every city load, 3 s after load)
- `data/surface.txt`: `U|type|cx|cz|w|l|angleDeg` (type: PavementA, PavementB, Gravel, Ruined, Field, Clip, None). `surface` applies the file,
  `pave type cx cz w l angle` does one rectangle. Written straight into `TerrainManager.RawSurface` (edges feathered one 16 m cell) and the area is
  refreshed. The result is stored in the saved city, so on load it is only redone if `data/surface.onload` exists.
- `data/look.txt` (`key=value`, `#` comments): `grade=<LUT name|none|custom>`, `lut.saturation|contrast|brightness|gamma=n`, `lut.tint=r,g,b`
  (for `grade=custom`, which builds a 32^3 LUT), and `terrain|water|watert|topography|decoration.<_Prop>=n` or `=r,g,b[,a]` material tweaks.
  `tint` applies the file, `tint probe` logs which known property names each terrain/water material has, `grade list` logs the LUT names,
  `grade <name>` / `grade custom` switches directly.
- `data/models.txt`: `K|kind|x|z|angleDeg|scale`, kind = `sealion` (~2 m), `tower` (~60 m), `statue` (~8 m). Head/front looks along (sin a, cos a).
  `models` rebuilds them (also on every city load).

## Tests
1. `gameanything native build ...` compiles with no errors; install, load a city, wait 3 s: the log has `models:`, `look:` lines.
2. `cmd.txt`: `tint probe` then `grade list`; read `[M2WCity] probe ...` and `grade: LUTs ...` in the log.
3. `pave PavementA 0 0 60 40 30` then `shot` over (0,0): a rotated grey paved rectangle with soft edges.
4. Put one `K|tower|0|0|0|1`, one `K|sealion|...` and one `K|statue|...` in models.txt, run `models`, `shot` at each.
5. `grade custom` with `lut.saturation=1.3`: the picture changes at once; `grade none` reverts.
6. Save, reload the city: models and look come back without any command.

## OBJ models (`models.txt`, `models` command)
- `K|obj|<name>|x|z|angleDeg|scale|y` : places `data/models/<name>.obj`. `y` is optional (empty = on the higher of ground and water surface; given = absolute world y).
  Front (+z of the OBJ) looks along (sin a, cos a).
- `K|objherd|<name>|cx|cz|radius|count|scale|seed` : `count` copies in a disc, random yaw, scale jitter 0.8-1.25, each resting on max(ground, water surface). All copies share one Mesh and Material.
- Next to the OBJ (all optional): texture `<name>.png|.jpg` (or `<name>_base_color`, `_albedo`, `_basecolor`, `_diffuse`) and `<name>.txt` with `key=value` lines:
  `size=<metres>` (largest dimension after normalising, default 10), `scale=<k>` (extra multiplier), `yoffset=<m>`, `up=y|z` (default y, Meshy exports are Y-up), `maxtris=<n>` (stride decimation).
- The model is centred on x/z with its lowest point at y=0. Supported OBJ: v, vt, vn, f (triangles, quads, n-gons fan-triangulated, `v`, `v/vt`, `v//vn`, `v/vt/vn`, negative indices), any number of objects/groups (merged, one material);
  materials/`.mtl` are ignored. Vertices are unwelded per corner, meshes are split at 64998 vertices, missing normals are computed (smooth per position).
- Each OBJ is parsed once (cached, re-parsed if the file changes). If `<name>.obj` is missing and `<name>` is `sealion`, `tower` or `statue`, the procedural primitive is built instead (the `K|sealion|x|z|...` lines still work).

## Surface and error dialogs
- `pave` / `surface` / `cleansurface` write `RawSurface`, then call ONE `TerrainModify` update for the union area (int/cell overload, clamped to the 1080 grid, 96-cell tiles, inside Begin/EndUpdateArea on the simulation thread).
- Any modal named `ExceptionPanel` is closed automatically (checked once per second, logged as `closed an error dialog`).

## Tests
1. `surface` on a data set with rectangles touching the map edge: log shows `surface updated ... tile(s)`, no `Simulation error`, no dialog; then build a road with `roads` and check again.
2. `pave PavementA 0 0 100 60 30`, `pave None 0 0 100 60 30`; `pave Gravel -8600 -8600 200 200 0` (corner).
3. `cleansurface` (whole map), then `surface`.
4. Force an error dialog (e.g. a bad command that throws on the simulation thread): it disappears within 1 s and is logged.
5. `models` with one `K|obj|...` line (textured, 1 mesh), then a >65000-vertex OBJ (several meshes), a Z-up OBJ (`up=z`), a quad/n-gon OBJ with negative indices, an OBJ without normals, an OBJ without texture (grey).
6. `K|objherd|sealion|...|30|...|7` on a beach: copies sit on the water surface/ground, differ in yaw and scale; run `models` twice: the log shows each OBJ parsed only once.
7. Missing OBJ named `tower`: primitive fallback; missing OBJ with another name: logged and skipped.

## Recording, tours, sun glow, water texture filtering (Record.cs)
Commands:
- `record <name> <seconds> [fps=12] [width=960]` : captures the main camera (no UI, one reused RenderTexture/Texture2D, JPG quality 85, height = width*9/16) into `shots/rec_<name>/00000.jpg ...`, paced with `Time.unscaledTime`, one frame per `WaitForEndOfFrame`. The command queue waits until it is finished; `record& ...` returns at once (the recording runs on while later commands execute). The log ends with `record: N frames in S s (X fps achieved, target Y ...)`. If the game renders slower than the target fps frames are not duplicated, so build the video from `times.txt` (`NNNNN seconds`) or at the achieved fps. The folder is emptied of old `*.jpg` at start.
- `tour <name> [fps] [width]` : records while flying through ALL memories in order (smooth 2.6 s flight like the button, then an 8 s orbit instead of 22 s; the on-screen title/text overlay is shown in the game as usual but is NOT in the capture). Writes next to the frames: `chapters.txt` (`seconds|memory id|title   titleEn`, seconds = when the caption appears, i.e. at arrival) and `chapters_full.txt` (`start|end|id|title|titleEn|text`, `\n` kept escaped) so captions can be burned in with ffmpeg.
- `data/tour.txt` (optional): `<memory id>|<hour>` : at the start of that memory's flight the sky is held at that hour (clear weather); memories without a line keep the current sky. The previous hold is restored at the end.
- `cine <name> [fps=24] [width=1280] [aa=8]` (Cine.cs) : deterministic, frame-stepped cinematic capture. The camera is a function of virtual time `t = frame/fps` read from `data/cine.txt`; per frame the loop sets the camera, waits 1 frame (3 after a jump larger than 25% of the camera distance, 6 at a chapter start / cut) plus `WaitForEndOfFrame`, then grabs a JPG (quality 92, height = width*9/16) to `shots/rec_<name>/NNNNN.jpg`. Playback at the given fps is smooth whatever the capture speed (log prints the real capture fps). Chapters are concatenated with hard cuts. Writes `chapters.txt` and `chapters_full.txt` (same formats as `tour`, in VIRTUAL seconds; start = chapter start, end = chapter end). The simulation keeps running in real time (water, people, lights animate; they are not locked to virtual time). The chapter hour is held (`holdHour`, clear weather) while the chapter is captured; the previous hold is restored. If the sim is paused (or forced-paused) `cine` unpauses it at speed 1 and re-pauses/restores the speed at the end. `tour` is unchanged.
- `glow` : logs which glow shaders exist (`Shader.Find` of Particles/Additive, Legacy Shaders/Particles/Additive, Sprites/Default, ...) and the sun light.
- `watertex` : logs every texture of the water and transparent-water materials (name, type, size, wrap, filter, aniso, mip bias, format, mip count) and sets them to Trilinear + `anisoLevel` (default 8) + optional mip bias. Render textures are logged but not touched.

Data formats:
- `data/look.txt`: `hour.sunset=18.0`, `hour.sunrise=6.4` (defaults; used by the Sunset/Sunrise buttons and `sky sunset|sunrise`), `water.mipbias=<n>` (e.g. 0.5 blurs/away from the sharp aliasing; negative sharpens), `water.aniso=<1-16>`. Water keys are applied by `tint` and on every city load; they only run `watertex` filtering when at least one of them is present.
- `data/models.txt`: `K|glow|x|z|y|size` : a camera-facing quad with a generated soft radial warm-orange gradient (additive shader if found, else alpha), kept 6000 m (at most 90% of the camera far plane) from the camera in the direction of the sun (negated forward of `RenderSettings.sun`, else the first enabled directional light; `x|z` is only the fallback horizontal direction, default -1|0.3), `y` = extra height in metres (default 0), `size` = metres across at 6000 m (default 2500). Visible only for sim hour 17 - 19.5: fades in 17 -> 18, fades out 18.75 -> 19.5. The sun direction's vertical part is clamped to >= 0 (the glow never goes below the horizon).

- `data/cine.txt` (for `cine`; `#` comments): `C|<id>|<title>|<titleEn>|<text, \n = newline>|<hour>` starts a chapter (hour optional/empty = leave the sky). `K|<sec>|x|z|dist|yaw|pitch[|ease]` keyframe at chapter-relative seconds (target x,z, y = ground; dist = camera distance; yaw/pitch degrees). `H|<sec>|x|z|y|dist|yaw|pitch` hero keyframe (y empty = ground; explicit y is blended to the neighbours). Position, dist, pitch use Catmull-Rom, yaw uses Catmull-Rom on shortest-angle unwrapped values. Segment easing: default none (uniform Catmull-Rom parameter, so the glide stays continuous through K points); `ease` = `smooth` (smoothstep), `slow` (smootherstep), `lin`, applying to the segment that STARTS at that key; any segment touching an `H` key uses smootherstep, so the camera slows to a near stop at heroes. The chapter length is its last key's time (need >= 2 keys).

Tests:
1. Build is clean; load a city; `glow` shows which shaders exist and `RenderSettings.sun`.
2. `record t1 5` : 60 frames in about 5 s, jpgs 960x540, `times.txt` present; `record& t2 10` then `wait 3`, `shot x ...` works while it records.
3. `tour t3 10 960`: frames, `chapters.txt` with one line per memory in order; with `data/tour.txt` containing `<id>|18.0` the sky is dusk during that memory.
4. Add `K|glow|0|0|0|2500` to models.txt, `models`, `time 18` and look west: a warm soft glow on the horizon; `time 12` and `time 20`: gone; `time 17.5`: faint.
5. `hour.sunset=17.5` in look.txt, `tint`, press Sunset: hour 17.5. Remove the key: 18.0.
6. `watertex`: log lists textures; set `water.mipbias=1`, `tint`, compare the far sea (checker pattern) with `water.mipbias=0` and with `-0.5`.
7. `cine c1 24 1280` with a 2-chapter cine.txt (each ~6 s, one with hour 18): `frames = round(length*24)` per chapter, jpgs 1280x720, `chapters_full.txt` times are multiples of 1/24; `ffmpeg -framerate 24 -i %05d.jpg` plays smoothly even if capture ran at 3 fps. Sky holds the chapter hour.
8. `cine` with the game paused: log says "sim was paused, running at speed 1", water/people move, game re-pauses at the end. Missing/empty cine.txt: logged, nothing recorded. A yaw going 350 -> 10 turns 20 degrees, not 340. Run `tour` afterwards: still works.

## Movement, paths, follow camera, deterministic cine time (Movers.cs, Cine.cs)
`data/models.txt` lines `K|obj|name|x|z|angleDeg|scale|y` and `K|objherd|name|cx|cz|radius|count|scale|seed` accept optional trailing fields (any order, after all the fixed ones; leave the `y`/`seed` fields empty if you skip them):
`|move=<mode>:<params>` and `|id=<tag>` (the tag names the model for `F` cine keys; for an objherd only the first copy gets the tag). Without them nothing changes. Movement works only on OBJ models (not on the primitive fallbacks).
- `move=walk:<speed>:<range>` (defaults 1.3 m/s, 12 m): a random heading (seeded by position / herd seed) is chosen; the model walks back and forth along that line within +-range of its start and turns around (yaw follows: 180 deg at the ends). The line is scanned once at build time in 1 m steps and shortened where the ground is under sea level + 0.2 (if a water plan with a sea exists) or has more than 0.2 m of water: walkers never enter the pool or the sea; a start point in water makes the model stand. Each frame: ground height from the terrain sampler, vertical bob 0.08 m at 2 steps/s, 5 cm side sway, 2 deg roll.
- `move=bob:<amp>:<period>` (0.3 m, 4 s): vertical bob +-amp around the placed y with a small roll/pitch (surfers, floaters). Yaw stays.
- `move=fly:<radius>:<speed>:<height>` (30 m, 8 m/s, 25 m): circle around the placed x,z at the radius, height metres ABOVE the placed y (constant), yaw along the tangent, 20 deg bank toward the centre; negative speed = other direction. In a herd each copy gets its own phase and radius x 0.7-1.3 (no wing animation).
- `move=path:<pathname>:<speed>[:pingpong]` (10 m/s): follows the polyline `P|<pathname>|x,z x,z x,z ...` of `data/paths.txt` (`#` comments; at least 2 points, positions in game x,z metres). Default = loop (jumps back to the start at the end); `pingpong` drives back and forth. Yaw = tangent (taken over +-1.5 m so corners are smooth), pitch follows the slope, y = ground. In a herd each copy starts at a random distance. The placed x,z is ignored (the model is put on the path); cars may overlap.
- Everything is a PURE FUNCTION of `Host.VirtualTime` (no integrated state): `Time.time` normally, `frame/fps` while `cine` records, so people / cars move at the correct speed in the video whatever the capture speed. A model out of range simply catches up (is at the right place) when it is updated again.
- Cost: one `Host.Update` loop over a cached `List<Mover>` (no allocations); only movers within 400 m of the camera target point or of the camera itself (and tagged ones) are evaluated (about 2 terrain samples for walkers, 3 for cars, 0 for bob/fly; one `Quaternion.Euler` + 2 transform writes). Static models (no `move=`) cost nothing.

`F` cine keys (follow camera) in `data/cine.txt`: `F|<sec>|<tag>|<dist>|<yawOffset>|<pitch>|<height>`. The target point is the model with that `id=` tag (position smoothed with a 6/s exponential filter in virtual time, heading smoothed the same way), `height` = metres above the model's y, `dist`/`pitch` as for `K`. Camera yaw = model heading + yawOffset, where yaw uses the same convention as `K` (0 = looking along the model's front, i.e. the camera sits BEHIND the model and looks the way it travels; 180 = camera in front looking back at it; 90 = camera on the model's left looking across it; -90 = on its right). F keys can be mixed with K/H keys of the same chapter: position, dist, pitch, height and yaw all blend with Catmull-Rom as before (the F key's position/yaw are re-evaluated every frame). Example: `F|0|car1|18|0|20|1.5`, `F|10|car1|12|60|15|1.5`. A tag that does not exist logs `follow tag ... not found` and the key is skipped.

`cine` determinism (Cine.cs): while recording, `Time.captureFramerate = fps` (restored in a `finally`), so every rendered frame advances `Time.time` and shader time (water, lights) by exactly 1/fps; the pose is written before the settle waits, again just before the capture, and again in `Host.LateUpdate` (script execution order 32000, after the game's CameraController). `VirtualTime = frame/fps` (continues across chapters). At the start the log lists CameraController fields whose name contains shake / collision / smooth / inertia / damp (shake floats are set to 0), and at the end: `camera pose check: max |readback - written|` (position, camera rotation at capture time) and the drift the game applied between our writes (position / size / angle). Values near 0 mean the game does not move the camera behind our back.

### Close cameras, eye keys, antialiasing (Cine.cs, Record.cs)
Findings from the IL of `CameraController` (LateUpdate = UpdateFreeCamera, UpdateTargetPosition, UpdateCurrentPosition, UpdateTransform): every frame `m_targetSize = Clamp(size, m_minDistance (40), m_maxDistance)`; target pitch is clamped to >= 0 and the pitch actually used is `90 - (90 - pitch) * (maxTilt/2) / (maxTilt/2 + size)`, i.e. pulled to top-down unless `m_maxTiltDistance` is large (hence pitch 7-15 looked like ~20); `m_targetHeight` is only the terrain height under the target point (feeds `m_currentHeight`, which scales the eye distance by `1 - h/maxDistance`; it is not a setting); the eye is pushed up by `CalculateCameraHeightOffset` (terrain, plus buildings / props / trees + 5 m unless the static `m_disableCollision` is set); near plane = `Max(origNear, size*0.005)` each frame; eye = `currentPosition + rot*(0,0,-D)`, `D = size*Max(0,1-h/maxDist)/tan(fov*Deg2Rad)`, `rot = AngleAxis(yaw,up)*AngleAxis(pitch,right)`.
- `CamLift()` / `CamUnlift()` (ref-counted, restored in `finally`) are active during `cine`, `tour` and `shot`: `m_minDistance` = 3, `m_maxTiltDistance` = 1e6, `m_disableCollision` = true, `m_unlimitedCamera` = true. In addition `Host.LateUpdate` (order 32000, after the game) recomputes the final camera transform from the last `Cam()` / `CamEye()` pose with the game's own formula but no clamps, and sets `nearClipPlane = Min(current, 0.5)` when the eye distance is < 150 m. So `dist` down to 1 m and pitch down to 1 deg (E keys: -89..89) are exact. `cam` (interactive, no scope) and `record` are NOT lifted. Side effects while lifted: camera collision is off (the camera no longer rides 5 m over buildings / trees; it keeps the game's +1 m over terrain), tilt-shift / depth-of-field amounts use `m_minDistance` and change slightly.
- Per-chapter camera mode: `C|id|title|titleEn|text|hour|lift`, optional 7th field `lift` 0/1. Default 0 = NORMAL game camera (min distance 40, tilt term, collision push-up over buildings/trees, exactly the pre-lift behaviour: no CamLift, `Host.LateUpdate` does not touch the transform). 1 = lifted (close views, pitch 1 deg). Chapters with only `E` keys are always lifted. `cine` lifts/unlifts at chapter boundaries (log line `cine chapter X: LIFTED / NORMAL`, 4 extra frames + 10 settle frames after a switch). Use lift=1 for close/low shots, leave 0 for chases where the game's own push-up is wanted.
- Lifted-camera safety (CineLateUpdate): pitch clamped to 1..89 (E: -89..89), NaN/Inf rejected, rotation built with `LookRotation(forward, up)` (no roll), D >= 1.5 m, eye kept >= terrain + 1.5 m at its x/z, and in chapters with F keys >= car height + 2.5 m (if raised, the pitch is recomputed to keep looking at the target, still 1..89). Follow smoothing uses the virtual dt = 1/fps (position 6/s, heading 4/s, shortest-angle).
- `E|<sec>|x|y|z|yaw|pitch` (cine.txt): absolute eye key, camera AT world (x, y, z) (y = metres above sea level 0, NOT above ground), looking with yaw/pitch (same convention as `K`; pitch positive = down, negative = up). Same Catmull-Rom as K for x, y, z, yaw (shortest-angle unwrapped) and pitch; segments use the default uniform parameter (an `H` neighbour does not apply). A chapter whose keys are ALL `E` is in eye mode and the camera is placed exactly (no terrain/building push-up). If `E` is mixed with `K/H/F` in one chapter the `E` keys are converted to look-at keys with dist 10 (target 10 m ahead of the eye) and a log line says so, so use pure-E chapters for street level. Example: `E|0|120|4.2|-80|90|3` ... `E|8|160|4.2|-80|90|3` (walk 40 m east at 4.2 m with the eye 1.7 m over a 2.5 m ground).
- Capture RenderTexture: `antiAliasing` 8 (fallback 4, 2, 1 if `Create()` fails), used by `cine`, `record`, `tour`, `shot`; the log prints `capture RT WxH: requested antiAliasing N, render texture reports M`. `cine <name> <fps> <width> [aa]`: width up to 2560 (clamped, logged), height = width*9/16. 2560x1440 with 8x MSAA is about 240 MB of GPU memory (colour + depth, multisampled) plus 11 MB RGB24 readback; JPG quality 92 is about 1 to 2 MB per frame (24 fps x 60 s = 1440 frames = 1.5 to 3 GB) and encoding takes tens of ms on the main thread, so expect a few capture fps. Downscale with `ffmpeg -framerate 24 -i %05d.jpg -vf scale=1920:1080:flags=lanczos ...`. If MSAA is ignored (deferred path, or the game's SMAA only) the reported value is 1; supersampling by width then still works.

Tests (close camera / E keys / AA):
1. Build compiles. `cine c 24 1280` with `K|0|x|z|8|30|10` / `K|4|x|z|8|60|10` in an open street: log shows `camera limits lifted` and, at the end, `limits restored`; the video is 8 m from the target at 10 deg pitch (before: ~40 m, ~20 deg). The pose check line (`position`, `camera rotation`) stays near 0.
2. After the cine, orbit with the mouse: min zoom is 40 again, pitch/tilt behave as before (`m_minDistance`, `m_maxTiltDistance` restored in the log).
3. `E` chapter: `E|0|x|4|z|0|3` -> `E|6|x|4|z+60|0|3`: the video moves along the street at eye height 4 m, looking along +z, horizon in the middle; yaw 350 -> 10 turns 20 degrees; a chapter with an `E` and a `K` key logs the conversion.
4. `cine c 24 2560`: log `capture RT 2560x1440 ... reports 8` (or the fallback), jpgs 2560x1440, no crash; `cine c 24 4000` logs the width limit; `shot` at dist 6 works and the limits are restored afterwards.

Tests (movement / follow / cine):
1. Build compiles. `models` with `K|obj|person|x|z|0|1||move=walk:1.3:12|id=p1` (y empty): the person walks 24 m up and down along a line, yaw flips at the ends, bobs, never enters water (test next to the sea or a pool: the line is shortened).
2. `K|objherd|person|cx|cz|30|40|1|7|move=walk` : 40 people with different headings/phases; frame rate in a 2500-model scene unchanged within noise (`Host.Update` cost is only the models within 400 m).
3. `move=bob:0.4:3`, `move=fly:40:9:30` on a herd of gulls (banking circles, different phases), `move=path:road1:12` with `P|road1|x,z x,z ...` (loop) and `...:12:pingpong` (cars turn around, yaw flips).
4. Missing path name / unknown mode / bad numbers: logged (`models: ...`), the model stays where it is.
5. `cine t 24 1280` with `F` keys on a car: video shows the camera behind the car, moving with it; yawOffset 180 = camera in front; the car's speed in the video equals its `speed` (measure the distance over N frames / 24); capture slower than real time does not change it.
6. After cine: `Time.captureFramerate` back to 0 (game runs normally), the log shows the pose check lines, water in the video no longer jumps between frames; movers keep moving with `Time.time` again.
