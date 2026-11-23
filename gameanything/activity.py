"""What an agent run is doing right now, in her words, read from the run's own event stream (no agent has to remember to report).

    Tail(root, run_id, log, provider).step()      reads what the run's log gained since the last call and appends short activity lines
                                                  to <project>/conversation/.activity/<run>.jsonl ({at, kind, zh, en}); the tail's own
                                                  state (offset, last line, pause, open tools) is <run>.json next to it
    translate(provider, event, root) -> [act]     one decoded event of a provider's stream -> neutral acts (PARSERS; register() adds one)
    describe_cmd / describe_path                  a shell command / a file -> a plain line ("在编译 mod", "在改剧情镜头的代码 Story.java")
    limit_of(text) / reset_at(text)               a usage-limit / login message and when the limit resets

Lines never carry a whole command, an env value or a secret: a command becomes what it does, a file its name (paths inside the project
relative to it, outside only the file name), and every line goes through clean() (keys and long tokens masked, MAX_TEXT long).
Providers: claude-code (stream-json), codex (exec --json), opencode (run --format json), gemini (-o stream-json), dsh (--profile headless
--json); a new CLI registers its
parser with register(name, fn). Everything here is best effort: an unknown event is skipped, never an error.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import clock

MAX_TEXT = 80
READ_CHUNK = 4 << 20              # at most this much of a log per step (a 5 h build log is ~50 MB; a step must stay quick)
FIRST_TAIL = 1 << 20              # a log first seen when it is already big (an adopted run): only its last part
KEEP_LINES = 2000                 # activity lines kept per run (older ones are dropped when the file is rewritten)
IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
SRC = (".java", ".cs", ".py", ".js", ".ts", ".lua", ".kt", ".gd", ".cpp", ".cc", ".c", ".h", ".hpp", ".gradle", ".sh", ".ps1", ".html", ".css",
       ".shader", ".hlsl", ".glsl", ".rs", ".go")
DATA = (".json", ".yaml", ".yml", ".mcmeta", ".xml", ".toml", ".cfg", ".ini", ".txt", ".md", ".csv")
CODE = SRC + DATA


def adir(root) -> Path: return Path(root) / "conversation" / ".activity"


def now() -> str: return datetime.now().isoformat(timespec="seconds")


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def _write(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); os.replace(tmp, p)


# ---------------------------------------------------------------- keeping secrets and long things out
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|eyJ[A-Za-z0-9._\-]{16,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{12,}|AIza[A-Za-z0-9_\-]{20,}"
                     r"|\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9+/_\-]{40,}={0,2})")
_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=(\"[^\"]*\"|'[^']*'|\S+)")


def clean(text, n=MAX_TEXT) -> str:
    """One short line: secrets and long tokens masked, KEY=value -> KEY=…, whitespace folded, at most n characters."""
    s = " ".join(str(text or "").split())
    s = _ASSIGN.sub(lambda m: f"{m.group(1)}=…", s)
    s = _SECRET.sub("…", s)
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def act(kind, zh, en, **kw) -> dict:
    return {"kind": kind, "zh": clean(zh), "en": clean(en), **kw}


# ---------------------------------------------------------------- files
# words in a file name -> what that code is about (her words); the first match wins
TOPICS = [(r"story|cutscene|scene|cine|camera|\bcam|director|^dir\b|tour", "剧情镜头", "story camera"),
          (r"\bui\b|hud|menu|gui|screen|font|lang|i18n|locali|text|sign", "界面文字", "UI text"),
          (r"terrain|ground|island|isle|heightmap|\bdem\b|osm|geo|map|world", "地形", "terrain"),
          (r"road|route|street|path|traffic", "道路", "roads"),
          (r"room|house|interior|lux|furn|build|struct|block|deck|fac", "场景搭建", "scene building"),
          (r"npc|soldier|villager|entity|character|actor|person|people|\bcims?\b|citizen|student", "角色", "character"),
          (r"model|mesh|\bobj\b|decim|lowpoly|asset|prop|landmark", "模型", "model"),
          (r"tex|texture|material|colou?r|paint|shader", "贴图颜色", "texture"),
          (r"sound|audio|music|sfx|voice", "声音", "sound"),
          (r"memor|moment|event|quest|dialog|dialogue|line", "回忆片段", "memory")]


def topic(name: str):
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", Path(name).stem).lower().replace("_", " ").replace("-", " ").replace(".", " ")
    for rx, zh, en in TOPICS:
        if re.search(rx, s): return zh, en
    return None


def rel(path, root=None) -> str:
    """A path for a line: inside the project relative to it (at most its last 3 parts), elsewhere only the file name."""
    p = str(path or "").strip().strip("'\"")
    if not p: return ""
    if root:
        try:
            r = Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
            parts = r.split("/"); return "/".join(parts[-3:])
        except (ValueError, OSError, RuntimeError): pass
    return Path(p).name or p


SPECIAL_FILES = {"status.yaml": ("开发状态", "the dev status"), "build_status.yaml": ("构建进度", "the build progress"),
                 "play.yaml": ("试玩页", "the play page"), "build_changes.yaml": ("她改的要求", "her changes"),
                 "world_plan.yaml": ("方案", "the plan"), "board.yaml": ("回忆板", "the memory board")}


def describe_path(path, verb, root=None) -> dict:
    """verb: read | edit | write -> an act ("在改剧情镜头的代码 Story.java")."""
    name = rel(path, root); base = Path(name).name; low = base.lower(); suf = Path(low).suffix
    if not base: return act("tool", {"read": "在读文件", "edit": "在改文件", "write": "在写文件"}[verb], {"read": "Reading a file", "edit": "Editing a file", "write": "Writing a file"}[verb])
    full = str(path or "").replace("\\", "/").lower()
    if low in SPECIAL_FILES:
        zh, en = SPECIAL_FILES[low]
        return act("tool", ("在看" if verb == "read" else "在更新") + zh, ("Reading " if verb == "read" else "Updating ") + en, file=name)
    if "/lessons/" in full or low.startswith("lessons"):
        return act("tool", "在读经验本" if verb == "read" else "在往经验本里记一条", "Reading the lessons" if verb == "read" else "Adding a lesson", file=name)
    if verb == "read" and suf in IMAGE:
        if re.search(r"shot|screen|round|tour|play|evidence|compare|frame|sheet|cam|_vs_", full):
            return act("look", f"在看截图 {base}", f"Looking at the screenshot {base}", file=name, image=str(path))
        return act("look", f"在看图 {base}", f"Looking at the picture {base}", file=name, image=str(path))
    if verb == "read" and (suf == ".md" or low in ("claude.md", "agents.md")):
        return act("tool", f"在读说明 {base}", f"Reading the notes {base}", file=name)
    tp = topic(base) if suf in SRC or not suf else None
    if suf in SRC:
        if verb == "read":
            return act("tool", f"在读{tp[0]}的代码 {base}" if tp else f"在读代码 {base}", f"Reading the {tp[1]} code {base}" if tp else f"Reading code {base}", file=name)
        zh = ("在改" if verb == "edit" else "在写") + (f"{tp[0]}的代码 {base}" if tp else f"代码 {base}")
        en = ("Editing " if verb == "edit" else "Writing ") + (f"the {tp[1]} code {base}" if tp else f"code {base}")
        return act("edit", zh, en, file=name)
    zh = {"read": "在读", "edit": "在改", "write": "在写"}[verb] + f" {base}"
    en = {"read": "Reading", "edit": "Editing", "write": "Writing"}[verb] + f" {base}"
    return act("tool" if verb == "read" else "edit", zh, en, file=name)


# ---------------------------------------------------------------- shell commands
M2W = {  # "group sub" -> (zh, en); "group" alone = the default of that group
    "status show": ("在看开发状态", "Reading the dev status"), "status init": ("在列出要求清单", "Listing her requirements"),
    "status set-item": ("在更新开发状态", "Updating the dev status"), "status add-issue": ("在记一个已知问题", "Noting a known issue"),
    "status recheck": ("在复查每一版都要看的清单", "Running the recheck list"), "status card": ("在做成果卡", "Making the result card"),
    "status": ("在看开发状态", "Reading the dev status"),
    "lessons show": ("在读经验本", "Reading the lessons"), "lessons add": ("在往经验本里记一条", "Adding a lesson"), "lessons": ("在读经验本", "Reading the lessons"),
    "build status": ("在更新构建进度", "Updating the build progress"), "build deliver": ("在登记成果", "Registering the result"),
    "build check": ("在检查成果能不能交付", "Checking the delivery"), "build": ("在看构建", "Looking at the build"),
    "agentd notify": ("在给驻场 agent 报进度", "Reporting to the resident agent"), "agentd request": ("在提交请求", "Sending a request"),
    "agentd": ("在看后台调度", "Looking at the dispatcher"),
    "native shot": ("在游戏里截图", "Taking a screenshot in the game"), "native drive": ("在游戏里操作", "Playing the game"),
    "native launch": ("在启动游戏", "Starting the game"), "native close": ("在关游戏", "Closing the game"), "native": ("在用本机游戏工具", "Using the game tools"),
    "chat say": ("在回复你", "Replying to you"), "chat card": ("在给你发卡片", "Sending you a card"), "chat read": ("在读你的消息", "Reading your messages"),
    "chat claim": ("在接手对话", "Picking up the chat"), "chat progress": ("在更新进度卡", "Updating the progress card"), "chat": ("在看对话", "Looking at the chat"),
    "flow": ("在看流程走到哪了", "Checking the flow"), "gen request": ("在申请付费生成", "Queueing a paid generation"), "gen": ("在看付费生成", "Looking at generation"),
    "refs fetch": ("在找参考图", "Fetching reference pictures"), "refs": ("在找参考图", "Fetching reference pictures"),
    "lab": ("在用实验室工具", "Using the lab tools"), "project": ("在看项目设置", "Reading the project settings"),
}
_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_WRAP = re.compile(r"^(?:/usr)?/bin/(?:ba|z)?sh\s+-l?c\s+(.*)$", re.S)
_LEAD = re.compile(r"^(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|timeout\s+\S+|nohup|setsid|sudo|exec|time|env|nice|command|builtin|\(|\{|then|do|else)\s+)+")
_FILE = re.compile(r"""(?<![\w.])([\w./\-]*\w\.(?:%s))(?![\w\-])""" % "|".join(s.lstrip(".") for s in CODE + IMAGE))
_NULL = re.compile(r"\d*>>?\s*/dev/null|\d*>&\d|&>\s*/dev/null|<\s*/dev/null")


def unwrap(cmd: str) -> str:
    """`/bin/bash -lc '…'` (Codex) -> the inner command."""
    c = str(cmd or "").strip(); m = _WRAP.match(c)
    if not m: return c
    s = m.group(1).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"": s = s[1:-1].replace("'\\''", "'")
    return s


def segments(cmd: str):
    """The simple commands of a shell line, heredoc bodies cut out -> [(segment, heredoc body)]."""
    out, lines, i = [], unwrap(cmd).split("\n"), 0
    while i < len(lines):
        ln = lines[i]; body = ""
        m = _HEREDOC.search(ln)
        if m:
            end = m.group(1); j = i + 1; b = []
            while j < len(lines) and lines[j].strip() != end: b.append(lines[j]); j += 1
            body = "\n".join(b); i = j
        parts = [p for p in _SPLIT.split(ln) if p.strip()]
        for k, p in enumerate(parts): out.append((_LEAD.sub("", _NULL.sub("", p).strip()).strip("() {}"), body if k == len(parts) - 1 or "<<" in p else ""))
        i += 1
    return [(s, b) for s, b in out if s]


def _m2w(seg):
    m = re.search(r"(?:^|[\s/])(?:gameanything|m2w)(?:\.exe)?\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?", seg)
    if not m: return None
    g, s = m.group(1), m.group(2) or ""
    zh, en = M2W.get(f"{g} {s}") or M2W.get(g) or (f"在运行 gameanything {g}", f"Running gameanything {g}")
    if g == "status" and s == "set-item":
        i = re.search(r"--id\s+['\"]?(\w+)", seg); st = re.search(r"--state\s+['\"]?(\w+)", seg)
        if i and st: zh, en = f"在更新开发状态（{i.group(1)} → {st.group(1)}）", f"Updating the dev status ({i.group(1)} -> {st.group(1)})"
    return zh, en


WAIT_WORDS = [(r"state|in_world|started|ready|start\.log|loaded|steam|launch|boot|listen|port", "在等游戏启动", "Waiting for the game to start"),
              (r"tour|chapter|scene|cine|cutscene", "在等游戏里的镜头走完", "Waiting for the in-game tour"),
              (r"png|shot|screenshot|jpg", "在等截图", "Waiting for the screenshots"),
              (r"mp4|rec|video|ffmpeg", "在等录像", "Waiting for the recording"),
              (r"build|gradle|compile|jar|dll", "在等编译", "Waiting for the build")]

# (pattern on one simple command, priority, zh, en); the highest priority over all segments wins
RULES = [
    (r"\b(gradlew|gradle|mvn|javac|dotnet\s+(build|publish|msbuild)|msbuild|xbuild|cmake|cargo\s+build|tsc|mcs|csc)\b|^make\b", 90, "在编译 mod", "Compiling the mod"),
    (r"rec_start|record-start|recordmydesktop|x11grab|wf-recorder|\brec\s+start", 85, "在录游戏画面", "Recording the game"),
    (r"rec_stop|record-stop", 84, "在停止录像", "Stopping the recording"),
    (r"\b(scrot|xwd|grim|maim|screencapture)\b|import\s+-window|\bshots?\.sh\b|tourshots|\bcam\.sh\b|screenshot|\bshot\b", 80, "在游戏里截图", "Taking screenshots in the game"),
    (r"\bstart\.sh\b|mc-start|lab-up|\bup\s+\S+-m\d|steam\s|-applaunch|launch_game|run_game|\.x64\b|cslab.*start", 78, "在启动游戏", "Starting the game"),
    (r"mc-stop|\bstop\.sh\b|lab-down|\bdown\s+\S+-m\d", 77, "在关游戏", "Stopping the game"),
    (r"\bffmpeg\b|\bffprobe\b|\bmagick\b|\bconvert\s+\S+\.(png|jpg)", 60, "在处理视频和图片", "Processing video and pictures"),
    (r"\bmc\s+(cmd|tp|say)\b|xdotool|\brcon\b|mc-cmd", 58, "在给游戏发指令", "Sending commands to the game"),
    (r"\bmc\s+(state|entities|blocks|log)\b|mc-log|latest\.log|game\.log|output_log|Player\.log", 55, "在看游戏的状态和日志", "Checking the game state and log"),
    (r"\b(pip|pip3|apt|apt-get|npm|yarn|brew)\s+(install|add)\b", 50, "在装工具", "Installing tools"),
    (r"\b(curl|wget)\b", 40, "在从网上取东西", "Fetching from the network"),
    (r"\bgit\b", 30, "在看版本记录", "Looking at the version history"),
    (r"\b(unzip|tar|zip|7z)\b", 28, "在打包 / 解包文件", "Packing files"),
    (r"^(cp|mv|rsync|install|ln)\b", 26, "在整理文件", "Moving files around"),
    (r"^kill\b", 25, "在停掉一个进程", "Stopping a process"),
    (r"^docker\s+(exec|cp)\b|/dx\.sh\b", 20, "在沙箱里运行命令", "Running a command in the sandbox"),
]


def describe_cmd(cmd, root=None, background=False) -> dict:
    """A shell command -> what it does, never the command itself."""
    segs = segments(cmd); best = None
    if re.match(r"^\s*(until|while)\b", unwrap(cmd)):                    # a wait loop: what it waits for is the point
        txt = unwrap(cmd)
        hit = next(((zh, en) for rx, zh, en in WAIT_WORDS if re.search(rx, txt, re.I)), ("在等", "Waiting"))
        return act("wait", *hit)
    for seg, body in segs:
        cand = None; m = _m2w(seg)
        if m: cand = (100, act("tool", *m))
        if cand is None:
            for rx, pr, zh, en in RULES:
                if re.search(rx, seg, re.I): cand = (pr, act("tool", zh, en)); break
        if cand is None:
            py = re.match(r"^(?:python3?|py|node|bash|sh|pwsh|powershell)(?:\.exe)?\s+(?:-\S+\s+)*([\w./\\-]+\.(?:py|js|sh|ps1))\b", seg)
            if py: cand = (45, act("tool", f"在运行脚本 {Path(py.group(1)).name}", f"Running the script {Path(py.group(1)).name}"))
            elif re.match(r"^(?:python3?|node)\s+(-|-c\b)", seg):
                w = re.search(r"open\(\s*(\w+|['\"][^'\"]+['\"])\s*,\s*['\"][wa]|\.write(_text)?\(|write_text\(", body + seg)
                f = _FILE.search(body or seg)
                if w and f: cand = (70, describe_path(f.group(1), "edit", root))
                else: cand = (35, act("tool", "在用小脚本查数据", "Running a small script"))
            elif re.match(r"^sed\s+(-\w*i|--in-place)", seg) or re.match(r"^perl\s+-\w*i", seg):
                f = _FILE.search(seg); cand = (70, describe_path(f.group(1), "edit", root) if f else act("edit", "在改文件", "Editing a file"))
            elif re.match(r"^(cat|tee)\b.*>\s*\S", seg) or (re.match(r"^cat\s*>", seg)):
                f = re.search(r">\s*['\"]?([^\s'\"<>]+)", seg)
                cand = (65, describe_path(f.group(1), "write", root) if f else act("edit", "在写文件", "Writing a file"))
            elif re.match(r"^(until|while)\b", seg) or re.match(r"^sleep\s+\d", seg):
                txt = " ".join(s for s, _ in segs)
                hit = next(((zh, en) for rx, zh, en in WAIT_WORDS if re.search(rx, txt, re.I)), None)
                sec = re.search(r"^sleep\s+(\d+)", seg)
                if hit: cand = (52, act("wait", *hit))
                else: cand = (15, act("wait", f"在等 {sec.group(1)} 秒" if sec else "在等", f"Waiting {sec.group(1)} s" if sec else "Waiting"))
            elif re.match(r"^(cat|head|tail|less|sed\s+-n|wc|stat|file|du|jq|yq|unzip\s+-l|xxd|strings|diff)\b", seg):
                f = _FILE.search(seg); cand = (12, describe_path(f.group(1), "read", root) if f else act("tool", "在看文件", "Looking at files"))
            elif re.match(r"^(grep|rg|find|ls|tree|fd|locate|which|type)\b", seg):
                cand = (10, act("tool", "在找文件", "Looking for files"))
            elif re.match(r"^(cd|export|echo|printf|set|true|false|date|source|\.|pwd|mkdir|touch|chmod|rm|unset|wait|exit|return)\b", seg):
                cand = (0, None)
            else: cand = (5, act("tool", "在运行命令", "Running a command"))
        if cand[1] is not None and (best is None or cand[0] > best[0]): best = cand
    a = best[1] if best else act("tool", "在运行命令", "Running a command")
    if background and a["kind"] != "wait": a = {**a, "zh": clean(a["zh"] + "（在后台）"), "en": clean(a["en"] + " (in the background)")}
    return a


# ---------------------------------------------------------------- usage limits and logins
LIMIT_RE = re.compile(r"usage limit|rate.?limit|session limit|weekly limit|hit your limit|limit reached|limit will reset|out of (extra )?usage|"
                      r"too many requests|\b429\b|resource.?exhausted|quota exceeded|exceeded your current quota|credit balance is too low|"
                      r"exhausted your (daily )?quota|TerminalQuotaError|daily quota", re.I)
AUTH_RE = re.compile(r"authentication_failed|not logged in|oauth access token is invalid|invalid api key|invalid x-api-key|\b401\b|unauthori[sz]ed|"
                     r"please run /login|login (has )?expired|token (has )?expired|api key not valid|permission_denied.*key|"
                     r"missing_credential|invalid_credential|authentication fails|insufficient balance", re.I)


def limit_of(text):
    """'limit' / 'auth' / None for an error text of a CLI."""
    s = str(text or "")
    if AUTH_RE.search(s): return "auth"
    if LIMIT_RE.search(s): return "limit"
    return None


def reset_at(text, base=None):
    """When a usage limit resets, from its message -> epoch seconds or None. Knows `…|1793057400`, 'resets 6pm (America/Los_Angeles)',
    'resets at 18:30', 'try again at 5:10 PM', 'try again in 2 hours 5 minutes' / 'in 3h'."""
    s = str(text or ""); base = time.time() if base is None else base
    m = re.search(r"\|\s*(\d{10})\b", s) or re.search(r"\breset[s]?\D{0,12}(\d{10})\b", s)
    if m: return float(m.group(1))
    m = re.search(r"\b(?:in|after)\s+(\d+)\s*(h|hours?|hrs?|小时|m|mins?|minutes?|分钟?)\b(?:\s*(?:and\s*)?(\d+)\s*(?:m|mins?|minutes?|分钟?)\b)?", s, re.I)
    if m and re.search(r"try again|reset|retry|再试|恢复", s, re.I):
        n = int(m.group(1)); hours = m.group(2).lower().startswith("h") or m.group(2) == "小时"
        return base + (n * 3600 + int(m.group(3) or 0) * 60 if hours else n * 60)
    m = re.search(r"(?:resets?|try again|available again|until)\s*(?:at|on)?\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?:\s*\(([\w/+\-]+)\))?", s, re.I)
    if not m and re.search(r"daily quota", s, re.I):                # Gemini's free tier: the daily quota resets at midnight Pacific time
        try:
            from zoneinfo import ZoneInfo
            ref = datetime.fromtimestamp(base, ZoneInfo("America/Los_Angeles"))
            return (ref.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
        except Exception: return base + 3600
    if not m: return None
    h, mi, ap, tz = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", ""), m.group(4)
    if ap == "pm" and h < 12: h += 12
    if ap == "am" and h == 12: h = 0
    if h > 23 or mi > 59: return None
    zone = None
    if tz:
        try:
            from zoneinfo import ZoneInfo
            zone = timezone.utc if tz.upper() in ("UTC", "GMT") else ZoneInfo(tz)
        except Exception: zone = None
    ref = datetime.fromtimestamp(base, zone) if zone else datetime.fromtimestamp(base)
    t = ref.replace(hour=h, minute=mi, second=0, microsecond=0)
    if t.timestamp() < base - 60: t += timedelta(days=1)
    return t.timestamp()


def _error(text, **kw) -> dict:
    k = limit_of(text)
    if k == "limit": return {"t": "limit", "text": clean(text, 160), "resets": reset_at(text), **kw}
    if k == "auth": return {"t": "auth", "text": clean(text, 160), **kw}
    return {"t": "error", "text": clean(text, 160), **kw}


# ---------------------------------------------------------------- provider streams -> neutral events
def _tool(name, inp, tid=None, root=None, bg=False):
    n = (name or "").lower(); inp = inp if isinstance(inp, dict) else {}
    path = inp.get("file_path") or inp.get("filePath") or inp.get("absolute_path") or inp.get("path") or inp.get("notebook_path")
    if n in ("bash", "shell", "run_shell_command", "local_shell", "exec_command", "command_execution", "powershell"):
        a = describe_cmd(inp.get("command") or inp.get("cmd") or "", root, background=bg or bool(inp.get("run_in_background")))
    elif n in ("read", "read_file", "view", "notebookread", "read_many_files"): a = describe_path(path, "read", root)
    elif n in ("edit", "multiedit", "replace", "apply_patch", "patch", "notebookedit", "str_replace_editor", "str_replace", "edit_file"): a = describe_path(path, "edit", root)
    elif n in ("write", "write_file", "create_file"): a = describe_path(path, "write", root)
    elif n in ("glob", "grep", "search_file_content", "list_directory", "ls", "list", "find", "codebase_search", "glob_file_search"): a = act("tool", "在找文件", "Looking for files")
    elif n in ("webfetch", "websearch", "web_fetch", "google_web_search", "web_search", "fetch"): a = act("tool", "在网上查资料", "Looking something up online")
    elif n in ("monitor", "taskoutput", "bashoutput", "await", "sleep", "wait"):
        a = describe_cmd(inp.get("command") or "", root) if inp.get("command") else act("wait", "在等后台任务", "Waiting for a background task")
        if a["kind"] != "wait": a = act("wait", "在等后台任务", "Waiting for a background task")
    elif n in ("task", "agent"): a = act("tool", "在请一个助手帮忙查", "Asking a helper agent")
    elif n in ("todowrite", "update_plan", "todo_write"): a = act("plan", "在列下一步要做的事", "Planning the next steps")
    else: a = act("tool", "在用工具", "Using a tool")
    return {"t": "tool", "id": tid, "act": a}


def _say(text):
    s = str(text or "").strip()
    return {"t": "say", "act": act("say", s.split("\n", 1)[0], s.split("\n", 1)[0])} if s else None


def _claude(e, root=None):
    t = e.get("type"); out = []
    if t == "assistant":
        msg = e.get("message") or {}; err = e.get("error") or msg.get("error")
        texts = [b.get("text") or "" for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
        if err or msg.get("model") == "<synthetic>" or any(x.startswith("API Error") for x in texts):
            joined = " ".join(texts) or str(err)
            if limit_of(f"{err} {joined}") or err: out.append(_error(f"{err or ''} {joined}".strip())); return out
        for b in msg.get("content") or []:
            if not isinstance(b, dict): continue
            if b.get("type") == "tool_use": out.append(_tool(b.get("name"), b.get("input"), b.get("id"), root))
            elif b.get("type") == "text":
                s = _say(b.get("text"))
                if s: out.append(s)
            elif b.get("type") == "thinking": out.append({"t": "beat"})
    elif t == "user":
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_result": out.append({"t": "tool_end", "id": b.get("tool_use_id")})
    elif t == "rate_limit_event":
        i = e.get("rate_limit_info") or {}
        if i.get("status") == "rejected" and not i.get("isUsingOverage"):    # plan limit hit but the account runs on extra usage: the run goes on
            out.append({"t": "limit", "resets": float(i["resetsAt"]) if isinstance(i.get("resetsAt"), (int, float)) else None,
                        "text": f"{i.get('rateLimitType') or 'usage'} limit", "window": i.get("rateLimitType")})
        else: out.append({"t": "ok"})
    elif t == "result":
        txt = str(e.get("result") or "")
        if e.get("is_error") or e.get("subtype", "success") != "success":
            out.append(_error(f"{txt} {e.get('api_error_status') or ''} {' '.join(map(str, e.get('errors') or []))}".strip()))
        out.append({"t": "end", "ok": not e.get("is_error")})
    elif t == "system":
        st = e.get("subtype")
        if st == "api_retry":
            status = e.get("error_status") or e.get("status")
            if status in (429,) or limit_of(e.get("error")): out.append({"t": "retry", "text": clean(f"{e.get('error') or ''} {status or ''}", 120)})
        elif st == "task_started" and e.get("is_backgrounded"): out.append({"t": "bg_start", "id": e.get("task_id"), "desc": e.get("description")})
        elif st == "task_updated" and (e.get("patch") or {}).get("is_backgrounded"): out.append({"t": "bg_start", "id": e.get("task_id")})
        elif st == "task_notification": out.append({"t": "bg_end", "id": e.get("task_id")})
        elif st == "init": out.append({"t": "beat"})
    elif t == "tool_progress": out.append({"t": "beat", "tool": e.get("parent_tool_use_id")})
    return out


def _codex(e, root=None):
    t = e.get("type"); it = e.get("item") or {}; out = []
    if t in ("item.started", "item.updated", "item.completed"):
        k = it.get("type")
        if k == "command_execution":
            if t == "item.started": out.append(_tool("bash", {"command": it.get("command")}, it.get("id"), root))
            elif t == "item.completed": out.append({"t": "tool_end", "id": it.get("id")})
        elif k == "file_change" and t != "item.updated":
            for c in it.get("changes") or []:
                v = "write" if c.get("kind") == "add" else "edit"
                out.append({"t": "tool", "id": None, "act": describe_path(c.get("path"), v, root)})
        elif k == "agent_message" and t == "item.completed":
            s = _say(it.get("text"))
            if s: out.append(s)
        elif k in ("web_search",) and t == "item.started": out.append({"t": "tool", "id": it.get("id"), "act": act("tool", "在网上查资料", "Looking something up online")})
        elif k == "mcp_tool_call" and t == "item.started": out.append({"t": "tool", "id": it.get("id"), "act": act("tool", "在用工具", "Using a tool")})
        elif k == "error": out.append(_error(it.get("message")))
        else: out.append({"t": "beat"})
    elif t == "error": out.append(_error(e.get("message")))
    elif t == "turn.failed": out.append(_error((e.get("error") or {}).get("message") or e.get("error")))
    elif t in ("turn.started", "thread.started"): out.append({"t": "ok"})
    elif t == "turn.completed": out.append({"t": "beat"})
    return out


def _opencode(e, root=None):
    t = e.get("type"); p = e.get("part") or {}; out = []
    if t == "tool_use" or p.get("type") == "tool":
        st = p.get("state") or {}
        if st.get("status") in (None, "running", "pending", "completed"):
            out.append(_tool(p.get("tool"), st.get("input") or {}, p.get("callID") or p.get("id"), root))
            if st.get("status") == "completed": out.append({"t": "tool_end", "id": p.get("callID") or p.get("id")})
    elif t == "text":
        s = _say(p.get("text"))
        if s: out.append(s)
    elif t == "error":
        d = (e.get("error") or {}).get("data") or {}; out.append(_error(d.get("message") or e.get("error")))
    elif t in ("step_start", "step_finish"): out.append({"t": "beat"})
    return out


def _gemini(e, root=None):
    t = e.get("type"); out = []
    if t == "tool_use": out.append(_tool(e.get("tool_name"), e.get("parameters") or {}, e.get("tool_id"), root))
    elif t == "tool_result": out.append({"t": "tool_end", "id": e.get("tool_id")})
    elif t == "message" and e.get("role") == "assistant" and not e.get("delta"):
        s = _say(e.get("content"))
        if s: out.append(s)
    elif t == "error": out.append(_error(e.get("message") or e))
    elif t == "result":
        if e.get("status") == "error": out.append(_error((e.get("error") or {}).get("message") or e.get("error")))
        out.append({"t": "end", "ok": e.get("status") != "error"})
    elif t in ("init", "message"): out.append({"t": "beat"})
    return out


def _dsh(e, root=None):
    t = e.get("type"); out = []
    if t == "tool_call": out.append(_tool(e.get("tool"), e.get("input") or {}, e.get("callId"), root))
    elif t == "tool_result": out.append({"t": "tool_end", "id": e.get("callId")})
    elif t == "text":
        s = _say(e.get("text"))
        if s: out.append(s)
    elif t == "error": out.append(_error(e.get("message") or e))
    elif t == "status" and e.get("phase") == "turn_end" and (e.get("reason") or {}).get("kind") == "error":
        err = (e.get("reason") or {}).get("error") or {}; out.append(_error(f"{err.get('code') or ''} {err.get('message') or ''}".strip()))
    elif t == "final":                    # 0.2.1-rc.2: no reason here (it came with turn_end); newer: the same reason again
        r = e.get("reason") or {}
        out.append({"t": "end", "ok": r.get("kind") == "completed" if r else None})
    elif t in ("session", "status", "thinking"): out.append({"t": "beat"})
    return out


PARSERS = {"claude-code": _claude, "codex": _codex, "opencode": _opencode, "gemini": _gemini, "dsh": _dsh}


def register(name, fn):
    """A new agent CLI's stream parser: fn(event dict, project root) -> [neutral events] (see _claude for their shapes)."""
    PARSERS[name] = fn


def translate(provider, e, root=None) -> list:
    if not isinstance(e, dict): return []
    fn = PARSERS.get(provider or "claude-code") or _claude
    try: return [x for x in fn(e, root) if x]
    except Exception: return []                      # a stream shape we do not know: skipped, never an error


def _stamp(e):
    """The event's own time (Claude events carry an ISO timestamp in UTC) as local ISO seconds, else None."""
    ts = e.get("timestamp") if isinstance(e, dict) else None
    if not isinstance(ts, str): return None
    try: return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError: return None


# ---------------------------------------------------------------- tailing one run's log
LOOP_WINDOW, LOOP_DISTINCT = 16, 3            # Tail.looping: 16 tool calls in a row among at most 3 different ones, no file written
class Tail:
    """Follows one run's log. step() -> the new activity lines; .state: {offset, grew_at, last, pause, tools, bg, ended, n}."""

    def __init__(self, root, run_id, log, provider="claude-code", role="resident", clock=time.time):
        self.root, self.run, self.log, self.provider, self.role, self.clock = Path(root), str(run_id), Path(log) if log else None, provider or "claude-code", role, clock
        self.sf = adir(root) / f"{self.run}.json"; self.lf = adir(root) / f"{self.run}.jsonl"
        self.images = []                          # pictures the run looked at in the last step: [{at, path, zh, en}] (never written to the file)
        self.state = _read(self.sf) or {}
        if self.state.get("log") != (str(self.log) if self.log else None):
            self.state = {"run": self.run, "role": role, "provider": self.provider, "log": str(self.log) if self.log else None, "offset": None,
                          "grew_at": None, "last": None, "pause": None, "tools": {}, "bg": {}, "n": 0, "started": now()}

    def save(self): _write(self.sf, self.state)

    def _append(self, lines):
        if not lines: return
        self.lf.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lf, "a", encoding="utf-8") as f:
            for x in lines: f.write(json.dumps(x, ensure_ascii=False) + "\n")
        self.state["n"] = int(self.state.get("n") or 0) + len(lines)
        if self.state["n"] > KEEP_LINES * 1.5:
            keep = self.lf.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
            self.lf.write_text("\n".join(keep) + "\n", encoding="utf-8"); self.state["n"] = len(keep)

    def step(self) -> list:
        """Read what the log gained; -> the activity lines written (also kept in the file)."""
        st = self.state; out = []; self.images = []
        if not self.log: return out
        try: s = self.log.stat()
        except OSError: return out
        size = s.st_size; st["grew_at"] = s.st_mtime                  # the run writes its log: its last write is its last sign of life
        off = st.get("offset"); first = off is None
        if first: off = max(0, size - FIRST_TAIL)
        if size < off: off = 0; first = False                          # a log that was rewritten: from the start
        if size > off:
            with open(self.log, "rb") as f:
                f.seek(off); data = f.read(min(READ_CHUNK, size - off))
            if first and off:                                          # started in the middle of a line: skip to the next one
                nl = data.find(b"\n"); skip = nl + 1 if nl >= 0 else len(data); data = data[skip:]; off += skip
            cut = data.rfind(b"\n")
            if cut >= 0:
                chunk = data[:cut + 1]; off += len(chunk)
                for ln in chunk.decode("utf-8", errors="replace").splitlines():
                    ln = ln.strip()
                    if not ln.startswith("{"): continue
                    try: e = json.loads(ln)
                    except ValueError: continue
                    out += self._event(e)
        st["offset"] = off
        lines = []
        for a in out:                                                 # consecutive repeats are one line (its count and newest time)
            last = st.get("last") or {}
            if a.get("zh") == last.get("zh") and a.get("kind") == last.get("kind") and a.get("kind") != "look":
                last["n"] = int(last.get("n") or 1) + 1; last["at"] = a["at"]; st["last"] = last
                if a.get("kind") != "say": st["now"] = dict(last)
                continue
            img = a.pop("image", None)
            if img: self.images.append({"at": a["at"], "path": img, "zh": a["zh"], "en": a["en"]})
            st["last"] = dict(a); lines.append(a)
            if a.get("kind") != "say": st["now"] = dict(a)
        self._append(lines); self.save()
        return lines

    def _event(self, e) -> list:
        st = self.state; at = _stamp(e) or now(); out = []
        for x in translate(self.provider, e, self.root):
            k = x.get("t")
            if k == "tool":
                a = {**x["act"], "at": at}
                if x.get("id"): st["tools"][str(x["id"])] = {"at": at, "zh": a["zh"], "en": a["en"]}
                if len(st["tools"]) > 20: st["tools"] = dict(list(st["tools"].items())[-20:])
                out.append(a); st["pause"] = None
                st["recent"] = (st.get("recent") or [])[-(LOOP_WINDOW * 2):] + [[a.get("kind"), a.get("zh")]]
            elif k == "tool_end": st["tools"].pop(str(x.get("id")), None)
            elif k == "say":
                out.append({**x["act"], "at": at})
            elif k in ("limit", "auth"):
                p = {"kind": k, "since": at, "resets": x.get("resets"), "text": x.get("text"), "window": x.get("window")}
                if not (st.get("pause") or {}).get("kind") == k: out.append({**pause_line(p), "at": at})
                st["pause"] = p
            elif k == "retry": st["retry"] = {"at": at, "text": x.get("text")}
            elif k == "error": out.append({**act("error", "出错了：" + x.get("text", ""), "Error: " + x.get("text", "")), "at": at})
            elif k == "ok": st["pause"] = None
            elif k == "bg_start" and x.get("id"): st["bg"][str(x["id"])] = {"at": at, "desc": clean(x.get("desc") or "", 40)}
            elif k == "bg_end": st["bg"].pop(str(x.get("id")), None)
            elif k == "end": st["ended"] = at; st["tools"] = {}
        return out

    # ---- what the monitors ask
    def quiet_secs(self) -> float:
        """Seconds since the log last grew (the run said or did nothing since)."""
        g = self.state.get("grew_at")
        try: g = self.log.stat().st_mtime if self.log else g
        except OSError: pass
        return max(0.0, self.clock() - float(g)) if g else 0.0

    def looping(self):
        """A run that goes round in circles (QA 2026-10-29: OpenCode / Kimi did claim -> read -> claim ... 29 times until its 80-step cap):
        the last LOOP_WINDOW tool calls are at most LOOP_DISTINCT different ones and none of them writes a file -> those actions, else None."""
        r = (self.state.get("recent") or [])[-LOOP_WINDOW:]
        if len(r) < LOOP_WINDOW or any(k in ("edit", "write") for k, _ in r): return None
        acts = list(dict.fromkeys(z for _, z in r))
        return acts if len(acts) <= LOOP_DISTINCT else None

    def open_tool(self):
        """The oldest tool call still running in the foreground -> (secs, act) or None."""
        ts = self.state.get("tools") or {}
        if not ts: return None
        k, v = min(ts.items(), key=lambda kv: kv[1].get("at") or "")
        try: secs = self.clock() - clock.epoch(v["at"], self.clock())
        except (TypeError, ValueError): return None
        return secs, v


def pause_line(p) -> dict:
    """The activity line of a pause (usage limit / login)."""
    if p.get("kind") == "auth": return act("pause", "停下了：登录失效，需要重新登录", "Paused: the login expired, it needs a new login")
    r = p.get("resets")
    if r: return act("pause", f"停下了：用量到上限，大约 {hhmm(r)} 恢复", f"Paused: usage limit reached, back around {hhmm(r, 'en')}")
    return act("pause", "停下了：用量到上限，要等额度恢复", "Paused: usage limit reached, waiting for it to reset")


def hhmm(epoch, lang="zh") -> str:
    """A local time for her: 「00:12」 today, 「明天 00:12」 / "tomorrow 00:12", else 「11月2日 09:05」 / "Nov 2 09:05" (not 「11-02 09:05」,
    QA2 2026-10-30)."""
    try:
        d = datetime.fromtimestamp(float(epoch)); n = datetime.now()
        t = d.strftime("%H:%M"); days = (d.date() - n.date()).days
        if days == 0: return t
        if days == 1: return ("tomorrow " if lang == "en" else "明天 ") + t
        if days == -1: return ("yesterday " if lang == "en" else "昨天 ") + t
        return f"{d.strftime('%b')} {d.day} {t}" if lang == "en" else f"{d.month}月{d.day}日 {t}"
    except (TypeError, ValueError, OSError, OverflowError): return "?"


def lines(root, run_id, n=40) -> list:
    """The newest n activity lines of a run (oldest first)."""
    f = adir(root) / f"{run_id}.jsonl"
    try: rows = f.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError: return []
    out = []
    for r in rows:
        try: out.append(json.loads(r))
        except ValueError: pass
    return out


def state(root, run_id) -> dict:
    return _read(adir(root) / f"{run_id}.json") or {}


def scan_log(log, provider="claude-code", tail_bytes=200_000):
    """The pause (usage limit / login) the end of a finished run's log shows -> {kind, resets, text} or None. A later normal event clears it."""
    try:
        with open(log, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - tail_bytes)); data = f.read().decode("utf-8", errors="replace")
    except (OSError, TypeError): return None
    p = None
    for ln in data.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"): continue
        try: e = json.loads(ln)
        except ValueError: continue
        for x in translate(provider, e):
            if x.get("t") in ("limit", "auth"): p = {"kind": x["t"], "resets": x.get("resets"), "text": x.get("text")}
            elif x.get("t") in ("tool", "ok"): p = None
    return p
