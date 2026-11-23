"""`gameanything lab env up|status` (labup.py): the base environment of a lab seat (pod, X display + viewer, Steam logged on), lease-checked.
No real docker: a fake engine answers the probes and records what was started; no real broker: the guard is a stub."""
import json

import pytest

from gameanything import labup, lab

POOL = {"sandboxes": {"wc-cities": {"kind": "steam", "display": ":136", "viewer_port": 6440}, "mclab-x": {"kind": "lab", "seats": 4},
                      "lucy-vk": {"kind": "external"}}}
CITIES = "wenyi/my-san-diego-memory/wc-cities:whole"


class Pod:
    """A docker-rt pod: what runs in it. logs_on: Steam logs on by itself once started (a saved login); guard: a sign-in window instead."""
    def __init__(self, up=True, x=True, viewer=True, steam=False, logged=False, logs_on=True, guard=False, script=True, refused=None):
        self.up, self.x, self.steam, self.logged, self.logs_on, self.guard, self.script, self.refused = up, x, steam, logged, logs_on, guard, script, refused
        self.vnc = self.ws = self.viewer = viewer
        self.started = []; self.now = 1000; self.last_at = 900; self.probes = 0
        self.steam_at = 800 if steam else None                         # when the running client started (pod clock)
        self.start_rc = 0                                              # what the STEAM start exec returns (124: the client timed out)


class FakeEngine:
    backend = "docker-rt"

    def __init__(self, pod, answers=True): self.pod = pod; self._answers = answers; self.execs = []

    def answers(self): return self._answers

    def wrapper(self): return False

    def state(self, name):
        if not self._answers: return None
        return "up" if self.pod.up else "not running"

    def sh(self, name, script, timeout=60, env=None):
        p = self.pod; self.execs.append((name, script, env)); p.now += 5
        if script == labup.PROBE:
            return 0, "\n".join(["display=:136", "viewer_port=6080", f"x={int(p.x)}", f"vnc={int(p.vnc and p.x)}", f"ws={int(p.ws)}",
                                 f"viewer={int(p.viewer)}", "entrypoint=1"] + (["seat_x=0"] if env and env.get("SEAT_DISPLAY") else []))
        if script == labup.STEAM_PROBE:
            p.probes += 1
            if p.steam and p.logs_on and not p.logged and not p.guard and not p.refused and "steam" in p.started: p.logged = True; p.last_at = p.now
            last = "[2026-10-26 21:15:07] [Logged On, 4, 7] ok" if p.logged else "[2026-10-26 20:20:17] [Logged Off, 0, 0] Log session ended"
            return 0, "\n".join([f"steam={int(p.steam)}", f"wrapper={int(self.wrapper())}", f"script={int(p.script)}", f"now={p.now}", f"last={last}",
                                 f"last_at={p.last_at}", f"fail_at={p.now if p.refused else 0}", f"fail={p.refused or ''}",
                                 f"login_window={int(p.guard and p.steam)}"]
                             + ([f"steam_up={p.now - p.steam_at}"] if p.steam and p.steam_at is not None else []))
        if script == labup.ENTRYPOINT:
            assert env == {"LAUNCH_GAME": "0"}, "the entrypoint is re-run without its game"
            p.started.append("entrypoint"); p.x = p.vnc = p.ws = p.viewer = True; return 0, ""
        if script == labup.STEAM: p.started.append("steam"); p.steam = True; p.steam_at = p.now; return p.start_rc, ""
        for k, cmd in (("vnc", labup.VNC), ("ws", labup.WS), ("viewer", labup.VIEWER)):
            if script == cmd: p.started.append(k); setattr(p, k, True); return 0, ""
        raise AssertionError(f"unexpected exec: {script[:80]}")


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


def go(pod, lease=CITIES, start=True, guard=None, engine=None, timeout=60):
    c = Clock()
    return labup.run(lease, start=start, timeout=timeout, engine=engine or FakeEngine(pod), pool=POOL,
                     guard=guard or (lambda seat, sb, l: (True, "ok")), sleep=c.sleep, clock=c, env={})


def test_up_starts_steam_in_the_background_and_waits_for_the_log_on():
    pod = Pod(steam=False)
    r = go(pod)
    assert r["state"] == "ok" and r["code"] == 0 and r["did"] == ["steam"] and pod.started == ["steam"]
    assert r["viewer_port"] == 6440 and r["kind"] == "steam" and {c["name"]: c["ok"] for c in r["checks"]} == {"pod": True, "display": True, "viewer": True, "steam": True}
    assert "setsid nohup /scripts/steam-then-game.sh sleep infinity" in labup.STEAM and "< /dev/null &" in labup.STEAM, "detached, no game"


def test_up_with_everything_up_does_nothing_and_status_never_starts_anything():
    pod = Pod(steam=True, logged=True); r = go(pod)
    assert r["state"] == "ok" and r["did"] == [] and pod.started == []
    pod = Pod(steam=False, x=False); r = go(pod, start=False)
    assert r["state"] == "failed" and pod.started == [] and not next(c for c in r["checks"] if c["name"] == "display")["ok"]
    pod = Pod(steam=False); r = go(pod, start=False)
    assert r["state"] == "failed" and r["code"] == 1 and "env up" in r["why"] and pod.started == []


def test_steam_that_needs_her_login_is_reported_not_waited_on_forever():
    pod = Pod(steam=False, guard=True); r = go(pod)
    assert r["state"] == "needs_her" and r["code"] == 4 and pod.started == ["steam"]
    assert "6440" in r["why_zh"] and "她" in r["why_zh"] and "密码" in r["why_zh"]
    # a client that just never logs on: needs her after the timeout, no restart, no second start
    pod = Pod(steam=False, logs_on=False); r = go(pod, timeout=30)
    assert r["state"] == "needs_her" and pod.started == ["steam"] and pod.probes < 20
    # the log-on refused (Steam Guard): at once
    pod = Pod(steam=False, refused="AccountLogonDenied"); r = go(pod)
    assert r["state"] == "needs_her" and "AccountLogonDenied" in next(c for c in r["checks"] if c["name"] == "steam")["detail"]
    # a running client that is logged off: waited on, never restarted
    pod = Pod(steam=True, logs_on=False); r = go(pod, timeout=20)
    assert r["state"] == "needs_her" and pod.started == []
    # status of a sign-in window: needs her too
    assert go(Pod(steam=True, guard=True), start=False)["state"] == "needs_her"


def test_pod_down_is_its_own_state_and_nothing_is_created():
    pod = Pod(up=False); eng = FakeEngine(pod); r = go(pod, engine=eng)
    assert r["state"] == "down" and r["code"] == 5 and "launch_rt" in r["why"] and pod.started == [] and eng.execs == []
    assert go(pod, engine=FakeEngine(pod, answers=False))["state"] == "failed"


def test_a_restarted_pod_gets_its_entrypoint_again_then_steam():
    pod = Pod(x=False, viewer=False, steam=False); r = go(pod)
    assert r["state"] == "ok" and pod.started == ["entrypoint", "steam"]
    pod = Pod(steam=True, logged=True); pod.viewer = False; pod.ws = False; r = go(pod)
    assert r["state"] == "ok" and pod.started == ["ws", "viewer"], "only the missing viewer parts, X kept"


def test_lab_seat_without_steam_and_its_own_display():
    pod = Pod(steam=False); r = go(pod, lease="wenyi/adaptation-3/mclab-x:2")
    assert r["state"] == "ok" and pod.started == [] and r["kind"] == "lab"
    seat = next(c for c in r["checks"] if c["name"] == "seat_display"); assert seat["ok"] and "lab-display.sh 2 up" in seat["detail"]


def test_refused_unsupported_and_plain_docker():
    pod = Pod()
    assert go(pod, guard=lambda *a: (False, "leased to someone else"))["state"] == "refused"
    assert go(pod, lease="")["code"] == 3 and go(pod, lease="nonsense")["state"] == "refused"
    assert go(pod, lease="wenyi/p/lucy-vk:1")["state"] == "unsupported"
    assert go(pod, lease="wenyi/p/nowhere:1")["state"] == "unsupported"
    assert go(Pod(steam=False, script=False))["state"] == "unsupported"
    eng = FakeEngine(pod); eng.backend = "docker"
    r = labup.run("me/p/local:1", engine=eng, pool={"sandboxes": {"local": {"kind": "lab", "seats": 2}}}, guard=lambda *a: (True, ""), env={})
    assert r["state"] == "ok" and "seat.py" in next(c for c in r["checks"] if c["name"] == "seat")["detail"] and eng.execs == []
    r = labup.run("me/p/local:whole", engine=eng, pool={"sandboxes": {"local": {"kind": "steam"}}}, guard=lambda *a: (True, ""), env={})
    assert r["state"] == "unsupported" and r["code"] == 6


def test_the_command_refuses_residents_and_prints_json(monkeypatch, capsys):
    monkeypatch.setenv("GAMEANYTHING_INSTANCE", "run1"); monkeypatch.delenv("GAMEANYTHING_ROLE", raising=False)
    assert lab.main(["env", "up", "--lease", CITIES]) == 3 and "常驻 agent 不能动沙箱环境" in capsys.readouterr().err
    monkeypatch.setenv("GAMEANYTHING_ROLE", "builder")
    monkeypatch.setattr(labup, "run", lambda lease, **k: {"state": "needs_her", "code": 4, "ok": False, "lease": lease, "sandbox": "wc-cities", "seat": "whole",
                                                         "checks": [], "did": [], "why": "w", "why_zh": "z", "start": k["start"]})
    assert lab.main(["env", "status", "--json", "--lease", CITIES]) == 4
    d = json.loads(capsys.readouterr().out); assert d["state"] == "needs_her" and d["start"] is False
    monkeypatch.delenv("GAMEANYTHING_INSTANCE"); monkeypatch.delenv("GAMEANYTHING_ROLE"); monkeypatch.setenv("GAMEANYTHING_LEASE", CITIES)
    assert lab.main(["env", "up"]) == 4 and "NEEDS_HER" in capsys.readouterr().out, "a coordinator by hand may; the lease comes from $GAMEANYTHING_LEASE"


def test_residents_are_denied_the_command_and_builders_get_it_but_not_raw_steam():
    from gameanything import agent_providers as ap
    def denied(cmd, rules): return any(__import__("fnmatch").fnmatchcase(cmd, r[5:-1]) for r in rules)
    for cmd in ("gameanything lab env up", "/x/.venv/bin/m2w lab env up --lease a/b/c:1", "python -m gameanything lab env up"):
        assert denied(cmd, ap.DENY_RESIDENT) and not denied(cmd, ap.DENY_BUILDER)
    raw = "docker exec wc-cities sh -c 'setsid nohup /scripts/steam-then-game.sh sleep infinity &'"
    assert denied(raw, ap.DENY_BUILDER) and denied(raw, ap.DENY_RESIDENT)
    assert not denied("bash /srv/lab/runs/cslab/sdmem/cs install", ap.DENY_BUILDER)


# ---------------------------------------------------------------- 2026-10-27: after a pod restart `up` waited on a Steam that was not there
import re
import shutil
import subprocess
import sys


def _patterns():
    return re.findall(r'pgrep (?:-o )?-f "([^"]+)"', labup.STEAM_PROBE)


def _wrapped(script):
    """The command lines docker-rt leaves in the pod for one `docker exec c sh -c script` (its handshake wrapper repeats it)."""
    return [f"sh -c {script}", f'sh -c "$@"; rc=$?; printf "\\nMARK\\n" 1>&2; timeout 60 cat > /dev/null; exit $rc sh sh -c {script}']


class ProcEngine(FakeEngine):
    """Answers `wrapper=` the way pgrep would: the probe's patterns against the pod's command lines, which always include the probe
    itself (and docker-rt's wrapper of it) while it runs."""
    procs = ()

    def wrapper(self):
        pat = _patterns()[1]
        return any(re.search(pat, c) for c in list(self.procs) + _wrapped(labup.STEAM_PROBE))


def test_the_steam_probe_never_matches_itself_or_docker_rts_exec_wrapper():
    steam_pat, wrap_pat = _patterns()
    own = _wrapped(labup.STEAM_PROBE) + _wrapped(labup.STEAM) + ["env SEAT_DISPLAY=:106 sh -c " + labup.STEAM_PROBE,
                                                                 "bash -c cat /scripts/steam-then-game.sh", "grep steam-then-game.sh x"]
    for c in own:
        assert not re.search(steam_pat, c) and not re.search(wrap_pat, c), c[:80]
    for c in ("bash /scripts/steam-then-game.sh sleep infinity", "/bin/bash /scripts/steam-then-game.sh /csscripts/start-game.sh",
              "/usr/bin/env bash /scripts/steam-then-game.sh sleep infinity"):
        assert re.search(wrap_pat, c), c
    for c in ("/home/player/.steam/debian-installation/ubuntu12_32/steam -no-cef-sandbox -nochatui",
              "/home/player/.steam/debian-installation/ubuntu12_32/steam"):
        assert re.search(steam_pat, c), c
    assert "/scripts/steam-then-game.sh" not in labup.STEAM_PROBE, "the start script's path written out matches pgrep -f of the probe"


def test_a_restarted_pod_without_steam_gets_steam_started_not_waited_on():
    pod = Pod(steam=False); eng = ProcEngine(pod); r = go(pod, engine=eng)
    assert r["state"] == "ok" and pod.started == ["steam"]
    # a real start script still waiting for its client: waited on, never a second start
    pod = Pod(steam=False, logs_on=False); eng = ProcEngine(pod); eng.procs = ["bash /scripts/steam-then-game.sh sleep infinity"]
    r = go(pod, engine=eng, timeout=20)
    assert pod.started == [] and r["state"] == "failed" and "did not stay up" in r["why"]


def test_a_start_exec_that_times_out_is_checked_not_failed():
    pod = Pod(steam=False); pod.start_rc = 124; r = go(pod)
    assert r["state"] == "ok" and pod.started == ["steam"] and r["did"] == ["steam"]


def test_a_stale_logged_on_line_from_before_the_restart_does_not_count():
    # Steam runs (someone else started it at 990) but has not logged on; the last line is the old client's [Logged On at 900
    pod = Pod(steam=True, logged=True, logs_on=False); pod.steam_at = 990; r = go(pod, timeout=20)
    assert r["state"] == "needs_her" and pod.started == []
    d = next(c for c in r["checks"] if c["name"] == "steam")["detail"]
    assert "from before" in d and "21:15:07" in d
    # once this client logs on (a line newer than its start) it counts
    pod = Pod(steam=True, logs_on=True); pod.steam_at = 990; pod.started = ["steam"]; r = go(pod)
    assert r["state"] == "ok"
    # status sees the stale line as not logged on either
    pod = Pod(steam=True, logged=True); pod.steam_at = 990
    assert go(pod, start=False)["state"] == "failed"
    # a client that started before its log-on line: logged on at once
    pod = Pod(steam=True, logged=True); pod.steam_at = 800; assert go(pod)["state"] == "ok" and pod.started == []


@pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("pgrep"), reason="needs Linux pgrep")
def test_the_real_steam_probe_in_a_real_shell(tmp_path):
    """The probe run by sh inside docker-rt's handshake wrapper, with real pgrep: nothing but itself runs -> steam=0 wrapper=0;
    a process that looks like the start script -> wrapper=1."""
    wrapper = ['sh', '-c', '"$@"; rc=$?; exit $rc', 'sh', 'sh', '-c', labup.STEAM_PROBE]
    d = labup._kv(subprocess.run(wrapper, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout)
    assert d["steam"] == "0" and d["wrapper"] == "0", d
    fake = subprocess.Popen(["bash /scripts/steam-then-game.sh sleep infinity"], executable=sys.executable, stdin=subprocess.PIPE)
    try:
        fake.stdin.write(b"import time; time.sleep(30)\n"); fake.stdin.close()
        import time; time.sleep(0.5)
        d = labup._kv(subprocess.run(wrapper, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout)
        assert d["wrapper"] == "1" and d["steam"] == "0", d
    finally:
        fake.kill(); fake.wait()
