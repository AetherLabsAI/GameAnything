"""No Man's Sky: the code hooks of the nms game package (game.yaml has the folders, saves, logs and launch).

The 7.06 Windows executable still references the loose-file loader paths below, but the real-game smoke remains pending: one folder per mod in
<game>/GAMEDATA/MODS/<ModName>/ with the vanilla folder structure inside it:
    *.EXML          patches (partial MXML: only the changed properties, list entries targeted with _id / _index), applied by the
                    game itself at start on top of the vanilla data; GLOBALS patches go in a GLOBALS/ subfolder
    *.MBIN          whole-file replacements (compiled from MXML with MBINCompiler; break easily on game updates)
    LocTable.MXML   the mod's own language table (new text IDs), in the mod folder's root
    DDS / WEM / BNK resources work as before. Traditional .pak mods use a different PCBANKS/MODS layout and are deliberately outside
                    this first adapter; accepting them here would install them into the wrong folder.
The game records the mods it found (order, enabled) in <game>/Binaries/SETTINGS/GCMODSETTINGS.MXML (backed up with the saves).
An old DISABLEMODS.TXT in GAMEDATA/PCBANKS turned every mod off: install moves it into GameAnything's own folder (never deletes
it) and uninstall of the last GameAnything mod puts it back.

    build(src)          checks the folder and stages a copy (nothing to compile: EXML patches are text the game applies)
    check_installable   a folder with at least one EXML / MBIN / LocTable.MXML, no .pak, EXML that parse with <Data template=...>
    check_mod(src, it)  the same, plus warnings: files the game ignores (.MXML other than LocTable.MXML, .lua, .txt), GLOBALS
                        patches outside GLOBALS/, folder name length (the game's limit is 122 characters)
    user_dir()          Linux: the game is the Windows build under Proton; its saves are in the Proton prefix of the Steam library
                        that has the game: steamapps/compatdata/275850/pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS
Online parts: No Man's Sky has multiplayer and online features. Tests use the main menu only (or a throwaway local save with network
play off in Options), never join other players; GameAnything never touches the save files except backup / restore.
"""
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from gameanything.native import steam
from gameanything.native.games import DeclarativeGame, NativeError, _copy

DATA_EXT = {".exml", ".mbin"}
RESOURCE_EXT = {".dds", ".wem", ".bnk", ".png"}
IGNORED_EXT = {".mxml", ".lua", ".txt", ".md", ".pak"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+ -]{0,121}$")      # the game's limit: 122 characters
DISABLE = "DISABLEMODS.TXT"


def scan(folder: Path) -> dict:
    """A mod folder -> {exml, mbin, loctable, resources, ignored, pak} (relative posix paths)."""
    folder = Path(folder); out = {k: [] for k in ("exml", "mbin", "loctable", "resources", "ignored", "pak")}
    for f in sorted(folder.rglob("*")):
        if not f.is_file(): continue
        rel = f.relative_to(folder).as_posix(); ext = f.suffix.lower()
        if ext == ".exml": out["exml"].append(rel)
        elif ext == ".mbin": out["mbin"].append(rel)
        elif rel.upper() == "LOCTABLE.MXML": out["loctable"].append(rel)
        elif ext == ".pak": out["pak"].append(rel)
        elif ext in RESOURCE_EXT: out["resources"].append(rel)
        else: out["ignored"].append(rel)
    return out


class Nms(DeclarativeGame):
    # ---- folders
    def _steamapps(self):
        gd = self.game_dir()
        if gd and gd.parent.name == "common" and gd.parent.parent.name == "steamapps": return gd.parent.parent
        return None

    def proton_user_dirs(self) -> list:
        """Linux: <library>/steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser of the library with the game, then every library."""
        libs = [self._steamapps()] if self._steamapps() else []
        for r in steam.roots(self.sys, self.home, self.env):
            libs += [lib / "steamapps" for lib in steam.libraries(r)]
        out = []
        for sa in libs:
            p = sa / "compatdata" / str(self.steam_appid) / "pfx" / "drive_c" / "users" / "steamuser"
            if p not in out: out.append(p)
        return out

    def user_dir(self):
        if self.sys == "linux":
            cands = [p / "AppData" / "Roaming" / "HelloGames" / "NMS" for p in self.proton_user_dirs()]
            return next((c for c in cands if c.is_dir()), cands[0] if cands else Path("proton-prefix-not-found"))
        return super().user_dir()

    def gamedata(self): return (self.game_dir() or Path("game-not-found")) / "GAMEDATA"
    def mod_settings(self): return (self.game_dir() or Path("game-not-found")) / "Binaries" / "SETTINGS" / "GCMODSETTINGS.MXML"

    def disable_files(self) -> list:
        g = self.gamedata()
        return [p for p in (g / DISABLE, g / "PCBANKS" / DISABLE, g / "MODS" / DISABLE) if p.is_file()]

    def info(self):
        d = super().info()
        d["mod_settings"] = str(self.mod_settings()) if self.mod_settings().is_file() else None
        d["disablemods"] = [str(p) for p in self.disable_files()]
        d["authoring_tools"] = self.authoring_tools()
        return d

    # ---- tools (optional: only to look up vanilla data while writing a mod; the game applies EXML patches itself)
    def authoring_tools(self) -> dict:
        tools = self.root / "tools" / "nms"
        def find(names, var):
            if self.env.get(var) and Path(self.env[var]).is_file(): return self.env[var]
            for n in names:
                if (tools / n).is_file(): return str(tools / n)
                if shutil.which(n): return shutil.which(n)
            return None
        return {"hgpaktool": find(["hgpaktool", "hgpaktool.exe"], "GAMEANYTHING_HGPAKTOOL"),
                "mbincompiler": find(["MBINCompiler-linux", "MBINCompiler", "MBINCompiler.exe", "mbincompiler"], "GAMEANYTHING_MBINCOMPILER")}

    def toolchain(self):
        t = self.authoring_tools(); have = [k for k, v in t.items() if v]
        return {"ok": True, "name": "none (EXML patches are text)", "setup": "",
                "detail": "nothing to compile: the game applies .EXML patches itself. To look up vanilla data while writing one: HGPAKtool "
                          "(MIT, github.com/monkeyman192/HGPAKtool, `pip install hgpaktool`) unpacks GAMEDATA/PCBANKS, MBINCompiler (LGPL-3, "
                          f"github.com/monkeyman192/MBINCompiler, the release matching the game version) turns .MBIN into .MXML; found: {', '.join(have) or 'none'}"}

    # ---- the loader switch: a legacy DISABLEMODS.TXT is moved aside while GameAnything mods are installed, never deleted
    def _keep_dir(self) -> Path: return self.root / "nms-disablemods"

    def _move_disable_aside(self) -> list:
        moved = []
        for f in self.disable_files():
            rel = f.relative_to(self.game_dir()); k = self._keep_dir() / rel
            if k.exists(): self._trash(k, "old-disablemods")
            k.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(f), str(k)); moved.append(str(rel))
        if moved:
            m = self._keep_dir() / "moved.json"; old = json.loads(m.read_text(encoding="utf-8")) if m.is_file() else []
            m.write_text(json.dumps(sorted(set(old + moved)), indent=1), encoding="utf-8")
        return moved

    def _put_disable_back(self) -> list:
        m = self._keep_dir() / "moved.json"
        if not m.is_file() or self.mods(): return []
        back = []
        for rel in json.loads(m.read_text(encoding="utf-8")):
            k = self._keep_dir() / rel; dst = self.game_dir() / rel
            if k.is_file() and not dst.exists(): _copy(k, dst); os.remove(k); back.append(rel)
        os.remove(m)
        return back

    # ---- build (nothing to compile: check and stage)
    def build(self, src, name=None) -> dict:
        src = Path(src).expanduser().resolve()
        if not src.is_dir(): raise NativeError(f"找不到 mod 文件夹：{src}")
        self.check_installable(src)
        name = name or src.name
        if not NAME_RE.match(name): raise NativeError(f"mod 文件夹名字不合适（字母数字开头，最长 122 个字符）：{name}")
        w = self.build_dir(name)
        if w.exists(): self._trash(w, "old-build")
        st = w / "mod" / name
        shutil.copytree(src, st, ignore=shutil.ignore_patterns(".git", "*.bak", "*~", "README*"))
        it = {"errors": [], "warnings": [], "notes": []}; self._lint(st, it)
        return {"staged": str(st), "files": sum(len(v) for v in scan(st).values()), "warnings": it["warnings"]}

    # ---- install
    def check_installable(self, src):
        src = Path(src)
        if not src.is_dir(): raise NativeError(f"要装的是一个 mod 文件夹（里面是 .EXML / .MBIN，保持游戏原来的文件夹结构）：{src}")
        s = scan(src)
        if s["pak"]: raise NativeError(
            f"{src.name} 里有 .pak（{', '.join(s['pak'][:3])}）：这是 PCBANKS/MODS 布局，"
            "当前适配器只支持 GAMEDATA/MODS/<ModName> 里的松散 .EXML / .MBIN"
        )
        if not (s["exml"] or s["mbin"] or s["loctable"]):
            raise NativeError(f"{src.name} 里没有 .EXML / .MBIN / LocTable.MXML：游戏不会加载任何东西")
        for rel in s["exml"] + s["loctable"]:
            try: root = ET.parse(src / rel).getroot()
            except (ET.ParseError, OSError) as e: raise NativeError(f"{rel} 不是有效的 XML：{e}")
            if root.tag != "Data" or not root.get("template"): raise NativeError(f"{rel} 的根元素要是 <Data template=\"...\">（MXML 格式）")

    def install(self, src, name=None):
        self._need_closed("安装")
        src = Path(src).expanduser()
        return super().install(src, name or src.name)

    def after_install(self, dst):
        moved = self._move_disable_aside()
        return {"enabled": True, "switch": f"moved {', '.join(moved)} to GameAnything's folder" if moved else "nothing to switch (no DISABLEMODS.TXT)"}

    def uninstall(self, name):
        self._need_closed("卸载")
        out = super().uninstall(name)
        back = self._put_disable_back()
        if back: out["switch"] = f"put back {', '.join(back)}"
        return out

    # ---- headless check
    def _lint(self, src: Path, it: dict):
        s = scan(src)
        for rel in s["ignored"]:
            if rel.lower().endswith(".mxml"): it["warnings"].append(f"{rel}：游戏只认 .EXML 补丁和 .MBIN（.MXML 只认根目录的 LocTable.MXML），这个文件不起作用")
        for rel in s["exml"]:
            if rel.upper().startswith("GC") and "/" not in rel: it["warnings"].append(f"{rel}：GLOBALS 的 EXML 补丁要放在 GLOBALS/ 子文件夹里")
        if len(src.name) > 122: it["errors"].append(f"mod 文件夹名字太长（{len(src.name)} 个字符，游戏最多 122）")
        return s

    def check_mod(self, src: Path, it: dict):
        src = Path(src)
        try: self.check_installable(src)
        except NativeError as e: it["errors"].append(str(e)); return
        s = self._lint(src, it)
        it["notes"].append(f"{src.name}：{len(s['exml'])} 个 EXML 补丁，{len(s['mbin'])} 个 MBIN，{len(s['loctable'])} 个 LocTable，{len(s['resources'])} 个资源文件")
        if s["mbin"]: it["warnings"].append("MBIN 是整个文件的替换：游戏一更新就可能坏掉，能用 EXML 补丁就用补丁")
        if self.disable_files(): it["notes"].append(f"{', '.join(str(p) for p in self.disable_files())} 在：install 会把它挪到 GameAnything 自己的文件夹（不删）")
