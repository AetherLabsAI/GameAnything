"""GameAnything command line.

    gameanything ingest <folder> --project <dir> [--no-transcribe] [--vocab "name1,name2"] [--whisper-model PATH_OR_NAME]
    gameanything status --project <dir>     (the README)  |  gameanything status {show,init,set-item,add-issue,add-regression,recheck,feedback,decide,card} --project <dir>
                                               (the development status 5_build/STATUS.yaml, see devstatus.py, dev-status.md)
    gameanything lessons {show,add,review} ...          (what builders / playtesters learned: per game, per role, local; see lessons.py, lessons.md)
    gameanything ui [--project <dir|id>] [--port 8765]     (without --project: the last-opened project of `gameanything project list`)
    gameanything project {list,new,open,remove,export,import,set-mode,set-launch,set-study,migrate-mode}     (the project list, one-file export / import, where builds run; see projects.py, transfer.py, buildmode.py)
    gameanything backup {enable,disable,run,status,token}     (optional automatic backup, default off, see backup.py)
    gameanything extras {status,install} [transcribe|detect] [--project P]     (optional features, installed only after her yes on a card, see extras.py)
    gameanything perceive --project <dir> [--model M] [--lang L] [--only id,...] [--dry-run | --yes | --emit | --collect]
    gameanything chat {claim,wait,read,say,card,progress,import,idle,release} --project <dir> [--session NAME]     (the conversation with the UI, see conversation.py)
    gameanything agentd [run|status|request|notify]     (the supervisor: one headless agent run per project with new user words, see agentd.py)
    gameanything gen list | estimate --tool fal:image --n 4 | request --project P --tool ADAPTER:CAP --inputs F --permission CARD --go CARD
                                               (asset generation, gen/: agentd checks both cards and runs the adapter, see genrun.py;
                                                old projects: --tool NAME queues 4_design/tools/gen_NAME.py) | status --project P | key set NAME
    gameanything hub [--port 8800] [--host 127.0.0.1]    (several users on one server: login, roles, access requests, see ui/hub.py and users.py)
    gameanything hub user {add,passwd,list,remove,login} ... | gameanything hub migrate --owner <user> [--dry-run]
    gameanything build {watch,status} --project <dir> ...     (a running build: keep its progress card current / the page's "building" banner)
    gameanything i18n {missing,add} --project <dir> [--file part.yaml]     (English for the project content, see translate.py)
    gameanything game {list,new,check} ...     (the game packages: list, scaffold one for your favourite game, validate it; see games/, add-a-game.md)
    gameanything native {doctor,backup,backups,restore,build,install,uninstall,mods,log} [--game G]     (native mode on the user's own game, D19, see native/)
    gameanything native {launch,close,reload,check,launches} --project P [--game G]     (本机模式少打扰: open her game only with her yes, close only what
                                               GameAnything opened, hot reload, headless checks; see native/quiet.py, native/checks.py)
    gameanything native {shot,drive} --project P / gameanything native {idle,permissions}     (look at / press keys in only the game GameAnything opened, never
                                               taking focus, never while she is at the computer; see native/hands.py, native/idle.py)
    gameanything native ready [--project P] [--if-needed] [--card-file F] [--lang zh|en] [--json]     (能不能操作屏幕: can the agent running this look at / click the
                                               game - its framework / sandbox and the system's permissions, a tiny capture probe, never a key;
                                               exit 0 full, 1 look only, 3 none; see native/ready.py)
    gameanything lab {acquire,release,heartbeat,status,queue,stale,register-existing} ...     (seats in the shared lab sandboxes, see lab.py)
    gameanything flow {next,check} --project P [--step S] [--json]     (the flow state machine: the step to work on, its actions and exit criteria; flow.py)
    gameanything setup guide [--project P] [--mode sandbox|native] [--system S] [--json]     (the setting: detect the computer, pick the mode, the guide
                                               to read in skills/gameanything/references/setups/, recorded as setup: in the project; setupguide.py)
    gameanything setup tables [--write]          (the guides' per-game tables, generated from sandbox.sources())
    gameanything visuals --project P [--no-people]     (adaptation: keyframes per shot and people crops from the work's videos, local only; visuals.py)
    gameanything adaptation translate --project P [--out F | --apply F]     (both languages for the 场景 / 角色 / 方案 data; adaptation_tr.py)
    gameanything video contact <video> [--out sheet.jpg] [--cols 6] [--rows 5] [--width 320] [--start S] [--end S]
"""
import argparse
import re
import os
import sys
import time
from pathlib import Path

from . import osdirs


def _utf8_stdio():
    """Windows: a piped / redirected stdout (an agent running GameAnything, `gameanything ui > log`) uses the ANSI code page (cp1252 cannot print Chinese,
    cp936 garbles it for a UTF-8 reader); the console itself is UTF-8 already. Text in and out of GameAnything is UTF-8 on every system."""
    from . import osdirs
    if osdirs.system() != "windows": return
    for s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"): s.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    from . import projects
    _utf8_stdio()
    args = sys.argv[1:] if argv is None else list(argv)
    from . import isolation
    if isolation.client_mode() and not isolation.forwarded():       # an agent run under its own account: writes go through the gate
        from . import gate
        r = gate.maybe_forward(args)
        if r is not None: return r
    elif not isolation.client_mode():
        isolation.server_init()                                     # the service account: never follow a link an agent planted
    if args[:1] == ["isolation"]:                                   # docs/agent-isolation.md: status / migrate (dry run by default) / rollback
        from .isolation_setup import main as iso_main
        return iso_main(args[1:])
    if args[:1] == ["lab"]:                      # lab seats: its own argument parser (gamebench hosting/broker.py, see lab.py)
        from .lab import main as lab_main
        return lab_main(args[1:])
    ap = argparse.ArgumentParser(prog="gameanything")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lab", help="seats in the shared lab sandboxes: acquire / release / heartbeat / status / queue / stale / register-existing; `env up|status` the seat's base environment; `login steam|microsoft|ea` the user's own store sign-in in their sandbox, watched (`gameanything lab -h`)")
    x = sub.add_parser("extras", help="optional features left out of the basic install (transcribe: speech in videos -> text; detect: person boxes "
                                      "on the people page). install asks her on a card first and installs only after her yes. Exit 0 installed / done, "
                                      "2 waiting for her, 3 she said not now / the install failed")
    x.add_argument("what", choices=["status", "install"]); x.add_argument("name", nargs="?", choices=["transcribe", "detect"])
    x.add_argument("--project", default=None, help="project folder or id (install: the chat that gets the card)")
    x.add_argument("--no-post", action="store_true", help="install: only say what would happen, post no card")
    x.add_argument("--ask-again", action="store_true", help="install: ask again although she said not now (only when she brought it up)")
    x.add_argument("--json", action="store_true")
    p = sub.add_parser("ingest", help="inventory and normalize a folder of memories into <project>/1_ingest (local only, no LLM)")
    p.add_argument("folder", type=Path)
    p.add_argument("--project", type=Path, required=True, help="project directory (created if missing) or a registered project id; keep it outside any git repo")
    p.add_argument("--no-transcribe", action="store_true", help="skip speech-to-text for videos / audio")
    p.add_argument("--vocab", default="", help="comma-separated names / terms for speech-to-text (added to <project>/config/vocab.txt)")
    p.add_argument("--no-detect", action="store_true", help="skip local person boxes (used by the tagging UI)")
    p.add_argument("--whisper-model", default=None, help="faster-whisper model name or local path (default: $GAMEANYTHING_WHISPER_MODEL or large-v3-turbo)")
    q = sub.add_parser("perceive", help="one model call per item -> <project>/2_perceive/cards/ (sends reduced images + text; asks first)")
    q.add_argument("--project", type=Path, required=True)
    q.add_argument("--model", default="claude-sonnet-5-5")
    q.add_argument("--lang", default="English", help="language of the descriptions (quotes and text in images stay as they are)")
    q.add_argument("--backend", default="claude-code", help="claude-code (default: your Claude Code CLI, or $GAMEANYTHING_CLAUDE)")
    q.add_argument("--jobs", type=int, default=4)
    q.add_argument("--only", default="", help="comma-separated item ids")
    q.add_argument("--yes", action="store_true", help="consent to sending the listed content without asking")
    q.add_argument("--dry-run", action="store_true", help="only list what would be sent")
    q.add_argument("--emit", action="store_true", help="agent-native: write one request per item for your Claude Code session to answer")
    q.add_argument("--collect", action="store_true", help="agent-native: validate the cards the session wrote and record them")
    u = sub.add_parser("ui", help="local tagging page for people and groups (127.0.0.1 only; writes into the project)")
    u.add_argument("--project", default=None, help="project folder or id (default: the last-opened one; none yet: the welcome page)")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--upload-max-gb", type=float, default=20, help="largest single file the browser upload accepts (default 20 GB)")
    u.add_argument("--content", type=Path, default=None, help="the game's unpacked Content folder (for the look page's live sprite rebuilds)")
    ar = sub.add_parser("art", help="Stardew art: walk sprites from looks.yaml (local) and portraits (sends face crops to the image model)")
    ar.add_argument("what", choices=["walks", "portraits"])
    ar.add_argument("--project", type=Path, required=True)
    ar.add_argument("--content", type=Path, required=True, help="the game's unpacked Content folder (StardewXnbHack output)")
    ar.add_argument("--only", default="", help="comma-separated person ids")
    ar.add_argument("--expressions", default="neutral", help="comma-separated: " + "neutral,happy,laugh,touched,surprised,shy")
    ar.add_argument("--yes", action="store_true", help="portraits: consent to sending the face crops")
    v = sub.add_parser("video", help="contact sheet of a video (frames with time stamps), for reviewing a replay in one image (local)")
    v.add_argument("what", choices=["contact"])
    v.add_argument("video", type=Path)
    v.add_argument("--out", type=Path, default=None, help="default: <video>.contact.jpg next to the video")
    v.add_argument("--cols", type=int, default=6); v.add_argument("--rows", type=int, default=5); v.add_argument("--width", type=int, default=320)
    v.add_argument("--start", type=float, default=0.0); v.add_argument("--end", type=float, default=None)
    r = sub.add_parser("status", help="without a subcommand: write <project>/README.md and print it. With one: the development status 5_build/STATUS.yaml "
                       "(her requirements and their state, known issues, regressions, the recheck list, her unhandled words, decisions; dev-status.md)")
    r.add_argument("what", nargs="?", default="readme", choices=["readme", "show", "init", "set-item", "add-issue", "add-regression", "recheck", "feedback", "decide", "card"],
                   help="show: print it | init: seed it from the latest go card, the world plan and her unhandled words | set-item: change / add a requirement | "
                        "add-issue / add-regression: known issues, regressions | recheck: the every-round checklist | feedback: her words handled / answered | "
                        "decide: record a decision | card: a result card from it")
    r.add_argument("--project", type=Path, required=True, help="project folder or id")
    r.add_argument("--id", default=None, help="set-item / add-issue / add-regression: the entry (r1, k1, g1); a new item gets the next id when left out")
    r.add_argument("--text", default=None, help="set-item / add-issue / decide: the text; set-item: needed for a new item")
    r.add_argument("--text-en", default=None, help="set-item: the English of the item (the page shows it in EN)")
    r.add_argument("--state", default=None, help="set-item: done | partial | todo | broken | regressed;  feedback: open | answered | handled")
    r.add_argument("--build", default=None, help="the build / round it is about (m3): set-item's since, recheck's round")
    r.add_argument("--by", default=None, choices=["builder", "playtester"], help="set-item: who verified it (default: kept); recheck: who rechecked (default playtester)")
    r.add_argument("--evidence", default=None, help="set-item: what shows it (build / round + time or frame)")
    r.add_argument("--source", default=None, help="set-item: where the requirement comes from (go:<event>, plan:<m>, feedback:<event>)")
    r.add_argument("--severity", default="medium", choices=["low", "medium", "high"], help="add-issue")
    r.add_argument("--since", default=None, help="add-issue: since which build"); r.add_argument("--plan", default=None, help="add-issue: what will be done about it")
    r.add_argument("--fixed", action="store_true", help="add-issue --id K: the issue is gone (removed from the list)")
    r.add_argument("--what", dest="what_text", default=None, help="add-regression: what broke"); r.add_argument("--broke-in", default=None, help="add-regression: the build it broke in")
    r.add_argument("--cause", default=None, help="add-regression: why"); r.add_argument("--fixed-in", default=None, help="add-regression: the build that fixed it")
    r.add_argument("--item", default=None, help="add-regression: the requirement it is about (r2)")
    r.add_argument("--add", nargs="+", default=[], help="recheck: new checklist lines")
    r.add_argument("--pass", dest="passed", nargs="+", default=[], help="recheck: ids that passed in --build"); r.add_argument("--fail", dest="failed", nargs="+", default=[], help="recheck: ids that failed")
    r.add_argument("--note", default=None, help="recheck --fail: what went wrong")
    r.add_argument("--event", default=None, help="feedback / decide: the thread event id"); r.add_argument("--add-event", action="store_true", help="feedback: add the event to open_feedback")
    r.add_argument("--m", default=None, help="card: the milestone"); r.add_argument("--title", default=None, help="card: the card title"); r.add_argument("--image", default=None, help="card: the picture (/build/<m>/…)")
    r.add_argument("--out", type=Path, default=None, help="card: write the yaml here (default: print it)")
    r.add_argument("--force", action="store_true", help="init: merge the seeds into an existing STATUS.yaml")
    r.add_argument("--json", action="store_true", help="show: print the data as JSON")
    ls = sub.add_parser("lessons", help="agent experience memory: what builders / playtesters learned, per game, per role and local-only (lessons.md)")
    ls.add_argument("what", choices=["show", "add", "review"], help="show: the merged view (confirmed first) | add: append a candidate (similar ones are folded in) | "
                    "review: the candidates for the coordinator (--confirm / --drop / --merge)")
    ls.add_argument("--game", default=None, help="the game id (show: default every lesson of the role; add: needed unless --general)")
    ls.add_argument("--role", default=None, choices=["builder", "playtester"], help="show: only this role; add: required")
    ls.add_argument("--symptom", default=None); ls.add_argument("--cause", default="")
    ls.add_argument("--fix", default=None); ls.add_argument("--evidence", default="", help="build / round + time or frame")
    ls.add_argument("--confidence", default=None, help="tried once (default) | verified repeatedly")
    ls.add_argument("--local", action="store_true", help="add: only on this machine (<project list folder>/lessons/), never committed")
    ls.add_argument("--general", action="store_true", help="add: not about one game (the role's file)")
    ls.add_argument("--force", action="store_true", help="add: append even when a similar lesson exists")
    ls.add_argument("--project", type=Path, default=None, help="add: refuse names from this project's vocab / people in a shared lesson")
    ls.add_argument("--confirm", nargs="+", default=[], metavar="ID"); ls.add_argument("--drop", nargs="+", default=[], metavar="ID")
    ls.add_argument("--merge", nargs=2, default=None, metavar=("A", "B"), help="review: fold B into A")
    ls.add_argument("--json", action="store_true")
    fb = sub.add_parser("feedback", help="her feedback as records (docs/feedback-loop.md): one record per point she makes, the agent's reading confirmed when unsure, "
                        "linked to a STATUS item, verified at the same anchor (before / after), the metrics (repeat-feedback rate)")
    fb.add_argument("what", choices=["show", "add", "set", "confirm", "link", "verify", "pairs", "verdict", "accept", "card", "metrics", "backfill", "brief", "label", "condition",
                                       "judge", "agreement", "retro", "critic", "match", "datacheck"],
                    help="show: the records | add: a record from her words (--event) | set: reading, class, kind, scope, certainty | confirm: her answer on the confirm card | "
                         "link: the STATUS item it became | verify: the after picture of a fixed record (same anchor) | pairs: the before / after pairs of a version "
                         "(--todo: what still needs a re-shoot) | verdict: her ok / not ok on a pair | accept: she accepted a version | card: the confirm / verify card | "
                         "metrics: the numbers | backfill: records from an existing project's history (merge-only, safe on a live project) | brief: what a build starts with | "
                         "label: --export / --import a labelling sheet (--human-sheet: a blind shuffled sheet) | condition: the evaluation condition C0-C4 (blind: never tell her) | "
                         "judge: the LLM judge behind her permission card (--card, --emit --model M, --collect) | agreement: kappa / alpha between labellers | "
                         "retro: the retrospective of a delivered version (--emit / --collect / --todo) | critic: predictions before delivery (--emit / --collect) | "
                         "match: the critic's predictions vs her records | datacheck: every datum the evaluation needs, recorded or not. "
                         "Study mode only (gameanything project set-study ID on): metrics, label, condition, judge, agreement, match, datacheck")
    fb.add_argument("--project", type=Path, required=True, help="project folder or id")
    fb.add_argument("--id", default=None, help="the record (f3)"); fb.add_argument("--ids", nargs="+", default=None, help="card confirm: the records")
    fb.add_argument("--event", default=None, help="add: the thread event of her words; confirm / verdict: the event of her answer")
    fb.add_argument("--words", default=None, help="add: her words (verbatim; a part of the event's text when one message makes two points)")
    fb.add_argument("--m", default=None, help="the version (m3)")
    fb.add_argument("--interpretation", default=None, help="your reading of her words (never edit hers)"); fb.add_argument("--interpretation-en", default=None)
    fb.add_argument("--class", dest="cls", default=None, choices=["bug", "taste", "request", "question"])
    fb.add_argument("--kind", default=None, help="the complaint kind (docs 7.2): sparse_plain, not_like_reference, mood, color_light, clipping, unreadable_object, "
                    "layout_scale, model_quality, missing_content, npc_life, camera, text_language, ui_delivery, game_error, other")
    fb.add_argument("--scope", default=None, choices=["project", "user", "game", "mode", "craft", "system"])
    fb.add_argument("--certainty", default=None, choices=["high", "low"], help="low = confirm it with her (a card) before changing anything")
    fb.add_argument("--target", default=None, help="the scene / place / object it is about")
    fb.add_argument("--state", default=None, help="set: force a state (dropped / answered need her agreement)")
    fb.add_argument("--as", dest="outcome", default=None, choices=["confirmed", "corrected"], help="confirm: was your reading right")
    fb.add_argument("--item", default=None, help="link: the STATUS item (r4)"); fb.add_argument("--new-item", default=None, help="link: make a new STATUS item with this text")
    fb.add_argument("--text-en", default=None, help="link --new-item: its English")
    fb.add_argument("--after", type=Path, default=None, help="verify: the re-shot after picture (inside the project, e.g. 5_build/m4/play/verify/f3_after.png)")
    fb.add_argument("--method", default="reshoot", choices=["reshoot", "chapter_offset", "listed"])
    fb.add_argument("--ok", action="store_true", help="verdict: she is happy with it"); fb.add_argument("--not-ok", action="store_true", help="verdict: not fixed")
    fb.add_argument("--how", default="explicit", help="accept: how she accepted (explicit / all_ok / take_home)")
    fb.add_argument("--kind-of-card", dest="card_kind", default="confirm", choices=["confirm", "verify"], help="card: which card")
    fb.add_argument("--out", type=Path, default=None, help="card / label --export: write here")
    fb.add_argument("--todo", action="store_true", help="pairs: only list what still needs a re-shot after picture (no automatic frames)")
    fb.add_argument("--role", default="builder", help="brief: builder | playtester"); fb.add_argument("--budget", type=int, default=12, help="brief: at most this many entries")
    fb.add_argument("--export", action="store_true"); fb.add_argument("--import", dest="import_file", type=Path, default=None)
    fb.add_argument("--labeller", default="judge", choices=["judge", "human"]); fb.add_argument("--set", dest="set_cond", default=None, help="condition: C0 … C4")
    fb.add_argument("--dry-run", action="store_true", help="backfill: only count what would be added")
    fb.add_argument("--card", dest="judge_card", action="store_true", help="judge: print the permission card (key feedback-judge)")
    fb.add_argument("--emit", action="store_true", help="judge: write the requests (only after her yes)"); fb.add_argument("--collect", action="store_true")
    fb.add_argument("--model", default=None, help="judge --emit: the model that answers the requests"); fb.add_argument("--frames", action="store_true", help="judge --emit: also the frames")
    fb.add_argument("--run", default=None, help="judge --collect: the run (default the newest)")
    fb.add_argument("--a", default="judge", help="agreement: labeller a (heuristic / resident / judge / judge_b / human:<name> / live)")
    fb.add_argument("--b", default="human", help="agreement: labeller b"); fb.add_argument("--field", default="kind", choices=["kind", "class", "target"])
    fb.add_argument("--human-sheet", action="store_true", help="label: a blind shuffled sheet for a human labeller"); fb.add_argument("--seed", type=int, default=0)
    fb.add_argument("--name", default=None, help="label --import: who labelled (human:<name>)"); fb.add_argument("--apply", action="store_true", help="label --import: also make them the live labels")
    fb.add_argument("--json", action="store_true")
    pf = sub.add_parser("profile", help="her preference profile (private, per user, docs/feedback-loop.md section 4): show / add / set / on / off / remove")
    pf.add_argument("what", choices=["show", "add", "set", "on", "off", "remove"])
    pf.add_argument("--project", type=Path, default=None, help="the profile of this project's owner (default: --owner, else local)")
    pf.add_argument("--owner", default=None); pf.add_argument("--id", default=None, help="the entry (p2)")
    pf.add_argument("--text", default=None); pf.add_argument("--text-en", default=None); pf.add_argument("--kind", default=None, help="the complaint kind it prevents")
    pf.add_argument("--modes", default=None, help="comma-separated project kinds it applies to (empty = all)"); pf.add_argument("--games", default=None); pf.add_argument("--projects", default=None)
    pf.add_argument("--from", dest="sources", nargs="+", default=None, metavar="PROJECT:RECORD", help="the feedback records it comes from")
    pf.add_argument("--confidence", default=None, choices=["low", "medium", "high"]); pf.add_argument("--status", default=None, choices=["candidate", "confirmed"])
    pf.add_argument("--by", default="retrospective", choices=["retrospective", "resident", "her"])
    pf.add_argument("--json", action="store_true")
    c = sub.add_parser("chat", help="the conversation shown in the browser UI: read what the user said, answer with text / cards / progress")
    c.add_argument("what", choices=["claim", "wait", "read", "say", "card", "progress", "import", "idle", "release"],
                   help="claim: become the one agent session that owns this conversation (exit 3 if another live one does; --force takes over) | wait: block until the user says something (exit 0; 2 on timeout) | read: print new user events, advance the cursor, copy their words to "
                        "feedback/answers.md | say: send a message | card: send a card from a yaml/json file | progress: update the progress card | import: seed history from answers.md | "
                        "release: let the conversation go (the next message is taken at once)")
    c.add_argument("--project", type=Path, default=None, help="the project folder (every command except `wait --all`)")
    c.add_argument("--listen", action="store_true", help="wait: run as a BACKGROUND listener while you keep working: the page keeps showing "
                   "\"agent is working\" until you run `gameanything chat idle`")
    c.add_argument("--unowned", action="store_true", help="wait: for a parent session that starts one sub-agent per project: wake when a project has new user "
                   "words and no live owner (claims nothing; prints UNOWNED<TAB>id<TAB>title<TAB>path); respects the maximum of active projects")
    c.add_argument("--ignore", nargs="*", help="wait --unowned: project paths to skip (a sub-agent is already starting there)")
    c.add_argument("--all", action="store_true", help="wait: watch every registered project; claims a new one automatically while fewer than the set maximum are active (D20), prints the projects to read")
    c.add_argument("--session", default=None, help="your session name (default: $CLAUDE_SESSION_ID, else host:ppid); the owner is the only session read / wait / say / card / progress accept")
    c.add_argument("--attach", nargs="+", type=Path, help="say: files to offer as download buttons under the message (copied into conversation/files/)")
    c.add_argument("--force", action="store_true", help="claim: take the conversation over from a live owner (posts a system event to the thread)")
    c.add_argument("--timeout", type=float, default=3600, help="wait: seconds before giving up (exit code 2)")
    c.add_argument("--text", default=None, help="say: the message (default: stdin)")
    c.add_argument("--text-en", default=None, help="say / card: the English of --text (shown when the UI is in EN); a card file may carry `en:` with the English card")
    c.add_argument("--user", action="store_true", help="say: record what the user told you in the terminal, as the user's own words (source terminal)")
    c.add_argument("--file", type=Path, default=None, help="card: yaml / json file with kind, title and the kind's fields")
    c.add_argument("--key", default="progress", help="progress: the card key (a new card with the same key replaces the old one)")
    c.add_argument("--milestone", default="", help="progress: label of the round")
    c.add_argument("--title", default="进行中", help="progress: card title")
    c.add_argument("--steps", nargs="+", default=[], help='progress: steps, each "text" or "state:text" (state done / current / todo; default todo)')
    c.add_argument("--title-en", default=None, help="progress: English card title")
    c.add_argument("--steps-en", nargs="+", default=[], help="progress: English of --steps, same order and format")
    e = sub.add_parser("estimate", help="what a build round may cost (wall time; dollars for API accounts, a quota warning for subscriptions): attach it to the `go` card")
    e.add_argument("--project", type=Path, default=None, help="the project: without --agent / --model the estimate is for its build model (config/project.yaml "
                   "build_model, the 「构建」 chip), the only model its builds run with")
    e.add_argument("--size", choices=["small", "medium", "large"], required=True, help="small = a feature like the record player; medium / large = wedding rounds")
    e.add_argument("--agent", default=None, help="claude-code | codex | opencode | gemini | dsh (default: the project's build model, else claude-code)")
    e.add_argument("--model", default=None, help="provider/model, e.g. anthropic/claude-opus-4, openrouter/deepseek/deepseek-chat")
    e.add_argument("--account", choices=["subscription", "api"], default=None, help="default: subscription for claude-code / codex, api otherwise")
    e.add_argument("--json", action="store_true", help="print only the JSON")
    e.add_argument("--yaml", action="store_true", help="print only the `estimate:` + `en:` yaml to paste into the go card file")
    e.add_argument("--runners", default=None, help="the go card's `runners:` (D21): comma-separated harness:model[:note], the first is recommended, e.g. "
                   "'Claude Code:anthropic/claude-sonnet:用过最多次,Claude Code:anthropic/claude-opus:更强、更贵'")
    bw = sub.add_parser("build", help="builds: `watch` keeps the progress card current (playtest round, time) while a gamebench trial runs; "
                        "`status` writes 5_build/<m>/build_status.yaml, which the page shows as the \"building\" banner (the coordinator, while a builder runs); "
                        "`deliver` is the builder's LAST step before reporting (checks the video, writes a missing play.yaml, registers the milestone in "
                        "world_plan.yaml; exit 1 = not delivered); `check` lists every 5_build folder and what it lacks (read only; the resident runs it before a result card); "
                        "`resume` (the coordinator) hands an auto build that waits (blocked / waiting_seat / elsewhere) back to agentd, tried again at "
                        "its next scan (release your own `gameanything lab` lease first: agentd waits while the project has a lease it did not take); "
                        "`takeover` (the coordinator) makes an auto build yours for good (agentd leaves it alone)")
    bw.add_argument("what", choices=["watch", "status", "deliver", "check", "resume", "takeover"])
    bw.add_argument("--project", type=Path, required=True); bw.add_argument("--session", default=None)
    bw.add_argument("--m", default=None, help="status: the milestone (m6)"); bw.add_argument("--round", type=int, default=None, help="status: the playtest round now")
    bw.add_argument("--max", type=int, default=None, help="status: at most this many rounds"); bw.add_argument("--step", default=None, help="status: what the builder does now (Chinese)")
    bw.add_argument("--step-en", default=None, help="status: the English of --step"); bw.add_argument("--started", default=None, help="status: when the build started (ISO time; default: kept, or now)")
    bw.add_argument("--done", action="store_true", help="status: the build is over (the banner goes away)")
    bw.add_argument("--blocked", default=None, help="status (builders): you stop because the LAB ENVIRONMENT is gone and `gameanything lab env up` could not "
                    "bring it back (the reason, one line): agentd keeps the request, brings the environment up again and restarts you with a resume note")
    bw.add_argument("--name", default=None, help="deliver: the round's name for the page, e.g. 「第 3 版 3D 菜品」 (kept when not given)")
    bw.add_argument("--what", dest="what_text", default=None, help="deliver: one line of what this round did (world_plan `what`; kept when not given)")
    bw.add_argument("--chapters", type=Path, default=None, help="deliver: a yaml / json file with the chapters ([{moment, title, t}] or {chapters: […]}, e.g. cine's final.chapters.yaml)")
    bw.add_argument("--key", default=None); bw.add_argument("--milestone", default=""); bw.add_argument("--trial", type=Path, default=None, help="the gamebench trial folder (…/trials/<task>/a1)")
    bw.add_argument("--steps", nargs="+", default=None, help="like chat progress; placeholders {round} {max_rounds} {round_text} {time_text}")
    bw.add_argument("--steps-en", nargs="+", default=[], help="placeholders {round_en} {time_en}")
    bw.add_argument("--title", default="构建中"); bw.add_argument("--title-en", default="Building")
    bw.add_argument("--max-rounds", type=int, default=6); bw.add_argument("--wall-min", type=int, default=300); bw.add_argument("--every", type=int, default=60)
    bw.add_argument("--runner", default=None, help='shown under the meter, e.g. "Claude Code + Claude Sonnet 5.5"')
    ad = sub.add_parser("agentd", help="the supervisor: starts one headless agent run per project with new user words (agentd.py)")
    ad.add_argument("what", nargs="?", default="run", choices=["run", "status", "request", "notify"],
                    help="run: the daemon | status: what it does now | request: (a run) ask the coordinator | notify: (the coordinator) tell a project's agent")
    ad.add_argument("--project", type=Path, default=None, help="request / notify: the project folder or id")
    ad.add_argument("--kind", default=None, help="request: build_start | build_change | question | gen_request_ready | other")
    ad.add_argument("--text", default=None, help="request / notify: what it is about, one or two plain sentences")
    ad.add_argument("--details", default=None, help="request: a JSON object (or @file.json) with the exact facts, e.g. card keys, runner, item list")
    ad.add_argument("--log-root", type=Path, default=None, help="run: logs go to <log-root>/<date>/agentd.log and agentd-runs/ (default <data>/agentd-logs)")
    ad.add_argument("--pid-file", type=Path, default=None); ad.add_argument("--once", action="store_true", help="run: one scan, then exit (tests)")
    ad.add_argument("--requests-dir", type=Path, default=None, help="run: where runs write coordinator requests (default $GAMEANYTHING_PARENT_REQUESTS or <data>/parent-requests)")
    ad.add_argument("--provider", default=os.environ.get("GAMEANYTHING_AGENT_PROVIDER", "claude-code"), choices=["claude-code", "codex", "opencode", "gemini", "dsh"],
                    help="headless coding agent for project conversations (default $GAMEANYTHING_AGENT_PROVIDER or claude-code)")
    ad.add_argument("--model", default=None, help="provider model (default: sonnet for Claude Code; Codex uses its configured model; OpenCode: "
                    "provider/model, default $GAMEANYTHING_OPENCODE_MODEL or openrouter/moonshotai/kimi-k2.6; Gemini: default $GAMEANYTHING_GEMINI_MODEL or the CLI's; "
                    "DeepSeek Harness (dsh): a DeepSeek model, default $GAMEANYTHING_DSH_MODEL or deepseek-v4-pro, or provider/model through dsh's pi-ai routes, "
                    "e.g. openrouter/deepseek/deepseek-v4.1-flash with OPENROUTER_API_KEY)")
    ad.add_argument("--agent-bin", default=None, help="provider CLI path (default $GAMEANYTHING_CLAUDE / $GAMEANYTHING_CODEX / $GAMEANYTHING_OPENCODE / $GAMEANYTHING_GEMINI / $GAMEANYTHING_DSH or PATH)")
    ad.add_argument("--claude", default=None, help="deprecated alias for --agent-bin with --provider claude-code")
    ad.add_argument("--budget-usd", type=float, default=None, help="run: --max-budget-usd for each agent run")
    ad.add_argument("--builds", default=os.environ.get("GAMEANYTHING_BUILDS", "auto"), choices=["auto", "coordinator"],
                    help="run: auto = agentd starts a builder for each build_start request itself (builds.py; default, env GAMEANYTHING_BUILDS) | "
                         "coordinator = build requests only wait for a coordinator session")
    ad.add_argument("--from", dest="sender", default="coordinator", choices=["coordinator", "builder"],
                    help="notify: who the note is from (the builder of a background build: --from builder)")
    gn = sub.add_parser("gen", help="asset generation, card-checked: list / estimate / request (queue; agentd checks both cards and runs it: genrun.py, gen/)")
    gn.add_argument("what", choices=["request", "status", "list", "estimate", "key"],
                    help="list: adapters, capabilities, key there yes/no | estimate: the go card's estimate | request: (a run) queue it, runs nothing | "
                         "status: the queue and the runs | key set|status|remove NAME: a key in the system keyring (single-user installs)")
    gn.add_argument("rest", nargs="*", help="key: set|status|remove and the key name (FAL_KEY (FAL_API_KEY also read), MESHY_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY)")
    gn.add_argument("--project", type=Path, default=None, help="the project folder or id (request / status; list: whose keys)")
    gn.add_argument("--tool", default=None, help="<adapter>:<capability> (fal:image, meshy:image-to-3d, gemini:edit, comfy:image ...); "
                                                 "old projects: the name after gen_ (meshy3d -> 4_design/tools/gen_meshy3d.py)")
    gn.add_argument("--permission", "--permission-key", dest="permission", default=None, help="request: the permission card's key or id (she said yes)")
    gn.add_argument("--go", "--go-key", dest="go", default=None, help="request: the go card's key or id (she pressed start); each go card runs once")
    gn.add_argument("--arg", action="append", default=[], help="old gen_<tool>.py request: one argument for the script after the project path (repeat; --arg=--redo for a dash)")
    gn.add_argument("--inputs", default=None, help="request / estimate: a yaml / json inside the project: {model, out, options, redo, jobs: [{name, prompt, images, n, options}]}")
    gn.add_argument("--prompt", default=None, help="request / estimate: one job's prompt (instead of --inputs)")
    gn.add_argument("--image", action="append", default=[], help="one job's input picture, project-relative (repeat)")
    gn.add_argument("--name", default=None, help="one job's output name (file stem)")
    gn.add_argument("--n", type=int, default=None, help="outputs per job (estimate: how many outputs)")
    gn.add_argument("--out", default=None, help="where under 4_design/ (targets, art/3d, ...)")
    gn.add_argument("--model", default=None, help="a model of the adapter's table (default: its first)")
    gn.add_argument("--option", action="append", default=[], help="K=V model option for every job (V read as yaml: 2048, true, [0, 0.1, 1, 0.9])")
    gn.add_argument("--redo", action="store_true", help="request: draw again even when the output exists")
    gn.add_argument("--from-file", type=Path, default=None, help="key set: read the key from this file instead of a hidden prompt")
    gn.add_argument("--json", action="store_true", help="list / estimate: print JSON")
    hb = sub.add_parser("hub", help="several users on one server (one port): login, own projects, roles, access requests (ui/hub.py, users.py)")
    hb.add_argument("--port", type=int, default=8800); hb.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (this machine only); 0.0.0.0 = reachable from the network (opt-in)")
    hb.add_argument("--upload-max-gb", type=float, default=20); hb.add_argument("--content", type=Path, default=None)
    hs = hb.add_subparsers(dest="hcmd")
    hu = hs.add_parser("user", help="hub users: add / passwd / list / remove / login (log in to Claude under the user's own config dir)")
    hus = hu.add_subparsers(dest="ucmd", required=True)
    x = hus.add_parser("add", help="add a user (asks for the password, or reads the first line of --password-file)")
    x.add_argument("name"); x.add_argument("--admin", action="store_true"); x.add_argument("--display", default=None, help="the name others see")
    x.add_argument("--password-file", type=Path, default=None)
    x.add_argument("--data-root", type=Path, default=None, help="where the user's projects go (default ~/workspace/<name>/m2w)")
    x.add_argument("--claude-config-dir", type=Path, default=None, help="the user's Claude login, CLAUDE_CONFIG_DIR of their agent runs (default ~/workspace/<name>/.claude-m2w)")
    x.add_argument("--env-file", type=Path, default=None, help="the user's own KEY=value file (API keys) for their agent runs; never printed")
    x.add_argument("--codex-home", type=Path, default=None, help="the user's own CODEX_HOME (their `codex login`; default ~/workspace/<name>/.codex-m2w)")
    x.add_argument("--agent", choices=["claude-code", "codex", "opencode", "gemini", "dsh"], default=None, help="which agent CLI runs their projects (default: agentd's --provider)")
    x = hus.add_parser("passwd", help="set a new password (ends the user's sessions)"); x.add_argument("name"); x.add_argument("--password-file", type=Path, default=None)
    hus.add_parser("list", help="the users, their folders and whether they have a Claude login")
    x = hus.add_parser("remove", help="remove a user (their projects stay)"); x.add_argument("name"); x.add_argument("--yes", action="store_true")
    x = hus.add_parser("login", help="start `claude` with CLAUDE_CONFIG_DIR = the user's config dir, to log in once (type /login there); "
                       "--agent codex: `codex login --device-auth` with CODEX_HOME = the user's codex home (their ChatGPT login); "
                       "--agent opencode: `opencode auth login` in the user's OpenCode home; --agent gemini: `gemini` with GEMINI_CLI_HOME = the user's Gemini home")
    x.add_argument("name"); x.add_argument("--claude", default=None, help="the claude CLI (default $GAMEANYTHING_CLAUDE or `claude` on PATH)")
    x.add_argument("--agent", choices=["claude-code", "codex", "opencode", "gemini"], default="claude-code", help="which login (default claude-code)")
    x = hus.add_parser("agent", help="which agent CLI runs a user's projects: claude-code | codex | opencode | gemini | dsh"); x.add_argument("name")
    x.add_argument("agent", choices=["claude-code", "codex", "opencode", "gemini", "dsh"])
    x = hus.add_parser("model", help="the model a user's OpenCode (provider/model), Gemini CLI or DeepSeek Harness runs use"); x.add_argument("name")
    x.add_argument("agent", choices=["opencode", "gemini", "dsh"]); x.add_argument("model", help="e.g. openrouter/moonshotai/kimi-k2.6 | gemini-3.1-pro-preview | deepseek-flash | openrouter/deepseek/deepseek-v4-pro ('' = default)")
    x = hs.add_parser("migrate", help="give every registered project without an owner this owner (config/project.yaml owner:)")
    x.add_argument("--owner", required=True); x.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("i18n", help="English for the project's content: list what has no translation yet, merge translations the agent wrote")
    i.add_argument("what", choices=["missing", "add"], help="missing: print the untranslated content strings as yaml to fill (nothing = complete) | add: merge a yaml file {中文: English}")
    i.add_argument("--project", type=Path, required=True)
    i.add_argument("--lang", default="en", choices=["en"])
    i.add_argument("--file", type=Path, default=None, help="add: the filled yaml")
    tx = sub.add_parser("text", help="text tools for adaptation projects: `simplify` converts traditional Chinese to simplified (OpenCC)")
    tx.add_argument("action", choices=["simplify"]); tx.add_argument("src", type=Path); tx.add_argument("-o", "--out", type=Path, help="default: print to stdout")
    tx.add_argument("--yaml", action="store_true", help="src is YAML (e.g. adaptation.yaml): convert every string value, keep keys and ids")
    dm = sub.add_parser("demo", help="a read-only, clickable copy of the browser UI on one project, as static files (docs/demo.md): `export`")
    dm.add_argument("action", choices=["export"])
    dm.add_argument("--project", type=Path, required=True, help="the project folder (export a cleaned COPY: the demo shows what is in it)")
    dm.add_argument("--out", type=Path, required=True, help="the folder to write (outside the project; re-running updates it, keeps encoded videos)")
    dm.add_argument("--lang", choices=["zh", "en"], action="append", default=None, help="the languages to export (default both; repeat for several)")
    dm.add_argument("--ffmpeg", default=None, help="ffmpeg to re-encode the videos with (default: GAMEANYTHING_FFMPEG or the one on PATH)")
    dm.add_argument("--max-mb", type=float, default=30, help="the size each video is encoded to stay under (default 30)")
    dm.add_argument("--keep-times", action="store_true", help="keep the dates and clock times (default: every time value is blanked)")
    dm.add_argument("--home", default="../", help="where the page's 「all examples」 tag links to (default ../)")
    dm.add_argument("--cover", action="append", default=[], metavar="WxH:x,y,w,h", help="paint this box black on every picture and video of exactly "
                    "that size (e.g. a tool's overlay in recordings); repeat for several")
    dm.add_argument("--preset", default="slow", help="x264 preset for the videos (default slow; veryfast on a busy machine)")
    dm.add_argument("--placeholder", action="append", default=[], metavar="GLOB", help="exported paths whose pictures / videos are replaced by a "
                    "neutral placeholder (e.g. 'media/1_ingest/*' for your own photos, or one file with real people in it); repeat for several")
    pj = sub.add_parser("project", help="the project list, and export / import of a whole project as one file")
    ps = pj.add_subparsers(dest="pcmd", required=True)
    ps.add_parser("list", help="the registered projects (id, kind, last opened, folder)")
    x = ps.add_parser("settings", help="the browser Settings as JSON (max_active_projects, record_builds, keys_file, keys_available): check record_builds before starting a build, keys_available before an approved model call")
    x.add_argument("--keys-file", default=None, help="set the user's KEY=value file (e.g. a .env) that approved model calls read their key from (never printed or copied); '' clears it")
    x.add_argument("--study", choices=["on", "off"], default=None, help="the global default of study mode for every project without its own (study.py; off by default; `set-study` per project)")
    x = ps.add_parser("set-study", help="study mode of one project (config/project.yaml study:): on = the evaluation of docs/feedback-loop.md 7 runs (blind conditions, "
                      "LLM judge card, label sheets, metrics log and panel); off = the product loop only (every version the full loop, nothing logged for a study); "
                      "default = follow the global default (`project settings --study`). No value: print it")
    x.add_argument("id"); x.add_argument("value", nargs="?", choices=["on", "off", "default"], default=None)
    x = ps.add_parser("new", help="create an empty project (folder skeleton + config/project.yaml) and register it")
    x.add_argument("--title", required=True); x.add_argument("--kind", choices=list(projects.KINDS), default="memory")
    x.add_argument("--game", choices=list(projects.GAMES), default=None, help="the game this project targets (written to config/project.yaml; default stardew, slay_the_spire for --kind gameplay)")
    x.add_argument("--dir", type=Path, default=None, help="where to create it (default: <data>/projects/<id>)"); x.add_argument("--lang", choices=["zh", "en"], default="en")
    x.add_argument("--mode", choices=["lab", "native"], default=None, help="where builds run (config/project.yaml build_mode): lab = the server's docker sandbox, native = the user's own copy of the game; omitted: not written (the automatic rule)")
    x = ps.add_parser("set-model", help="which agent CLI + model this project's chat (the resident) and builds use (config/project.yaml chat_model / build_model; "
                      "default = the owner's 「我的 agent」 in the hub, else the daemon's --provider / --model). No value: print both; --list: what the owner can use")
    x.add_argument("id"); x.add_argument("role", nargs="?", choices=["chat", "build"], default=None)
    x.add_argument("value", nargs="?", default=None, help="agent[:model], e.g. claude-code:opus, codex:gpt-6.1-sol, opencode:openrouter/z-ai/glm-5.3, codex (its default model); default = remove the choice")
    x.add_argument("--list", action="store_true", help="the agents and models the project's owner can use (the chat page's menu)")
    x = ps.add_parser("set-mode", help="change where a project's builds run (build_mode: lab | native); `--show` prints the choices for its game on this computer")
    x.add_argument("id"); x.add_argument("mode", nargs="?", choices=["lab", "native"], default=None); x.add_argument("--show", action="store_true")
    x = ps.add_parser("set-launch", help="native mode: when agents may open her game for a test (native_launch: ask = a card first, the default | window = only in a time window | always | idle = only after she has not used the computer for --minutes)")
    x.add_argument("id"); x.add_argument("policy", nargs="?", choices=["ask", "window", "always", "idle"], default=None)
    x.add_argument("--window", default=None, help="local time window, e.g. 22:00-08:00 (used by `window`, and the card's 「今晚 HH:MM 后」)")
    x.add_argument("--minutes", type=int, default=None, help="`idle`: minutes without mouse / keyboard input before the game may be opened (default 10)")
    x.add_argument("--drive", choices=["idle", "always"], default=None, help="may `gameanything native drive` press keys in the game GameAnything opened while she is at the computer (native_drive; default idle = only when she is away)")
    x.add_argument("--front", choices=["never", "away"], default=None, help="Windows: may drive bring the game GameAnything opened to the front while she is away "
                                                                          "(native_front, 「测试时允许把游戏切到前面」; default never)")
    x.add_argument("--hands", choices=["agent", "self"], default=None, help="who clicks in tests: agent (shot / drive) or self (she clicks, the agent never calls drive; "
                                                                          "native_hands, set by 「不给，我自己点」 on the readiness card)")
    x = ps.add_parser("migrate-mode", help="write build_mode into every registered project that has none (opt-in; default lab, the rule they were built with on Linux + docker)")
    x.add_argument("--mode", choices=["lab", "native"], default="lab"); x.add_argument("--dry-run", action="store_true")
    x = ps.add_parser("open", help="mark a project as the last-opened one and print its folder; --ui starts the browser UI on it")
    x.add_argument("id"); x.add_argument("--ui", action="store_true"); x.add_argument("--port", type=int, default=8765)
    x = ps.add_parser("game", help="change the game of a project that has no build yet")
    x.add_argument("id"); x.add_argument("game", choices=list(projects.GAMES))
    x = ps.add_parser("remove", help="unregister a project and move its folder to <data>/.trash/ (nothing is deleted)")
    x.add_argument("id"); x.add_argument("--yes", action="store_true", help="do not ask")
    x = ps.add_parser("export", help="pack the whole project into one zip (with a checksum list)")
    x.add_argument("--project", required=True, help="project folder or id"); x.add_argument("--out", type=Path, required=True)
    x.add_argument("--with-raw", type=Path, nargs="+", default=[], metavar="PATH", help="also pack these original-material folders under raw/")
    x = ps.add_parser("import", help="restore a project from an export zip (verifies every checksum; never overwrites a folder)")
    x.add_argument("file", type=Path); x.add_argument("--into", type=Path, default=None, help="parent folder (default: <data>/projects)")
    x.add_argument("--name", default=None, help="folder name of the restored project")
    bk = sub.add_parser("backup", help="optional automatic backup to a folder or a private Hugging Face dataset (off unless you turn it on)")
    bs = bk.add_subparsers(dest="bcmd", required=True)
    for n_, h_ in (("enable", "turn it on (asks you to type the target; needs a terminal)"), ("disable", "turn it off"),
                   ("run", "back up now (only new / changed files)"), ("status", "show settings and the last result")):
        x = bs.add_parser(n_, help=h_); x.add_argument("--project", required=True, help="project folder or id")
        if n_ == "enable":
            g = x.add_mutually_exclusive_group(required=True)
            g.add_argument("--folder", type=Path, help="backup folder (external disk, synced folder)"); g.add_argument("--hf", metavar="OWNER/NAME", help="your private Hugging Face dataset")
            x.add_argument("--include-raw", action="store_true"); x.add_argument("--raw", type=Path, nargs="+", default=[], help="original-material folders to include")
            x.add_argument("--every-minutes", type=int, default=30)
    x = bs.add_parser("token", help="Hugging Face token: `set` reads it with a hidden prompt, stores it in the keyring or a 0600 file; `status` says where it is found")
    x.add_argument("what", choices=["set", "status"])
    gm = sub.add_parser("game", help="the game packages (gameanything/games/ + plugins): list them, scaffold a new one, validate one (see games/tools.py, "
                                     "skills/gameanything/references/add-a-game.md)")
    gs = gm.add_subparsers(dest="gcmd", required=True)
    x = gs.add_parser("list", help="every registered game: id, title, engine, mod loader, adapter, lab, where it comes from")
    x.add_argument("--json", action="store_true"); x.add_argument("--markdown", action="store_true", help="the table of docs/games.md")
    x.add_argument("--write-docs", action="store_true", help="rewrite the table in docs/games.md (a checkout only)")
    x = gs.add_parser("new", help="scaffold a game package: game.yaml, adapter.py, a smoke mod for the loader type, a test file")
    x.add_argument("id"); x.add_argument("--title", required=True)
    x.add_argument("--loader", default="other", help="bepinex | smapi | tmodloader | fabric | modthespire | script | builtin | other")
    x.add_argument("--engine", default="TODO"); x.add_argument("--steam-appid", type=int, default=None)
    x.add_argument("--plugin", type=Path, default=None, help="make a separate pip-installable plugin in this folder (entry point gameanything.games) instead of a package in this checkout")
    x = gs.add_parser("check", help="validate a game package (fields, adapter, smoke mod, tests, docs) and what this computer has for it; exit 1 on errors")
    x.add_argument("id", nargs="?", default=None); x.add_argument("--path", type=Path, default=None, help="a package folder that is not registered yet")
    x.add_argument("--build", action="store_true", help="also build the smoke mod and run `native check` on it (when the game, its loader and the toolchain are here)")
    x.add_argument("--json", action="store_true")
    nt = sub.add_parser("native", help="native mode (D19): your own copy of the game, no docker: check, back up saves, install mods, launch, read the log")
    ns = nt.add_subparsers(dest="ncmd", required=True)
    from .native.games import GAMES as NATIVE_GAMES                 # every native adapter (games.py), new ones included
    G = list(NATIVE_GAMES)
    x = ns.add_parser("doctor", help="what this machine has (system, mode, lab backend, ffmpeg / dotnet / java) and where each game is (read only); --project: that project's chosen build_mode")
    x.add_argument("--game", choices=G, default=None); x.add_argument("--json", action="store_true")
    x.add_argument("--project", default=None, help="project folder or id: show its build_mode (lab | native) as the mode")
    x.add_argument("--copy", action="store_true", help="macOS: put the game's Steam launch option (--game) on the clipboard (pbcopy): paste it with Cmd-V, "
                                                     "typing it can turn the quotes into curly quotes")
    for n_, h_ in (("backup", "copy the game's saves (and Cities' mod switches) to GameAnything's backup folder"), ("backups", "list the backups"),
                   ("restore", "put a backup back (the game must be closed; what is there now goes to the trash)"),
                   ("build", "compile a mod (Stardew Valley: *.cs + manifest.json [+ *.csproj] -> the SMAPI mod DLL with ModBuildConfig; Cities: Skylines: Source/*.cs -> <name>.dll, needed on macOS; The Sims 4: scripts/*.py -> .ts4script with Python 3.7, package/ -> .package; "
                            "Slay the Spire: src/**/*.java + resources/ -> <modid>.jar; Overcooked! 2 / Valheim: *.csproj -> the BepInEx plugin DLL; Terraria: build.txt + *.cs -> <Name>.tmod with tModLoader's own packer)"),
                   ("install", "copy a built mod into the game's Mods folder (saves are backed up first; a same-named mod goes to the trash)"),
                   ("uninstall", "move a mod GameAnything installed to the trash"), ("mods", "the mods GameAnything installed"),
                   ("log", "the end of the game's newest log")):
        x = ns.add_parser(n_, help=h_); x.add_argument("--game", choices=G, required=True)
        if n_ == "restore": x.add_argument("stamp", help="from `gameanything native backups`")
        if n_ == "build": x.add_argument("src", type=Path, help="the mod folder (Stardew: *.cs + manifest.json, or a content pack: manifest.json with ContentPackFor + content.json; Cities: Source/*.cs; Sims 4: scripts/ and / or package/; Slay the Spire: src/ + resources/ModTheSpire.json; Overcooked! 2 / Valheim: *.csproj + *.cs)"); x.add_argument("--name", default=None); x.add_argument("--install", action="store_true", help="install the result right away")
        if n_ == "install": x.add_argument("src", type=Path, help="the mod folder (or a .jar for Minecraft and Slay the Spire, a .dll for Overcooked! 2 / Valheim, a .tmod for Terraria)"); x.add_argument("--name", default=None, help="folder name in Mods (default: the source name)")
        if n_ == "uninstall": x.add_argument("name")
        if n_ == "log": x.add_argument("--lines", type=int, default=40); x.add_argument("--grep", default=None, help="only lines containing this")
    # 本机模式少打扰: these act for one project (its game and its 「什么时候开游戏」 setting)
    x = ns.add_parser("launch", help="open the project's game for a test, ONLY with her yes: native_launch ask (default) posts the card 「要开游戏测一下，现在可以吗？」 and "
                                     "returns pending (exit 2) until she taps 现在可以 (or 今晚 HH:MM 后 has come); window / always follow her setting. Refuses (exit 3) when the game is already open. "
                                     "Batch the round's changes first: one launch per round")
    x.add_argument("--reason", default=None, help="one line for her above the card: what will be tested (Chinese)"); x.add_argument("--reason-en", default=None)
    x.add_argument("--minutes", type=int, default=None, help="about how long the game stays open (on the card)")
    x.add_argument("--round", default=None, help="a label for this build round (e.g. m2-r1): `launches` counts per round for the progress card")
    x.add_argument("--wait", type=float, default=0, help="seconds to wait for her answer before returning pending (run it in the background)")
    x.add_argument("--ask-again", action="store_true", help="post a new card (only after she said 「等我说」 and then said in the chat that it is fine now)")
    x.add_argument("--no-post", action="store_true", help="only look: never post a card")
    x.add_argument("--dry-run", action="store_true", help="say whether it would open the game now; open nothing")
    x.add_argument("--keep-window", action="store_true", help="do not switch the game to a small window for this launch")
    x.add_argument("--settle", type=float, default=30, help="seconds to look for the game's process after opening it")
    x.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    x = ns.add_parser("close", help="close the game GameAnything opened for this project (and put its window settings back); never a game she opened herself")
    x = ns.add_parser("reload", help="hot reload a newly built mod into the open game where the game can (Overcooked 2 / Valheim with BepInEx ScriptEngine, Cities: Skylines on Windows / macOS; not on Linux); "
                                     "others say why not (restart needed)")
    x.add_argument("src", type=Path, help="the built mod (the staged folder or DLL from `native build`)"); x.add_argument("--name", default=None)
    x.add_argument("--setup", action="store_true", help="Overcooked 2 / Valheim: switch on ScriptEngine's file watcher in its own config (backed up first)")
    x = ns.add_parser("check", help="headless checks without opening her game: references against the game's assemblies / jars, manifests, bytecode; "
                                    "Minecraft --server: the mod in a headless Fabric dedicated server")
    x.add_argument("--src", type=Path, default=None, help="the built mod (folder, .jar, .dll); default: every mod GameAnything installed for the game")
    x.add_argument("--server", action="store_true", help="Minecraft: start a headless Fabric server with the mod (her one-time setup, see docs)")
    x.add_argument("--gametest", action="store_true", help="Minecraft: run the mod's GameTests on that server (-Dfabric-api.gametest) and exit")
    x.add_argument("--timeout", type=int, default=300); x.add_argument("--json", action="store_true")
    x = ns.add_parser("launches", help="when GameAnything opened the game for this project, and how many launches each round used (for the progress card)")
    x.add_argument("--round", default=None)
    x = ns.add_parser("shot", help="a picture of ONLY the game window GameAnything opened for this project (not the screen; never brings it to the front). Refused (exit 3) for a game she opened")
    x.add_argument("--out", type=Path, default=None, help="the .png (default <project>/5_build/native-shots/<game>-<time>.png)")
    x = ns.add_parser("drive", help="keys / clicks / text to ONLY the game window GameAnything opened (no focus change). Exit 2 (paused) while she is at the computer "
                                    "(input in the last 60 s) unless native_drive is always; stops as soon as she comes back; exit 3 refused (not GameAnything's game, or native_hands: self). "
                                    "Windows: keys reach only the foreground window; with native_front: away the game is brought to the front only while she is away")
    x.add_argument("steps", nargs="+", help='each one: "key <name>" | "click <x> <y> [right]" (in the window) | "type <text>" | "sleep <ms>"')
    x.add_argument("--click", choices=["auto", "pid", "hid"], default="auto",
                   help="macOS: how clicks are sent. pid = CGEventPostToPid (no cursor move); hid = a real cursor move + click, only while the game is the "
                        "front window and she is away; auto = what works for this game (Stardew Valley, Slay the Spire: hid)")
    ns.add_parser("idle", help="seconds since the last mouse / keyboard input on this computer, or unknown (Wayland without GNOME, no display)")
    x = ns.add_parser("permissions", help="what this computer allows for shot / drive / idle (macOS: Accessibility + Screen Recording) and how to grant it")
    x.add_argument("--open", action="store_true", help="macOS: open the two System Settings panes"); x.add_argument("--json", action="store_true")
    x.add_argument("--lang", choices=["zh", "en"], default=None, help="language of the printed text (default en; --json has both)")
    x = ns.add_parser("ready", help="能不能操作屏幕: can the agent that runs this command look at / click the game? Its framework and sandbox (run it FROM the agent), "
                                    "the system's permissions for the app it runs in, and one tiny capture (never saved, never a key or click). Exit 0 full (look + click), "
                                    "1 look only, 3 none. --project: records it for the project's agent + model, applies her answer on the readiness card and says what to do next")
    x.add_argument("--project", default=None, help="project folder or id (records the result; re-checks when the role's agent / model changes)")
    x.add_argument("--role", choices=["chat", "build"], default=None, help="whose agent this is for (default: build when GAMEANYTHING_ROLE=builder, else chat)")
    x.add_argument("--if-needed", action="store_true", help="use the project's record when it was made for the same agent + model (no probe)")
    x.add_argument("--card-file", type=Path, default=None, help="when a card is needed: write it here (yaml) for `gameanything chat card --file` (write it under $TMPDIR)")
    x.add_argument("--lang", choices=["zh", "en"], default=None, help="language of the printed text (default: the project's lang, else en; --json has both)")
    x.add_argument("--json", action="store_true")
    x = ns.add_parser("minecraft", help="Minecraft: Java Edition without the Launcher (Windows / macOS / Linux): `login` shows a code, she signs in "
                                        "on her own phone at microsoft.com/link (no password passes through GameAnything) and the account is checked "
                                        "to own the game; `download` then fetches the game + Fabric + Fabric API from the official sources (every "
                                        "file hash-checked) into this system's .minecraft; `status` / `logout`")
    x.add_argument("what", choices=["login", "status", "logout", "download"])
    x.add_argument("--recheck", action="store_true", help="status: check ownership again from the saved token (no new sign-in)")
    x.add_argument("--version", default=None); x.add_argument("--fabric", default=None); x.add_argument("--fabric-api", default=None)
    x.add_argument("--json", action="store_true")
    for n_ in ("launch", "close", "reload", "check", "launches", "shot", "drive"):
        x = ns.choices[n_]; x.add_argument("--project", required=True, help="project folder or id"); x.add_argument("--game", choices=G, default=None, help="default: the project's game")
    fl = sub.add_parser("flow", help="where the project is in its flow (flow.py): `next` = the step to work on and exactly what it needs; `check` = its exit criteria")
    fl.add_argument("what", choices=["next", "check"]); fl.add_argument("--project", required=True, help="project folder or id")
    fl.add_argument("--step", default=None, help="check: this step (default: the step to work on)"); fl.add_argument("--json", action="store_true")
    sg = sub.add_parser("setup", help="the setting a project works in (setupguide.py): `guide` = detect this computer, pick the mode, print the guide to read "
                        "(skills/gameanything/references/setups/) and record it in the project; `tables` = the guides' generated per-game tables")
    sg.add_argument("what", choices=["guide", "tables"]); sg.add_argument("--project", default=None, help="project folder or id")
    sg.add_argument("--mode", choices=["sandbox", "native"], default=None, help="default: the project's build_mode (lab = sandbox), else the recommended one")
    sg.add_argument("--system", choices=["linux", "mac", "windows"], default=None, help="when detection failed, or on the hub for native mode: the user's own system")
    sg.add_argument("--hub", action="store_true", help="this runs on the hub's server (detected by itself for hub projects)")
    sg.add_argument("--no-record", action="store_true", help="guide: only print, do not write setup: into config/project.yaml")
    sg.add_argument("--read", default=None, metavar="TOKEN", help="guide: you read the whole guide it printed: its read marks in order, joined with - (records guide_read_at)")
    sg.add_argument("--write", action="store_true", help="tables: rewrite the out-of-date tables"); sg.add_argument("--json", action="store_true")
    rf = sub.add_parser("refs", help="reference pictures of PUBLIC places from the web, only after her yes on a websearch card (refs.py): `fetch` saves one "
                        "into 2_perceive/landmark_refs/<place>/ with its source (in a run: agentd downloads it), `status`, `check`")
    rf.add_argument("what", choices=["fetch", "status", "check"]); rf.add_argument("--project", required=True, help="project folder or id")
    rf.add_argument("--place", default=None, help="fetch: the public place (folder name), e.g. \"Geisel Library\"")
    rf.add_argument("--url", default=None, help="fetch: the picture's own http(s) address (not the page)")
    rf.add_argument("--query", default=None, help="fetch: the search words you used (only the public place: no names of people)")
    rf.add_argument("--consent", default=None, help="fetch: the key or id of the websearch permission / options card she said yes on")
    rf.add_argument("--page", default=None, help="fetch: the page the picture is on (for the source)")
    rf.add_argument("--license", default=None, help="fetch: its license as the page says (CC BY-SA 4.0, public domain, ...; default unknown)")
    rf.add_argument("--author", default=None); rf.add_argument("--side", default=None, help="fetch: which side it shows (front, aerial, detail ...)")
    rf.add_argument("--wait", type=int, default=60, help="fetch in a run: seconds to wait for agentd (then the outcome comes as a note)")
    vs = sub.add_parser("visuals", help="adaptation: keyframes per shot (ffmpeg scene changes) and people crops clustered by look, from the work's videos; local only")
    vs.add_argument("--project", required=True); vs.add_argument("--no-people", action="store_true"); vs.add_argument("--threshold", type=float, default=0.3)
    adp = sub.add_parser("adaptation", help="adaptation data tools: `translate` lists / merges the other-language fields the pages show")
    adp.add_argument("what", choices=["translate"]); adp.add_argument("--project", required=True)
    adp.add_argument("--out", default=None, help="write the missing fields as a fill-in yaml"); adp.add_argument("--apply", default=None, help="merge a filled yaml")
    a = ap.parse_args(argv)
    if a.cmd == "flow":
        from . import flow
        return flow.main(a)
    if a.cmd == "setup":
        from . import setupguide
        return setupguide.main(a)
    if a.cmd == "refs":
        from . import refs
        if a.what == "fetch" and not (a.place and a.url and a.query and a.consent): sys.exit("[refs] fetch 需要 --place、--url、--query 和 --consent")
        return refs.main(a)
    if a.cmd == "visuals":
        from . import visuals
        r = visuals.run(projects.resolve(a.project), not a.no_people, a.threshold)
        if not r.get("videos"): print("[visuals] 这个项目的素材里没有视频"); return 0
        print(f"[visuals] {r['videos']} 段视频，{r['shots']} 个镜头，{r['frames']} 张关键画面 -> 2_perceive/keyframes/index.yaml"
              + (f"；{r['people']} 组人物画面（{r['method']}）-> 2_perceive/people/index.yaml" if "people" in r else "")
              + "。只在本机，不发给模型；已记进 privacy_ledger.yaml"); return 0
    if a.cmd == "adaptation":
        from . import adaptation_tr
        return adaptation_tr.main(a)
    if a.cmd == "text": return text_cmd(a)
    if a.cmd == "demo": return demo_cmd(a)
    if a.cmd == "native": return native_cmd(a)
    if a.cmd == "game": return game_cmd(a)
    if a.cmd == "project": return project_cmd(a)
    if a.cmd == "backup": return backup_cmd(a)
    if a.cmd == "chat": return chat(a)
    if a.cmd == "estimate": return estimate_cmd(a)
    if a.cmd == "extras": return extras_cmd(a)
    if a.cmd == "i18n": return i18n(a)
    if a.cmd == "agentd": return agentd_cmd(a)
    if a.cmd == "gen": return gen_cmd(a)
    if a.cmd == "hub": return hub_cmd(a)
    if a.cmd == "build" and a.what in ("deliver", "check", "resume", "takeover"): a.project = projects.resolve(a.project)   # a folder or a project id
    if a.cmd == "build" and a.what in ("resume", "takeover"):
        from . import builds
        if not a.m: sys.exit(f"[build] {a.what} 需要 --m（例如 m6）")
        try: r = (builds.resume if a.what == "resume" else builds.takeover)(a.project, a.m)
        except ValueError as e: sys.exit(f"[build] {e}")
        print(f"[build] {a.project.name} {a.m}: {r['state']}"
              + ("  agentd tries it again at its next scan" if a.what == "resume" else "  agentd leaves it alone from now on"))
        return 0
    if a.cmd == "build" and a.what == "status":
        from .buildwatch import write_status
        if not a.m: sys.exit("[build] status 需要 --m（例如 m6）")
        try: f, d = write_status(a.project, a.m, a.round, a.max, a.step, a.started, a.done, a.step_en, blocked=a.blocked)
        except (ValueError, OSError) as e: sys.exit(f"[build] {e}")
        print(f"[build] {f}: " + ("done" if d.get("done") else f"round {d.get('round')}/{d.get('max_rounds')} · {d.get('step') or ''}")
              + (f" · blocked: {d['blocked']['reason']}" if d.get("blocked") else ""))
        if a.done:
            from .delivery import check
            r = next((x for x in check(a.project, a.m, probe=False) if x["m"] == a.m), None)
            if r and not r["ok"]:
                print(f"[build] 注意：{a.m} 还没交付好（{'；'.join(r['problems'])}），试玩页可能看不到它。"
                      f"请跑 gameanything build deliver --project {a.project} --m {a.m} --name …", file=sys.stderr)
        return 0
    if a.cmd == "build" and a.what == "deliver":
        from .delivery import deliver
        if not a.m: sys.exit("[build] deliver 需要 --m（例如 m6）")
        r = deliver(a.project, a.m, a.name, a.what_text, a.chapters)
        mark = {"ok": "OK  ", "fix": "改了", "warn": "注意", "fail": "不行"}
        print(f"[build deliver] {a.project} {a.m}")
        for k, t in r["lines"]: print(f"  {mark[k]} {t}")
        print("  交付好了：试玩页会列出这一版" if r["ok"] else "  没交付好：修好上面「不行」的几项再跑一次（不要发 result 卡）")
        return 0 if r["ok"] else 1
    if a.cmd == "build" and a.what == "check":
        from .delivery import check, check_text
        rows = check(a.project, a.m)
        print(check_text(rows, str(a.project)))
        return 0 if all(r["ok"] for r in rows) else 1
    if a.cmd == "build":
        if not (a.key and a.trial and a.steps): sys.exit("[build] watch 需要 --key、--trial 和 --steps")
        from .buildwatch import watch
        from .conversation import Thread, default_session
        T = Thread(a.project); me = a.session or default_session(); T.guard(me)
        s = watch(T, me, a.key, a.milestone, a.trial, a.steps, a.steps_en, a.max_rounds, a.wall_min, a.every, a.title, a.title_en, a.runner)
        print(f"[build] {s['status']}: {s['round_text']} · {s['time_text']}"); return 0
    if a.cmd == "ui":
        from .ui import serve
        from . import agentd
        how = agentd.ensure_running()        # the page's agent is the supervisor's runs: no supervisor, no answers
        if how == "started": print("[ui] 后台调度 (gameanything agentd) 没在运行，已经替你启动")
        elif how == "failed": print("[ui] 后台调度 (gameanything agentd) 启动失败：对话里的话会排队。可以另开终端运行 gameanything agentd run", file=sys.stderr)
        elif how == "no_claude": print("[ui] 没找到 claude 命令：后台调度起不来，对话里的话会排队没人读。先装好并登录 Claude Code。", file=sys.stderr)
        elif how == "no_agent": print("[ui] 没找到配置的 agent 命令：后台调度起不来，对话里的话会排队没人读。请检查 GAMEANYTHING_AGENT_PROVIDER 和对应 CLI。", file=sys.stderr)
        root = projects.resolve(a.project) if a.project else projects.last_opened()
        # no project yet: the page starts with the welcome page and its new-project wizard
        serve(root, a.port, a.content, upload_max=int(a.upload_max_gb * 2 ** 30)); return 0
    if a.cmd == "video":
        from . import video
        r = video.contact(a.video, a.out or a.video.with_suffix(".contact.jpg"), a.cols, a.rows, a.width, a.start, a.end)
        print(f"[video] {r['sheet']}  {r['size'][0]}x{r['size'][1]}, {len(r['frames'])} frames"); return 0
    if a.cmd == "art":
        import yaml
        from .worlds.stardew.art import sprites, portraits
        A = a.project / "4_design" / "art"; looks = yaml.safe_load(open(A / "looks.yaml", encoding="utf-8")) or {}
        ids = [x for x in a.only.split(",") if x] or list(looks)
        if a.what == "walks":
            (A / "walk").mkdir(exist_ok=True)
            for pid in ids: sprites.build(a.content, looks[pid]).save(A / "walk" / f"{pid}.png")
            print(f"[art] {len(ids)} walk sprites in {A / 'walk'}")
        else:
            ex = [x for x in a.expressions.split(",") if x]
            print(f"[art] portraits for {len(ids)} people x {len(ex)} expression(s): sends each person's face crop + a vanilla style reference to the image model")
            if not a.yes: sys.exit("[art] not sent: add --yes to confirm")
            for pid in ids: portraits.generate(a.project, a.content, pid, ex)
        return 0
    if a.cmd == "lessons": return lessons_cmd(a)
    if a.cmd == "feedback": return feedback_cmd(a)
    if a.cmd == "profile": return profile_cmd(a)
    if a.cmd == "status" and a.what != "readme": return devstatus_cmd(a)
    if a.cmd == "status":
        from .status import write
        print(write(a.project)); return 0
    if a.cmd == "perceive":
        from .perceive import perceive
        perceive(a.project, a.model, lang=a.lang, backend=a.backend, jobs=a.jobs, only=[x for x in a.only.split(",") if x], yes=a.yes, dry_run=a.dry_run,
                 mode="emit" if a.emit else "collect" if a.collect else "call")
    if a.cmd == "ingest":
        from .ingest import ingest
        if not a.project.is_dir():                                     # a registered id (2026-11-01: an id made a stray folder in the cwd)
            try: a.project = Path(projects.find(str(a.project))["path"])
            except KeyError: pass
        ingest(a.folder, a.project, transcribe=not a.no_transcribe, whisper_model=a.whisper_model,
               vocab=[w.strip() for w in a.vocab.split(",") if w.strip()], detect=not a.no_detect)
    from .status import write
    write(a.project)
    return 0


def project_cmd(a):
    from . import projects, transfer
    c = a.pcmd
    try:
        if c == "settings":
            import json
            from . import keys
            if a.keys_file is not None: projects.save_settings({"keys_file": a.keys_file})
            if a.study is not None:
                from . import study
                for i, v in study.set_global(a.study == "on", by="cli"): print(f"[project] {i}  study={'on' if v else 'off'} (the global default)", file=sys.stderr)
            print(json.dumps({**projects.settings(), "keys_available": {k: keys.available(k) for k in ("OPENROUTER_API_KEY",)}})); return 0
        if c == "list":
            es = projects.load()
            for e in sorted(es, key=lambda e: e.get("last_opened") or ""):
                print(f"{e['id']:<24} {e['kind']:<10} {e.get('game') or 'stardew':<16} {(e.get('last_opened') or '-')[:16]:<16}  {e['title']}  {e['path']}")
            if not es: print("(no projects yet: gameanything project new --title ...)")
        elif c == "new":
            g = a.game or projects.DEFAULT_GAME.get(a.kind, "stardew")
            e = projects.create(a.title, a.kind, a.dir, a.lang, g, build_mode=a.mode); print(f"[project] {e['id']}  {e['path']}  game={g}" + (f"  build_mode={a.mode}" if a.mode else ""))
        elif c == "set-mode":
            from . import buildmode
            e = projects.find(a.id)
            if a.mode: buildmode.set_mode(a.id, a.mode)
            mode, src = buildmode.effective(Path(e["path"]))
            print(f"[project] {e['id']}  build_mode={mode}" + ("" if src == "project" else " (not chosen: the automatic rule)"))
            if a.show or not a.mode:
                o = buildmode.all_options(hub=False)[projects.game_of(Path(e["path"]))]
                for x in o["options"]:
                    print(f"  {x['mode']:<7} {'ok' if x['ok'] else 'no'}{'  (recommended: ' + o['why'].format(**o['vars']) + ')' if o['recommended'] == x['mode'] else ''}  {x['note'] or x['why'].format(**x['vars'])}")
        elif c == "set-model":
            from . import models
            e = projects.find(a.id); root = Path(e["path"])
            if a.value is not None:
                if not a.role: sys.exit("[project] set-model: say chat or build before the value")
                ag, _, mo = a.value.partition(":")
                try: models.set_choice(root, a.role, None if ag == "default" else ag, mo)
                except models.ModelError as x: sys.exit(f"[project] {x}")
                if models.warning(ag, mo): print(f"[project] 注意：{models.warning(ag, mo)}")
            print(f"[project] {e['id']}  {models.text(root)}")
            if a.list:
                st = models.state(root)
                for g in st["agents"]:
                    print(f"  {g['id']:<12} " + ", ".join(m["id"] or "(default)" for m in g["models"]) + (f"  (or any: {g['placeholder']})" if g.get("free") else ""))
                if not st["agents"]: print("  (the owner has no agent login yet)")
        elif c == "set-study":
            from . import study
            e = projects.find(a.id)
            if a.value: study.set_project(Path(e["path"]), {"on": True, "off": False, "default": None}[a.value], by="cli")
            print(f"[project] {e['id']}  {study.text(Path(e['path']))}")
        elif c == "set-launch":
            from .native import quiet
            e = projects.find(a.id)
            if a.policy or a.window or a.minutes is not None or a.drive or a.front or a.hands:
                quiet.set_policy(a.id, a.policy or (quiet.policy(Path(e["path"]))["mode"] if a.window or a.minutes is not None else None),
                                 a.window, a.minutes, a.drive, a.front, a.hands)
            p = quiet.policy(Path(e["path"]))
            print(f"[project] {e['id']}  native_launch={p['mode']}" + ("" if p["chosen"] else " (default)") + f"  window={p['window']}"
                  f"  idle_minutes={p['idle_minutes']}  drive={p['drive']}  front={p['front']}  hands={p['hands']}")
        elif c == "migrate-mode":
            from . import buildmode
            done = buildmode.migrate(a.mode, a.dry_run)
            for i, p in done: print(f"[project] {i}  build_mode={a.mode}{' (dry run)' if a.dry_run else ''}  {p}")
            if not done: print("[project] every registered project already has a build_mode")
        elif c == "game":
            e = projects.set_game(a.id, a.game); print(f"[project] {e['id']}  game={e['game']}")
        elif c == "open":
            e = projects.touch(projects.find(a.id)["path"]); print(f"[project] {e['id']}  {e['path']}")
            if a.ui:
                from .ui import serve
                serve(Path(e["path"]), a.port)
        elif c == "remove":
            e = projects.find(a.id)
            if not a.yes:
                if not sys.stdin.isatty(): sys.exit("[project] remove asks first: run it in a terminal, or add --yes")
                if input(f"Move {e['path']} to the trash and remove '{e['id']}' from the list? Type the id to confirm: ").strip() != e["id"]: sys.exit("[project] cancelled")
            print(f"[project] moved to {projects.remove(e['id'])}" if Path(e["path"]).exists() else "[project] unregistered (the folder was already gone)")
        elif c == "export":
            last = [0.0]

            def prog(done, total, nf, tf):
                if time.time() - last[0] > 2 and sys.stderr.isatty(): last[0] = time.time(); print(f"\r[export] {done / 2 ** 20:.0f} / {total / 2 ** 20:.0f} MB", end="", file=sys.stderr, flush=True)
            r = transfer.export_project(projects.resolve(a.project), a.out, a.with_raw, prog)
            print(f"\n[export] {r['path']}  {r['bytes'] / 2 ** 20:.1f} MB, {r['files']} files" + (f" ({r['skipped']} caches / game files left out)" if r["skipped"] else ""))
        elif c == "import":
            r = transfer.import_project(a.file, a.into, a.name)
            print(f"[import] {r['path']}  ({r['files']} files, {r['bytes'] / 2 ** 20:.1f} MB, all checksums match; registered as '{r['id']}')"
                  + (f"\n[import] original material: {r['raw']}" if r["raw"] else ""))
    except (transfer.TransferError, KeyError, ValueError, OSError) as e:
        sys.exit(f"[project] {e.args[0] if isinstance(e, KeyError) else e}")
    return 0


def lessons_cmd(a):
    import json
    from . import lessons as L, projects
    try:
        if a.what == "show":
            if a.json:
                print(osdirs.json_text([{k: v for k, v in e.items() if k != "_extra"} for e in L.show(a.game, a.role)], indent=1)); return 0
            print(L.show_text(a.game, a.role)); return 0
        if a.what == "add":
            if not a.role: sys.exit("[lessons] add 需要 --role builder|playtester")
            if not a.game and not a.general: sys.exit("[lessons] add 需要 --game（和游戏无关的加 --general）")
            if a.symptom is None or a.fix is None: sys.exit("[lessons] add 需要 --symptom 和 --fix（--cause、--evidence 也最好写）")
            r = L.add(a.game, a.role, a.symptom, a.cause, a.fix, a.evidence, local=a.local, general=a.general, confidence=a.confidence,
                      force=a.force, project=projects.resolve(a.project) if a.project else None)
            if a.json: print(osdirs.json_text(r)); return 0
            if r["action"] == "merged":
                print(f"[lessons] 和 {r['id']} 很像（{r['similar'][0][1]:.2f}）：没有新加，给它加了一行证据，可信度改成 verified repeatedly。真的不一样就加 --force")
            else: print(f"[lessons] 加了候选 {r['id']}  {r['file']}")
            return 0
        done = False
        for i in a.confirm: print(f"[lessons] 确认 {i}  {L.confirm(i)}"); done = True
        for i in a.drop: print(f"[lessons] 删掉 {i}  {L.drop(i)}"); done = True
        if a.merge: print(f"[lessons] {a.merge[1]} 并进了 {a.merge[0]}  {L.merge(*a.merge)}"); done = True
        if done: return 0
        if a.json:
            print(osdirs.json_text([{k: v for k, v in e.items() if k != "_extra"} for e in L.candidates()], indent=1)); return 0
        print(L.review_text()); return 0
    except L.LessonError as e: sys.exit(f"[lessons] {e}")


STUDY_ONLY = ("metrics", "label", "condition", "judge", "agreement", "match", "datacheck")      # `gameanything feedback …` commands of the study (study.py)


def feedback_cmd(a):
    import json
    import yaml
    from . import feedback as F, projects
    root = projects.resolve(a.project)
    js = lambda x: print(osdirs.json_text(x, indent=1, default=str))
    try:
        w = a.what
        from . import study
        if w in STUDY_ONLY and not study.on(root):
            sys.exit(f"[feedback] 研究模式没开（gameanything project set-study <项目> on）：`feedback {w}` 只在做研究时用；不要跟她提研究")
        if w == "show":
            if a.json: js(F.load(root)); return 0
            print(F.show_text(root)); return 0
        if w == "add":
            r = F.add(root, a.words, a.event, a.m, a.interpretation, a.cls, a.kind, a.scope, a.certainty, a.target)
            print(f"[feedback] {r['id']} 记下了（{r['state']}）" + (f"；和 {', '.join(r['repeat_of'])} 是同一类意见：这是她第二次说" if r.get("repeat_of") else "")
                  + ("；理解不确定：先发确认卡 gameanything feedback card --project P --ids " + r["id"] if r.get("certainty") == "low" else "")); return 0
        if not a.id and w in ("set", "confirm", "link", "verify", "verdict"): sys.exit(f"[feedback] {w} 需要 --id")
        if w == "set":
            r = F.set_fields(root, a.id, a.interpretation, a.interpretation_en, a.cls, a.kind, a.scope, a.certainty, a.target, a.state)
            print(f"[feedback] {r['id']}：{r['state']} {r.get('class')}/{r.get('kind')}" + (f"；重复：{', '.join(r['repeat_of'])}" if r.get("repeat_of") else "")
                  + ("；理解不确定：先发确认卡（gameanything feedback card --project P --ids " + r["id"] + "），她答了再改" if r["state"] == "confirming" else "")); return 0
        if w == "confirm":
            r = F.confirm(root, a.id, a.outcome or "confirmed", a.interpretation, a.event); print(f"[feedback] {r['id']}：{r['confirm']['state']}，现在 {r['state']}"); return 0
        if w == "link":
            r = F.link(root, a.id, a.item, a.new_item, a.text_en); print(f"[feedback] {r['id']} → STATUS {r['status_item']}（{r['state']}）"); return 0
        if w == "verify":
            if not a.m: sys.exit("[feedback] verify 需要 --m")
            r = F.verify(root, a.id, a.m, a.after, a.method); v = r["verification"]
            print(f"[feedback] {r['id']} {a.m}：{v['method']}" + (f"，对比图 {v['pair']}" if v.get("pair") else "") + (f"（对比图没做成：{v['pair_error']}）" if v.get("pair_error") else "")); return 0
        if w == "pairs":
            if not a.m: sys.exit("[feedback] pairs 需要 --m")
            if a.todo:
                rs = F.unverified(root, a.m)            # empty when this version has no re-shot step (its condition; never named here)
                print(f"[feedback] {a.m}：{len(rs)} 条要在同一个画面复拍" + ("" if rs else "（都有了）"))
                for r in rs:
                    an = r.get("anchor") or {}; v = an.get("video") or {}
                    print(f"  {r['id']} 「{r['words'][:50]}」 改前：{F._before(r) or '（没有画面）'}" + (f"，录像 {v.get('m')} {v['t']:.1f}s" if v.get("t") is not None else "")
                          + (f"，章节 {an['chapter']['title']}" if an.get("chapter") else "") + (f"，{an['target']}" if an.get("target") else ""))
                return 0
            ps = F.pairs(root, a.m)
            for p in ps: print(f"  {p['id']} {p['method']}" + (f"  {p['pair']}" if p.get("pair") else ""))
            print(f"[feedback] {a.m}：{len(ps)} 条，{sum(1 for p in ps if p.get('pair'))} 对改前 / 改后"); return 0
        if w == "verdict":
            if a.ok == a.not_ok: sys.exit("[feedback] verdict 要 --ok 或 --not-ok")
            r = F.verdict(root, a.id, a.ok, a.event); print(f"[feedback] {r['id']}：{r['state']}"); return 0
        if w == "accept":
            if not a.m: sys.exit("[feedback] accept 需要 --m")
            F.accept(root, a.m, a.how); print(f"[feedback] 记下了：她接受了 {a.m}"); return 0
        if w == "card":
            c = F.card(root, a.card_kind, a.m, a.ids); text = yaml.safe_dump(c, allow_unicode=True, sort_keys=False, width=160)
            if a.out: a.out.write_text(text, encoding="utf-8"); print(f"[feedback] {a.out}：gameanything chat card --project P --file {a.out}")
            else: print(text, end="")
            return 0
        if w == "metrics":
            m = F.metrics(root); m.pop("repeats", None)
            if a.json: js(m); return 0
            rs, rl = m["rfr_strict"], m["rfr_loose"]
            f = lambda x: f"{x['k']}/{x['n']} = {x['rate']:.0%}" if x["n"] else "—"
            print(f"[feedback] {m['records']} 条记录，{m['complaints']} 条意见；重复意见率 严格 {f(rs)}，宽松 {f(rl)}"
                  f"（按每次交付，{m['by_delivery']['deliveries']} 次：严格 {f(m['by_delivery']['rfr_strict'])}，宽松 {f(m['by_delivery']['rfr_loose'])}）")
            print("  按类：" + "、".join(f"{k} {v}" for k, v in m["by_class"].items()) + "；按种类：" + "、".join(f"{k} {v}" for k, v in m["by_kind"].items()))
            for v in m["versions"]: print(f"  {v['m']}: {v['complaints']} 条意见，重复（严格 / 宽松）{v['repeats_strict']} / {v['repeats_loose']}")
            vv = m["verification"]; print(f"  修好 {vv['fixed']} 条，同一画面复拍 {vv['paired']} 条，她确认 {vv['her_ok']} 条；规则命中 {m['rule_hits']['hits']}/{m['rule_hits']['applicable']}")
            return 0
        if w == "backfill":
            r = F.backfill(root, dry_run=a.dry_run)
            if a.json or a.dry_run: js(r); return 0
            print(f"[feedback] backfill：新加 {r['added']} 条（{r['already_recorded']} 条早就有记录，没动；{r['skipped_not_feedback']} 句不是反馈，没记）；"
                  f"现在一共 {r['records']} 条记录，{r['complaints']} 条意见，{r['linked']} 条连上了 STATUS" + (f"；备份 {r['backup']}" if r.get("backup") else ""))
            print("  按类：" + "、".join(f"{k} {v}" for k, v in r["by_class"].items())); print("  按种类：" + "、".join(f"{k} {v}" for k, v in r["by_kind"].items()))
            f = lambda x: f"{x['k']}/{x['n']} = {x['rate']:.0%}" if x["n"] else "—"
            print(f"  重复意见率：严格 {f(r['rfr_strict'])}，宽松 {f(r['rfr_loose'])}；按每次交付（{r['by_delivery']['deliveries']} 次）："
                  f"严格 {f(r['by_delivery']['rfr_strict'])}，宽松 {f(r['by_delivery']['rfr_loose'])}"); return 0
        if w == "brief":
            r = F.brief(root, a.role, a.budget, a.m)
            print(f"[feedback] 开工前要知道的（{len(r['entries'])} 条）：" if r["lines"] else "[feedback] 没有要特别注意的")
            for x in r["lines"]: print("  " + x)
            return 0
        if w == "label":
            if a.human_sheet:
                from . import judge as J
                print(f"[feedback] {J.sample_sheet(root, a.out, a.seed)}（给人标注：填 class / kind / target，然后 --import … --labeller human --name 名字）"); return 0
            if a.export: print(f"[feedback] {F.label_export(root, a.out)}"); return 0
            if a.import_file: print(f"[feedback] 合并了 {F.label_import(root, a.import_file, a.labeller, a.name, a.apply)} 条标注"); return 0
            sys.exit("[feedback] label 要 --export 或 --import FILE")
        if w in ("judge", "agreement"):
            from . import judge as J
            try:
                if w == "agreement":
                    k = J.agreement([root], a.a, a.b, a.field); al = J.alpha([root], field=a.field)
                    if a.json: js({"kappa": k, "alpha": al}); return 0
                    f = lambda v: "—" if v is None else f"{v:.2f}"
                    print(f"[feedback] {a.a} vs {a.b}（{a.field}）：n={k['n']}，一致 {f(k['observed'])}，Cohen κ {f(k['kappa'])}；"
                          f"Krippendorff α（{', '.join(al['raters']) or '—'}，{al['units']} 条）{f(al['alpha'])}"); return 0
                if a.judge_card:
                    text = yaml.safe_dump(J.consent_card(root, a.frames), allow_unicode=True, sort_keys=False, width=160)
                    if a.out: a.out.write_text(text, encoding="utf-8"); print(f"[feedback] {a.out}：gameanything chat card --project P --file {a.out}")
                    else: print(text, end="")
                    return 0
                if a.emit:
                    r = J.emit(root, a.model, a.frames, a.ids)
                    print(f"[feedback] judge {r['run']}：{r['records']} 条记录、{r['pairs']} 对重复候选，{len(r['requests'])} 个请求在 {r['dir']}。"
                          f"每个请求在一个新的上下文里答（子 agent 或你自己，不看别的文件），写到请求里给的输出文件，然后 gameanything feedback judge --project P --collect")
                    for x in r["requests"]: print("  " + x)
                    return 0
                if a.collect:
                    r = J.collect(root, a.run)
                    print(f"[feedback] judge {r['run']}：存了 {r['stored']} 个标签（顺序 a {r['labelled']['a']} / b {r['labelled']['b']}，重复对 {r['pairs']}），"
                          f"已记进 privacy_ledger.yaml" + (f"；没答的：{r['missing']}" if any(r["missing"].values()) else "") + (f"；问题：{'；'.join(r['problems'][:5])}" if r["problems"] else ""))
                    return 0
                ok, cid, why = J.consent(root); print(f"[feedback] judge：{'她同意了（' + cid + '）' if ok else why}；跑过 {len(J.runs(root))} 次"); return 0
            except J.JudgeError as e: sys.exit(f"[feedback] {e}")
        if w in ("retro", "critic", "match"):
            from . import retro as R
            try:
                if w == "retro" and a.todo:
                    t = R.retro_todo(root, a.m); print(f"[feedback] 还没回顾的版本：{', '.join(t) or '没有'}"); return 0
                if not a.m: sys.exit(f"[feedback] {w} 需要 --m")
                if w == "match":
                    r = R.match(root, a.m)
                    if a.json: js(r); return 0
                    f = lambda v: "—" if v is None else f"{v:.2f}"
                    print(f"[feedback] {a.m}：{r['predictions']} 条预测，她的意见 {r['her_records']} 条；宽松 P {f(r['loose']['precision'])} R {f(r['loose']['recall'])}，"
                          f"严格 P {f(r['strict']['precision'])} R {f(r['strict']['recall'])}，Brier {f(r['loose']['brier'])}"); return 0
                if w == "retro" and a.emit:
                    r = R.retro_emit(root, a.m)
                    print(f"[feedback] {a.m} 的回顾请求：{r['request']}（{r['resolved']} 条修好的，{r['repeats']} 条她又说了一次的）。在一个新的上下文里答"
                          f"（子 agent 或你自己，只看这个文件），写到 {r['out']}，然后 gameanything feedback retro --project P --m {a.m} --collect"); return 0
                if w == "retro" and a.collect:
                    r = R.retro_collect(root, a.m, a.model)
                    for x in r["applied"]: print(f"  ✓ {x['scope']}/{x['kind']} {','.join(x['evidence'])} → {x['result']}")
                    for x in r["refused"]: print(f"  ✗ 第 {x['n']} 条：{x['refused']}")
                    print(f"[feedback] {a.m} 回顾：用了 {len(r['applied'])} 条，没用 {len(r['refused'])} 条" + (f"；这些她又说了一次的还没有提议：{', '.join(r['uncovered_repeats'])}" if r["uncovered_repeats"] else "")
                          + ("；她的偏好有新候选：告诉她「我的偏好」页上可以看、打开或删掉" if any(str(x.get("result", "")).startswith("profile:") and "candidate" in str(x.get("result")) for x in r["applied"]) else ""))
                    return 0
                if w == "critic" and a.emit:
                    r = R.critic_emit(root, a.m)
                    if r["skip"]: print(f"[feedback] {a.m}：这一版不用预评，直接交付（不用在消息里提）"); return 0
                    print(f"[feedback] {a.m} 的预评请求：{r['request']}（{r['frames']} 张画面）。在一个新的上下文里答（子 agent 最好；只看这个文件和里面列的画面），"
                          f"写到 {r['out']}，然后 gameanything feedback critic --project P --m {a.m} --collect"); return 0
                if w == "critic" and a.collect:
                    r = R.critic_collect(root, a.m, a.model)
                    print(f"[feedback] {a.m}：{len(r['predictions'])} 条预测，{len(r['high'])} 条 p ≥ {R.THETA}" + ("：交付前最后修一轮（只一轮），然后交付：" if r["high"] else "：直接交付"))
                    for p in r["high"]: print(f"  {p['kind']} {p.get('target') or ''} p={p['p']:.2f}：{p.get('text') or ''}")
                    return 0
                sys.exit(f"[feedback] {w} 要 --emit 或 --collect" + (" 或 --todo" if w == "retro" else ""))
            except R.RetroError as e: sys.exit(f"[feedback] {e}")
        if w == "datacheck":
            r = F.datacheck(root)
            if a.json: js(r); return 0
            print(F.datacheck_text(r)); return 0 if not r["missing"] else 1
        if w == "condition":
            if a.set_cond: print(f"[feedback] 条件：{F.condition(root, a.set_cond, a.m)}" + (f"（只给 {a.m}）" if a.m else "（这个项目以后没定条件的版本）")); return 0
            if a.m: print(f"[feedback] {a.m} 的条件：{F.condition(root, m=a.m)}"); return 0
            got = F.assignments(root)
            txt = ", ".join(f"{k} {v['name']}（{v.get('how')}）" for k, v in got.items()) or "还没有版本定了条件"
            print(f"[feedback] 条件（盲法，不给她看）：{txt}"); return 0
    except F.FeedbackError as e: sys.exit(f"[feedback] {e}")
    return 0


def profile_cmd(a):
    import json
    from . import profile as Pf, projects
    owner = a.owner or (Pf.owner_of(projects.resolve(a.project)) if a.project else "local")
    try:
        if a.what == "show":
            d = Pf.load(owner)
            if a.json: print(osdirs.json_text(d, indent=1, default=str)); return 0
            print(f"[profile] {Pf.path(owner)}：{len(d['entries'])} 条")
            for e in d["entries"]:
                print(f"  {e['id']} [{'开' if e.get('on') else '关'}·{e.get('status')}·{e.get('confidence')}] {e.get('text')}"
                      + (f"  （来自 {', '.join(x['project'] + ':' + x['record'] for x in e.get('from') or [])}）" if e.get("from") else ""))
            return 0
        if a.what == "add":
            e = Pf.add(owner, a.text, a.text_en, a.kind, a.modes, a.games, a.projects, a.sources, a.confidence, a.status, a.by)
            print(f"[profile] 加了 {e['id']}（{e['status']}，{'开' if e['on'] else '关：她在「我的偏好」页打开或者第二个项目里证实后才用'}）"); return 0
        if not a.id: sys.exit(f"[profile] {a.what} 需要 --id")
        if a.what == "set":
            e = Pf.update(owner, a.id, text=a.text, text_en=a.text_en, kind=a.kind, modes=a.modes, games=a.games, projects=a.projects, sources=a.sources,
                          confidence=a.confidence, status=a.status)
        elif a.what in ("on", "off"): e = Pf.toggle(owner, a.id, a.what == "on")
        else: e = Pf.remove(owner, a.id); print(f"[profile] 删了 {e['id']}"); return 0
        print(f"[profile] {e['id']}：{'开' if e.get('on') else '关'} · {e.get('text')}"); return 0
    except Pf.ProfileError as e: sys.exit(f"[profile] {e}")


def devstatus_cmd(a):
    import json
    from . import devstatus as S
    from . import projects
    root = projects.resolve(a.project)
    try:
        if a.what == "show":
            if a.json:
                d, P = S.load(root); print(osdirs.json_text({"exists": S.exists(root), **d, "problems": P, "counts": S.counts(d)}, indent=1, default=str)); return 0
            print(S.show_text(root)); return 0
        if a.what == "init":
            r = S.init(root, a.force)
            if not r["created"]: print(f"[status] {r['file']} 已经有了（--force 把新的条目并进去，已有的状态不动）"); return 0
            print(f"[status] {r['file']}：{r['added']} 条要求，{r.get('feedback', 0)} 条她还没处理的话"); print(S.show_text(root)); return 0
        if a.what == "set-item":
            r = S.set_item(root, a.id, a.state, a.text, a.build, a.by, a.evidence, a.text_en, a.source)
            x = r["item"]; print(f"[status] {x['id']} {x.get('state')}：{x.get('text')}")
            if r["note"]: print(f"[status] {r['note']}")
            return 0
        if a.what == "add-issue":
            r = S.add_issue(root, a.text, a.severity, a.since, a.plan, a.id, a.fixed)
            print(f"[status] 已知问题 {(r.get('issue') or r.get('removed'))['id']} " + ("关掉了" if "removed" in r else "记下了")); return 0
        if a.what == "add-regression":
            r = S.add_regression(root, a.what_text, a.broke_in, a.cause, a.fixed_in, a.item, a.id)
            g = r["regression"]; print(f"[status] 回归 {g['id']}：{g.get('what')}（{g.get('broke_in')} 坏的" + (f"，{g['fixed_in']} 修好）" if g.get("fixed_in") else "）")); return 0
        if a.what == "recheck":
            r = S.recheck(root, a.build, a.add, a.passed, a.failed, a.note, a.by or "playtester")
            print(f"[status] 复查（{r['build'] or '?'}）：还有 {len(r['todo'])} 条没复查" + (f"，{len(r['failed'])} 条没通过" if r["failed"] else ""))
            for x in r["todo"]: print(f"  · {x['id']} {x.get('text')}")
            for x in r["failed"]: print(f"  ✗ {x['id']} {x.get('text')}" + (f"：{x['note']}" if x.get("note") else ""))
            return 0
        if a.what == "feedback":
            if not a.event: sys.exit("[status] feedback 需要 --event")
            r = S.feedback(root, a.event, a.state, a.text, a.add_event); print(f"[status] {a.event}: {r['feedback'].get('state')}"); return 0
        if a.what == "decide":
            S.decide(root, a.text, a.event); print("[status] 决定记下了"); return 0
        if a.what == "card":
            import yaml
            if not a.m: sys.exit("[status] card 需要 --m")
            c = S.result_card(root, a.m, a.title, a.image)
            text = yaml.safe_dump(c, allow_unicode=True, sort_keys=False, width=160)
            if a.out: a.out.write_text(text, encoding="utf-8"); print(f"[status] {a.out}（发之前 gameanything build check --project {root} --m {a.m}）")
            else: print(text, end="")
            return 0
    except S.StatusError as e: sys.exit(f"[status] {e}")
    return 0


def game_cmd(a):
    import json
    from . import games as registry
    from .games import tools
    if a.gcmd == "list":
        if a.write_docs: tools.write_docs(); print(f"[game] {tools.DOCS} updated"); return 0
        if a.markdown: print(tools.markdown(builtin_only=False), end=""); return 0
        rs = tools.rows()
        if a.json: print(osdirs.json_text({"games": rs, "errors": registry.errors()}, indent=1)); return 0
        for r in rs:
            print(f"{r['id']:<16} {r['title']:<22} {r['loader']:<32} {r['adapter']:<22} lab {r['lab']:<3}  {r['source']}")
        for e in registry.errors(): print(f"[game] skipped {e['source']}: {e['error']}", file=sys.stderr)
        return 0
    if a.gcmd == "new":
        try: r = tools.new(a.id, a.title, a.loader, a.engine, a.steam_appid, a.plugin)
        except ValueError as e: sys.exit(f"[game] {e}")
        print(f"[game] {r['package']}"); print("\n".join("  " + f for f in r["files"]))
        print("[game] next: fill every TODO in game.yaml, write the smoke mod and adapter.py, then  gameanything game check " + a.id
              + ("  (after pip install -e of the plugin)" if a.plugin else "") + "  (skills/gameanything/references/add-a-game.md)")
        return 0
    if not a.id and not a.path: sys.exit("[game] check needs an id or --path")
    r = tools.check_folder(a.path) if a.path else tools.check(a.id, build=a.build)
    if a.json: print(osdirs.json_text(r, indent=1)); return 0 if r["ok"] else 1
    mark = {"error": "ERROR", "warning": "warn ", "ok": "ok   ", "info": "     "}
    print(f"[game] {r['game']} ({r.get('source', '?')}, {r.get('path', '')})")
    for i in r["items"]: print(f"  {mark[i['level']]} {i['text']}")
    print("[game] " + ("ok" if r["ok"] else "has errors: fix the ERROR lines"))
    return 0 if r["ok"] else 1


def minecraft_cmd(a):
    """`native minecraft login | status | logout | download`: the sandbox's ga-mc account + download (msauth, mcdownload) for her own
    computer: the token stays in <data>/native/minecraft-account (private file, never printed); the files go to this system's .minecraft."""
    import json
    from .native import games, mcdownload, msauth
    g = games.get("minecraft"); acct = g.root / "minecraft-account"; acct.mkdir(parents=True, exist_ok=True)
    if a.what == "logout": msauth.logout(acct); print("[native] signed out of Minecraft (the saved token is deleted)"); return 0
    if a.what == "status":
        if a.recheck:
            try: msauth.recheck(acct)
            except msauth.AuthError as e: print(f"[native] recheck failed: {e}", file=sys.stderr)
        s = {**msauth.status(acct), "minecraft_dir": str(g.user_dir()), "installed": g.installed(), "fabric": g.loader()["ok"]}
        print(osdirs.json_text(s, indent=1) if a.json else
              f"[native] signed in: {'yes' if s['signed_in'] else 'no'}, owns Minecraft: Java Edition: {'yes' if s['owns_java'] else 'no'}\n"
              f"[native] {s['minecraft_dir']}: {'installed' if s['installed'] else 'not there yet'}, Fabric {'ok' if s['fabric'] else 'missing'}")
        return 0
    if a.what == "login":
        try:
            dc = msauth.device_code()
            print(f"[native] 在你自己的手机或电脑上打开 {dc.get('verification_uri') or 'https://www.microsoft.com/link'}，输入代码 {dc['user_code']}，"
                  f"登录你的微软账号（{int(dc.get('expires_in') or 900) // 60} 分钟内有效）\n"
                  f"[native] on your own phone or computer open {dc.get('verification_uri') or 'https://www.microsoft.com/link'} and enter "
                  f"{dc['user_code']} (no password is typed here)", flush=True)
            r = msauth.check_and_save(acct, msauth.poll(dc))
        except msauth.AuthError as e: sys.exit(f"[native] Minecraft sign-in: {e}")
        if a.json: print(osdirs.json_text(r)); return 0 if r["owns_java"] else 1
        if not r["owns_java"]: print("[native] signed in, but this account does not own Minecraft: Java Edition (Bedrock alone is not enough)"); return 1
        print("[native] signed in: the account owns Minecraft: Java Edition. Next: gameanything native minecraft download"); return 0
    if not msauth.status(acct)["owns_java"]:
        sys.exit("[native] sign in first and own Minecraft: Java Edition: gameanything native minecraft login")
    kw = {k: v for k, v in (("version", a.version), ("fabric", a.fabric), ("fabric_api", a.fabric_api)) if v}
    try: r = mcdownload.download(g.user_dir(), os_name=g.sys, log=lambda m: print(f"[native] {m}", flush=True), **kw)
    except (mcdownload.DownloadError, OSError) as e: sys.exit(f"[native] download failed: {e} (run it again: files already there are kept)")
    print(json.dumps(r, indent=1) if a.json else
          f"[native] Minecraft {r['version']} + {r['fabric_profile']} in {g.user_dir()}: {r['fetched']} files fetched "
          f"({r['bytes'] / 1e6:.0f} MB), {r['kept']} kept, {r['seconds']:.0f} s; Java: {r['java']}")
    return 0


def native_cmd(a):
    import json
    from . import native
    try:
        if a.ncmd == "doctor":
            from . import projects
            d = native.doctor(a.game, projects.resolve(a.project) if a.project else None)
            if a.copy:
                from .native import macapp
                opt = [g["launch_option"] for g in d["games"] if g.get("launch_option")]
                if not a.game or len(opt) != 1:
                    sys.exit("[native] --copy needs --game <a game with a Steam launch option>" + (f": {a.game} has none here" if a.game else ""))
                if d["system"] != "mac": sys.exit("[native] --copy works on macOS (pbcopy); the launch option is:\n" + opt[0])
                if not macapp.copy(opt[0]): sys.exit("[native] pbcopy failed; the launch option is:\n" + opt[0])
                print(f"[native] copied to the clipboard: {opt[0]}\n[native] Steam > {d['games'][0]['title']} > Properties > Launch Options: click the box, Cmd-V (do not type it)", file=sys.stderr)
            if a.json: print(osdirs.json_text(d, indent=1)); return 0
            t = d["tools"]; dn, jv = t["dotnet"], t["java"]; lb = d["lab"]
            src = (" (chosen by the project)" if d["mode_source"] == "project" else " (the project has not chosen: the automatic rule)") if a.project else ""
            print(f"[native] system {d['system']}, mode {d['mode']}{src}: {d['mode_why']}\n"
                  + (f"[native] lab: backend {lb['backend'] or 'none'}, gamebench {lb['gamebench'] or 'not found'}{' (launch scripts ok)' if lb['kit'] else ''}, pool {lb['pool'] or 'none'}\n"
                     if d["system"] == "linux" else "") +                      # the maintainers' lab exists only on Linux
                  f"[native] data: {d['data']}\n"
                  f"[native] ffmpeg {'ok' if t['ffmpeg'] and t['ffprobe'] else 'MISSING (ingest of videos needs it)'}, "
                  f"dotnet {', '.join(dn['sdks']) or 'none'}, java {jv['version'] or 'none'}")
            if d.get("windows_package"):
                print(f"[native] WARNING: this runs inside the packaged app {d['windows_package']}: Windows redirects new folders under AppData "
                      f"to %LOCALAPPDATA%\\Packages\\{d['windows_package']}\\LocalCache, where a game started from Steam does not look "
                      "(Cities: Skylines mods, a downloaded .minecraft, GameAnything's own backups). Run gameanything from a normal terminal "
                      "(Windows Terminal / PowerShell) for install, backup and launch.", file=sys.stderr)
            for g in d["games"]:
                if not g["installed"]:
                    print(f"\n{g['title']}: not found (installed somewhere else? set {g['pin_var']}=<its folder>)"
                          + ("\n  or without the Launcher: gameanything native minecraft login (sign in on your phone), then "
                             "gameanything native minecraft download" if g.get("game") == "minecraft" else "")); continue
                lo, tc = g["loader"], g["toolchain"]
                print(f"\n{g['title']}: {g['game_dir'] or g['user_dir']}\n  mods   {g['mods_dir']}\n  saves  {g['saves_dir']}\n  log    {g['log'] or '(none yet)'}\n"
                      f"  loader {lo['name']}: {'ok' if lo['ok'] else 'MISSING'} ({lo['detail']})\n"
                      f"  build  {tc['name']}: {'ok' if tc['ok'] else 'MISSING'} ({tc['detail']})" + (f"\n         get it: {tc['setup']}" if tc["setup"] and not tc["ok"] else "")
                      + f"\n  running: {'yes' if g['running'] else 'no' if g['running'] is False else 'unknown'}"
                      + (f"\n  start  {g['launch_hint']}" if g.get("launch_hint") else "")
                      + (f"\n  option {g['launch_option']}" if g.get("launch_option") else "")
                      + "".join(f"\n  extra  {x['name']}: {x['detail']}" for x in g.get("extras") or []))
            return 0
        if a.ncmd == "minecraft": return minecraft_cmd(a)
        if a.ncmd in ("launch", "close", "reload", "check", "launches", "shot", "drive"): return quiet_cmd(a)
        if a.ncmd == "idle":
            from .native import idle
            p = idle.probe(); print("unknown" if p["seconds"] is None else f"{p['seconds']:.0f}"); print(f"[native] {p['source']}", file=sys.stderr); return 0
        if a.ncmd == "ready": return ready_cmd(a)
        if a.ncmd == "permissions":
            import json
            from .native import hands
            r = hands.permissions()
            if a.open and r["system"] == "mac": hands.open_panes()
            if a.json: print(osdirs.json_text(r, indent=1)); return 0 if r["ok"] else 1
            _print_items(r["items"], _native_lang(a))
            return 0 if r["ok"] else 1
        g = native.get(a.game)
        if a.ncmd == "backup":
            m = g.backup("manual"); n = sum(i["files"] for i in m["items"]); b = sum(i["bytes"] for i in m["items"])
            print(f"[native] backup {m['stamp']}: {n} files, {b / 2 ** 20:.1f} MB -> {g._bdir() / m['stamp']}"); return 0
        if a.ncmd == "backups":
            for m in g.backups(): print(f"{m['stamp']}  {m['at']}  {sum(i['bytes'] for i in m['items']) / 2 ** 20:8.1f} MB  {m['reason']}")
            return 0
        if a.ncmd == "restore": r = g.restore(a.stamp); print(f"[native] restored {r['restored']}; the previous files are in {', '.join(r['moved_to_trash']) or '-'}"); return 0
        if a.ncmd == "build":
            b = g.build(a.src, a.name)
            print(f"[native] content pack for {b['content_pack']}: nothing to compile" if b.get("content_pack") else f"[native] built {b.get('dll') or b['staged']}")
            print(f"[native] mod folder: {b['staged']}")
            for wl in b.get("warnings") or []: print(f"[native] WARNING {wl}")
            if not a.install: return 0
            a.src, a.name = Path(b["staged"]), None
        if a.ncmd in ("build", "install"):
            r = g.install(a.src, a.name)
            print(f"[native] installed {r['name']} -> {r['path']}" + (f"\n[native] saves backed up first: {r['backup']}" if r["backup"] else "")
                  + (f"\n[native] the previous {r['name']} is in {r['replaced_to_trash']}" if r["replaced_to_trash"] else "")
                  + (f"\n[native] mod switch: {r['switch']}" if r.get("switch") else "")
                  + ("\n[native] next: the game scans the new mod at its next start (Civ VI switches it on itself); install again after that start to confirm" if r.get("pending") else "")
                  + (f"\n[native] Options.ini: {r['options']}; Resource.cfg: {r['resource_cfg']}" if r.get("options") else "")); return 0
        if a.ncmd == "uninstall": r = g.uninstall(a.name); print(f"[native] {r['name']} moved to {r['moved_to_trash'] or '(it was already gone)'}"); return 0
        if a.ncmd == "mods":
            for n, e in g.mods().items(): print(f"{n}  {e['at']}  {e['path']}")
            return 0
        f = g.log()
        if not f: sys.exit(f"[native] no log yet for {g.title} (it appears after the game ran once)")
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if a.grep: lines = [l for l in lines if a.grep in l]
        print(f"[native] {f}"); print("\n".join(lines[-a.lines:]))
    except (native.NativeError, OSError) as e:
        sys.exit(f"[native] {e}")
    return 0


def _native_lang(a, root=None) -> str:
    """--lang, else the project's lang, else en (like lab login)."""
    if getattr(a, "lang", None): return a.lang
    if root is not None:
        from . import projects
        try: l = (projects.config_of(root) or {}).get("lang")
        except Exception: l = None
        if l in ("zh", "en"): return l
    return "en"


def _print_items(items, lang):
    from .native import hands
    for it in items:
        how = hands.text(it, "how", lang)
        print(f"[native] {'ok ' if it['ok'] else '?? ' if it['ok'] is None else 'NO '} {hands.text(it, 'name', lang)}: {hands.text(it, 'why', lang)}"
              + (f"\n       how: {how}" if how and it["ok"] is not True else ""))


def extras_cmd(a):
    """Optional features (extras.py). Exit 0 installed / done, 2 pending (her answer), 3 refused / failed."""
    import json
    import shlex
    from . import extras
    if a.what == "status":
        st = extras.status()
        if a.json: print(json.dumps(st, indent=1)); return 0
        for n, f in extras.FEATURES.items():
            ok = st[n]["installed"]
            print(f"[extras] {'ok ' if ok else 'NO '} {n}: {f['title_en']}" + (f" ({st[n]['version']})" if ok and st[n]["version"] else "")
                  + ("" if ok else f"\n       without it: {f['without_en']}\n       size: {f['size_en']}\n       install yourself: {shlex.join(extras.command(n))}"))
        return 0
    if not a.name: sys.exit("gameanything extras install: which one? transcribe | detect")
    if not a.project: sys.exit("gameanything extras install needs --project (the card goes to that project's chat); at your own terminal: gameanything extras status shows the command")
    from . import projects
    d = extras.install(projects.resolve(a.project), a.name, post=not a.no_post, ask_again=a.ask_again)
    if a.json: print(json.dumps(d, indent=1, ensure_ascii=False))
    else:
        print(f"[extras] {d['state']}: {d['why']}")
        if d.get("log") and d["state"] == "failed": print(d["log"])
    return {"installed": 0, "done": 0, "pending": 2}.get(d["state"], 3)


def ready_cmd(a):
    """能不能操作屏幕 (native/ready.py). Exit 0 full, 1 look only, 3 none."""
    import json
    from . import native, projects
    from .native import ready
    root = projects.resolve(a.project) if a.project else None
    if root is not None:
        try: title = native.get(projects.game_of(root)).title
        except Exception: title = "游戏"
        r = ready.run(root, a.role, a.if_needed, card_file=a.card_file, game_title=title)
    else: r = ready.check(None, a.role or ready.default_role())
    if a.json: print(osdirs.json_text(r, indent=1)); return ready.EXIT[r["level"]]
    c = r["caller"]; lang = _native_lang(a, root); en = lang == "en"
    print(f"[native] {(ready.LEVEL_EN if en else ready.LEVEL_TEXT)[r['level']]} ({r['level']})  system {r['system']}"
          + (f"  agent {c['framework']}" if c["framework"] else "") + (f"  app {ready.app_text(r['app'] or c['app'], lang)}" if r.get("app") or c["app"] else "")
          + (f"  sandbox {c['sandbox']}" if c["sandbox"] else "") + ("  (recorded " + r["at"] + ")" if r.get("cached") else ""))
    _print_items(r["items"], lang)
    if a.project:
        print(f"[native] next: {r['next']} - {r.get('why_en', r['why']) if en else r['why']}")
        if r.get("card_file"):
            print(f"[native] card: gameanything chat card --project \"$P\" --file {r['card_file']} --text \"{'…one sentence…' if en else '…一句话说明…'}\"")
    return ready.EXIT[r["level"]]


def quiet_cmd(a):
    """本机模式少打扰: launch (only with her yes) / close (only what GameAnything opened) / reload / check / launches. Exit codes: 0 done or go,
    2 pending (waiting for her answer or her time window), 3 refused / not possible here."""
    import json
    from . import native, projects
    from .native import checks, hands, quiet
    root = projects.resolve(a.project)
    g = native.get(a.game or projects.game_of(root))
    try:
        if a.ncmd == "launch":
            if a.yes: print("[native] --yes no longer opens the game: her yes must be on the card in the chat (this command posts it)", file=sys.stderr)
            from .native import ready
            try: st = ready.state(root, ready.default_role())
            except Exception: st = {"fresh": True}
            if not st["fresh"]:                                       # 能不能操作屏幕 (2026-11-01): checked before the first launch and after an agent / model change
                print(f"[native] NOTE 能不能操作屏幕还没查（{st.get('why')}）：先跑 gameanything native ready --project \"$P\" --if-needed", file=sys.stderr)
            kw = dict(reason=a.reason, reason_en=a.reason_en, minutes=a.minutes, post=not (a.no_post or a.dry_run), ask_again=a.ask_again)
            d = quiet.wait_decision(root, g, a.wait, **kw) if a.wait else quiet.decide(root, g, **kw)
            print(f"[native] {d['state']}: {d['why']}" + (f" (until {d['until']})" if d.get("until") else ""))
            if d["state"] == "open": return 0
            if d["state"] != "go": return 2 if d["state"] == "pending" else 3
            if a.dry_run: print("[native] dry run: nothing opened"); return 0
            r = quiet.launch(root, g, settle=a.settle, round_=a.round, keep_window=a.keep_window, decision=d)
            if r.get("manual"): print(f"[native] {r['why']}"); return 3
            w = r.get("window") or {}
            print(f"[native] opened {r['url']}" + (f" (game process {', '.join(map(str, r['pids']))})" if r.get("pids") else " (its process did not show up yet; `close` finds it later)")
                  + (f"\n[native] small window for this test: {', '.join(w['changed'])} (put back by `gameanything native close`)" if w.get("changed") else "")
                  + (f"\n[native] window: {w['how']}" if w.get("how") else "")
                  + "".join(f"\n[native] {k}: {v}" for k, v in (r.get("after") or {}).items()))
            if g.launch_hint(): print(f"[native] {g.launch_hint()}")
            return 0
        if a.ncmd == "close":
            r = quiet.close(root, g); w = r.get("window") or {}
            print(f"[native] {r['why']}" + (f"; window settings put back: {', '.join(w.get('restored') or []) or '-'}" if w else "")
                  + (f" (asked with: {r['how']})" if r.get("how") and not r["closed"] else "")); return 0 if r["closed"] else 3
        if a.ncmd == "launches":
            p = quiet.policy(root); ls = quiet.launches(root, a.round)
            print(f"[native] native_launch={p['mode']}" + ("" if p["chosen"] else " (default)") + f"  window={p['window']}")
            for x in ls: print(f"  {x['at']}  {x['game']:<16} {x.get('round') or '-':<10} {x['code']:<7} {x['state']}"
                               + (f"  after: {json.dumps(x['after'], ensure_ascii=False)}" if x.get("after") else ""))
            rounds = {}
            for x in ls: rounds[x.get("round") or "-"] = rounds.get(x.get("round") or "-", 0) + 1
            print("[native] launches per round: " + (", ".join(f"{k}: {v}" for k, v in rounds.items()) or "none")); return 0
        if a.ncmd in ("shot", "drive"):
            try:
                if a.ncmd == "shot":
                    r = hands.shot(root, g, a.out)
                    print(r["path"]); print(f"[native] {r['backend']}: window {r['window']['id']} \"{r['window'].get('title') or ''}\" {r['window']['w']}x{r['window']['h']}")
                    if r.get("warning"): print(f"[native] WARNING {r['warning']}")
                    if r.get("note"): print(f"[native] {r['note']}")
                    return 0
                r = hands.drive(root, g, a.steps, click=a.click)
                print(f"[native] sent {r['done']} step(s) to {r['window'].get('title') or r['window']['id']} ({r['backend']}"
                      + (f", clicks: {r['click_method']}" if r.get("click_method") else "") + f"; {r['why']})"); return 0
            except hands.Refused as e:
                print(f"[native] {'paused' if e.pending else 'refused'} ({e.code}): {e.why}"); return 2 if e.pending else 3
        if a.ncmd == "reload":
            try: r = checks.reload(g, a.src, a.name, a.setup)
            except checks.NoReload as e: print(f"[native] no hot reload: {e}"); return 3
            for c in r["copied"]: print(f"[native] copied {c}")
            for wl in r["warnings"]: print(f"[native] WARNING {wl}")
            if r.get("setup"): print(f"[native] {r['setup']}")
            print(f"[native] {r['how']}"); return 0
        r = checks.check(g, a.src, a.server, a.gametest, a.timeout)
        if a.json: print(osdirs.json_text(r, indent=1)); return 0 if r["ok"] else 1
        for it in r["mods"]:
            print(f"[native] {it['mod']}: {'ok' if not it['errors'] else str(len(it['errors'])) + ' error(s)'}  {it['path']}")
            for k, tag in (("errors", "ERROR"), ("warnings", "WARNING"), ("notes", "note")):
                for l in it[k]: print(f"  {tag} {l}")
        return 0 if r["ok"] else 1
    except (native.NativeError, OSError, ValueError) as e:
        sys.exit(f"[native] {e}")


def backup_cmd(a):
    from . import backup, projects
    try:
        if a.bcmd == "token":
            if a.what == "status": print(f"[backup] token: {backup.token_source() or 'none'}"); return 0
            import getpass
            print(f"[backup] stored in the {backup.set_token(getpass.getpass('Hugging Face token (hidden): '))}"); return 0
        root = projects.resolve(a.project)
        if a.bcmd == "enable":
            if not (sys.stdin.isatty() and sys.stdout.isatty()): sys.exit("[backup] enable needs a person at a terminal (or use the consent dialog in the browser UI); there is no --yes")
            tgt = {"kind": "folder", "path": str(a.folder)} if a.folder else {"kind": "hf", "repo": a.hf}
            cfg = {**backup.load_cfg(root), "target": tgt, "include_raw": a.include_raw, "raw_paths": [str(r) for r in a.raw] if a.include_raw else []}
            backup.check_target(root, cfg); p = backup.plan(root, cfg); where = backup.target_text(tgt)
            print(f"This will copy {p['files']} files ({p['bytes'] / 2 ** 20:.1f} MB) of '{root.name}' to {where}"
                  + ("  [leaves this computer; the dataset must be private]" if a.hf else "") + f", every {a.every_minutes} min when something changed:")
            for f in p["folders"]: print(f"  {(f['name'] if f['name'] != '.' else '(root)'):<28} {f['files']:>6} files  {f['bytes'] / 2 ** 20:>9.1f} MB")
            print("Never copied: the game itself (*.xnb, Content (unpacked), decompiled sources), caches. Nothing on the target is ever deleted.")
            if input(f"Type the target ({tgt.get('path') or tgt['repo']}) to turn the backup on: ").strip() != (tgt.get("path") or tgt["repo"]):
                sys.exit("[backup] not turned on")
            backup.enable(root, tgt, a.include_raw, a.raw, a.every_minutes, via="cli"); print("[backup] on; first run: gameanything backup run --project ..."); return 0
        if a.bcmd == "disable": backup.disable(root); print("[backup] off"); return 0
        if a.bcmd == "run":
            r = backup.run(root); print(f"[backup] {'ok' if r['ok'] else 'FAILED: ' + str(r['error'])}: {r['files']} files, {r['bytes'] / 2 ** 20:.1f} MB copied, {r['removed']} removed here (kept there)")
            return 0 if r["ok"] else 1
        s = backup.status(root); c = backup.changes(root, backup.load_cfg(root)) if s["configured"] else ([], [])
        print(f"[backup] {'on' if s['enabled'] else 'off'}  target: {s['target'] or '-'}  every {s['every_minutes']} min  raw: {'yes' if s['include_raw'] else 'no'}\n"
              f"[backup] last: {s['last'] or '-'}\n[backup] holds {s['held']} files; {len(c[0])} new / changed, {len(c[1])} removed since; token: {backup.token_source() or 'none'}")
    except (backup.BackupError, KeyError, ValueError, OSError) as e:
        sys.exit(f"[backup] {e.args[0] if isinstance(e, KeyError) else e}")
    return 0


def _gen_options(a) -> dict:
    """--option K=V (V read as yaml: true, 3000, [0, 0.1, 1, 0.9])."""
    import yaml
    from . import gen
    opts = {}
    for kv in a.option:
        k, eq, v = kv.partition("=")
        if not eq or not k.strip(): raise gen.GenSpecError(f"--option {kv!r} 应该是 K=V")
        opts[k.strip()] = yaml.safe_load(v)
    return opts


def _gen_spec(a, root):
    from . import gen
    spec = gen.load_inputs(root, a.inputs) if a.inputs else {}
    if a.prompt or a.image:
        if spec.get("jobs"): raise gen.GenSpecError("--inputs 和 --prompt / --image 只用一种")
        spec["jobs"] = [{"name": a.name or "asset", "prompt": a.prompt, "images": a.image, **({"n": a.n} if a.n else {})}]
    opts = dict(spec.get("options") or {})
    opts.update(_gen_options(a))
    if opts: spec["options"] = opts
    for f in ("model", "out"):
        if getattr(a, f): spec[f] = getattr(a, f)
    if a.redo: spec["redo"] = True
    return spec


def gen_key_cmd(a):
    import getpass
    from . import keys, users
    if os.environ.get("GAMEANYTHING_GEN_OFF"): sys.exit("[gen] 在 agent 运行里不能读写 key / keys cannot be read or written inside an agent run")
    act, name = (a.rest + ["", ""])[:2]
    if act not in ("set", "status", "remove"): sys.exit("[gen] 用法: gameanything gen key set|status|remove NAME")
    names = [name] if name else list(users.GEN_KEYS)
    if name and name not in users.GEN_KEYS: sys.exit(f"[gen] 不认识 {name}（{', '.join(users.GEN_KEYS)}）")
    if act == "status":
        for n in names: print(f"{n:20} {keys.source(n) or 'no'}")
        return 0
    if not name: sys.exit("[gen] 需要 key 的名字，例如 gameanything gen key set FAL_KEY")
    if act == "remove": print(f"[gen] {name}: {'removed from the keyring' if keys.keyring_clear(name) else 'nothing removed (no keyring entry)'}"); return 0
    v = (a.from_file.read_text(encoding="utf-8") if a.from_file else getpass.getpass(f"{name} (hidden): ")).strip()
    if not v: sys.exit("[gen] 空的，没有保存")
    if not keys.keyring_set(name, v):
        sys.exit("[gen] 这台电脑没有可用的系统钥匙串（Linux 需要 secret-tool，macOS 用 Keychain）：请把 key 写进 keys 文件（gameanything project settings --keys-file <路径>，"
                 f"一行 {name}=...，文件权限只给自己）")
    print(f"[gen] {name}: stored in the system keyring (never printed)"); return 0


def gen_cmd(a):
    import json
    from . import gen, genrun, projects
    if a.what == "key": return gen_key_cmd(a)
    if a.what == "list":
        env = None
        if a.project:
            env, blk = genrun.env_for(projects.resolve(a.project))
            if blk: sys.exit(f"[gen] {blk}")
        rows = gen.listing(env)
        if a.json: print(osdirs.json_text(rows, indent=1)); return 0
        for r in rows: print(f"{r['tool']:22} {'ready' if r['ready'] else '-    '}  {r['key']:28} {r['model']:42} {r['price']:22} sends {r['sends']}")
        return 0
    if a.what == "estimate":
        try:
            if a.inputs or a.prompt or a.image:
                if not a.project: sys.exit("[gen] --inputs / --prompt 需要 --project")
                root = projects.resolve(a.project); spec = gen.normalize(root, a.tool, _gen_spec(a, root))
                e = gen.estimate(spec["tool"], model=spec["model"], jobs=spec["jobs"])
            else:
                e = gen.estimate(a.tool, n=a.n or 1, model=a.model, options=_gen_options(a))
        except gen.GenSpecError as x: sys.exit(f"[gen] {x}")
        if a.json: print(osdirs.json_text(e, indent=1)); return 0
        lo, hi = e["estimate"]["cost_usd"]
        print(f"[gen] {e['tool']} {e['model']}: {e['outputs']} outputs, about ${lo:g}-{hi:g}, {e['estimate']['wall_h'][0]:g}-{e['estimate']['wall_h'][1]:g} h; "
              f"sends {e['sends']} to {e['to']}; price {'verified' if e['price']['verified'] else 'NOT verified'} ({e['price']['source']})")
        print("[gen] go card: \"estimate\": " + json.dumps(e["estimate"], ensure_ascii=False) + f", \"cost_usd\": {hi:g}")
        return 0
    if not a.project: sys.exit("[gen] 需要 --project")
    root = projects.resolve(a.project)
    if a.what == "status": print("\n".join(genrun.status_lines(root))); return 0
    try:
        spec = _gen_spec(a, root) if gen.is_adapter_tool(a.tool) else None
        f = genrun.request(root, a.tool, a.permission, a.go, a.arg, spec=spec)
    except (ValueError, OSError) as e: sys.exit(f"[gen] {e}")
    print(f"[gen] 已排队，后台核对两张卡后会开始，完成后会通知你：{f.name}"); return 0


def agentd_cmd(a):
    import json
    from . import agentd, projects
    if a.what == "status": print("\n".join(agentd.status_lines())); return 0
    if a.what in ("request", "notify"):
        if not a.project or not a.text: sys.exit(f"[agentd] {a.what} 需要 --project 和 --text")
        root = projects.resolve(a.project)
        try:
            if a.what == "notify": print(f"[agentd] 留言给这个项目的 agent：{agentd.notify(root, a.text, sender=a.sender)}"); return 0
            det = a.details
            if det and det.startswith("@"): det = Path(det[1:]).read_text(encoding="utf-8")
            f = agentd.write_request(root, a.kind or "", a.text, json.loads(det) if det else None)
        except (ValueError, OSError) as e: sys.exit(f"[agentd] {e}")
        print(f"[agentd] 请求已交给{'后台（付费生成队列）' if a.kind == 'gen_request_ready' else '协调者'}：{f}"); return 0
    if a.requests_dir: os.environ["GAMEANYTHING_PARENT_REQUESTS"] = str(a.requests_dir)
    quiet = not sys.stdout.isatty()                     # started in the background: the log file has every line, stdout only a crash
    if a.claude and a.provider != "claude-code": sys.exit("[agentd] --claude 只能和 --provider claude-code 一起用；请用 --agent-bin")
    if a.budget_usd is not None and a.provider != "claude-code": sys.exit(f"[agentd] {a.provider} 没有单次美元上限参数；请去掉 --budget-usd")
    return agentd.Agentd(a.claude, a.model, a.log_root, a.requests_dir, budget=a.budget_usd, quiet=quiet,
                         provider=a.provider, agent=a.agent_bin, builds=a.builds).serve(a.pid_file, a.once)


def _password(a, confirm=True) -> str:
    import getpass
    if a.password_file:
        try: return a.password_file.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError): sys.exit("[hub] cannot read the first line of --password-file")
    if not sys.stdin.isatty(): sys.exit("[hub] no terminal to ask for the password: use --password-file")
    pw = getpass.getpass("Password (hidden): ")
    if confirm and getpass.getpass("Again: ") != pw: sys.exit("[hub] the two passwords differ")
    return pw


def hub_cmd(a):
    from . import users
    try:
        if a.hcmd is None:
            from .ui.hub import serve
            serve(a.port, a.host, a.content, int(a.upload_max_gb * 2 ** 30)); return 0
        if a.hcmd == "migrate":
            if not users.get_user(a.owner): print(f"[hub] note: {a.owner} is not a hub user yet (gameanything hub user add {a.owner} --admin ...)")
            for pid, path, what in users.migrate(a.owner, a.dry_run): print(f"{pid:<24} {what:<28} {path}")
            return 0
        c = a.ucmd
        if c == "add":
            u = users.add_user(a.name, _password(a), a.admin, a.display, a.data_root, a.claude_config_dir, a.env_file, a.codex_home, a.agent)
            print(f"[hub] added {a.name}{' (admin)' if a.admin else ''}: projects in {u['data_root']}, Claude login in {u['claude_config_dir']}")
            if not users.claude_login(u): print(f"[hub] next: {a.name} logs in to the hub and pastes a token under 「我的 Claude」 (or on the server: gameanything hub user login {a.name});"
                                               f" until then agentd does not run {a.name}'s projects")
        elif c == "passwd":
            if not users.get_user(a.name): sys.exit(f"[hub] no user {a.name}")
            users.set_password(a.name, _password(a)); print(f"[hub] new password for {a.name} (old sessions ended)")
        elif c == "list":
            us = users.load_users()
            for n, u in us.items():
                st = users.agent_status({**u, "name": n})
                print(f"{n:<16} {(u.get('display') or n):<16} {'admin' if u.get('admin') else '-':<6} {st['agent'].replace('claude-code', 'claude')} {'yes' if st['connected'] else 'NO ':<4}"
                      f" data {u.get('data_root')}  config {u.get('claude_config_dir')}" + (f"  env {u['env_file']}" if u.get("env_file") else ""))
            if not us: print(f"(no users yet: gameanything hub user add <name> --admin; file {users.users_file()})")
        elif c == "remove":
            if not a.yes:
                if not sys.stdin.isatty(): sys.exit("[hub] remove asks first: run it in a terminal, or add --yes")
                if input(f"Remove hub user {a.name}? Their projects and files stay. Type the name to confirm: ").strip() != a.name: sys.exit("[hub] cancelled")
            users.remove_user(a.name); print(f"[hub] removed {a.name}")
        elif c == "agent":
            st = users.set_agent(a.name, a.agent); print(f"[hub] {a.name}'s projects now run on {st['agent']}" + ("" if st["connected"] else " (not logged in yet)"))
        elif c == "model":
            st = users.set_model(a.name, a.agent, a.model); print(f"[hub] {a.name}'s {a.agent} model: {st[a.agent].get('model') or '(default)'}")
        elif c == "login" and a.agent in ("opencode", "gemini"):
            from . import agent_providers
            u = users.get_user(a.name)
            if not u: sys.exit(f"[hub] no user {a.name}")
            env = {k: v for k, v in os.environ.items() if not users.CRED_RE.match(k)}
            exe = agent_providers.provider(a.agent, binary=a.claude).binary
            if a.agent == "opencode":
                d = users.opencode_home(u)
                for s in ("config", "data", "state"): (d / s).mkdir(parents=True, exist_ok=True); env[f"XDG_{s.upper()}_HOME"] = str(d / s)
                print(f"[hub] starting `opencode auth login` with its config / data in {d}: pick the provider, paste {a.name}'s own key")
                os.execvpe(exe, [exe, "auth", "login"], env)
            d = users.gemini_home(u); d.mkdir(parents=True, exist_ok=True); env["GEMINI_CLI_HOME"] = str(d)
            print(f"[hub] starting gemini with GEMINI_CLI_HOME={d}: choose 'Login with Google', sign in with {a.name}'s own account, then /quit")
            os.execvpe(exe, [exe], env)
        elif c == "login" and a.agent == "codex":
            from . import agent_providers
            u = users.get_user(a.name)
            if not u: sys.exit(f"[hub] no user {a.name}")
            d = users.codex_home(u); d.mkdir(parents=True, exist_ok=True)
            codex = agent_providers.provider("codex", binary=a.claude).binary
            env = {k: v for k, v in os.environ.items() if not users.CRED_RE.match(k)}; env["CODEX_HOME"] = str(d)
            print(f"[hub] starting `codex login --device-auth` with CODEX_HOME={d}: open the link, sign in with {a.name}'s own ChatGPT account")
            os.execvpe(codex, [codex, "login", "--device-auth"], env)
        elif c == "login":
            import shutil
            u = users.get_user(a.name)
            if not u: sys.exit(f"[hub] no user {a.name}")
            d = Path(u["claude_config_dir"]).expanduser(); d.mkdir(parents=True, exist_ok=True)
            claude = a.claude or os.environ.get("GAMEANYTHING_CLAUDE") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
            env = {k: v for k, v in os.environ.items() if not users.CRED_RE.match(k)}
            if not users.is_default_config(d): env["CLAUDE_CONFIG_DIR"] = str(d)
            print(f"[hub] starting claude with CLAUDE_CONFIG_DIR={d}: type /login, log in with {a.name}'s own account, then /exit")
            os.execvpe(claude, [claude], env)
    except users.HubError as e:
        sys.exit(f"[hub] {e}")
    return 0


def i18n(a):
    import yaml
    from . import translate
    if a.what == "missing":
        m = translate.missing(a.project, a.lang)
        if m: print(yaml.safe_dump(m, allow_unicode=True, sort_keys=False, width=1000), end="")
        return 0
    if not a.file: sys.exit("[i18n] add needs --file")
    try: n = translate.add(a.project, yaml.safe_load(a.file.read_text(encoding="utf-8")), a.lang)
    except (ValueError, OSError, yaml.YAMLError) as e: sys.exit(f"[i18n] {e}")
    print(f"[i18n] added {n[0]}, replaced {n[1]}, skipped {n[2]} blank"); return 0


def estimate_cmd(a):
    import json
    import yaml
    from .estimate import estimate
    if a.runners:                                     # one estimate per runner, ready to paste as the go card's runners
        out, out_en = [], []
        for i, spec in enumerate(x for x in a.runners.split(",") if x.strip()):
            parts = spec.split(":"); harness, model = parts[0].strip(), ":".join(parts[1:2]).strip(); note = ":".join(parts[2:]).strip()
            agent = {"claude code": "claude-code", "codex": "codex", "opencode": "opencode"}.get(harness.lower(), harness.lower().replace(" ", "-"))
            try: r = estimate(a.size, agent, model, a.account)
            except ValueError as e: sys.exit(f"[estimate] {e}")
            rid = f"{agent}:{model}"
            out.append({"id": rid, "harness": harness, "model": model, "note": note, **({"recommended": True} if i == 0 else {}), "estimate": r["estimate"]})
            out_en.append({"id": rid, "harness": harness, "model": model, "note": note, **({"recommended": True} if i == 0 else {}), "estimate": r["estimate_en"]})
        print(yaml.dump({"runners": out, "en": {"runners": out_en}}, allow_unicode=True, sort_keys=False, Dumper=type("D", (yaml.SafeDumper,), {"ignore_aliases": lambda *_: True})), end=""); return 0
    agent, model = a.agent, a.model
    if a.project and not agent and not model:          # builds run only on the project's build model: estimate that one
        from . import models
        b = models.effective(Path(a.project), "build"); agent, model = b["agent"], b["model"] or None
    try: r = estimate(a.size, agent or "claude-code", model, a.account)
    except ValueError as e: sys.exit(f"[estimate] {e}")
    if a.yaml: print(yaml.dump({"estimate": r["estimate"], "en": {"estimate": r["estimate_en"]}}, allow_unicode=True, sort_keys=False, Dumper=type("D", (yaml.SafeDumper,), {"ignore_aliases": lambda *_: True})), end=""); return 0
    if not a.json: print(r["sentence_zh"]); print(r["sentence_en"]); print()
    print(osdirs.json_text(r, indent=2)); return 0


def _flow_step(project):
    """The step an agent works on now (flow.py), stamped on the cards it sends so the flow knows which step a card belongs to."""
    try:
        from . import flow, projects
        root = Path(project); kind = projects.config_of(root).get("kind")
        return flow.state(root)["todo"] if flow.opted_in(kind) else None
    except Exception:
        return None


def _flow_guard(project):
    """`gameanything chat say` while the step needs a card: a warning for the agent (stderr), never a block."""
    try:
        from . import flow, projects
        root = Path(project)
        if not flow.opted_in(projects.config_of(root).get("kind")): return
        n = flow.next_step(root)
        if n.get("card_required"):
            print(f"[chat] 注意：现在这一步（{n['todo']}）要的是卡片，不是文字：{'；'.join(n['actions'][:2])}。用 gameanything chat card --project … --file card.yaml 发"
                  f"（例子见 {n['step']['doc']}）。文字可以先说一句，但卡片一定要发。", file=sys.stderr)
    except Exception:
        pass


def _card_of_this_project(project, file, body: dict) -> dict:
    """A card file that belongs to ANOTHER project is refused (hotfix 2026-10-30: runs shared one $TMPDIR and one project's
    $TMPDIR/go.yaml was posted in another project's chat): a `project:` stamp that is not this project, or a file in another project's run
    temp folder. Go and permission cards need a key (a newer one replaces them; a keyless wrong go card stayed clickable). -> the card
    without its stamp."""
    from . import agent_providers, projects
    root = Path(project).resolve()
    try: e = projects.find(root); ids = {e["id"], str(Path(e["path"]).resolve())}
    except KeyError: e = None; ids = {root.name, str(root)}
    stamp = body.pop("project", None)
    if stamp is not None and str(stamp) not in ids and str(Path(str(stamp)).expanduser()) not in ids:
        sys.exit(f"[chat] 这张卡写着 project: {stamp}，不是这个项目（{e['id'] if e else root.name}）的卡，没有发。每个项目的卡片文件用 mktemp 在自己的 $TMPDIR 里新建。")
    owner = agent_providers.run_tmp_project(file)
    if owner is not None and owner not in ids:
        sys.exit(f"[chat] {file} 在另一个项目（{owner}）的临时文件夹里，不是这个项目的卡，没有发。卡片文件用 mktemp 在自己的 $TMPDIR 里新建。")
    if body.get("kind") in ("go", "permission") and not str(body.get("key") or "").strip():
        sys.exit(f"[chat] {body['kind']} 卡要有 key（例如 {'m1-go' if body['kind'] == 'go' else 'm1-permission'}）：改了再发时同一个 key 会替换旧卡，旧的不会还能点。")
    return body


def chat(a):
    import time
    import yaml
    from .conversation import CardError, Owned, Thread, default_session
    if os.environ.get("GAMEANYTHING_ROLE") == "builder":          # builders never read, claim or post in her chat (the resident does; builds.py)
        sys.exit("[chat] 构建 agent 不用对话：不读、不认领、不发言。进度和结果用 gameanything agentd notify --from builder --project \"$P\" --text …，常驻 agent 会转告她")
    me = a.session or default_session()
    if a.what == "wait" and a.unowned:
        from . import dispatch
        ready = dispatch.wait_unowned(a.timeout, ignore=set(a.ignore or ()))
        if not ready: print("[chat] 超时：没有无人接手的新消息"); return 2
        for e, _ in ready: print(f"UNOWNED\t{e['id']}\t{e['title']}\t{e['path']}")
        return 0
    if a.what == "wait" and a.all:
        from . import dispatch
        ready = dispatch.wait_all(me, a.timeout)
        if not ready: print("[chat] 超时，没有新的消息"); return 2
        for e, _ in ready: print(f"[chat] {e['title']} 有新消息：gameanything chat read --project {e['path']} --session {me}")
        return 0
    if a.project is None: sys.exit("[chat] 需要 --project（只有 wait --all 不用）")
    T = Thread(a.project)
    try:
        if a.what == "claim":
            o, took = T.claim(me, a.force)
            print(f"[chat] {'接手了' if took else '现在是 owner：'}{o['session']}（自 {o['since']}）"); return 0
        if a.what not in ("import", "release"): T.guard(me)                       # one owner per conversation; no owner -> the first caller claims
        if a.what in ("read", "say", "card", "progress"): T.mark_busy()       # working here until the next wait
        if a.what == "wait":
            end = time.time() + a.timeout; mt = None; tick = 0; ppid0 = os.getppid()
            while True:
                m = T.log.stat().st_mtime_ns if T.log.exists() else 0
                if m != mt:
                    mt = m
                    new = T.unread()
                    if new: T.notice(new[-1]["id"]); print("[chat] 用户说话了：gameanything chat read"); return 0   # the page shows "working" at once
                if time.time() >= end: print("[chat] 超时，没有新的消息"); return 2
                if not (T.dir.parent / "config" / "project.yaml").exists():      # the project was removed (moved to .trash): stop, never re-create its folder
                    print("[chat] 这个项目已被删除（移到了回收文件夹），wait 退出"); return 4
                time.sleep(1); T.seen(); tick += 1
                if not a.listen: T.mark_waiting()        # --listen: a background listener while the agent works: keep the page's "working" line
                if os.getppid() != ppid0:                # the shell / session that started it is gone: stop, never keep a dead session "owned"
                    print("[chat] 启动这个 wait 的会话已经结束，wait 退出"); return 5
                if tick % 5 == 0:
                    o = T.owner()
                    if o and (not T.is_mine(o, me) or o.get("released")): print(f"[chat] 对话已被会话 {o.get('session')} 接手，这个 wait 退出"); return 3
                    if tick % 20 == 0: T.touch_owner(me)       # the heartbeat: an owner unseen for OWNER_STALE_SECS (90 s) is gone
        if a.what == "idle":
            T.mark_waiting(); print("[chat] 页面显示：agent 空闲（工作完成）"); return 0
        if a.what == "release":
            print("[chat] 放开了这个对话：下一句话来时后台调度会马上叫 agent" if T.release(me) else "[chat] 这个对话本来就不归你"); return 0
        if a.what == "read":
            lines, mine = T.read()
            print("\n".join(f"[用户] {x}" for x in lines) if lines else "[chat] 没有新的消息")
            try:                                          # her anchored words become feedback records (docs/feedback-loop.md 1.3)
                from . import feedback
                for r in feedback.capture(a.project, mine):
                    v = (r.get("anchor") or {}).get("video") or {}
                    where = f"试玩 {r.get('milestone')} {int(v['t'] // 60)}:{int(v['t'] % 60):02d}" if v.get("t") is not None else (r.get("modality") or "")
                    print(f"[feedback] 新记录 {r['id']}（{where}）「{r['words'][:40]}」：写下你的理解 gameanything feedback set --project \"$P\" --id {r['id']} "
                          f"--interpretation … --class … --kind … --certainty high|low（猜的是 {r.get('class')}/{r.get('kind')}）")
            except Exception as x: print(f"[feedback] 没能记下反馈：{type(x).__name__}: {x}", file=sys.stderr)
            return 0
        if a.what == "say":
            text = a.text if a.text is not None else sys.stdin.read()
            if not a.user: _flow_guard(a.project)
            ev = T.user_text(text, source="terminal") if a.user else T.agent_text(text.strip(), a.text_en, session=me, attach=a.attach or ())
            if a.user: T.to_answers_md([(ev, ev["text"])])
            T.seen(); print(ev["id"]); return 0
        if a.what == "card":
            if not a.file: sys.exit("[chat] card 需要 --file")
            body = yaml.safe_load(a.file.read_text(encoding="utf-8"))
            if isinstance(body, dict): body = _card_of_this_project(a.project, a.file, body)
            fix = ""
            if isinstance(body, dict) and body.get("kind") == "go":      # where it runs, said right (QA2 2026-10-30: 「你电脑本地沙盒」 on a server)
                _go_where_ok(a.project, body)
            if isinstance(body, dict) and body.get("kind") == "go":      # builds run ONLY on the project's build model: the card names it, read only
                from . import models
                had = bool(body.get("runners"))
                try: body, fix = models.stamp_build_model(a.project, body)
                except Exception as x: print(f"[chat] build model not put on the go card ({type(x).__name__}: {x})", file=sys.stderr)
                if had: print(f"[chat] 开工卡的 runners 去掉了：构建只用项目的构建模型（{(body.get('build_model') or {}).get('label')}），卡上写着它；她要换就点输入框旁的「构建」。")
            ev = T.card(body, text=a.text, text_en=a.text_en, session=me, flow_step=_flow_step(a.project)); T.seen(); print(ev["id"])
            try:                                              # a card file the agent wrote in her project folder is not left there (QA2 2026-10-30)
                if a.file.resolve().parent == Path(a.project).resolve() and a.file.suffix in (".yaml", ".yml", ".json"):
                    a.file.unlink(); print(f"[chat] {a.file.name} 发出去了，已从项目文件夹删掉（卡片文件请写在 $TMPDIR 里）", file=sys.stderr)
            except OSError: pass
            if fix: print(f"[chat] 注意：{fix}", file=sys.stderr)
            if isinstance(body, dict) and body.get("kind") == "go" and not body.get("estimate"):
                print("[chat] 注意：这张开工卡没有 estimate。用户开工前应该看到花费：gameanything estimate --project P --size small|medium|large --yaml（按项目的构建模型估），把结果并进卡片文件再发一次（key 相同会替换）。", file=sys.stderr)
            return 0
        if a.what == "progress":
            steps = []
            for s_ in a.steps:
                st, _, tx = s_.partition(":")
                steps.append({"state": st, "text": tx} if st in ("done", "current", "todo") and tx else {"state": "todo", "text": s_})
            en = None
            if a.steps_en or a.title_en:
                en = {"steps": [{"state": s["state"], "text": x.partition(":")[2] if x.partition(":")[0] in ("done", "current", "todo") and x.partition(":")[2] else x}
                                for s, x in zip(steps, a.steps_en)]} if a.steps_en else {}
                if a.title_en: en["title"] = a.title_en
            ev = T.card({"kind": "progress", "title": a.title, "milestone": a.milestone or a.key, "key": a.key, "steps": steps}, card_en=en, session=me); T.seen(); print(ev["id"]); return 0
        n = T.import_answers(); print(f"[chat] 导入了 {n} 轮原话"); return 0
    except Owned as e:
        print(f"[chat] {e}", file=sys.stderr); return 3
    except (CardError, OSError, yaml.YAMLError) as e:
        sys.exit(f"[chat] {e}")



# "the sandbox is on her computer" (not 「不动你电脑上的游戏」, which is true for a server sandbox too)
_LOCAL_SANDBOX = re.compile(r"(你的?电脑|本地|本机)[^，。；,.;]{0,8}(沙[箱盒]|docker)|(local|your computer)[^,.;]{0,20}(sandbox|docker)|"
                            r"(sandbox|docker)[^,.;]{0,12}on your (computer|machine)|localhost:", re.I)


def _go_where_ok(project, body):
    """A go card of a project whose sandbox runs on the server must not tell her it runs on her computer (launch_notes, items, text)."""
    from . import buildmode, projects
    from .conversation import CardError
    cfg = projects.config_of(project); st = cfg.get("setup") if isinstance(cfg.get("setup"), dict) else {}
    if buildmode.effective(project)[0] != "lab" or st.get("where") != "server": return
    en = body.get("en") if isinstance(body.get("en"), dict) else {}
    words = [str(x) for k in ("launch_notes", "items") for src in (body, en) for x in (src.get(k) or []) if isinstance(src.get(k), list)]
    bad = [w for w in words if _LOCAL_SANDBOX.search(w)]
    if bad:
        raise CardError(f"这个项目的沙箱在服务器上，不在她的电脑上；开工卡写错了：「{bad[0][:60]}」。请写「服务器上的沙箱」（en: a sandbox on the server），不要写本地 / 你电脑 / localhost")

if __name__ == "__main__":
    sys.exit(main())


def demo_cmd(a):
    from . import demo
    st = demo.export(a.project, a.out, tuple(a.lang or ("zh", "en")), a.ffmpeg, a.max_mb, a.keep_times, a.home, cover=a.cover, placeholder=a.placeholder, preset=a.preset)
    print(f"[demo] {a.out}: {st['api']} answers, {st['files']} files ({st['videos']} videos, {st.get('covered', 0)} pictures covered, {st.get('hidden', 0)} replaced by a placeholder), {st['bytes'] / 1e6:.0f} MB")
    for u in st["missing"]: print(f"[demo] missing: {u}")
    for w in st["warnings"]: print(f"[demo] check {w['kind']}: {w['file']} {w['at']}: {w['text']!r}")
    return 0


def text_cmd(a):
    from .textconv import to_simplified, traditional_ratio
    raw = a.src.read_text(encoding="utf-8", errors="replace")
    if a.yaml:
        import yaml
        conv = lambda x: to_simplified(x) if isinstance(x, str) else {k: conv(v) for k, v in x.items()} if isinstance(x, dict) else [conv(v) for v in x] if isinstance(x, list) else x
        out = yaml.safe_dump(conv(yaml.safe_load(raw)), allow_unicode=True, sort_keys=False, width=200)
    else:
        out = to_simplified(raw)
    if a.out: a.out.write_text(out, encoding="utf-8"); print(f"[text] {a.src} -> {a.out} (traditional share before: {traditional_ratio(raw):.0%})", file=sys.stderr)
    else: sys.stdout.write(out)
