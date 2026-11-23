"""Delivering a build: 5_build/<m>/play/ (video + play.yaml) and its milestone in 4_design/world_plan.yaml.

The 试玩 page lists a build from both: the world_plan milestone (name, status, at) and the play folder (play.yaml: video, chapters,
checks, scenes, sounds, stills). A build that is only a folder (no milestone, or no play.yaml) used to be missing from the page or break
it (2026-10-24: feature m3 / m3b, sims4-flying-car round2). Three layers keep that from happening again:
- read side (`load_play`, `play_folders`): the page normalizes a malformed play.yaml and synthesizes one for a folder with only a video;
- `gameanything build deliver` (`deliver`): the builder's last step; registers the milestone, writes a missing play.yaml, validates it all;
- `gameanything build check` (`check`): every 5_build folder and what it still lacks; the resident runs it before a `result` card.
`deliver` also warns (never fails) from 5_build/STATUS.yaml (devstatus.py): broken / regressed items, open regressions, this build's recheck not done.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")
FULL_TITLE = "完整录像"
DONE = ("built", "accepted")


def _y(p: Path):
    """-> (data, error): data None when the file is missing; error is the YAML error text."""
    try: return yaml.safe_load(p.read_text(encoding="utf-8")), None
    except FileNotFoundError: return None, None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e: return None, str(e).splitlines()[0] if str(e) else type(e).__name__


def _atomic(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name("." + p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8"); os.replace(tmp, p)


# ---------------------------------------------------------------- play folder (read side, used by the page)
def find_video(play: Path, named=None):
    """The build's video file name inside play/: play.yaml's `video` if that file exists, else video.mp4, else the first video file."""
    if isinstance(named, str) and named and (play / named).is_file(): return named
    if (play / "video.mp4").is_file(): return "video.mp4"
    vids = sorted(f.name for f in play.glob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXT) if play.is_dir() else []
    return vids[0] if vids else None


def has_play(play: Path) -> bool:
    """A play folder the page can show: it has a play.yaml or at least a video."""
    return (play / "play.yaml").is_file() or find_video(play) is not None


def play_folders(B: Path) -> list:
    """Names of the 5_build/<m> folders whose play/ has a play.yaml or a video."""
    if not B.is_dir(): return []
    return sorted(d.name for d in B.iterdir() if d.is_dir() and not d.name.startswith(".") and has_play(d / "play"))


def _num(v):
    if isinstance(v, bool): return None
    try: x = float(v)
    except (TypeError, ValueError): return None
    return x if x == x and abs(x) != float("inf") else None


def chapter_problems(ch) -> list:
    """What is wrong with a `chapters` value (Chinese, one line each); [] = fine."""
    if ch is None: return []
    if not isinstance(ch, list): return [f"chapters 应该是列表，现在是 {type(ch).__name__}"]
    out = []
    for i, c in enumerate(ch):
        if not isinstance(c, dict): out.append(f"chapters[{i}] 应该是 {{moment, title, t}}，现在是 {type(c).__name__}"); continue
        for k in ("moment", "title"):
            if not isinstance(c.get(k), str) or not c.get(k).strip(): out.append(f"chapters[{i}] 缺 {k}")
        if _num(c.get("t")) is None or _num(c.get("t")) < 0: out.append(f"chapters[{i}] 缺 t（从录像开头算的秒数）")
    return out


def normalize_chapters(ch, full_title=FULL_TITLE) -> list:
    """Any `chapters` value -> [{moment, title, t}] sorted by t; never raises. A dict {moment: t | {title, t}} is read as a list."""
    if isinstance(ch, dict):
        ch = [{"moment": k, **(v if isinstance(v, dict) else {"t": v})} for k, v in ch.items()]
    if not isinstance(ch, list): return []
    out, last = [], 0.0
    for i, c in enumerate(ch):
        if isinstance(c, str): c = {"title": c}
        if not isinstance(c, dict): continue
        t = _num(c.get("t")); t = last if t is None or t < 0 else t; last = t
        mo = c.get("moment"); mo = str(mo) if mo not in (None, "") else ("full" if len(ch) == 1 else f"ch{i + 1}")
        ti = c.get("title"); ti = str(ti) if ti not in (None, "") else (full_title if mo == "full" else mo)
        out.append({**c, "moment": mo, "title": ti, "t": t})
    return sorted(out, key=lambda c: c["t"])


def _dicts(x) -> list:
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []


def load_play(play: Path, full_title=FULL_TITLE) -> dict:
    """play.yaml as the page reads it, never raising: lists are lists of dicts, chapters are {moment, title, t}; a folder without
    play.yaml (or with one that does not parse) but with a video gets {video, chapters: [one full chapter]}; nothing: {}."""
    d, _ = _y(play / "play.yaml"); d = d if isinstance(d, dict) else {}
    vid = find_video(play, d.get("video"))
    if not d and not vid: return {}
    out = dict(d)
    if vid and not (isinstance(d.get("video"), str) and (play / d["video"]).is_file()): out["video"] = vid
    ch = normalize_chapters(d.get("chapters"), full_title)
    if not ch and vid: ch = [{"moment": "full", "title": full_title, "t": 0}]
    out["chapters"] = ch
    for k in ("checks", "sounds", "scenes"):
        if k in out: out[k] = _dicts(out[k])
    for i, c in enumerate(out.get("checks") or []):
        if c.get("id") in (None, ""): c["id"] = f"c{i + 1}"
    if "stills" in out and not isinstance(out["stills"], list): out["stills"] = []
    return out


# ---------------------------------------------------------------- video
def probe_video(f: Path):
    """-> (ok, text). ffprobe when installed (a video stream and a duration > 0), else PyAV, else just size > 0."""
    if not f.is_file(): return False, "文件不存在"
    size = f.stat().st_size
    if size <= 0: return False, "文件是空的（0 字节）"
    ff = shutil.which("ffprobe")
    if ff:
        try:
            r = subprocess.run([ff, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height:format=duration",
                                "-of", "json", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            j = json.loads(r.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError) as e: return False, f"ffprobe 读不了：{e}"
        st = (j.get("streams") or [{}])[0]; dur = _num((j.get("format") or {}).get("duration"))
        if r.returncode or not j.get("streams"): return False, "ffprobe 读不出画面：" + ((r.stderr or "").strip().splitlines() or ["不是视频"])[0]
        if not dur or dur <= 0: return False, "ffprobe 读不出时长"
        return True, f"{st.get('codec_name', '?')} {st.get('width', '?')}x{st.get('height', '?')}，{dur:.1f} 秒，{size / 2 ** 20:.1f} MB（ffprobe）"
    try:
        import av
        with av.open(str(f)) as c:
            if not c.streams.video: return False, "PyAV 读不出画面"
            dur = c.duration / 1e6 if c.duration else None
            v = c.streams.video[0]
            return (True, f"{v.codec_context.name} {v.width}x{v.height}，{dur:.1f} 秒（PyAV）") if dur else (False, "PyAV 读不出时长")
    except ImportError: return True, f"{size / 2 ** 20:.1f} MB（没有 ffprobe，只看了大小）"
    except Exception as e: return False, f"PyAV 读不了：{type(e).__name__}"


# ---------------------------------------------------------------- referenced files
def missing_refs(play: Path, d: dict) -> list:
    """Files play.yaml points to (video, video_full, stills, scenes, sounds) that are not in play/."""
    out = []
    def _ok(f, scenes=False):
        return (play / f).is_file() or (scenes and (play / "scenes" / f).is_file())
    for k in ("video", "video_full"):
        if isinstance(d.get(k), str) and d[k] and not _ok(d[k]): out.append(f"{k}: {d[k]}")
    for s in d.get("stills") or [] if isinstance(d.get("stills"), list) else []:
        f = s if isinstance(s, str) else s.get("file") if isinstance(s, dict) else None
        if f and not _ok(f): out.append(f"stills: {f}")
    for k in ("scenes", "sounds"):
        for e in _dicts(d.get(k)):
            f = e.get("file")
            if isinstance(f, str) and f and not _ok(f, k == "scenes"): out.append(f"{k}: {f}")
    return out


def schema_problems(d) -> list:
    """play.yaml schema: a mapping; chapters a list of {moment, title, t}; checks / sounds / scenes lists of mappings."""
    if not isinstance(d, dict): return [f"play.yaml 应该是一个映射（key: value），现在是 {type(d).__name__}"]
    out = chapter_problems(d.get("chapters"))
    if not d.get("chapters") and not out: out.append("没有 chapters（至少一章：moment、title、t）")
    if not isinstance(d.get("video"), str) or not d.get("video"): out.append("没有 video")
    for k in ("checks", "sounds", "scenes"):
        if k in d and d[k] is not None and (not isinstance(d[k], list) or any(not isinstance(e, dict) for e in d[k])): out.append(f"{k} 应该是列表，每条一个映射")
    if isinstance(d.get("checks"), list):
        ids = [c.get("id") for c in d["checks"] if isinstance(c, dict)]
        if any(i in (None, "") for i in ids): out.append("checks 里有条目没有 id")
        dup = sorted({str(i) for i in ids if i not in (None, "") and ids.count(i) > 1})
        if dup: out.append("checks 的 id 重复：" + ", ".join(dup))
    if "stills" in d and not isinstance(d["stills"], list): out.append("stills 应该是文件名列表")
    return out


# ---------------------------------------------------------------- world_plan.yaml (comment-preserving edit of one milestone)
def _ind(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> bool:
    s = line.strip(); return bool(s) and not s.startswith("#")


def _key(line: str):
    s = line.strip()
    if not _content(line) or ":" not in s: return None, None
    k, _, rest = s.partition(":")
    return k.strip().strip("'\""), rest.strip()


def _block_end(lines, i, ind) -> int:
    """Index after the block that starts at line i (all following lines indented deeper than `ind`, plus blank / comment lines in it)."""
    j, end = i + 1, i + 1
    while j < len(lines):
        if _content(lines[j]):
            if _ind(lines[j]) <= ind: break
            end = j + 1
        j += 1
    return end


def _patch_text(text: str, m: str, fields: dict):
    """Set world_plan.milestones.<m>.<k> = v for each field in the YAML text, keeping comments and layout; -> new text or None."""
    q = lambda v: json.dumps(v, ensure_ascii=False)
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"): lines[-1] += "\n"
    wi = next((i for i, l in enumerate(lines) if _ind(l) == 0 and _key(l)[0] == "world_plan"), None)
    if wi is None or (_key(lines[wi])[1] and not _key(lines[wi])[1].startswith("#")): return None
    we = _block_end(lines, wi, 0)
    kids = [i for i in range(wi + 1, we) if _content(lines[i])]
    ci = _ind(lines[kids[0]]) if kids else 2
    mi = next((i for i in kids if _ind(lines[i]) == ci and _key(lines[i])[0] == "milestones"), None)
    body = lambda ind: [" " * ind + f"{k}: {q(v)}\n" for k, v in fields.items()]
    if mi is None:
        lines[we:we] = [" " * ci + "milestones:\n", " " * (ci + 2) + f"{m}:\n"] + body(ci + 4); return "".join(lines)
    if _key(lines[mi])[1] and not _key(lines[mi])[1].startswith("#"): return None
    me = _block_end(lines, mi, ci)
    mk = [i for i in range(mi + 1, me) if _content(lines[i])]
    mci = _ind(lines[mk[0]]) if mk else ci + 2
    xi = next((i for i in mk if _ind(lines[i]) == mci and _key(lines[i])[0] == m), None)
    if xi is None:
        lines[me:me] = [" " * mci + f"{m}:\n"] + body(mci + 2); return "".join(lines)
    if _key(lines[xi])[1] and not _key(lines[xi])[1].startswith("#"): return None
    xe = _block_end(lines, xi, mci)
    fk = [i for i in range(xi + 1, xe) if _content(lines[i])]
    fi = _ind(lines[fk[0]]) if fk else mci + 2
    new = []
    for k, v in fields.items():
        li = next((i for i in fk if _ind(lines[i]) == fi and _key(lines[i])[0] == k), None)
        if li is None: new.append(" " * fi + f"{k}: {q(v)}\n"); continue
        nxt = next((i for i in fk if i > li), xe)
        rest = _key(lines[li])[1]
        if not rest or rest[0] in "|>[{&*!" or (nxt < xe and _ind(lines[nxt]) > fi): return None     # a multi-line value: not by hand
        lines[li] = " " * fi + f"{k}: {q(v)}\n"
    lines[xi + 1:xi + 1] = new
    return "".join(lines)


def register(root: Path, m: str, name=None, what=None, now=None):
    """Write / update world_plan.milestones.<m> (status built unless accepted, `at` = now when it was not built yet or had none, name /
    what when given; other fields kept). -> (changed, before, after, note). Keeps the file's comments when it can."""
    f = Path(root) / "4_design" / "world_plan.yaml"
    d, err = _y(f)
    if err: raise ValueError(f"{f} 读不了（YAML 错误：{err}）：先把它修好")
    if d is not None and not isinstance(d, dict): raise ValueError(f"{f} 应该是一个映射")
    d = d or {}
    wp = d.get("world_plan") if isinstance(d.get("world_plan"), dict) else {}
    if "world_plan" in d and not isinstance(d["world_plan"], dict) and d["world_plan"] is not None: raise ValueError(f"{f}: world_plan 应该是一个映射")
    ms = wp.get("milestones") if wp.get("milestones") is not None else {}
    if not isinstance(ms, dict): raise ValueError(f"{f}: world_plan.milestones 应该是一个映射（m1: {{…}}）")
    before = ms.get(m) if isinstance(ms.get(m), dict) else ({} if ms.get(m) is None else None)
    if before is None: raise ValueError(f"{f}: milestones.{m} 应该是一个映射")
    fields = {}
    st = before.get("status")
    if st not in DONE: fields["status"] = "built"
    if st not in DONE or not before.get("at"): fields["at"] = (now or datetime.now()).isoformat(timespec="seconds")
    if name and before.get("name") != name: fields["name"] = name
    if what and before.get("what") != what: fields["what"] = what
    if not fields: return False, before, before, ""
    if m not in ms: fields = {k: fields[k] for k in ("name", "status", "at", "what") if k in fields}
    after = {**before, **fields}
    want = {**d, "world_plan": {**wp, "milestones": {**ms, m: after}}}
    text = f.read_text(encoding="utf-8") if f.exists() and d else None
    new = _patch_text(text, m, fields) if text else None
    note = ""
    if new is not None:
        try: ok = yaml.safe_load(new) == want
        except yaml.YAMLError: ok = False
        if not ok: new = None
    if new is None:
        if text: note = "world_plan.yaml 改不了原样（有多行值或内联写法），整份重写了，原来的注释没了"
        new = ("# 4_design/world_plan.yaml\n" if not text else "") + yaml.safe_dump(want, allow_unicode=True, sort_keys=False, width=160)
    _atomic(f, new)
    return True, before, after, note


# ---------------------------------------------------------------- play.yaml (write side)
def _chapters_from(path: Path) -> list:
    d, err = _y(path)
    if err: raise ValueError(f"--chapters {path} 读不了：{err}")
    if d is None: raise ValueError(f"--chapters {path} 不存在或是空的")
    ch = d.get("chapters") if isinstance(d, dict) else d
    p = chapter_problems(ch) or ([] if ch else ["没有章节"])
    if p: raise ValueError(f"--chapters {path}：" + "；".join(p))
    return [{"moment": str(c["moment"]), "title": str(c["title"]), "t": float(c["t"]), **{k: v for k, v in c.items() if k not in ("moment", "title", "t")}} for c in ch]


def _prepend(text: str, lines: list) -> str:
    """Put top-level `key: value` lines before the first non-comment line (after a leading comment header)."""
    ls = text.splitlines(keepends=True); i = 0
    while i < len(ls) and not _content(ls[i]): i += 1
    return "".join(ls[:i] + lines + ls[i:])


def deliver(root: Path, m: str, name=None, what=None, chapters=None, now=None) -> dict:
    """The builder's last step. -> {ok, lines: [(mark, text)], fixed: [...]}; mark is ok | fix | warn | fail."""
    root = Path(root); lines = []; fixed = []
    add = lambda mark, t: lines.append((mark, t))
    if not m or "/" in m or "\\" in m or m.startswith("."): return {"ok": False, "lines": [("fail", f"milestone 不对：{m!r}")], "fixed": []}
    play = root / "5_build" / m / "play"; py = play / "play.yaml"
    if not play.is_dir(): add("fail", f"没有 {play}：先把录像和截图放进 5_build/{m}/play/")
    d, err = _y(py)
    if err: add("fail", f"play.yaml 读不了（YAML 错误：{err}）"); d = None
    elif d is not None and not isinstance(d, dict): add("fail", f"play.yaml 应该是一个映射，现在是 {type(d).__name__}"); d = None; err = "type"
    named = d.get("video") if isinstance(d, dict) else None
    vid = find_video(play, named) if play.is_dir() else None
    if isinstance(named, str) and named and not (play / named).is_file():
        add("fail", f"play.yaml 写的 video: {named}，文件不存在")
    if not vid: add("fail", f"5_build/{m}/play/ 里没有录像（{' / '.join(VIDEO_EXT)}）：交付必须有试玩录像")
    else:
        ok, info = probe_video(play / vid)
        add("ok" if ok else "fail", f"录像 {vid}：{info}")
    try: ch = _chapters_from(Path(chapters)) if chapters else None
    except ValueError as e: add("fail", str(e)); ch = None; chapters = None
    if any(k == "fail" for k, _ in lines): return {"ok": False, "lines": lines, "fixed": fixed}

    # play.yaml: create, or add what is missing (video / milestone / chapters); --chapters replaces the chapters
    full = [{"moment": "full", "title": FULL_TITLE, "t": 0}]
    if d is None:
        new = {"milestone": m, "video": vid, "chapters": ch or full}
        _atomic(py, "# 试玩页读这个文件（gameanything build deliver 写的）：video 录像；chapters 章节（moment、title、从开头算的秒数 t）；"
                    "可以再加 checks / scenes / sounds / stills\n" + yaml.safe_dump(new, allow_unicode=True, sort_keys=False, width=160))
        fixed.append("play.yaml"); add("fix", f"写了 play.yaml（{'--chapters 的 ' + str(len(ch)) + ' 章' if ch else '一章：完整录像'}）")
    elif ch is not None and d.get("chapters") != ch:
        _atomic(py, yaml.safe_dump({**d, "chapters": ch}, allow_unicode=True, sort_keys=False, width=160))
        fixed.append("play.yaml"); add("fix", f"play.yaml 的 chapters 换成了 --chapters 的 {len(ch)} 章（整份重写，注释没了）")
        d = {**d, "chapters": ch}
    else:
        text = py.read_text(encoding="utf-8"); top = []
        if d.get("milestone") in (None, ""): top.append(f"milestone: {json.dumps(m)}\n")
        if not isinstance(named, str) or not named: top.append(f"video: {json.dumps(vid, ensure_ascii=False)}\n")
        if top: text = _prepend(text, top)
        if "chapters" not in d:
            text = text + ("" if text.endswith("\n") else "\n") + yaml.safe_dump({"chapters": full}, allow_unicode=True, sort_keys=False)
        elif not d["chapters"]:                                       # chapters: [] / null: one full chapter (the file is rewritten)
            text = yaml.safe_dump({**yaml.safe_load(text), "chapters": full}, allow_unicode=True, sort_keys=False, width=160)
        if text != py.read_text(encoding="utf-8"):
            nd = yaml.safe_load(text)
            _atomic(py, text); fixed.append("play.yaml")
            add("fix", "play.yaml 补上了 " + "、".join(k for k in ("milestone", "video", "chapters") if not d.get(k)))
            d = nd
    d, _ = _y(py)
    probs = schema_problems(d)
    for p in probs: add("fail", "play.yaml：" + p)
    if not probs:
        n = len(d.get("chapters") or [])
        add("ok", f"play.yaml：{n} 章，{len(d.get('checks') or [])} 条检查，{len(d.get('scenes') or [])} 张场景图，{len(d.get('stills') or [])} 张截图")
        ts = [c["t"] for c in d["chapters"]]
        if ts != sorted(ts): add("warn", "chapters 的 t 不是从小到大：页面会按 t 重新排")
        if d.get("milestone") not in (None, m): add("warn", f"play.yaml 的 milestone 是 {d.get('milestone')}，文件夹是 {m}")
    miss = missing_refs(play, d) if isinstance(d, dict) else []
    for x in miss: add("fail", f"play.yaml 引用的文件不存在：{x}")
    if any(k == "fail" for k, _ in lines): return {"ok": False, "lines": lines, "fixed": fixed}

    try:
        changed, before, after, note = register(root, m, name, what, now)
    except ValueError as e:
        add("fail", str(e)); return {"ok": False, "lines": lines, "fixed": fixed}
    if changed:
        fixed.append("world_plan.yaml")
        add("fix", f"world_plan.yaml：{m} " + ("登记了" if not before else "更新了") + f"（status {after.get('status')}，at {after.get('at')}"
            + (f"，name {after.get('name')}" if after.get("name") else "") + "）")
        if note: add("warn", note)
    else: add("ok", f"world_plan.yaml：{m} 已登记（status {after.get('status')}，at {after.get('at')}）")
    if not after.get("name"): add("warn", f"{m} 没有 name：页面会显示文件夹名；加 --name「第 N 版 …」")
    from . import devstatus                                          # 5_build/STATUS.yaml: warns, never blocks the delivery
    for w in devstatus.deliver_warnings(root, m): add("warn", w)
    from . import feedback                                           # same-anchor before / after pairs of her comments (never blocks)
    for k, t in feedback.on_deliver(root, m): add(k, t)
    return {"ok": True, "lines": lines, "fixed": fixed}


# ---------------------------------------------------------------- check (read only)
def check(root: Path, only=None, probe=True) -> list:
    """Every 5_build/<m> folder (and every built milestone) with what it lacks. -> [{m, ok, problems: [...], warnings: [...], info}]."""
    root = Path(root); B = root / "5_build"
    wp, err = _y(root / "4_design" / "world_plan.yaml")
    ms = ((wp or {}).get("world_plan") or {}).get("milestones") if isinstance(wp, dict) and isinstance(wp.get("world_plan"), dict) else None
    ms = ms if isinstance(ms, dict) else {}
    names = sorted(d.name for d in B.iterdir() if d.is_dir() and not d.name.startswith(".")) if B.is_dir() else []
    names += [m for m, v in ms.items() if isinstance(v, dict) and v.get("status") in DONE and m not in names]
    out = []
    for m in names:
        if only and m != only: continue
        play = B / m / "play"; v = ms.get(m) if isinstance(ms.get(m), dict) else None
        P, W = [], []; r = {"m": m, "problems": P, "warnings": W, "info": ""}
        if err: P.append(f"world_plan.yaml 读不了：{err}")
        if not play.is_dir():
            if v and v.get("status") in DONE: P.append(f"world_plan 里是 {v.get('status')}，但没有 5_build/{m}/play/")
            else: r["info"] = "不是交付的版本（没有 play/）"; r["skip"] = True
            r["ok"] = not P; out.append(r); continue
        d, perr = _y(play / "play.yaml")
        vid = find_video(play, d.get("video") if isinstance(d, dict) else None)
        if not vid: P.append("没有录像")
        elif probe:
            ok, info = probe_video(play / vid)
            if not ok: P.append(f"录像 {vid} 放不了：{info}")
            else: r["info"] = f"{vid}：{info}"
        if perr: P.append(f"play.yaml 读不了（{perr}）")
        elif d is None: P.append("没有 play.yaml")
        else:
            P.extend("play.yaml：" + p for p in schema_problems(d))
            if isinstance(d, dict):
                P.extend(f"play.yaml 引用的文件不存在：{x}" for x in missing_refs(play, d))
                if d.get("milestone") in (None, ""): W.append("play.yaml 没写 milestone")
                elif d.get("milestone") != m: W.append(f"play.yaml 的 milestone 是 {d.get('milestone')}")
        if v is None: P.append("world_plan.yaml 里没有这个里程碑")
        else:
            if v.get("status") not in DONE: P.append(f"world_plan 里的状态是 {v.get('status') or '（没写）'}，不是 built")
            if not v.get("name"): W.append("world_plan 里没有 name")
            if not v.get("at"): W.append("world_plan 里没有 at")
        try:
            from . import feedback
            uv = feedback.unverified(root, m)
            if uv: W.append(f"{len(uv)} 条她的意见没有在同一个画面复拍：{', '.join(x['id'] for x in uv)}（gameanything feedback pairs --project <P> --m {m} --todo）")
        except Exception: pass
        r["ok"] = not P; out.append(r)
    return out


def check_text(rows: list, project="") -> str:
    lines = [f"[build check] {project}".rstrip()]
    for r in rows:
        if r.get("skip"): continue
        lines.append(f"  {'OK' if r['ok'] else 'NO'} {r['m']}" + (f"  ({r['info']})" if r["info"] and r["ok"] else ""))
        lines += [f"       缺：{p}" for p in r["problems"]] + [f"       注意：{w}" for w in r["warnings"]]
    bad = [r["m"] for r in rows if not r["ok"]]
    if not [r for r in rows if not r.get("skip")]: lines.append("  （没有交付的版本）")
    skip = [r["m"] for r in rows if r.get("skip")]
    if skip: lines.append(f"  （另外 {len(skip)} 个文件夹没有 play/，不算交付的版本：" + ", ".join(skip[:8]) + (" …" if len(skip) > 8 else "") + "）")
    lines.append(f"  {len(bad)} 个版本没交付好：" + ", ".join(bad) + "。修法：gameanything build deliver --project <P> --m <m> --name …" if bad else "  全部交付好了")
    return "\n".join(lines)
