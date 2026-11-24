"""The setup watchdog (watchdog.py + the KNOWN table hiccups.py): its matcher against snapshots rebuilt from the 2026-10-29 evidence,
the never-auto-accept rule for licences, stalls, heartbeats, screenshots (never of a sign-in window) and redaction.
No sandbox, no docker: a fake box answers the snapshot exec."""
import json
from pathlib import Path

import pytest

from gameanything import hiccups, watchdog

FIX = Path(__file__).parent / "fixtures" / "watchdog"
CASES = {k: v for k, v in json.loads((FIX / "snapshots.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
NOW = 1_800_000_000


def load(snap):
    """'@file' -> the fixture text (logs and manifests)."""
    def res(v):
        if isinstance(v, str) and v.startswith("@"): return (FIX / v[1:]).read_text(encoding="utf-8")
        if isinstance(v, dict): return {k: res(x) for k, x in v.items()}
        if isinstance(v, list): return [res(x) for x in v]
        return v
    return res(snap)


def ctx_of(case):
    c = dict(case.get("ctx") or {})
    ago = c.pop("requested_ago", None)
    if ago is not None: c["install_requested_at"] = NOW - ago
    return {**c, "now": NOW}


class Box:
    """A sandbox for the watchdog: py() returns the next snapshot (the last one repeats), sh() records actions."""
    def __init__(self, snaps, shot_bytes=b"PNG"):
        self.snaps, self.i, self.sh_calls, self.py_args, self.shot_bytes = list(snaps), 0, [], [], shot_bytes

    def py(self, source, env, timeout=90):
        assert source == watchdog.SNAPSHOT_PY
        arg = json.loads(env["GA_WD"]); self.py_args.append(arg)
        s = dict(self.snaps[min(self.i, len(self.snaps) - 1)])
        if not arg.get("shot"): self.i += 1
        else: s["screenshot"] = arg["shot"]
        return 0, json.dumps(s)

    def sh(self, script, timeout=90): self.sh_calls.append(script); return 0, ""

    def read(self, path): return self.shot_bytes


class Clock:
    def __init__(self, t=NOW): self.t = t
    def __call__(self): return self.t


# ---------------------------------------------------------------- the table
def test_the_table_is_valid_and_covers_every_hiccup_we_were_asked_for():
    assert hiccups.validate() == []
    ids = {e["id"] for e in hiccups.KNOWN}
    for need in ("steam_installer_dialog", "steam_updater_window", "steam_install_dialog", "steam_publisher_eula", "steam_download_stalled",
                 "steam_ghost_running", "steam_network_disk", "steam_shader_precache_on", "mc_world_not_found", "ms_code_expired"):
        assert need in ids
    assert {255710, 289070, 1281930} <= set(hiccups.EULAS)          # Cities (Paradox UA), Civ VI (Take-Two), tModLoader
    assert len(hiccups.KNOWN) >= 20


def test_every_fixture_entry_is_covered_and_every_case_names_a_real_entry():
    ids = {e["id"] for e in hiccups.KNOWN}
    for name, c in CASES.items():
        assert c["expect"] is None or c["expect"] in ids, name


@pytest.mark.parametrize("name", sorted(CASES))
def test_matcher_on_recorded_snapshots(name):
    c = CASES[name]
    f = watchdog.facts(load(c["snapshot"]), ctx_of(c))
    hits = watchdog.match(f, c["flow"], c["phase"], c.get("stalled_s", 0))
    real = [e["id"] for e in hits if e["kind"] != "ignore"]
    if c["expect"] is None: assert real == [], real
    else: assert real and real[0] == c["expect"], real
    for other in c.get("also", []): assert other in real
    for no in c.get("not", []): assert no not in real
    for ig in c.get("ignored", []): assert ig in [e["id"] for e in hits if e["kind"] == "ignore"]


def test_stall_entries_wait_for_their_stall_time():
    c = CASES["steam_download_stalled_0bps"]
    f = watchdog.facts(load(c["snapshot"]), ctx_of(c))
    assert "steam_download_stalled" not in [e["id"] for e in watchdog.match(f, "steam", "install", 60)]
    assert f["rate_zero_minutes"] >= 5 and f["app_pct"] == 60


def test_the_updater_window_called_steam_is_not_the_login_window_and_the_login_window_is_found_without_xdotool():
    up = watchdog.facts(load(CASES["steam_updater_window_is_not_login"]["snapshot"]))
    assert up["updater_window"] and not up["login_window"]
    lw = watchdog.facts(load(CASES["steam_login_window_xdotool_blind"]["snapshot"]))
    assert lw["login_window"] and lw["login_state"] == "WaitingForCredentials" and not lw["logged_on"]


def test_process_patterns_never_match_a_shell_that_only_mentions_them():
    f = watchdog.facts(load(CASES["ms_two_logins"]["snapshot"]))
    assert f["mc_login_procs"] == 2 and f["mc_older_login_pids"] == "77"      # the sh -c '... ga-mc account login ...' is not counted
    lw = watchdog.facts(load(CASES["steam_login_window_xdotool_blind"]["snapshot"]))
    assert lw["webhelper"]                                                      # from /proc/<pid>/exe, not from argv text


# ---------------------------------------------------------------- the watchdog loop
def dog(snaps, flow="steam", phase="install", ctx=None, clock=None, tmp=None, lang="en", consent=None, **kw):
    lines = []
    box = Box([load(s) for s in snaps])
    w = watchdog.Watchdog(box, flow, phase, lang=lang, say=lines.append, ctx=ctx or {}, clock=clock or Clock(), evidence=tmp,
                          consent=consent, **kw)
    return w, box, lines


def test_a_publisher_eula_is_never_accepted_it_stops_and_asks_with_the_publisher_and_url():
    c = CASES["steam_eula_cities"]
    w, box, lines = dog([c["snapshot"]], ctx={"app": 255710, "install_requested_at": NOW - 40}, lang="zh")
    r = w.tick()
    assert r["stop"] and r["stop"]["id"] == "steam_publisher_eula" and r["stop"]["license"]
    assert "Paradox" in lines[-1] and "legal.paradoxplaza.com/eula" in lines[-1] and "不会替你点" in lines[-1]
    assert "take2games.com/eula" in watchdog.say_of(hiccups.entry("steam_publisher_eula"), "en",
                                                    watchdog.facts({}, {"app": 289070}))["en"]
    assert box.sh_calls == []                                     # nothing was clicked, typed or run


def test_with_recorded_consent_the_user_still_clicks_accept_and_the_watchdog_only_waits(tmp_path):
    cf = tmp_path / "consents.json"
    watchdog.record_consent(cf, 255710, note="she said yes in chat")
    rec = watchdog.consents(cf)["255710"]
    assert rec["publisher"] == "Paradox Interactive" and rec["url"].endswith("/eula")
    clock = Clock()
    w, box, lines = dog([CASES["steam_eula_cities"]["snapshot"]], ctx={"app": 255710, "install_requested_at": NOW - 40}, clock=clock,
                        consent=watchdog.consents(cf))
    for _ in range(5):
        r = w.tick(); clock.t += 30
        assert r["stop"] is None
    assert box.sh_calls == []
    assert any("click Accept yourself" in m for m in lines)


def test_a_licence_entry_with_an_automatic_action_is_rejected_by_the_table_check_and_at_run_time():
    bad = [dict(hiccups.entry("steam_publisher_eula"), kind="auto", action="steam_restart")]
    assert any("never be accepted automatically" in p for p in hiccups.validate(bad))
    w, box, _ = dog([{}])
    with pytest.raises(RuntimeError): w._act(bad[0], "steam_restart", {"zh": "", "en": ""}, {})
    assert box.sh_calls == []


def test_the_installer_dialog_is_clicked_once_with_the_exact_script():
    w, box, lines = dog([CASES["steam_installer_dialog"]["snapshot"]], phase="start")
    for _ in range(3): w.tick()
    assert box.sh_calls == [watchdog.ACTIONS["click_installer_install"]]
    assert "Return is Cancel" not in watchdog.ACTIONS["click_installer_install"] and "key Return" not in watchdog.ACTIONS["click_installer_install"]
    assert "clicked Install" in lines[0]


def test_a_stalled_download_escalates_from_pause_resume_to_a_steam_restart():
    clock = Clock()
    c = CASES["steam_download_stalled_0bps"]
    w, box, lines = dog([c["snapshot"]], ctx={"app": 105600, "install_requested_at": NOW - 1200}, clock=clock)
    w.tick()                                                     # the state is new: no stall yet
    clock.t += 310; w.tick()
    assert box.sh_calls == ["ga-steam open downloads"]
    clock.t += 610; w.tick()
    assert box.sh_calls[-1] == "ga-steam stop; ga-steam start"
    assert any("restarted Steam" in m for m in lines)


def test_an_unknown_stall_is_reported_with_a_screenshot_and_a_redacted_snapshot(tmp_path):
    clock = Clock()
    snap = dict(load(CASES["unknown_stall"]["snapshot"]), logs={"steam_out": "AccountName \"wenyi\" mail me at someone@example.com"})
    w, box, lines = dog([snap], phase="login", clock=clock, tmp=tmp_path)
    w.tick(); clock.t += 30; r = w.tick()
    assert r["screenshot"] is None and not [e for e in w.events if e["kind"] == "unknown"]
    clock.t += 35; r = w.tick()
    unk = [e for e in w.events if e["kind"] == "unknown"]
    assert len(unk) == 1 and r["screenshot"] and Path(r["screenshot"]).read_bytes() == b"PNG"
    assert r["screenshot"] in unk[0]["en"] and "Steam 1024x768" in unk[0]["en"] and unk[0]["zh"]
    saved = next(tmp_path.glob("stall-*.json")).read_text(encoding="utf-8")
    assert "someone@example.com" not in saved and "[email]" in saved
    clock.t += 30; w.tick()
    assert len([e for e in w.events if e["kind"] == "unknown"]) == 1      # once per stalled state


def test_no_screenshot_is_ever_taken_while_the_sign_in_window_is_open(tmp_path):
    clock = Clock()
    w, box, lines = dog([CASES["steam_login_window_xdotool_blind"]["snapshot"]], phase="login", clock=clock, tmp=tmp_path,
                        ctx={"viewer": "http://localhost:6080/vnc.html"})
    for _ in range(6): w.tick(); clock.t += 30
    assert all(not a.get("shot") for a in box.py_args)
    assert not list(tmp_path.glob("*.png")) and list(tmp_path.glob("stall-*.json"))
    assert any("http://localhost:6080/vnc.html" in m and "Remember me" in m for m in lines)
    assert not [e for e in w.events if e["kind"] == "unknown"]           # waiting for her is a known state, not an unknown stall


def test_never_silent_for_more_than_two_minutes():
    clock = Clock()
    w, box, lines = dog([CASES["steam_login_window_xdotool_blind"]["snapshot"]], phase="login", clock=clock, lang="zh")
    said = []
    w.say_fn = lambda m: said.append((clock.t, m))
    for _ in range(80): w.tick(); clock.t += 5
    times = [NOW] + [t for t, _ in said]
    assert max(b - a for a, b in zip(times, times[1:])) <= 120
    hb = [e for e in w.events if e["kind"] == "heartbeat"]
    assert hb and "还在等你登录" in hb[0]["zh"] and "Steam Guard" in hb[0]["en"]


def test_once_entries_are_said_once_and_progress_words_are_filled_in():
    w, box, lines = dog([CASES["steam_commit_on_network_disk"]["snapshot"]], ctx={"app": 105600, "install_requested_at": NOW - 1500})
    for _ in range(4): w.tick()
    assert sum("network disk (fuse.juicefs)" in m for m in lines) == 1
    f = watchdog.facts(load(CASES["steam_client_downloading"]["snapshot"]))
    assert f["bootstrap_pct"] == 50
    words = watchdog.say_of(hiccups.entry("steam_client_downloading"), "zh", f)
    assert "50%" in words["zh"] and "5–20 分钟" in words["zh"] and "50%" in words["en"]


def test_every_entry_has_both_languages_and_no_unfilled_fields_for_its_own_facts():
    for e in hiccups.KNOWN:
        for k in ("zh", "en"):
            assert e["say"][k].strip()
            assert "{" not in watchdog.fmt(e["say"][k], {}) or False
    for k in ("zh", "en"):
        assert hiccups.UNKNOWN_SAY[k] and hiccups.HEARTBEAT_SAY[k] and hiccups.SHOT_PRIVATE[k]
    for p in hiccups.PHASES.values(): assert p["zh"] and p["en"] and p["normal_zh"] and p["normal_en"]


def test_redact_removes_tokens_ids_and_emails():
    t = watchdog.redact('{"refresh_token": "M.C540_BAY.0.U.-CrAZYtokenvalue1234567890abcdef", "access_token": "EwBwA8l6BAAUxyz"} '
                        '"AccountName"\t\t"wenyi_real" [U:1:12345678] 76561198000000000 me@ucsd.edu eyJhbGciOi.eyJzdWIiOi.sig123')
    for s in ("CrAZYtoken", "EwBwA8l6", "wenyi_real", "12345678", "76561198000000000", "me@ucsd.edu", "eyJhbGciOi"):
        assert s not in t


def test_known_in_log_for_the_launch_wait():
    hits = watchdog.known_in_log("minecraft", "launch", {"mc_game": (FIX / "mc_latest_world_missing.txt").read_text(encoding="utf-8")})
    assert [e["id"] for e in hits] == ["mc_world_not_found"]
    assert watchdog.known_in_log("minecraft", "launch", {"mc_game": "[12:00] joined the game"}) == []


# ---------------------------------------------------------------- the snapshot code itself (run here, on a fake Steam folder)
def test_snapshot_reads_logs_and_one_setting_but_never_a_whole_login_file(tmp_path):
    root = tmp_path / "steam"
    (root / "logs").mkdir(parents=True); (root / "config").mkdir()
    (root / "logs" / "steamui_login.txt").write_text((FIX / "steamui_login_waiting.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "config" / "config.vdf").write_text('"InstallConfigStore"\n{\n "ConnectCache" { "abc" "SECRET-LOGIN-TOKEN-0123" }\n'
                                                ' "EnableShaderBackgroundProcessing"\t\t"0"\n}\n', encoding="utf-8")
    s = watchdog.collect(watchdog.LocalBox(), "steam", root=str(root), display=":987")
    assert "error" not in s and "WaitingForCredentials" in s["logs"]["steamui_login"]
    assert s["greps"]["shader_bg"] == "0" and "SECRET-LOGIN-TOKEN" not in json.dumps(s)
    tok = tmp_path / "account" / "microsoft.json"; tok.parent.mkdir(); tok.write_text('{"refresh_token": "SECRET-REFRESH"}', encoding="utf-8")
    rc, out = watchdog.LocalBox().py(watchdog.SNAPSHOT_PY, {"GA_WD": json.dumps({"jsons": {"t": str(tok)}, "logs": {"t": str(tok)},
                                                                                  "secret": watchdog.SECRET_FILES.pattern, "display": ":987"})})
    assert rc == 0 and "SECRET-REFRESH" not in out and "t" not in json.loads(out)["jsons"]


def test_heartbeat_for_one_long_call():
    said = []
    import time
    with watchdog.Heartbeat(said.append, "mc_download", "zh", every=0.1, tick=0.02) as hb:
        time.sleep(0.3)
        hb.beat()
    assert said and "下载 Minecraft 文件" in said[0]


# ---------------------------------------------------------------- ga-steam (inside the image) uses the same pieces
def _ga_steam(tmp_path, monkeypatch):
    import importlib.machinery
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("GA_STEAM_ROOT", str(tmp_path / "steam")); monkeypatch.setenv("GA_SANDBOX", str(tmp_path / "sandbox"))
    loader = importlib.machinery.SourceFileLoader("ga_steam_t", str(root / "lab" / "images" / "common" / "ga-steam"))
    spec = importlib.util.spec_from_loader("ga_steam_t", loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    return m


def test_ga_steam_finds_the_watchdog_and_reads_the_first_start_update(tmp_path, monkeypatch):
    g = _ga_steam(tmp_path, monkeypatch)
    assert g.watchdog is not None
    (tmp_path / "steam" / "logs").mkdir(parents=True)
    (tmp_path / "steam" / "logs" / "bootstrap_log.txt").write_text((FIX / "bootstrap_downloading.txt").read_text(encoding="utf-8"), encoding="utf-8")
    assert g.bootstrap() == ("downloading", 50)
    (tmp_path / "steam" / "logs" / "webhelper.txt").write_text((FIX / "webhelper_login.txt").read_text(encoding="utf-8"), encoding="utf-8")
    assert g.desktop_login_window()


def test_ga_steam_shader_off_edits_only_that_setting(tmp_path, monkeypatch):
    g = _ga_steam(tmp_path, monkeypatch)
    vdf = '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"ConnectCache" { "x" "y" }\n\t\t\t}\n\t\t}\n\t}\n}\n'
    new = g.shader_off_text(vdf)
    assert '"EnableShaderBackgroundProcessing"\t\t"0"' in new and '"ConnectCache" { "x" "y" }' in new
    assert g.shader_off_text(new) == new.replace('"0"', '"0"')
    on = new.replace('"EnableShaderBackgroundProcessing"\t\t"0"', '"EnableShaderBackgroundProcessing"\t\t"1"')
    assert '"EnableShaderBackgroundProcessing"\t\t"0"' in g.shader_off_text(on)
    f = watchdog.facts({"greps": {"shader_bg": "0"}})
    assert f["shader_precache"] is False


def test_ga_steam_owns(tmp_path, monkeypatch, capsys):
    import argparse
    g = _ga_steam(tmp_path, monkeypatch)
    (tmp_path / "steam" / "steamapps").mkdir(parents=True); (tmp_path / "steam" / "logs").mkdir()
    g.cmd_owns(argparse.Namespace(appid=413150, json=True))
    assert json.loads(capsys.readouterr().out)["owned"] is None
    (tmp_path / "steam" / "logs" / "content_log.txt").write_text("[2026-10-26 10:00:00] AppID 105600 : No licenses\n", encoding="utf-8")
    g.cmd_owns(argparse.Namespace(appid=105600, json=True))
    assert json.loads(capsys.readouterr().out)["owned"] is False
    (tmp_path / "steam" / "steamapps" / "appmanifest_413150.acf").write_text((FIX / "acf_413150_dialog.acf").read_text(encoding="utf-8").replace('"2"', '"4"'), encoding="utf-8")
    g.cmd_owns(argparse.Namespace(appid=413150, json=True))
    assert json.loads(capsys.readouterr().out)["owned"] is True


def test_galab_launch_wait_knows_the_missing_world(monkeypatch):
    import sys
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "lab" / "images" / "common"))
    try:
        import galab
    finally: sys.path.remove(str(root / "lab" / "images" / "common"))
    monkeypatch.setenv("GAMEANYTHING_LANG", "zh")
    w = galab.known_in_log("ga-mc", (FIX / "mc_latest_world_missing.txt").read_text(encoding="utf-8"))
    assert w and "Create New World" in w and "存档" in w
    assert galab.known_in_log("ga-ksp", "anything") is None and galab.known_in_log("ga-mc", "[x] joined the game") is None


# ---------------------------------------------------------------- EA App (lab run 2026-10-29, HICCUPS ea)
def test_the_ea_user_agreement_is_never_clicked_and_a_recorded_yes_only_changes_the_words(tmp_path):
    snap = CASES["ea_user_agreement"]["snapshot"]
    w, box, lines = dog([snap], flow="ea", phase="ea_start", lang="zh")
    r = w.tick()
    assert r["stop"] and r["stop"]["id"] == "ea_user_agreement" and r["stop"]["license"]
    assert "Electronic Arts" in lines[-1] and "tos.ea.com" in lines[-1] and "LET'S GO" in lines[-1] and "不会替你点" in lines[-1]
    assert box.sh_calls == []
    cf = tmp_path / "consents.json"
    rec = watchdog.record_consent(cf, "ea", note="chat 10-29")
    assert rec["publisher"] == "Electronic Arts" and "tos.ea.com" in rec["url"]
    w, box, lines = dog([snap], flow="ea", phase="ea_start", consent=watchdog.consents(cf))
    for _ in range(3): assert w.tick()["stop"] is None
    assert box.sh_calls == [] and any("click LET'S GO yourself" in m for m in lines)


def test_no_screenshot_of_the_ea_sign_in_form(tmp_path):
    clock = Clock()
    w, box, lines = dog([CASES["ea_login_window"]["snapshot"]], flow="ea", phase="ea_login", clock=clock, tmp=tmp_path)
    w.tick(); clock.t += 120; w.tick()
    assert all(not a.get("shot") for a in box.py_args)
    assert box.py_args[0]["private"] == {"ea_fsm": "awaitingAuthentication"}


def test_ea_signed_in_counts_only_lines_written_after_the_start():
    snap = {"procs": [{"pid": 1, "state": "S", "argv": ["C:\\x\\EADesktop.exe"]}], "greps": {"ea_fsm": ["2026-10-29T19:21:38", "authenticated"]}}
    t = __import__("calendar").timegm((2026, 10, 29, 19, 21, 38, 0, 0, 0))
    assert watchdog.facts(snap)["ea_signed_in"] is True
    assert watchdog.facts(snap, {"ea_started_at": t + 300})["ea_signed_in"] is False      # the last run's line, before the new one
    assert watchdog.facts({**snap, "procs": []})["ea_signed_in"] is False                 # the app is not running
    early = {**snap, "greps": {"ea_fsm": ["2026-10-29T20:17:01", "awaitingMainAppReady"]}}
    assert watchdog.facts(early)["ea_signed_in"] is False                                  # seen 10-29 right after a restart


def test_ea_window_titles_with_a_no_break_space_are_normalised_in_the_snapshot_code():
    assert '.replace("\\u00a0", " ")' in watchdog.SNAPSHOT_PY


def _ga_ea(tmp_path, monkeypatch):
    import importlib.machinery
    import importlib.util
    monkeypatch.setenv("GA_EA_HOME", str(tmp_path)); monkeypatch.delenv("WINEPREFIX", raising=False)
    root = Path(__file__).resolve().parent.parent
    loader = importlib.machinery.SourceFileLoader("ga_ea_t", str(root / "lab" / "images" / "common" / "ga-ea"))
    spec = importlib.util.spec_from_loader("ga_ea_t", loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    return m


def test_ga_ea_starts_the_newest_versioned_launcher_and_reports_a_steam_linked_game(tmp_path, monkeypatch, capsys):
    import argparse
    m = _ga_ea(tmp_path, monkeypatch)
    assert m.watchdog is not None and m.launcher() is None
    for v in ("13.9.0.1", "13.813.1.6327"):
        p = m.EA_DIR / v / "EA Desktop" / "EALauncher.exe"; p.parent.mkdir(parents=True); p.write_text("", encoding="utf-8")
    assert m.launcher().parts[-3] == "13.813.1.6327"           # the junction "EA Desktop\EA Desktop" is broken under Wine
    monkeypatch.setattr(m, "facts", lambda: watchdog.facts({"procs": [{"pid": 1, "state": "S", "argv": ["C:\\x\\EADesktop.exe"]}],
                                                            "greps": {"ea_fsm": ["2026-10-29T19:21:38", "authenticated"],
                                                                      "ea_game_status": '{"externalSource":"STEAM","installed":false}'}}))
    m.owns(argparse.Namespace(json=True))
    o = json.loads(capsys.readouterr().out)
    assert o == {"signed_in": True, "owned": True, "source": "STEAM", "installed": False, "installing": False, "managed_by": None,
                 "steam_owned": False, "other_store": False}           # a linked Steam account alone is not "another store"


def test_a_browser_after_a_click_is_a_suspected_misclick_never_evidence_of_another_store():
    c = CASES["ea_browser_after_click"]
    f = watchdog.facts(load(c["snapshot"]))
    assert f["ea_browser_opened"] == 2 and f["ea_external_owned"] is False      # managedBy EA: the EA App downloads it itself
    w, box, lines = dog([c["snapshot"]], flow="ea", phase="ea_install", lang="zh", ctx={"game": "模拟人生 4"})
    r = w.tick()
    assert r["stop"] is None and box.sh_calls == ["ga-ea normalize"] and "点错了位置" in lines[-1]


def test_the_terms_of_play_before_the_download_are_never_clicked():
    w, box, lines = dog([CASES["ea_terms_of_play"]["snapshot"]], flow="ea", phase="ea_install", ctx={"game": "The Sims 4"})
    r = w.tick()
    assert r["stop"]["id"] == "ea_terms_of_play" and r["stop"]["license"] and box.sh_calls == []
    assert "Visual C++ 2015 and 2019" in lines[-1] and "will not click" in lines[-1]


# ---------------------------------------------------------------- "同意，帮我点": the click-for-me exception (Wenyi, 2026-10-29)
def _terms_dog(tmp_path, consent, clock):
    return dog([CASES["ea_terms_of_play"]["snapshot"]], flow="ea", phase="ea_install", ctx={"game": "The Sims 4"}, clock=clock,
               tmp=tmp_path, consent=consent)


def test_a_fresh_click_for_me_consent_clicks_once_and_logs_the_dialog_and_the_consent(tmp_path):
    cf = tmp_path / "c.json"
    watchdog.record_consent(cf, "ea_ts4_terms", click_for_me=True, words="同意，帮我点", now=NOW - 60)
    clock = Clock()
    w, box, lines = _terms_dog(tmp_path / "ev", watchdog.consents(cf), clock)
    r = w.tick()
    assert r["stop"] is None and r["acted"][0]["click_for_me"] is True
    assert box.sh_calls == [watchdog.ACTIONS["ea_click_terms_download"]]
    assert "同意，帮我点" in lines[-1] and "DOWNLOAD" in lines[-1]
    logs = sorted(p.name for p in (tmp_path / "ev").iterdir())
    assert any(n.startswith("accept-ea_terms_of_play") and n.endswith(".png") for n in logs)
    assert json.loads(next((tmp_path / "ev").glob("accept-*.json")).read_text(encoding="utf-8"))["consent"]["words"] == "同意，帮我点"
    clock.t += 5; w.tick()
    assert len(box.sh_calls) == 1                                 # once


@pytest.mark.parametrize("case", ["stale", "other_app", "plain_yes", "no_words"])
def test_a_stale_other_plain_or_wordless_consent_never_clicks(tmp_path, case):
    cf = tmp_path / "c.json"
    if case == "stale": watchdog.record_consent(cf, "ea_ts4_terms", click_for_me=True, words="同意，帮我点", now=NOW - 16 * 60)
    if case == "other_app": watchdog.record_consent(cf, "ea", click_for_me=True, words="同意，帮我点", now=NOW - 60)
    if case == "plain_yes": watchdog.record_consent(cf, "ea_ts4_terms", now=NOW - 60)
    if case == "no_words": watchdog.record_consent(cf, "ea_ts4_terms", click_for_me=True, words="", now=NOW - 60)
    w, box, lines = _terms_dog(tmp_path / "ev", watchdog.consents(cf), Clock())
    for _ in range(3): w.tick()
    assert box.sh_calls == []


def test_the_table_still_forbids_auto_for_agreements_and_accept_actions_elsewhere():
    bad = [{"id": "x", "flows": ["ea"], "when": {"a": 1}, "kind": "auto", "action": "ea_click_lets_go", "license": True,
            "say": {"zh": "x", "en": "x"}, "max_wait_s": 0},
           {"id": "y", "flows": ["ea"], "when": {"a": 1}, "kind": "tell", "accept_action": "ea_click_lets_go",
            "say": {"zh": "y", "en": "y"}, "max_wait_s": 0}]
    out = hiccups.validate(bad)
    assert any("never be accepted automatically" in o for o in out) and any("accept_action only for a licence" in o for o in out)
    for e in hiccups.KNOWN:
        if e.get("accept_action"): assert e["license"] and e["kind"] == "ask" and e["accept_action"] in watchdog.ACTIONS


def test_out_of_memory_since_the_watch_began_stops_and_says_the_limit():
    """Plain Docker --memory 700m, 2026-10-29: the kernel killed SMAPI in the sandbox (cgroup memory.events oom_kill). Only a kill AFTER
    the watch began counts: an old one (a sandbox reused after an earlier OOM) is not news."""
    base = {"windows": [], "procs": [], "oom_kills": 2, "mem_limit": 734003200}
    w, box, lines = dog([base, base, {**base, "oom_kills": 3}], flow="minecraft", phase="launch", lang="zh")
    assert w.tick()["stop"] is None and w.tick()["stop"] is None          # 2 kills before the watch: not reported
    r = w.tick()
    assert r["stop"]["id"] == "sandbox_out_of_memory"
    assert any("0.7 GB" in m and "不受影响" in m for m in lines)
    w, box, lines = dog([{"windows": [], "procs": []}], flow="steam", phase="start")   # no cgroup v2 file (Docker Desktop on old kernels)
    assert w.tick()["stop"] is None


def test_ga_steam_shm_fix_appends_the_flag_once(tmp_path, monkeypatch):
    # lucy-qwen 2026-10-29: a 64 MB /dev/shm; without --disable-dev-shm-usage the sign-in window never showed (HICCUPS #26)
    g = _ga_steam(tmp_path, monkeypatch)
    wrap = '#!/bin/bash\necho "<6>exec ./steamwebhelper $*"\n#exec /usr/bin/gdbserver 127.0.0.1:2345 ./steamwebhelper "$@"\nexec ./steamwebhelper "$@"\n'
    new = g.shm_fix_text(wrap)
    assert new.endswith('exec ./steamwebhelper "$@" --disable-dev-shm-usage\n') and new.count("--disable-dev-shm-usage") == 1
    assert len(new) == len(wrap) and new.startswith("#!/bin/bash\n")   # Steam checks its files by size: a longer one = reinstall (#26)
    assert g.shm_fix_text(new) == new and g.shm_fix_text("#!/bin/sh\n") is None
    assert g.shm_fix_text('#!/bin/bash\nexec ./steamwebhelper "$@"\n') is None          # no comment to shorten: not touched
    w = tmp_path / "steam" / "ubuntu12_64" / "steamwebhelper_sniper_wrap.sh"; w.parent.mkdir(parents=True); w.write_text(wrap, encoding="utf-8")
    monkeypatch.setattr(g, "shm_mb", lambda: 64)
    assert g.shm_fix(restart=False, quiet=True) == "set" and "--disable-dev-shm-usage" in w.read_text(encoding="utf-8")
    assert g.shm_fix(restart=False, quiet=True) == "ok"
    monkeypatch.setattr(g, "shm_mb", lambda: 1024); w.write_text(wrap, encoding="utf-8")
    assert g.shm_fix(restart=False, quiet=True) == "ok" and "--disable-dev-shm-usage" not in w.read_text(encoding="utf-8")
    assert watchdog.ACTIONS["steam_webhelper_no_shm"] == "ga-steam shm-fix"


def test_a_stale_steam_log_does_not_stop_the_check_before_steam_starts():
    """2026-10-31: /sandbox/logs/steam.log (the project volume) kept a 「Permission denied」 from a sandbox created at the wrong HOME; the
    re-created, fixed one stopped in "check" before Steam started. In "start" (this flow's own Steam) it is still caught."""
    c = CASES["steam_home_not_writable"]
    f = watchdog.facts(load(c["snapshot"]), ctx_of(c))
    assert "steam_home_not_writable" not in [e["id"] for e in watchdog.match(f, "steam", "check")]
    assert "steam_home_not_writable" in [e["id"] for e in watchdog.match(f, "steam", "start")]


def test_steam_crashing_under_qemu_on_a_mac_is_known():
    """Her Mac 2026-10-30 (Apple silicon, Docker Desktop): the 32-bit client ran under qemu-i386 and crashed ~10 s after every start."""
    snap = {"logs": {"console": "[2026-10-31 05:08:22] qemu: uncaught target signal 11 (Segmentation fault) - core dumped\n"}, "procs": [], "windows": []}
    f = watchdog.facts(snap, {"game": "slay_the_spire"})
    assert f["qemu_segv"] is True
    hit = [e for e in watchdog.match(f, "steam", "start") if e["id"] == "steam_crashes_under_qemu"]
    assert hit and hit[0]["kind"] == "ask" and "本机模式" in hit[0]["say"]["zh"] and "native mode" in hit[0]["say"]["en"]
    assert not watchdog.facts({"logs": {"console": "Steam started"}, "procs": [], "windows": []}, {})["qemu_segv"]


def test_no_ea_screenshot_when_its_state_log_cannot_be_read(tmp_path, monkeypatch):
    """2026-10-31: the login flow gave the watchdog no EA root (GA_EA_HOME unset on her machine), so it read no EADesktop.log, never saw
    the sign-in window and took a stall screenshot while it was open. An unreadable private-state log now counts as private."""
    from gameanything import loginflow
    monkeypatch.delenv("GA_EA_HOME", raising=False)
    assert loginflow.ea_home() == "/sandbox/ea"
    monkeypatch.delenv("GA_STEAM_ROOT", raising=False)
    s = watchdog.collect(watchdog.LocalBox(), "ea", shot=str(tmp_path / "shots" / "x.png"), root=str(tmp_path / "nowhere"))
    assert s.get("screenshot_skipped") == "private" and not (tmp_path / "shots").exists()
    log = tmp_path / "ea" / "pfx" / "drive_c" / "ProgramData" / "EA Desktop" / "Logs" / "EADesktop.log"; log.parent.mkdir(parents=True)
    log.write_text("[2026-10-31T01:42:13.000Z] PID: 1 DesktopFSM[awaitingAuthentication]\n", encoding="utf-8")
    s = watchdog.collect(watchdog.LocalBox(), "ea", shot=str(tmp_path / "shots" / "y.png"), root=str(tmp_path / "ea"))
    assert s.get("screenshot_skipped") == "private" and s["greps"]["ea_fsm"] == ["2026-10-31T01:42:13", "awaitingAuthentication"]
