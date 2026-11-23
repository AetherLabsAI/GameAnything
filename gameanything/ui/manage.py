"""What lives above a single project in the browser UI (D16): the project list and switching, export / import jobs, and the backup scheduler.

`Current` forwards every attribute to the open Project, so the request handler keeps using `proj.x` and a switch only replaces what it points at
(a single-user local server). `gameanything ui` keeps one Current per project and binds each request to the tab's project (/p/<id>/, ui.Local),
so a switch in one tab never re-points another. Export, import and backup runs happen in daemon threads; the page polls their job record.
"""
import re
import secrets
import threading
import time
from pathlib import Path

from .. import backup, buildmode, games as registry, projects, transfer
from ..native import quiet, ready
from . import onboard
from .i18n import err, scrub_paths
from .upload import Inbox

SCHEDULER_TICK = 30     # seconds between "is a backup due?" checks


class Current:
    """p is None when no project exists yet (the welcome page): then root is None and everything else fails loudly."""
    def __init__(self, p): self.p = p
    def __getattr__(self, k):
        if k == "root" and self.p is None: return None
        return getattr(self.p, k)


class Manager:
    def __init__(self, cur: Current, make_project, upload_max: int):
        self.cur = cur; self.make = make_project; self.jobs = {}; self.lock = threading.Lock(); self.bk_running = {}; self.exs = None
        data = projects.data_dir(cur.root)
        self.exports = data / "exports"; self.imports = Inbox(None, upload_max, data / "imports", {"zip"})
        threading.Thread(target=self._scheduler, daemon=True).start()

    # ---- project list
    def project_list(self, lang="zh"):
        cur = str(self.cur.root) if self.cur.root else None; out = []
        for e in projects.load():
            out.append({"id": e["id"], "title": e["title"], "kind": e.get("kind") or "memory", "game": e.get("game") or "stardew", "last_opened": e.get("last_opened"),
                        "current": str(Path(e["path"]).resolve()) == cur, "exists": Path(e["path"]).is_dir()})
        out.sort(key=lambda e: e["last_opened"] or "", reverse=True); out.sort(key=lambda e: not e["current"])
        return out

    def shell_extra(self, lang="zh"):
        e = self.entry()
        mode, src = buildmode.effective(self.cur.root)
        return {"project_id": e["id"], "kind": e["kind"], "projects": self.project_list(lang), "backup": self.backup_brief(lang),
                "build_mode": mode, "build_mode_source": src, "native_launch": quiet.policy(self.cur.root),
                "native_ready": ready.summary(self.cur.root),
                "coach_seen": onboard.coach_seen(self.cur.root, e["kind"], self.viewer()), "game_info": registry.ui_info()}

    # ---- first run: the welcome page, its examples, the wizard's game check
    def examples(self) -> list:
        return onboard.examples()

    def welcome(self, lang="zh"):
        self.exs = self.examples()
        ps = [p for p in self.project_list(lang) if p["exists"]]
        return {"has_projects": bool(ps), "projects": ps, "open": self.cur.p is not None, "examples": onboard.public(self.exs),
                "kinds": list(projects.KINDS), "games": projects.GAMES, "default_game": projects.DEFAULT_GAME, "kind_stills": onboard.kind_stills(),
                "game_info": registry.ui_info()}

    def example_file(self, i: int, what: str) -> Path:
        if self.exs is None: self.exs = self.examples()
        x = self.exs[i] if 0 <= i < len(self.exs) else {}
        p = x.get("image_path") if what == "image" else x.get("video_path") if what == "video" else None
        if not p or not Path(p).is_file(): raise FileNotFoundError(f"{i}/{what}")
        return Path(p)

    multi_user = False                                          # the hub: several people on one server

    def games(self, force=False):
        return onboard.game_checks(force, hub=self.multi_user)

    def coach(self, d):
        if self.cur.p is None: raise ValueError("还没有打开的项目")
        return onboard.set_coach_seen(self.cur.root, d.get("seen", True) is not False, self.entry()["kind"], self.viewer())

    def viewer(self) -> str: return "local"                    # who is looking (the hub: the session user)

    def entry(self):
        if self.cur.root is None: raise ValueError("还没有打开的项目")
        try: return projects.find(str(self.cur.root))
        except KeyError: return projects.register(self.cur.root)

    def open(self, d):
        e = projects.find(str(d.get("id") or ""))
        if not Path(e["path"]).is_dir(): raise ValueError("找不到这个项目的文件夹")
        self.cur.p = self.make(Path(e["path"])); projects.touch(e["path"]); return {"ok": True, "id": e["id"]}

    def settings(self, d=None):
        if d is not None: d = {k: v for k, v in d.items() if k != "study"}     # study mode is set from the CLI only (study.py logs its boundaries)
        return {"ok": True, **(projects.save_settings(d) if d is not None else projects.settings())}

    def set_game(self, d):
        e = projects.set_game(str(d.get("id") or self.entry()["id"]), str(d.get("game") or ""))
        if str(Path(e["path"]).resolve()) == str(self.cur.root): self.cur.p = self.make(Path(e["path"]))
        return {"ok": True, "id": e["id"], "game": e["game"]}

    def set_mode(self, d):
        """「在哪里做」 in the project menu: config/project.yaml build_mode."""
        e = buildmode.set_mode(str(d.get("id") or self.entry()["id"]), str(d.get("mode") or ""))
        return {"ok": True, "id": e["id"], "build_mode": buildmode.mode_of(Path(e["path"]))}

    def set_launch(self, d):
        """「什么时候开游戏」 in the project menu: config/project.yaml native_launch (+ native_launch_window), native/quiet.py."""
        e = quiet.set_policy(str(d.get("id") or self.entry()["id"]), str(d.get("mode") or ""), d.get("window") or None, d.get("minutes"), d.get("drive") or None,
                             d.get("front") or None, d.get("hands") or None)
        return {"ok": True, "id": e["id"], "native_launch": quiet.policy(Path(e["path"])), "native_ready": ready.summary(Path(e["path"]))}

    def remove(self, d):
        """Move a project's folder to <data>/.trash/ (never deletes); removing the open one switches to the most recent other project."""
        e = projects.find(str(d.get("id") or "")); cur = str(Path(e["path"]).resolve()) == str(self.cur.root)
        others = [x for x in self.project_list() if x["id"] != e["id"] and x["exists"]]
        dst = projects.remove(e["id"])
        if cur and others: o = projects.find(others[0]["id"]); self.cur.p = self.make(Path(o["path"])); projects.touch(o["path"])
        elif cur: self.cur.p = None                                  # the last one: back to the welcome page
        return {"ok": True, "trash": str(dst) if dst else None, "welcome": self.cur.p is None}

    def new_owner(self):
        """A plain `gameanything ui` has no login: the project belongs to the hub user of this data folder (users.local_owner); the hub overrides."""
        from .. import users
        return users.local_owner()

    def new(self, d):
        e = projects.create(str(d.get("title") or ""), str(d.get("kind") or "memory"), lang=d.get("lang") if d.get("lang") in ("zh", "en") else "en",
                            game=str(d.get("game") or "stardew"), build_mode=d.get("mode") or None, owner=self.new_owner())
        self.cur.p = self.make(Path(e["path"])); return {"ok": True, "id": e["id"]}

    # ---- jobs (export / import)
    def _job(self, kind, fn):
        jid = secrets.token_hex(6); j = {"id": jid, "kind": kind, "state": "running", "done": 0, "total": 0, "files": 0}
        with self.lock: self.jobs[jid] = j

        def prog(done, total, nf, tf): j.update(done=done, total=total, files=nf, total_files=tf)

        def go():
            try:                                       # an import's result carries the project's "kind": it must not replace the job's (the hub checks it)
                r = fn(prog); j.update({("project_kind" if k == "kind" else k): v for k, v in r.items()}, state="done")
            except (transfer.TransferError, OSError, ValueError, KeyError) as e: j.update(state="error", error=str(e.args[0] if isinstance(e, KeyError) else e))
            except Exception as e: j.update(state="error", error=f"{type(e).__name__}: {e}")
        threading.Thread(target=go, daemon=True).start(); return j

    def job(self, jid, lang="zh"):
        j = self.jobs.get(jid)
        if not j: raise KeyError(jid)
        return {**j, **({"error": scrub_paths(err(j["error"], lang))} if j.get("error") else {})}

    def export_start(self, d):
        root = self.cur.root; e = self.entry(); name = self.export_name(e)
        run = next((j for j in self.jobs.values() if j["state"] == "running" and j["kind"] == "export"), None)
        if run: return {"ok": True, "job": run}                                  # a second click joins the running export

        def fn(prog):
            r = transfer.export_project(root, self.exports / name, progress=prog)
            return {"name": name, "bytes": r["bytes"], "files": r["files"], "url": f"/exports/{name}", "path": r["path"]}
        return {"ok": True, "job": self._job("export", fn)}

    def export_name(self, e) -> str:
        return f"{e['id']}-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    def export_file(self, name: str) -> Path:
        p = self.exports / name
        if not re.fullmatch(r"[\w.-]+\.zip", name) or not p.is_file(): raise FileNotFoundError(name)
        return p

    def import_start(self, d):
        rel = str(d.get("path") or ""); f = (self.imports.dir / rel).resolve()
        if self.imports.dir.resolve() not in f.parents or not f.is_file(): raise ValueError("找不到上传的文件")
        if any(j["state"] == "running" and j["kind"] == "import" for j in self.jobs.values()): raise ValueError("正在导入：等它完成")
        return {"ok": True, "job": self._job("import", lambda prog: transfer.import_project(f, None, None, unique=True, progress=prog))}

    # ---- backup
    def backup_brief(self, lang="zh"):
        """-> {state: off | wait | running | ok | error, at, error} for the sidebar footer."""
        root = self.cur.root; s = backup.status(root); last = s["last"] or {}
        if self.bk_running.get(str(root)): return {"state": "running"}
        if not s["enabled"]: return {"state": "off"}
        if not last: return {"state": "wait"}
        if not last.get("ok"): return {"state": "error", "at": last.get("at"), "error": err(last.get("error") or "", lang)}
        return {"state": "ok", "at": last.get("at")}

    def backup_panel(self, lang="zh"):
        root = self.cur.root; s = backup.status(root); cfg = backup.load_cfg(root)
        ch, gone = backup.changes(root, cfg) if s["configured"] else ([], [])
        return {**s, "brief": self.backup_brief(lang), "pending": len([k for k in ch if k not in backup.RIDE_ALONG]), "removed": len(gone), "token": backup.token_source(), "project_id": cfg.get("project_id")}

    def _cfg_from(self, d):
        t = d.get("target") or {}
        target = {"kind": "folder", "path": str(t.get("path") or "").strip()} if t.get("kind") == "folder" else {"kind": "hf", "repo": str(t.get("repo") or "").strip()}
        raw = [str(x).strip() for x in (d.get("raw_paths") or []) if str(x).strip()]
        return {**backup.load_cfg(self.cur.root), "target": target, "include_raw": bool(d.get("include_raw")) and bool(raw), "raw_paths": raw if d.get("include_raw") else [],
                "every_minutes": max(1, min(int(d.get("every_minutes") or 30), 1440))}

    def backup_preview(self, d):
        """What the consent dialog lists: where, what (folders, counts), what never goes."""
        cfg = self._cfg_from(d); backup.check_target(self.cur.root, cfg); p = backup.plan(self.cur.root, cfg)
        for r in cfg["raw_paths"] if cfg["include_raw"] else []:
            if not Path(r).expanduser().is_dir(): raise backup.BackupError(f"找不到原始素材文件夹：{r}")
        return {"ok": True, "where": backup.target_text(cfg["target"]), "kind": cfg["target"]["kind"], "remote": cfg["target"]["kind"] == "hf",
                "files": p["files"], "bytes": p["bytes"], "folders": p["folders"], "every_minutes": cfg["every_minutes"], "include_raw": cfg["include_raw"],
                "token": backup.token_source() if cfg["target"]["kind"] == "hf" else None}

    def backup_enable(self, d):
        if not d.get("ack"): raise ValueError("要先在对话框里同意")
        cfg = self._cfg_from(d)
        backup.enable(self.cur.root, cfg["target"], cfg["include_raw"], cfg["raw_paths"], cfg["every_minutes"], via="ui")
        return {"ok": True}

    def backup_disable(self, d):
        backup.disable(self.cur.root); return {"ok": True}

    def backup_run(self, d):
        root = self.cur.root
        if not backup.consent_ok(backup.load_cfg(root)): raise backup.BackupError("备份没有开启")
        if self.bk_running.get(str(root)): raise backup.BackupError("备份正在运行")
        threading.Thread(target=self._backup, args=(root,), daemon=True).start(); return {"ok": True}

    def _backup(self, root):
        self.bk_running[str(root)] = True
        try: backup.run(root)
        except backup.BackupError: pass
        except Exception: pass
        finally: self.bk_running[str(root)] = False

    def _scheduler(self):
        while True:
            time.sleep(SCHEDULER_TICK)
            try:
                root = self.cur.root
                if root is None: continue
                if not self.bk_running.get(str(root)) and backup.due(root): self._backup(root)
            except Exception: pass
