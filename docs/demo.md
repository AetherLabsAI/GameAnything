# A clickable demo of a project (`gameanything demo export`)

A read-only copy of the browser UI on one finished project, as a folder of static files: the same pages (the conversation with all cards
and the answers given, scenes / board / plan, 试玩 with the videos and the time-anchored notes, 开发状态, the project home), the language
switch (中 / EN) works, and nothing can be changed. It needs no server and no account: any static host works (a Hugging Face static Space,
GitHub Pages, `python -m http.server`), at the root or under a sub-path (`/hlm/`).

```bash
gameanything demo export --project <a cleaned COPY of the project> --out <folder> \
    [--lang zh --lang en] [--max-mb 30] [--ffmpeg /path/to/ffmpeg] [--cover 1280x840:4,773,88,66] [--placeholder 'media/1_ingest/*'] [--preset slow] [--keep-times] [--home ../]
```

## What it does

1. Starts the UI server **in this process** on the project, on a free local port, with a throwaway project list and the supervisor off
   (`GAMEANYTHING_NO_AGENTD=1`, temporary `GAMEANYTHING_HOME` / `GAMEANYTHING_DATA`). Nothing is written into the project or into your real
   project list; no agent starts.
2. Saves every GET the pages make, per language: `/api/<name>?<query>` becomes `demo-data/<lang>/api/<name>[@<query>].json`
   (`demo.demo_key()`; the thread's poll cursor `after` is not part of the key). Per build: `/api/play?m=<m>` (and `/api/balance?m=<m>`).
3. Saves every picture and video the answers point at, at the same path as on the server (`build/...`, `media/...`, `conv/...`; a query
   becomes part of the file name: `r.png?v=1` → `r.png@v=1`). Videos are re-encoded to H.264 + AAC, at most 720 lines, two passes at the
   bitrate that stays under `--max-mb` (default 30 MB) and never above the source's; `faststart`, so they play while loading. AAC audio is kept as it is (re-encoding some recordings' AAC made ffmpeg hang); other audio is re-encoded to AAC;
   `--preset` picks the x264 preset (default `slow`). Encoded
   videos are kept between runs (a `.<name>.src` file next to each records the source size and the cover boxes).
4. Writes `index.html` (the conversation shell) and `app.html` (the workspace) from the server's pages, with `window.GA_DEMO = {...}` and
   `demo.js` loaded first and the page's own files referenced relative to the folder; copies the scripts, the stylesheet and the font.
5. Removes files an earlier export into the same folder wrote and this one no longer shows, and prints a scan of the saved answers for
   things that often should not be public (e-mail addresses, file paths, money, dates, keys, local addresses). The scan never changes
   anything: fix the project copy and export again.

What a demo does not show or blanks (`demo.for_demo()`): the old home page's data (`/api/home`, no page uses it), other projects, image costs, backups, the agent's online state and running
builds, the feedback study and the private preference profile, the dates on the version list (the "watch version N" todos use the version list's names), and (unless `--keep-times`) every date or
clock time in the answers.

`--placeholder GLOB` (repeatable) exports every picture / video whose exported path matches (e.g. `media/1_ingest/*`, your own uploaded
photos; `build/m9/play/compare/x.png`, one file with real people in it) as a neutral grey stand-in ("not shown in this demo"; a 3-second
video for a video) instead of the file.

`--cover WxH:x,y,w,h` paints a black box on every picture and every video of exactly that size (for an overlay a recording tool left in a
corner); repeat it for several sizes.

## Demo mode in the page (`gameanything/ui/static/demo.js`)

Only active when the page sets `window.GA_DEMO` before loading it (the exported `index.html` / `app.html` do; `gameanything ui` never
loads `demo.js`, so normal use is unchanged). It:

- maps every GET to `/api/...` to the saved file for the page's language (`X-Lang`), and the 2-second thread poll to "nothing new";
- maps every other root-absolute address (`/build/...`, `/media/...`) to the same file under the demo folder, for `fetch`, XHR and the
  `src` / `href` / `poster` / `data-zoom` / inline `url()` of elements the pages create;
- refuses every write (POST, upload, sending a message, answering a card, Start, settings, model chips) with a "这是演示 / This is a demo"
  toast; nothing leaves the page;
- hides what needs a server or an account: the project menu, other projects, backup, notifications, the model chips, attachments, the
  new-user guide, the agent's online pill, live view, the preference page and the upload area; the composer is read-only. A small
  "Demo · read only · all examples" tag links to `GA_DEMO.home` (`--home`, default `../`).

The only change to the normal pages: `shell.js` opens the workspace frame at `GA_DEMO.map(...)` (= `app.html?embed=1#<route>`) when
`GA_DEMO` is set.

## Before publishing

The export shows what is in the project, as it is. Export a **cleaned copy**, never the real project folder: names → "I" / neutral,
dates and times, costs, model and service names, internal ids and file paths, tooling talk (servers, restarts, failures), other projects
and users; drop status / progress noise. Then read the scan, open the folder in a browser (`python -m http.server` in its parent, then
`/<folder>/`), and look at every picture and video it contains.
