"""Sid Meier's Civilization VI: the code hooks of the civ6 game package (game.yaml has the folders, saves, logs and launch).

Civ VI has official mod support: a mod is a folder with one <Name>.modinfo (XML: <Mod id="GUID">, its Properties, the actions that load
its files in the front end / in game, and <Files>) plus the Lua / XML / SQL files it names. The game scans <user folder>/Mods/ at
start and lists every mod there in Additional Content; nothing has to be compiled.

    build(src)          checks the mod folder (the .modinfo and every file it names, XML well formed) and stages a copy in
                        <data>/native/build/<name>/mod/ (the folder `install` copies into Mods/)
    check_installable   a folder with exactly one .modinfo whose <Mod id> is a GUID and whose <File> entries all exist (a different
                        case is only a warning: the Linux build lower-cases its own files and ships a case-insensitive file layer,
                        libASL_Interpose.so)
    check_mod(src, it)  `gameanything native check`: the same, plus every .xml / .modinfo parses, Lua files are syntax-checked when a `luac`
                        is on PATH, and the mod id is not already used by another mod folder in Mods/
    after_install / after_uninstall   the enabled switch in Mods.sqlite (see enable_state): current builds keep it in the selected
                        ModGroup's ModGroupItems row (older builds used Mods.Disabled). The game scans a new mod at its next start and (1.0.12.9,
                        2026-10-28) adds it to that group switched on; GameAnything only edits a row the game made (an install after
                        that start turns a switched-off mod back on; game closed).
Hot reload: none (game.yaml reload.none): the game reads mods when a game starts; a change needs a new game or a restart.
"""
import re
import shutil
import sqlite3
from contextlib import closing
import xml.etree.ElementTree as ET
from pathlib import Path

from gameanything.native.games import DeclarativeGame, NativeError, _run

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+ -]{0,63}$")
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def read_modinfo(folder: Path) -> dict:
    """The one .modinfo of a mod folder -> {file, id, version, name, files: [relative paths], actions: [tag names]}; NativeError if
    the folder does not hold exactly one or it does not parse."""
    folder = Path(folder)
    mi = sorted(folder.glob("*.modinfo"))
    if len(mi) != 1:
        raise NativeError(f"{folder} 里要正好有一个 .modinfo（找到 {len(mi)} 个）：文明 6 只认带 .modinfo 的 mod 文件夹")
    try: root = ET.parse(mi[0]).getroot()
    except (ET.ParseError, OSError) as e: raise NativeError(f"{mi[0].name} 不是有效的 XML：{e}")
    if root.tag != "Mod": raise NativeError(f"{mi[0].name} 的根元素是 <{root.tag}>，应该是 <Mod id=\"...\">")
    mid = (root.get("id") or "").strip()
    if not mid: raise NativeError(f"{mi[0].name} 的 <Mod> 没有 id（一个 GUID）")
    files = [(f.text or "").strip() for f in root.iter("File") if (f.text or "").strip()]
    acts = [a.tag for sec in ("FrontEndActions", "InGameActions") for s in root.findall(sec) for a in s]
    return {"file": mi[0], "id": mid, "version": root.get("version") or "", "name": (root.findtext("Properties/Name") or "").strip(),
            "compatible": (root.findtext("Properties/CompatibleVersions") or "").strip(),
            "files": sorted(set(files)), "actions": acts,
            "toplevel_text": [(f.text or "").strip() for f in root.findall("LocalizedText/File")]}


def _find(folder: Path, rel: str, exact=True):
    """The file at rel under folder, matching every part's case exactly (exact=True) or ignoring case. -> the path, or None."""
    cur = folder
    for part in Path(rel.replace("\\", "/")).parts:
        try: names = {p.name: p.name for p in cur.iterdir()} if exact else {p.name.lower(): p.name for p in cur.iterdir()}
        except OSError: return None
        k = part if exact else part.lower()
        if k not in names: return None
        cur = cur / names[k]
    return cur if cur.is_file() else None


def _exact(folder: Path, rel: str): return _find(folder, rel, True)


class Civ6(DeclarativeGame):
    # macOS: the Steam start opens Aspyr's launcher (a 900x528 window of Civ6_Exe) and waits for PLAY; PLAY starts the game itself
    # (Civ6_Exe_Child), which plays an intro movie first. Measured on her Mac 2026-10-29 (launcher v1.4.6): PLAY at these fractions.
    LAUNCHER_PLAY = (0.776, 0.197)
    INTRO_ESCAPES, INTRO_GAP = 5, 6
    QUIT_OK = (0.41, 0.547)            # the OK of 「Exit to Desktop - Are you sure?」 (her Mac 2026-10-29, full screen 1470x956)

    def _children(self):
        r = _run(["pgrep", "-x", "Civ6_Exe_Child"])
        return [int(p) for p in r.stdout.split()] if r is not None and r.returncode == 0 else []

    def after_launch(self, root, pids, sleep=None):
        """macOS: press the launcher's PLAY, record the game process as GameAnything's, skip the intro with a real Escape. Both go through
        `native drive` (real input while she is at the computer only with native_drive: always, else when she is away). Only the PLAY
        button and Escape: nothing else in the launcher is touched."""
        if self.sys != "mac": return None
        import time
        from gameanything.native import hands, quiet
        sleep = sleep or time.sleep
        be = hands.backend(); mine = {int(p) for p in pids}; out = {}
        win = None; end = time.monotonic() + 90
        while time.monotonic() < end and not self._children():
            ws = [w for w in be._list(1 | 16, 0) if int(w.get("pid", 0)) in mine and w.get("layer") == 0 and w.get("w", 0) >= 600]
            if ws: win = ws[0]; break
            sleep(2)
        if win is not None and not self._children():
            sleep(2)                                                          # the launcher page draws after its window appears
            x, y = round(win["w"] * self.LAUNCHER_PLAY[0]), round(win["h"] * self.LAUNCHER_PLAY[1])
            for attempt in range(5):        # just after the start Steam / the launcher may still pull another window in front: try again
                try: hands.drive(root, self, [f"click {x} {y}"], click="hid"); out["launcher"] = "PLAY pressed"; break
                except hands.Refused as e:
                    if e.code not in ("covered", "not_frontmost") or attempt == 4:
                        return {"launcher": "waiting for PLAY (press it in the launcher)", "why": e.why}
                    sleep(2)
        end = time.monotonic() + 60
        while time.monotonic() < end and not self._children(): sleep(2)
        kids = self._children()
        if not kids: return {**out, "game": "the game process did not start yet"}
        quiet.add_pids(root, self, kids); out["game"] = f"Civ6_Exe_Child {kids}"
        # The intro is several movies (logos, then the opening film) and one Escape 10 s after the start came too early (her Mac,
        # 2026-10-29: the film kept playing). So Escape is pressed INTRO_ESCAPES times, INTRO_GAP s apart; on the main menu Escape does
        # nothing (checked the same day). The focus click is at the top middle (the title on the menu, nothing to press): the top-left
        # corner of a full-screen window is the screen's hot corner (it opened Mission Control).
        sent = 0; why = ""
        for i in range(self.INTRO_ESCAPES):
            sleep(self.INTRO_GAP)
            try:
                w = hands.drive(root, self, ["sleep 1"])["window"]
                steps = ([f"click {w['w'] // 2} {max(30, w['h'] // 12)}", "sleep 400"] if not sent else []) + ["key escape"]
                hands.drive(root, self, steps, click="hid"); sent += 1
            except hands.Refused as e: why = e.why
        out["intro"] = f"Escape sent {sent}x" if sent else "not skipped: " + why
        return out
    def confirm_quit(self, root):
        """macOS: Quit (Cmd-Q / NSRunningApplication) shows the game's 「Are you sure you want to exit the game?」: press its OK."""
        if self.sys != "mac": return None
        import time
        from gameanything.native import hands
        # one click did not always take (her Mac 2026-10-29: the second close left the box open; the same click by hand a minute later
        # closed the game): click up to 3 times, 3 s apart, until the game is gone
        for i in range(3):
            try:
                w = hands.drive(root, self, ["sleep 1"])["window"]
                hands.drive(root, self, [f"click {round(w['w'] * self.QUIT_OK[0])} {round(w['h'] * self.QUIT_OK[1])}"], click="hid")
            except hands.Refused: return "OK on Are you sure" if i else None
            time.sleep(3)
            if not self._children(): break
        return "OK on Are you sure"
    # ---- Mods.sqlite (the game's own list of scanned mods and whether each is enabled)
    def mods_db(self):
        for p in self._cands(self._s("mods_db", default=[])):
            if p.is_file(): return p
        return None

    @staticmethod
    def _layout(c) -> str:
        """The current DB uses ModGroupItems.Disabled; old releases kept Disabled directly on Mods."""
        cols = {r[1] for r in c.execute("PRAGMA table_info(Mods)")}
        return "legacy" if "Disabled" in cols else "groups"

    def enable_state(self, mod_id: str):
        """True / False after the game has scanned this mod, None before it has (or when there is no usable Mods.sqlite)."""
        db = self.mods_db()
        if db is None: return None
        try:
            with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as c:     # closed: Windows cannot move an open file
                if self._layout(c) == "legacy":
                    r = c.execute("SELECT Disabled FROM Mods WHERE lower(ModId) = lower(?)", (mod_id,)).fetchone()
                else:
                    scanned = c.execute("SELECT ModRowId FROM Mods WHERE lower(ModId) = lower(?)", (mod_id,)).fetchone()
                    if scanned is None: return None
                    r = c.execute("""SELECT i.Disabled FROM ModGroupItems i JOIN ModGroups g USING (ModGroupRowId)
                                     WHERE i.ModRowId = ? AND g.Selected = 1 ORDER BY g.ModGroupRowId LIMIT 1""", scanned).fetchone()
        except sqlite3.Error: return None
        return False if r is None else not bool(r[0])

    def _set_enabled(self, folder: Path, on: bool) -> dict:
        try: mid = read_modinfo(folder)["id"]
        except NativeError: return {}
        st = self.enable_state(mid)
        if st is None:
            return {"enabled": False, "pending": bool(on),
                    "switch": ("the game has not scanned it yet: its next start scans it and (current builds) switches it on; "
                               "an install after that start confirms the switch" if on else "none")}
        if st == on: return {"enabled": on, "switch": f"Mods.sqlite already {'enabled' if on else 'disabled'}"}
        self._need_closed("改 Mods.sqlite")
        with closing(sqlite3.connect(str(self.mods_db()))) as c, c:     # closed after the commit (restore moves the file)
            if self._layout(c) == "legacy":
                c.execute("UPDATE Mods SET Disabled = ? WHERE lower(ModId) = lower(?)", (0 if on else 1, mid))
            else:
                mod = c.execute("SELECT ModRowId FROM Mods WHERE lower(ModId) = lower(?)", (mid,)).fetchone()
                group = c.execute("SELECT ModGroupRowId FROM ModGroups WHERE Selected = 1 ORDER BY ModGroupRowId LIMIT 1").fetchone()
                if mod is None or group is None:
                    raise NativeError("Mods.sqlite 没有已扫描的 mod 或当前 mod 组：先启动游戏到主菜单，退出后再 install")
                row = c.execute("SELECT Disabled FROM ModGroupItems WHERE ModGroupRowId = ? AND ModRowId = ?",
                                (group[0], mod[0])).fetchone()
                if row is None:
                    if on: c.execute("INSERT INTO ModGroupItems (ModGroupRowId, ModRowId, Disabled) VALUES (?, ?, 0)", (group[0], mod[0]))
                else:
                    c.execute("UPDATE ModGroupItems SET Disabled = ? WHERE ModGroupRowId = ? AND ModRowId = ?",
                              (0 if on else 1, group[0], mod[0]))
        return {"enabled": on, "switch": f"Mods.sqlite: {mid} {'enabled' if on else 'disabled'}"}

    # ---- build (nothing to compile: check and stage)
    def build(self, src, name=None) -> dict:
        src = Path(src).expanduser().resolve()
        if not src.is_dir(): raise NativeError(f"找不到 mod 文件夹：{src}")
        self.check_installable(src)
        name = name or src.name
        if not NAME_RE.match(name): raise NativeError(f"mod 文件夹名字不合适：{name}")
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        st = w / "mod" / name
        shutil.copytree(src, st, ignore=shutil.ignore_patterns(".git", "*.bak", "*~"))
        mi = read_modinfo(st)
        return {"staged": str(st), "mod_id": mi["id"], "files": len(mi["files"]), "warnings": self._lint(st, mi)}

    # ---- install
    def check_installable(self, src):
        src = Path(src)
        if not src.is_dir(): raise NativeError(f"要装的是一个 mod 文件夹（里面有 .modinfo）：{src}")
        mi = read_modinfo(src)
        if not GUID_RE.match(mi["id"]): raise NativeError(f"{mi['file'].name} 的 id {mi['id']!r} 不是 GUID（文明 6 用 GUID 区分 mod）")
        miss = [f for f in mi["files"] if _find(src, f, exact=False) is None]
        if miss: raise NativeError(f"{mi['file'].name} 列出的文件不在：{', '.join(miss)}")
        if not mi["actions"]: raise NativeError(f"{mi['file'].name} 没有 FrontEndActions / InGameActions：游戏不会加载它的任何文件")
        if "2.0" not in {x.strip() for x in mi["compatible"].split(",")}:
            raise NativeError(f"{mi['file'].name} 的 Properties/CompatibleVersions 没有 2.0：当前游戏会标成 Not compatible 并自动禁用")

    def install(self, src, name=None):
        self._need_closed("安装")
        src = Path(src).expanduser()
        return super().install(src, name or src.name)

    def uninstall(self, name):
        self._need_closed("卸载")
        return super().uninstall(name)

    def after_install(self, dst): return self._set_enabled(Path(dst), True)
    def after_uninstall(self, dst): return self._set_enabled(Path(dst), False)

    # ---- headless check
    def _lint(self, src: Path, mi: dict) -> list:
        warn = []
        for f in mi.get("toplevel_text") or []:      # 2026-10-26 Linux round trip: such a text file never reached the game
            warn.append(f"{f}：放在 .modinfo 顶层的 <LocalizedText> 里不会被加载（那里只放 mod 自己的名字文字）；"
                        "改成 FrontEndActions / InGameActions 里的 <UpdateText><File>…</File></UpdateText>")
        listed = {f.replace("\\", "/") for f in mi["files"]}
        for f in sorted(src.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".lua", ".xml", ".sql") and f.relative_to(src).as_posix() not in listed:
                warn.append(f"{f.relative_to(src).as_posix()} 不在 .modinfo 的 <Files> 里：游戏不会用它")
        return warn

    def check_mod(self, src: Path, it: dict):
        src = Path(src)
        try: self.check_installable(src)
        except NativeError as e: it["errors"].append(str(e)); return
        mi = read_modinfo(src)
        it["notes"].append(f"{mi['name'] or src.name}（{mi['id']} v{mi['version']}）：{len(mi['files'])} 个文件，动作 {', '.join(mi['actions'])}")
        for rel in mi["files"]:
            f = _exact(src, rel)
            if f is None:
                it["warnings"].append(f"{rel}：文件名的大小写和 .modinfo 里写的不一样（Windows / macOS 不在乎；Linux 版靠 Aspyr 的大小写兼容层，最好写成一样）")
                f = _find(src, rel, exact=False)
            if f.suffix.lower() in (".xml", ".modinfo"):
                try: ET.parse(f)
                except ET.ParseError as e: it["errors"].append(f"{rel} 不是有效的 XML：{e}")
            elif f.suffix.lower() == ".lua":
                luac = shutil.which("luac5.1") or shutil.which("luac")
                if luac:
                    r = _run([luac, "-p", str(f)])
                    if r is not None and r.returncode != 0: it["errors"].append(f"{rel}：Lua 语法错误：{(r.stderr or r.stdout).strip()[:300]}")
        it["warnings"] += self._lint(src, mi)
        md = self.mods_dir() if self.installed() else None
        if md and md.is_dir():
            for other in md.iterdir():
                if other.is_dir() and other.name != src.name:
                    try: oid = read_modinfo(other)["id"]
                    except NativeError: continue
                    if oid.lower() == mi["id"].lower(): it["errors"].append(f"Mods/{other.name} 已经用了同一个 id {mi['id']}：换一个 GUID")
