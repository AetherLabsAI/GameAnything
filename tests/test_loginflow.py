"""`gameanything lab login steam|microsoft|ea` (loginflow.py): the state machine with a fake sandbox and a fake clock. No real login, no
docker, no Steam: the fake answers the same commands the real sandbox would (ga-steam / ga-mc and the watchdog's snapshot exec)."""
import json

import pytest

from gameanything import hiccups, loginflow, watchdog

STEAM = "/home/player/.steam/debian-installation"
P_STEAM = {"pid": 501, "state": "S", "exe": f"{STEAM}/ubuntu12_32/steam", "argv": ["steam"]}
P_HELPER = {"pid": 640, "state": "S", "exe": f"{STEAM}/ubuntu12_64/steamwebhelper", "argv": ["steamwebhelper"]}
LOGIN_LOG = "[2026-10-29 11:36:20] [ WaitingForCredentials ] Showing login window\n"
ON = "[2026-10-29 11:42:38] [Logged On, 4, 27] [U:1:1] RecvMsgClientLogOnResponse() : processing complete\n"

S_INSTALLER = {"windows": [{"title": "Steam installer", "w": 520, "h": 260}], "procs": [{"pid": 4, "state": "S", "exe": "/usr/bin/zenity", "argv": []}]}
S_DOWNLOAD = {"windows": [{"title": "Steam", "w": 400, "h": 129}], "procs": [P_STEAM],
              "logs": {"bootstrap": "[x] Downloading update (252,463 of 504,927 KB)..."}}
S_EXTRACT = {"windows": [{"title": "Steam", "w": 400, "h": 129}], "procs": [P_STEAM], "logs": {"bootstrap": "[x] Extracting package..."}}
S_LOGIN = {"windows": [{"title": "steamwebhelper", "w": 10, "h": 10}], "procs": [P_STEAM, P_HELPER], "logs": {"steamui_login": LOGIN_LOG}}
S_ON = {"windows": [], "procs": [P_STEAM, P_HELPER], "logs": {"connection": ON}}
S_HELPER = {"windows": [], "procs": [P_STEAM, P_HELPER], "logs": {}}


class Clock:
    def __init__(self): self.t = 1_800_000_000.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class FakeBox:
    """snaps: what the snapshot exec sees, one per call (the last repeats). answers: command -> output (str or callable)."""
    def __init__(self, snaps, answers=None, tools=("ga-steam",), up="up", clock=None):
        self.snaps, self.i, self.answers, self.tools, self.up, self.clock = list(snaps), 0, dict(answers or {}), set(tools), up, clock
        self.sh_calls, self.py_args = [], []

    def state(self): return self.up

    def py(self, source, env, timeout=90):
        a = json.loads(env["GA_WD"]); self.py_args.append(a)
        s = dict(self.snaps[min(self.i, len(self.snaps) - 1)]); self.i += 1
        if self.clock: s["at"] = int(self.clock())
        return 0, json.dumps(s)

    def sh(self, script, timeout=90):
        self.sh_calls.append(script)
        m = script.split()
        if script.startswith("command -v"): return 0, "yes" if m[2] in self.tools else "no"
        if script.startswith("xdpyinfo"): return 0, "x=1"
        for k, v in self.answers.items():
            if script.startswith(k): return 0, v(self) if callable(v) else v
        return 0, ""

    def read(self, path): return b""


def flow(box, store="steam", lang="en", clock=None, **kw):
    clock = clock or Clock(); box.clock = clock
    lines = []
    fl = loginflow.Flow(box, store, lang=lang, say=lines.append, clock=clock, sleep=clock.sleep, viewer="http://localhost:6081/vnc.html",
                        box_name="ga-stardew-steam", **kw)
    return fl, lines


def status(**kw):
    d = {"running": False, "logged_on_since_start": None, "login_window": False, "updating": False, "client_installed": False,
         "login_cache": False}
    d.update(kw); return json.dumps(d)


# ---------------------------------------------------------------- Steam
def test_first_start_installer_update_login_window_signed_in_and_owned():
    box = FakeBox([S_INSTALLER, S_INSTALLER, S_DOWNLOAD, S_DOWNLOAD, S_EXTRACT, S_LOGIN, S_LOGIN, S_ON],
                  {"ga-steam status --json": status(), "ga-steam owns 413150 --json": '{"owned": true, "how": "installed"}'})
    fl, lines = flow(box, game="stardew", title="Stardew Valley", app=413150)
    r = loginflow.steam(fl)
    assert r["state"] == "ok" and r["code"] == 0 and r["owned"] is True
    text = "\n".join(lines)
    order = [text.index(s) for s in ("This is the first start", "clicked Install", "50% downloaded", "extracting and installing",
                                     "sign-in window is up", "Before you sign in", "Waiting for you to sign in", "Signed in to Steam",
                                     "Stardew Valley is in your account")]
    assert order == sorted(order)
    assert "http://localhost:6081/vnc.html" in text
    assert watchdog.ACTIONS["click_installer_install"] in box.sh_calls and "ga-steam start" in box.sh_calls
    assert all(not a.get("shot") for a in box.py_args)                 # no screenshot during the whole login
    assert box.py_args[0]["probe_ns"] is True                           # the 1-second namespace probe ran first


def test_progress_is_in_the_users_language_and_json_events_have_both():
    events = []
    box = FakeBox([S_LOGIN, S_LOGIN, S_ON], {"ga-steam status --json": status(running=True, client_installed=True)})
    fl, lines = flow(box, lang="zh", emit=events.append)
    r = loginflow.steam(fl)
    assert r["code"] == 0
    assert any("在等你登录" in m for m in lines) and any("已登录 Steam" in m for m in lines)
    assert all(e["zh"] and e["en"] for e in events)
    assert {"progress", "known"} <= {e["kind"] for e in events}


def test_second_start_with_a_saved_login_says_auto_logon_and_never_asks_to_type():
    box = FakeBox([S_HELPER, S_HELPER, S_ON], {"ga-steam status --json": status(client_installed=True, login_cache=True)})
    fl, lines = flow(box)
    r = loginflow.steam(fl)
    text = "\n".join(lines)
    assert r["code"] == 0 and "saved login" in text and "Before you sign in" not in text and "already installed" in text


def test_already_signed_in_does_nothing():
    box = FakeBox([S_ON], {"ga-steam status --json": status(running=True, logged_on_since_start="2026-10-29 11:42:38", client_installed=True)})
    fl, lines = flow(box)
    assert loginflow.steam(fl)["code"] == 0
    assert "ga-steam start" not in box.sh_calls and any("Already signed in" in m for m in lines)


def test_mount_namespace_denied_stops_and_names_the_missing_options():
    box = FakeBox([{"ns_mount_ok": False}], {"ga-steam status --json": status()})
    fl, lines = flow(box)
    r = loginflow.steam(fl)
    assert r["state"] == "needs_user" and r["code"] == 4 and "seccomp-steam.json" in lines[-1] and "--shm-size 1g" in lines[-1]
    assert "ga-steam start" not in box.sh_calls


@pytest.mark.parametrize("up,tools,state", [("not running", ("ga-steam",), "down"), ("up", (), "unsupported")])
def test_sandbox_down_or_without_steam(up, tools, state):
    box = FakeBox([{}], tools=tools, up=up)
    fl, lines = flow(box, game="stardew")
    r = loginflow.steam(fl)
    assert r["state"] == state and r["code"] == loginflow.CODES[state]
    if state == "unsupported": assert "--image stardew`" in lines[-1] and "--steam" not in lines[-1]


def test_not_owned_is_said_plainly():
    box = FakeBox([S_ON], {"ga-steam status --json": status(running=True, logged_on_since_start="x"),
                           "ga-steam owns 646570 --json": '{"owned": false, "how": "steam: no licence"}'})
    fl, lines = flow(box, title="Slay the Spire", app=646570)
    r = loginflow.steam(fl)
    assert r["state"] == "not_owned" and r["code"] == 7 and "Slay the Spire is not in the account" in lines[-1]


def test_unknown_ownership_says_how_the_install_step_will_tell():
    box = FakeBox([S_ON], {"ga-steam status --json": status(running=True, logged_on_since_start="x"),
                           "ga-steam owns 413150 --json": '{"owned": null}'})
    fl, lines = flow(box, title="Stardew Valley", app=413150)
    r = loginflow.steam(fl)
    assert r["code"] == 0 and r["owned"] is None and "store page with a price" in lines[-1]


def test_timeout_never_silent_for_two_minutes():
    clock = Clock()
    box = FakeBox([S_LOGIN], {"ga-steam status --json": status(running=True, client_installed=True)})
    said = []
    fl, _ = flow(box, clock=clock, timeout=900)
    fl.say_fn = lambda m: said.append((clock.t, m))
    r = loginflow.steam(fl)
    assert r["state"] == "timeout" and r["code"] == 8
    times = [t for t, _ in said]
    assert max(b - a for a, b in zip(times, times[1:])) <= 120


def test_install_with_a_publisher_eula_stops_and_never_clicks():
    no_manifest = {"windows": [], "procs": [P_STEAM, P_HELPER], "logs": {"connection": ON}, "manifests": {"255710": None}}
    box = FakeBox([no_manifest], {"ga-steam status --json": status(running=True, logged_on_since_start="x"),
                                  "ga-steam owns 255710 --json": '{"owned": null}'})
    fl, lines = flow(box, title="Cities: Skylines", app=255710, install=True, lang="zh")
    r = loginflow.steam(fl)
    assert r["state"] == "needs_user" and r["why"] == "steam_publisher_eula"
    assert any("提前说一下" in m and "Paradox" in m for m in lines)          # told before the install
    assert "不会替你点" in lines[-1] and "legal.paradoxplaza.com/eula" in lines[-1]
    assert [c for c in box.sh_calls if c.startswith("ga-steam install")] == ["ga-steam install 255710"]
    assert not [c for c in box.sh_calls if "xdotool" in c or "Accept" in c]


def test_install_progress_then_installed():
    def man(flags, dl):
        return {"windows": [], "procs": [P_STEAM], "logs": {"connection": ON},
                "manifests": {"413150": f'"AppState"\n{{\n"StateFlags" "{flags}"\n"installdir" "Stardew Valley"\n'
                                        f'"BytesToDownload" "700000000"\n"BytesDownloaded" "{dl}"\n}}\n'}}
    box = FakeBox([man(2, 0), man(1026, 0), man(1026, 350000000), man(1026, 700000000), man(4, 700000000)],
                  {"ga-steam status --json": status(running=True, logged_on_since_start="x"), "ga-steam owns 413150 --json": '{"owned": null}'})
    fl, lines = flow(box, title="Stardew Valley", app=413150, install=True)
    r = loginflow.steam(fl)
    assert r["code"] == 0 and r["installed"] and any("Downloading Stardew Valley: 50%" in m for m in lines) and "installed" in lines[-1]


# ---------------------------------------------------------------- Microsoft
def mc_snap(code=None, procs=1, expires=4102444800):
    p = [{"pid": 70 + i, "state": "S", "start": i, "exe": "/opt/gameanything/venv/bin/python3",
          "argv": ["/opt/gameanything/venv/bin/python3", "/usr/local/bin/ga-mc", "account", "login"]} for i in range(procs)]
    return {"procs": p, "jsons": {"mc_login": {"url": "https://www.microsoft.com/link", "code": code, "expires_at": expires} if code else None}}


def test_microsoft_device_code_renewed_then_signed_in_and_owned():
    st = iter(['{"signed_in": false, "owns_java": false}', '{"signed_in": true, "owns_java": true, "items": ["game_minecraft"]}'])
    box = FakeBox([mc_snap(procs=0), mc_snap("AAAA1111"), mc_snap("AAAA1111"), mc_snap("BBBB2222"), mc_snap(procs=0)],
                  {"ga-mc account status": lambda b: next(st)}, tools=("ga-mc",))
    fl, lines = flow(box, store="microsoft")
    r = loginflow.microsoft(fl)
    assert r["code"] == 0 and r["owned"] is True
    text = "\n".join(lines)
    assert "AAAA1111" in text and "New code: BBBB2222" in text and "microsoft.com/link" in text and "Nothing is typed into the sandbox" in text
    assert sum(c.startswith("mkdir -p /sandbox/logs") for c in box.sh_calls) == 1


def test_microsoft_saved_sign_in_is_rechecked_without_a_code():
    box = FakeBox([mc_snap(procs=0)], {"ga-mc account status --recheck": '{"signed_in": true, "owns_java": true}',
                                       "ga-mc account status": '{"signed_in": true, "owns_java": true}'}, tools=("ga-mc",))
    fl, lines = flow(box, store="microsoft")
    r = loginflow.microsoft(fl)
    assert r["code"] == 0 and not [c for c in box.sh_calls if "account login" in c] and "Already signed in" in "\n".join(lines)


def test_microsoft_reuses_a_waiting_sign_in_instead_of_a_second_code():
    st = iter(['{"signed_in": false}', '{"signed_in": true, "owns_java": true}'])
    box = FakeBox([mc_snap("CCCC3333"), mc_snap("CCCC3333"), mc_snap(procs=0)], {"ga-mc account status": lambda b: next(st)}, tools=("ga-mc",))
    fl, lines = flow(box, store="microsoft")
    assert loginflow.microsoft(fl)["code"] == 0
    assert not [c for c in box.sh_calls if "account login" in c] and "already waiting" in "\n".join(lines)


def test_microsoft_not_owned():
    st = iter(['{"signed_in": false}', '{"signed_in": true, "owns_java": false, "items": []}'])
    box = FakeBox([mc_snap(procs=0), mc_snap("DDDD4444"), mc_snap(procs=0)], {"ga-mc account status": lambda b: next(st)}, tools=("ga-mc",))
    fl, lines = flow(box, store="microsoft", lang="zh")
    r = loginflow.microsoft(fl)
    assert r["state"] == "not_owned" and r["code"] == 7 and "没有 Minecraft: Java 版" in "\n".join(lines)


# ---------------------------------------------------------------- EA, the command, the rules
EA_APP = [{"pid": 40, "state": "S", "exe": "/w/wine64-preloader", "argv": ["C:\\Program Files\\Electronic Arts\\EA Desktop\\EADesktop.exe"]}]
E_INSTALLER = {"windows": [{"title": "EA app installer", "w": 480, "h": 450}], "procs": [], "logs": {"ea_installer": "i199: Detect complete"}}
E_INSTALLING = {"windows": [{"title": "EA app installer", "w": 480, "h": 450}], "procs": [], "logs": {"ea_installer": "Plan begin\nApply begin"}}
E_LOGIN = {"windows": [{"title": "EA", "w": 520, "h": 648}], "procs": EA_APP, "greps": {"ea_fsm": ["2026-10-29T19:17:34", "awaitingAuthentication"]}}
E_ON = {"windows": [{"title": "EA", "w": 1024, "h": 576}], "procs": EA_APP, "greps": {"ea_fsm": ["2099-01-01T00:00:00", "authenticated"]}}


def ea_status(**kw):
    d = {"fsm": None, "login_window": False, "signed_in": False, "installer_running": False, "app_installed": False, "app_running": False}
    d.update(kw); return json.dumps(d)


def test_ea_first_time_setup_agreement_stops_and_is_never_clicked():
    box = FakeBox([E_INSTALLER], {"ga-ea status --json": ea_status()}, tools=("ga-ea",))
    fl, lines = flow(box, store="ea", lang="zh", game="sims4", title="The Sims 4")
    r = loginflow.ea(fl)
    assert r["state"] == "needs_user" and r["code"] == 4 and r["why"] == "ea_user_agreement"
    assert "ga-ea setup" in box.sh_calls and "ga-ea install-app" in box.sh_calls
    assert not any("xdotool" in c for c in box.sh_calls)                    # LET'S GO is the user's click
    assert any("tos.ea.com" in m for m in lines)


def test_ea_after_lets_go_sign_in_then_owned_on_ea():
    box = FakeBox([E_INSTALLING, E_LOGIN, E_LOGIN, E_ON], {"ga-ea status --json": ea_status(installer_running=True),
                                                           "ga-ea owns --json": '{"owned": true, "source": null, "installed": false}'},
                  tools=("ga-ea",))
    fl, lines = flow(box, store="ea", game="sims4", title="The Sims 4")
    r = loginflow.ea(fl)
    assert r["code"] == 0 and r["owned"] is True
    text = "\n".join(lines)
    order = [text.index(x) for x in ("EA's sign-in window is up", "Waiting for you to sign in", "Signed in to EA", "The Sims 4 is in your account")]
    assert order == sorted(order) and "ga-ea setup" not in box.sh_calls
    assert all(not a.get("shot") for a in box.py_args)


def test_ea_saved_login_and_a_steam_linked_game_stops_with_its_own_code_and_the_next_command(capsys):
    box = FakeBox([E_ON], {"ga-ea status --json": ea_status(app_installed=True, app_running=True, signed_in=True, fsm="authenticated"),
                           "ga-ea owns --json": '{"owned": true, "source": "STEAM", "managed_by": "STEAM", "other_store": true, "installed": false}'}, tools=("ga-ea",))
    events = []
    fl, lines = flow(box, store="ea", lang="zh", game="sims4", title="The Sims 4", install=True, emit=events.append, project="wedding")
    r = loginflow.ea(fl)
    assert r["state"] == "other_store" and r["code"] == 9 and r["why"] == "ea_steam_owned"
    assert r["external_source"] == "STEAM" and r["external_store"] == "Steam" and r["store"] == "ea"
    assert r["next_command"] == "gameanything lab login steam --project wedding --app 1222670 --install"
    assert any("已经登录着 EA" in m for m in lines)
    assert "你的模拟人生 4 是在 Steam 上拿到的，EA App 会把下载交给 Steam" in lines[-1] and "用 Wine 跑" in lines[-1]
    assert r["zh"] and "came from Steam" in r["en"] and r["next_command"] in r["en"]
    assert events[-1]["external_source"] == "STEAM"


def test_ea_game_from_another_store_is_named_and_has_no_made_up_next_command():
    box = FakeBox([E_ON], {"ga-ea status --json": ea_status(app_installed=True, app_running=True, signed_in=True),
                           "ga-ea owns --json": '{"owned": true, "source": "EPIC", "managed_by": "EPIC", "other_store": true, "installed": false}'}, tools=("ga-ea",))
    fl, lines = flow(box, store="ea", game="sims4", title="The Sims 4")
    r = loginflow.ea(fl)
    assert r["code"] == 9 and r["external_store"] == "Epic Games" and r["next_command"] is None and "came from Epic Games" in lines[-1]


def test_ea_a_linked_steam_account_alone_does_not_stop_the_ea_download():
    box = FakeBox([E_ON], {"ga-ea status --json": ea_status(app_installed=True, app_running=True, signed_in=True),
                           "ga-ea owns --json": '{"owned": true, "source": "STEAM", "managed_by": "EA", "other_store": false, "installed": false}'},
                  tools=("ga-ea",))
    fl, lines = flow(box, store="ea", game="sims4", title="The Sims 4")
    r = loginflow.ea(fl)
    assert r["code"] == 0 and r["owned"] is True and not any("came from Steam" in m for m in lines)


def test_ea_restart_waits_for_a_fresh_sign_in_line():
    box = FakeBox([E_ON], {"ga-ea status --json": ea_status(app_installed=True)}, tools=("ga-ea",))
    fl, _ = flow(box, store="ea", game="sims4", title="The Sims 4", timeout=60)
    loginflow.ea(fl)
    assert "ga-ea start" in box.sh_calls


def test_ea_without_ga_ea_or_status_only():
    box = FakeBox([E_ON], tools=())
    fl, _ = flow(box, store="ea")
    assert loginflow.ea(fl)["state"] == "unsupported"
    box = FakeBox([E_ON], {"ga-ea status --json": ea_status(app_running=True, signed_in=True)}, tools=("ga-ea",))
    fl, _ = flow(box, store="ea")
    r = loginflow.ea(fl, status_only=True)
    assert r["status"] == "signed_in" and box.sh_calls[-1] == "ga-ea status --json"


def test_a_resident_may_not_start_a_login(monkeypatch, capsys):
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "x"); monkeypatch.delenv("GAMEANYTHING_ROLE", raising=False)
    assert loginflow.main(["steam", "--container", "c"]) == 3


def test_consent_is_recorded_only_with_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loginflow, "consent_file", lambda root=None: tmp_path / "consents.json")
    assert loginflow.consent_main(["--app", "255710"]) == 2
    assert loginflow.consent_main(["--app", "413150", "--yes"]) == 2          # no known agreement for Stardew
    assert loginflow.consent_main(["--app", "289070", "--yes", "--note", "chat 10-29"]) == 0
    assert json.loads((tmp_path / "consents.json").read_text(encoding="utf-8"))["289070"]["publisher"] == "Take-Two Interactive"
    assert loginflow.consent_main(["--app", "ea_ts4_terms", "--yes", "--click-for-me"]) == 2          # needs the user's words
    assert loginflow.consent_main(["--app", "ea_ts4_terms", "--yes", "--click-for-me", "--words", "同意，帮我点"]) == 0
    c = json.loads((tmp_path / "consents.json").read_text(encoding="utf-8"))["ea_ts4_terms"]
    assert c["click_for_me"] is True and c["words"] == "同意，帮我点" and c["at_ts"] > 0


def test_every_message_has_both_languages():
    for k, v in loginflow.MSG.items(): assert v["zh"].strip() and v["en"].strip(), k


def test_nothing_secret_is_ever_in_an_event():
    box = FakeBox([S_LOGIN, S_ON], {"ga-steam status --json": status(running=True, client_installed=True)})
    events = []
    fl, _ = flow(box, emit=events.append)
    loginflow.steam(fl)
    blob = json.dumps(events)
    assert "[U:1:1]" not in blob and "password" not in blob.lower().replace("your account and password yourself", "")


def test_consent_for_a_lab_lease_project_goes_to_the_users_file(tmp_path, monkeypatch, capsys):
    # `--project steam-dl` is a lab-lease project name, not a GameAnything project: record it (tagged) instead of failing (10-29)
    monkeypatch.setattr(loginflow, "consent_file", lambda root=None: (tmp_path / "proj.json") if root else (tmp_path / "user.json"))
    from gameanything import projects
    monkeypatch.setattr(projects, "resolve", lambda ref: (_ for _ in ()).throw(SystemExit("no such project")))
    assert loginflow.consent_main(["--app", "255710", "--project", "steam-dl", "--yes"]) == 0
    rec = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))["255710"]
    assert rec["project"] == "steam-dl" and rec["publisher"] == "Paradox Interactive"
    assert not (tmp_path / "proj.json").exists()


def test_lab_dispatches_login_and_consent(monkeypatch):
    from gameanything import lab
    seen = []
    monkeypatch.setattr(loginflow, "main", lambda argv: seen.append(("login", argv)) or 0)
    monkeypatch.setattr(loginflow, "consent_main", lambda argv: seen.append(("consent", argv)) or 0)
    lab.main(["login", "steam", "--status"]); lab.main(["consent", "--app", "1"])
    assert seen == [("login", ["steam", "--status"]), ("consent", ["--app", "1"])]


def test_hiccups_table_is_what_the_flow_uses():
    assert hiccups.entry("steam_login_window")["kind"] == "tell"
    assert loginflow.MC_LOGIN_START.count("ga-mc account login") == 1


def test_an_indented_status_with_installed_apps_is_read_whole():
    """2026-10-29, plain Docker: `ga-steam status --json` is indented; read line by line, the app list's last item ("  1070560") was the
    'JSON' (a crash), and before that a None item made an empty status (a false "first start" and a second `ga-steam start`)."""
    d = json.loads(status(running=True, logged_on_since_start="2026-10-29 22:00:19", client_installed=True, login_cache=True))
    for tail in ([413150, 1070560], [413150, None]):
        box = FakeBox([S_ON], {"ga-steam status --json": json.dumps({**d, "apps": tail}, indent=1)})
        fl, lines = flow(box)
        assert loginflow.steam(fl)["code"] == 0
        assert "ga-steam start" not in box.sh_calls and any("Already signed in" in m for m in lines)
