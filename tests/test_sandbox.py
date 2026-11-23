"""The user's own sandbox (gameanything/sandbox.py): detecting the computer, and every cell of the 「游戏从哪来」 table in
the decision of 2026-10-29 (game kind x system, Docker missing / not running, low memory, Mac without GPU, ARM chips). The expected
table is written out here by hand, from the decision, not derived from the code."""
import shutil

import pytest
import yaml

from gameanything import games as registry, sandbox
from gameanything.games import tools

LINUX_BUILD = ["stardew", "terraria", "slay_the_spire", "overcooked2", "cities_skylines", "civ6", "valheim", "ksp"]
THREE_D = {"overcooked2", "cities_skylines", "civ6", "valheim", "ksp", "minecraft", "sims4"}
GPU = {**{g: "recommended" for g in THREE_D}, "minecraft": "required"}          # 2026-10-29: Minecraft 26.x opens no window without one
STORE = {**{g: "steam" for g in LINUX_BUILD}, "minecraft": "microsoft", "sims4": "ea"}

# (game kind, system) -> (mount available, mount recommended, download recommended); the download is always available
TABLE = {
    ("linux", "linux"): (True, True, False),
    ("linux", "windows"): (False, False, True),
    ("linux", "mac"): (False, False, True),
    ("java", "linux"): (True, True, False),
    ("java", "windows"): (True, True, False),
    ("java", "mac"): (True, True, False),
    ("windows", "linux"): (False, False, True),
    ("windows", "windows"): (True, True, False),
    ("windows", "mac"): (False, False, True),
}
KIND = {**{g: "linux" for g in LINUX_BUILD}, "minecraft": "java", "sims4": "windows"}
CELLS = [(g, s) for g in KIND for s in sandbox.SYSTEMS]


def by_source(r):
    return {o["source"]: o for o in r["options"]}


def test_every_game_is_classified():
    """Every registered game is either in the table above or explicitly not offered (No Man's Sky)."""
    assert set(sandbox.offered()) == set(KIND)
    for g in registry.games():
        if g not in KIND: assert sandbox.facts(g)["offered"] is False, g
    assert sandbox.facts("nms") == {"offered": False, "build": None, "download": None, "three_d": False, "gpu": "none"}


@pytest.mark.parametrize("game", sorted(KIND))
def test_facts_come_from_game_yaml(game):
    f = sandbox.facts(game)
    assert f == {"offered": True, "build": KIND[game], "download": STORE[game], "three_d": game in THREE_D, "gpu": GPU.get(game, "none")}


@pytest.mark.parametrize("game,system", CELLS)
def test_cell(game, system):
    r = sandbox.sources(game, sandbox.machine(system, memory_gb=32))
    mac_gpu = system == "mac"                                   # 2026-10-30 「Mac 只支持本机」 (3D: no GPU, 10-29; 2D: Steam crashes) -> native only
    assert r["offered"] and not r["ask_system"] and r["fallback"] == ("native" if mac_gpu else None)
    mount_ok, mount_rec, dl_rec = TABLE[(KIND[game], system)]
    if mac_gpu: mount_ok = mount_rec = dl_rec = False
    o = by_source(r)
    assert set(o) == {"mount", STORE[game]} | ({"native"} if mac_gpu else set())
    assert (o["mount"]["available"], o["mount"]["recommended"]) == (mount_ok, mount_rec)
    dl = o[STORE[game]]
    assert dl["available"] is (not mac_gpu) and dl["recommended"] is dl_rec
    assert r["recommended"] == r["options"][0]["source"] == ("native" if mac_gpu else "mount" if mount_rec else STORE[game])
    assert sum(x["recommended"] for x in r["options"]) == 1                     # exactly one 「推荐」
    assert r["options"][0]["recommended"]                                          # and it comes first
    for x in r["options"]:
        assert x["reason_zh"] and x["reason_en"], x                               # greyed ones say why, both languages
    assert dl["note_zh"] and "验证码" in dl["note_zh"] and "code" in dl["note_en"]   # the first login may need a code
    if mac_gpu:                                                                     # not supported (her decision 2026-10-29): greyed, says why
        assert o["native"]["available"] and "本机模式" in o["native"]["reason_zh"] and "native mode" in o["native"]["reason_en"]
        for x in (o["mount"], dl):
            assert not x["available"] and x["reason_zh"].startswith("Mac 上不支持")
            assert ("显卡" in x["reason_zh"] and "graphics card" in x["reason_en"]) if game in GPU else ("Intel" in x["reason_zh"] and "Intel" in x["reason_en"])
        if game == "minecraft": assert "Minecraft" in dl["reason_zh"] and "26.x" in dl["reason_en"]
    elif not mount_ok:
        want = {"linux": "Linux 上一般没装", "windows": "Windows 版", "mac": "Mac 版"}[system]
        assert want in o["mount"]["reason_zh"]
    # Mac without a GPU: a 3D game gets the warning (it is a warning: the options stay as they are)
    codes = {w["code"] for w in r["warnings"]}
    assert ("mac_no_gpu" in codes) == (system == "mac" and game in THREE_D)
    assert "low_memory" not in codes and "emulated" not in codes


@pytest.mark.parametrize("game,system", CELLS)
@pytest.mark.parametrize("docker", ["missing", "not_running"])
def test_no_docker_greys_everything(game, system, docker):
    r = sandbox.sources(game, sandbox.machine(system, docker=docker))
    mac_gpu = system == "mac"
    if mac_gpu:                                                                     # native mode needs no Docker: still first, recommended
        nat = r["options"].pop(0)
        assert nat["source"] == "native" and nat["available"] and nat["recommended"] and r["recommended"] == "native"
    else:
        assert r["recommended"] is None
    assert [o["available"] for o in r["options"]] == [False, False]
    assert not any(o["recommended"] for o in r["options"])
    assert r["fallback"] == "native" and "本机模式" in r["fallback_zh"] and "native mode" in r["fallback_en"]
    for o in r["options"]:
        if mac_gpu: assert o["reason_zh"].startswith("Mac 上不支持"); continue      # with Docker or without: no GPU in a Mac sandbox
        if docker == "missing":
            assert "Docker" in o["reason_zh"] and ("apt install docker.io" if system == "linux" else "Docker Desktop") in o["reason_zh"]
        else:
            assert "没在运行" in o["reason_zh"] and "not running" in o["reason_en"]
    # the order of the table stays: the option that would be recommended is still first
    assert r["options"][0]["source"] == ("mount" if TABLE[(KIND[game], system)][1] else STORE[game])


@pytest.mark.parametrize("game", sorted(KIND))
@pytest.mark.parametrize("mem,warn", [(8, True), (15.5, True), (16, False), (64, False), (None, False)])
def test_low_memory_only_warns_for_3d(game, mem, warn):
    r = sandbox.sources(game, sandbox.machine("linux", memory_gb=mem))
    codes = [w["code"] for w in r["warnings"]]
    assert ("low_memory" in codes) == (warn and game in THREE_D)
    assert any(o["available"] for o in r["options"])                                # a warning, never a block


@pytest.mark.parametrize("system", sandbox.SYSTEMS)
def test_arm_chip_warns_emulated(system):
    r = sandbox.sources("stardew", sandbox.machine(system, arch="arm64"))
    assert "emulated" in {w["code"] for w in r["warnings"]}
    r = sandbox.sources("stardew", sandbox.machine(system, arch="x86_64"))
    assert "emulated" not in {w["code"] for w in r["warnings"]}


def test_not_offered_and_unknown_system():
    r = sandbox.sources("nms", sandbox.machine("windows"))
    assert r["offered"] is False and r["options"] == [] and r["fallback"] == "native" and r["reason_en"]
    m = sandbox.machine("linux"); m["system"] = None                                # detection failed
    r = sandbox.sources("stardew", m)
    assert r["ask_system"] is True and r["options"] == []
    with pytest.raises(ValueError): sandbox.machine("beos")


def test_all_sources_has_every_game():
    a = sandbox.all_sources(sandbox.machine("linux"))
    assert set(a) == set(registry.games()) and a["nms"]["offered"] is False


# ---------------------------------------------------------------- detection
class FakeProbe(sandbox.Probe):
    def __init__(self, platform, machine, env=None, runs=None, files=None, which=None, winmem=None):
        self._p, self._m, self._e, self._runs, self._files, self._which, self._winmem = platform, machine, env or {}, runs or {}, files or {}, which, winmem

    def platform(self): return self._p
    def machine(self): return self._m
    def env(self): return dict(self._e)
    def run(self, argv, timeout=6): return self._runs.get(tuple(argv[1:]) if argv[0] == self._which else tuple(argv))
    def which(self, name): return self._which if name == "docker" else None
    def read(self, path): return self._files.get(path)
    def windows_memory(self): return self._winmem


GB = 2 ** 30
DOCKER_INFO = ("info", "--format", "{{.MemTotal}}")


def test_detect_linux_with_docker():
    p = FakeProbe("linux", "x86_64", which="/usr/bin/docker", runs={DOCKER_INFO: str(31 * GB)}, env={"DISPLAY": ":0"},
                  files={"/proc/meminfo": "MemTotal:       65843200 kB\n", "/proc/version": "Linux version 6.8.0-90-generic"})
    d = sandbox.detect(probe=p)
    assert d["system"] == "linux" and d["arch"] == "x86_64" and d["chip"] is None and d["wsl"] is False
    assert d["docker"] == "ok" and d["memory_gb"] == 31.0 and d["host_memory_gb"] == 62.8 and d["detected"] and d["where"] == "this_computer"


def test_detect_a_headless_linux_is_a_server():
    """QA2 2026-10-30: the single-user UI on a Linux server without a screen recorded `where: this_computer`, and the agents told her the
    game runs 「在你电脑的沙箱里」. No display = a server; GAMEANYTHING_WHERE says it outright."""
    files = {"/proc/version": "Linux version 6.8.0-90-generic"}
    assert sandbox.detect(probe=FakeProbe("linux", "x86_64", files=files))["where"] == "server"
    assert sandbox.detect(probe=FakeProbe("linux", "x86_64", files=files, env={"WAYLAND_DISPLAY": "w"}))["where"] == "this_computer"
    assert sandbox.detect(probe=FakeProbe("linux", "x86_64", files=files, env={"DISPLAY": ":0", "GAMEANYTHING_WHERE": "server"}))["where"] == "server"
    assert sandbox.detect(probe=FakeProbe("linux", "x86_64", files=files, env={"GAMEANYTHING_WHERE": "this_computer"}))["where"] == "this_computer"


def test_detect_wsl_and_docker_states():
    p = FakeProbe("linux", "x86_64", files={"/proc/version": "Linux version 5.15.153.1-microsoft-standard-WSL2"})
    d = sandbox.detect(probe=p)
    assert d["wsl"] is True and d["docker"] == "missing" and d["memory_gb"] is None
    p = FakeProbe("linux", "x86_64", which="/usr/bin/docker", runs={})            # a client, the engine does not answer
    assert sandbox.detect(probe=p)["docker"] == "not_running"
    p = FakeProbe("linux", "x86_64", which="/usr/bin/docker", runs={DOCKER_INFO: "0"})  # client 27.x: prints 0, exits 0, no engine
    assert sandbox.detect(probe=p)["docker"] == "not_running"


def test_detect_nvidia_gpus():
    class P(FakeProbe):
        def which(self, name): return {"docker": "/usr/bin/docker", "nvidia-smi": "/usr/bin/nvidia-smi"}.get(name)
    smi = ("nvidia-smi", "--query-gpu=name", "--format=csv,noheader")
    d = sandbox.detect(probe=P("linux", "x86_64", runs={DOCKER_INFO: str(31 * GB), smi: "NVIDIA L40S\nNVIDIA L40S\n"}))
    assert d["gpus"] == ["NVIDIA L40S", "NVIDIA L40S"]
    assert sandbox.detect(probe=FakeProbe("linux", "x86_64"))["gpus"] == []
    assert sandbox.detect(probe=P("darwin", "arm64", runs={smi: "x"}))["gpus"] == []


@pytest.mark.parametrize("machine,translated,chip", [("arm64", None, "apple"), ("x86_64", "1", "apple"), ("x86_64", "0", "intel"),
                                                      ("x86_64", None, "intel")])
def test_detect_mac_chip(machine, translated, chip):
    runs = {("sysctl", "-n", "hw.memsize"): str(16 * GB)}
    if translated is not None: runs[("sysctl", "-n", "sysctl.proc_translated")] = translated
    d = sandbox.detect(probe=FakeProbe("darwin", machine, runs=runs))
    assert d["system"] == "mac" and d["chip"] == chip and d["arch"] == ("arm64" if chip == "apple" else "x86_64") and d["memory_gb"] == 16.0


@pytest.mark.parametrize("env,arch", [({"PROCESSOR_ARCHITECTURE": "AMD64"}, "x86_64"), ({"PROCESSOR_ARCHITECTURE": "ARM64"}, "arm64"),
                                      ({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"}, "x86_64")])
def test_detect_windows(env, arch):
    d = sandbox.detect(probe=FakeProbe("win32", "AMD64", env=env, winmem=8 * GB))
    assert d["system"] == "windows" and d["arch"] == arch and d["memory_gb"] == 8.0 and d["chip"] is None


def test_detect_failure_and_hub():
    d = sandbox.detect(probe=FakeProbe("sunos5", "sparc"))
    assert d["system"] is None and d["detected"] is False
    assert sandbox.sources("stardew", d)["ask_system"] is True
    p = FakeProbe("linux", "x86_64", which="/usr/bin/docker", runs={DOCKER_INFO: str(64 * GB)})
    d = sandbox.detect(hub=True, probe=p)                    # under the hub the server's system decides
    assert d["where"] == "server" and d["system"] == "linux"
    assert sandbox.sources("sims4", d)["options"][0]["source"] == "ea"


def test_detect_real_machine_does_not_crash():
    d = sandbox.detect()
    assert d["system"] in sandbox.SYSTEMS and d["docker"] in ("ok", "not_running", "missing")


# ---------------------------------------------------------------- game.yaml validation
def test_game_check_rejects_a_bad_sandbox_block(tmp_path):
    s = registry.games()["stardew"]
    with pytest.raises(ValueError): sandbox.facts_of({**s, "sandbox": {"build": "dos"}})
    with pytest.raises(ValueError): sandbox.facts_of({**s, "sandbox": {"build": "linux", "download": "gog"}})
    with pytest.raises(ValueError): sandbox.facts_of({**s, "sandbox": {"build": "linux", "gpu": "maybe"}})
    assert sandbox.facts_of({**s, "sandbox": {"build": "linux", "three_d": False, "gpu": "required"}})["gpu"] == "required"
    pkg = tmp_path / "sdcopy"; shutil.copytree(s.path, pkg)
    y = yaml.safe_load((pkg / "game.yaml").read_text(encoding="utf-8"))
    errs = lambda: [i["text"] for i in tools.check_folder(pkg)["items"] if i["level"] == "error" and i["text"].startswith("sandbox:")]
    assert errs() == []
    y["sandbox"] = {"build": "dos"}; (pkg / "game.yaml").write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
    assert errs() and "dos" in errs()[0]


def test_minecraft_mount_off_linux_says_it_fetches_the_linux_files():
    """Found 2026-10-29 (user sandbox test): a Windows or Mac .minecraft lacks the Linux native jars; the sandbox fetches them (public)."""
    for system in ("windows", "mac"):
        o = sandbox._mount_cell("java", system)
        assert o[:2] == (True, True) and "Linux" in o[2] and "no login" in o[3]
    assert "Linux" not in sandbox._mount_cell("java", "linux")[2]


# ---------------------------------------------------------------- decided 2026-10-29
@pytest.mark.parametrize("system", ("linux", "windows"))      # (not on a Mac: no Minecraft sandbox there, no GPU)
def test_minecraft_is_played_offline_the_account_only_downloads(system):
    """Minecraft in the sandbox starts offline (a local player name, single-player): no Microsoft login to develop and test mods."""
    o = by_source(sandbox.sources("minecraft", sandbox.machine(system)))
    assert "离线玩家名" in o["mount"]["reason_zh"] and "不用登录微软账号" in o["mount"]["reason_zh"]
    assert "offline" in o["mount"]["reason_en"] and "no Microsoft login" in o["mount"]["reason_en"]
    ms = o["microsoft"]
    assert "只用来下载" in ms["reason_zh"] and "不需要它" in ms["reason_zh"]
    assert "only to download" in ms["reason_en"] and "do not need it" in ms["reason_en"]


def test_mac_is_native_only():
    """2026-10-30 「Mac 只支持本机」: native first on a Mac for every game (3D and Minecraft: no GPU; 2D: the Steam client crashes); the
    other systems keep their sandbox."""
    for game in KIND:
        r = sandbox.sources(game, sandbox.machine("mac"))
        assert r["recommended"] == "native" and not any(o["available"] for o in r["options"] if o["source"] != "native"), game
    assert "Intel" in by_source(sandbox.sources("stardew", sandbox.machine("mac")))["steam"]["reason_zh"]   # an Intel Mac: not tested
    for system in ("linux", "windows"):
        assert sandbox.sources("minecraft", sandbox.machine(system))["recommended"] == "mount"
        assert sandbox.sources("stardew", sandbox.machine(system))["recommended"] in ("mount", "steam")
    w = {x["code"]: x for x in sandbox.sources("minecraft", sandbox.machine("mac"))["warnings"]}
    assert "开不了" in w["mac_no_gpu"]["zh"]


def test_build_always_passes_the_users_uid(monkeypatch):
    for game in sandbox.IMAGES:
        a = sandbox.build_argv(game, uid=(1006, 1006))
        assert a[:2] == ["docker", "build"] and "--build-arg" in a and a[a.index("--build-arg") + 1] == "PLAYER_UID=1006"
        assert a[a.index("-f") + 1] == str(sandbox.dockerfile(game)) and sandbox.dockerfile(game).is_file()
        assert f"RUNTIME=gameanything-lab-{sandbox.CHAINS[game][-1]}" in a and a[-1] == str(sandbox.ROOT)
        assert "PLAYER_UID" not in " ".join(sandbox.build_argv(game, uid=None))      # Windows: nothing to pass, the image keeps 1000
        assert f'{sandbox.UID_LABEL}="${{PLAYER_UID}}"' in sandbox.dockerfile(game).read_text(encoding="utf-8")
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 1234, raising=False)
    monkeypatch.setattr(sandbox.os, "getgid", lambda: 99, raising=False)
    assert sandbox.player_uid() == (1234, 99) and "PLAYER_UID=1234" in sandbox.build_argv("minecraft")
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 0, raising=False)
    assert sandbox.player_uid() is None and "PLAYER_UID" not in " ".join(sandbox.build_argv("minecraft"))
    monkeypatch.delattr(sandbox.os, "getuid", raising=False)                       # native Windows
    assert sandbox.player_uid() is None
    with pytest.raises(ValueError): sandbox.build_argv("nms")                      # not in the wizard: no image


def test_every_offered_game_has_an_image_and_a_chain():
    offered = {g for g in sandbox.registry.games() if sandbox.facts(g)["offered"]}
    assert offered == set(sandbox.IMAGES) == set(sandbox.CHAINS)
    for game, chain in sandbox.CHAINS.items():
        assert chain[0] == "base" and all((sandbox.ROOT / "lab" / "images" / l / "Dockerfile").is_file() for l in chain)
        df = sandbox.dockerfile(game).read_text(encoding="utf-8")
        assert f"ARG RUNTIME=gameanything-lab-{chain[-1]}" in df and "USER player" in df
        assert (game in sandbox.STEAM_IN_IMAGE) == (sandbox.facts(game)["build"] == "linux"), game     # every Steam game has Steam


def test_local_build_is_the_whole_chain_for_the_users_uid():
    a = sandbox.chain_argvs("stardew", uid=(1006, 1006))
    assert [x[x.index("-t") + 1] for x in a] == ["gameanything-lab-base", "gameanything-lab-steam", "gameanything-lab-dotnet", "gameanything-lab-stardew"]
    assert "PLAYER_UID=1006" in a[0] and "BASE=gameanything-lab-base" in a[1] and "BASE=gameanything-lab-steam" in a[2]
    assert "PLAYER_UID=1006" in a[-1] and "RUNTIME=gameanything-lab-dotnet" in a[-1]
    s = sandbox.chain_argvs("sims4", uid=None)
    assert [x[x.index("-t") + 1] for x in s][1] == "gameanything-lab-wine" and not any("PLAYER_UID" in " ".join(x) for x in s)


def test_pull_is_the_published_image_under_the_local_name():
    for game in sandbox.IMAGES:
        ref = sandbox.published_ref(game)
        assert ref.startswith(f"ghcr.io/aetherlabsai/gameanything-lab-{sandbox.IMAGES[game]}") and ("@sha256:" in ref or ref.endswith(":latest"))
        (p, t) = sandbox.pull_argvs(game, docker="dk")
        assert p == ["dk", "pull", "--platform", sandbox.PLATFORM, ref] and t == ["dk", "tag", ref, sandbox.image_tag(game)]
    for game, ref in sandbox.PUBLISHED.items():
        assert ref.startswith(f"{sandbox.REGISTRY}/{sandbox.image_tag(game)}@sha256:") and len(ref.split("@sha256:")[1]) == 64


def test_run_uses_the_users_uid_when_the_image_was_built_for_another():
    a = sandbox.run_argv("minecraft", "img", "/mc", saves_dir="/inst", image_uid=1000, uid=(1006, 1007))
    assert a[a.index("--user") + 1] == "1006:1007" and "HOME=/sandbox/home" in a
    assert "/mc:/game:ro" in a and "/inst:/saves:ro" in a and a[-1] == "img"
    assert "--user" not in sandbox.run_argv("minecraft", "img", "/mc", image_uid=1006, uid=(1006, 1006))   # built for her: nothing
    assert "--user" not in sandbox.run_argv("minecraft", "img", "/mc", uid=None)                         # Windows
    a = sandbox.run_argv("slay_the_spire", "img", "/sts", gpu=True, extra=[("/ws", "/workshop")], uid=None)
    assert "/ws:/workshop:ro" in a and "--gpus" in a


def test_viewer_port_is_published_on_loopback_only():
    """The viewer (and the Steam / EA sign-in window in it) must not be open on a server's public address: -p 127.0.0.1:6080:6080, and
    the docs and Dockerfile comments say the same (an SSH tunnel for a server)."""
    a = sandbox.run_argv("stardew", "img", "/g", uid=None)
    assert a[a.index("-p") + 1] == "127.0.0.1:6080:6080"
    a = sandbox.run_argv("stardew", "img", "/g", uid=None, port=6090)
    assert a[a.index("-p") + 1] == "127.0.0.1:6090:6080"
    assert sandbox.port_arg(6080, bind="0.0.0.0") == "0.0.0.0:6080:6080"                              # only when asked for
    import re
    docs = [sandbox.ROOT / "docs" / "sandbox-images.md", *sorted((sandbox.ROOT / "lab" / "images").glob("*/Dockerfile"))]
    for f in docs:
        assert not re.search(r"-p\s+(\d+:)?6080:6080", f.read_text(encoding="utf-8")), f"{f}: -p without 127.0.0.1"
    assert "ssh -L 6080:127.0.0.1:6080" in (sandbox.ROOT / "docs" / "sandbox-images.md").read_text(encoding="utf-8")


def test_apparmor_profile_per_host(tmp_path):
    """Ubuntu 24.04+ (AppArmor 4, abi/4.0) loads gameanything-steam.apparmor; Ubuntu 22.04 (AppArmor 3) the u2204 file; a host without
    AppArmor (Docker Desktop, SELinux distributions) nothing. Both files define the same profile, so the run option does not change."""
    def host(enabled, abi4):
        r = tmp_path / f"h{enabled}{abi4}"
        (r / "sys/module/apparmor/parameters").mkdir(parents=True)
        (r / "sys/module/apparmor/parameters/enabled").write_text("Y\n" if enabled else "N\n")
        (r / "etc/apparmor.d/abi").mkdir(parents=True); (r / "etc/apparmor.d/abi/3.0").write_text("")
        if abi4: (r / "etc/apparmor.d/abi/4.0").write_text("")
        return r
    assert sandbox.host_apparmor(host(True, True)) == 4 and sandbox.host_apparmor(host(True, False)) == 3
    assert sandbox.host_apparmor(host(False, True)) is None and sandbox.host_apparmor(tmp_path / "nothing") is None
    assert sandbox.apparmor_profile_file(4).name == "gameanything-steam.apparmor"
    assert sandbox.apparmor_profile_file(3).name == "gameanything-steam-u2204.apparmor"
    for abi in (3, 4):
        f = sandbox.apparmor_profile_file(abi); text = f.read_text()
        assert f.is_file() and "profile gameanything-steam " in text and f"abi <abi/{abi}.0>" in text
        assert ("userns," in text) == (abi == 4)
        load = sandbox.apparmor_load_commands(abi)
        assert load[0][-2:] == [str(f), "/etc/apparmor.d/gameanything-steam"] and load[1][:3] == ["sudo", "apparmor_parser", "-r"]
    assert sandbox.apparmor_load_commands(abi=None) == [] or sandbox.host_apparmor() is not None


def test_steam_home_for_another_uid_is_explicit():
    """A published image is built for uid 1000. On a host user with another uid it runs with --user <uid>:<gid> and HOME=/sandbox/home,
    and the Steam volumes go there; an image built for the user's uid (lab setup --build) or no uid at all (Windows, root) keeps
    /home/player. The steam layer has ~/.steam/debian-installation/steamapps in both homes (install-steam.sh), so Docker does not
    create them as root."""
    assert sandbox.steam_home(image_uid=1000, uid=(1004, 1004)) == "/sandbox/home"
    assert sandbox.steam_home(image_uid=1000, uid=(1000, 1000)) == "/home/player"
    assert sandbox.steam_home(image_uid=1004, uid=(1004, 1004)) == "/home/player"          # rebuilt for her uid
    assert sandbox.steam_home(image_uid=1000, uid=None) == "/home/player"                  # Windows / root: no --user
    r = sandbox.steam_run_args("ga-steam-home", "ga-steam-games", apparmor=False, image_uid=1000, uid=(1004, 1004))
    assert "ga-steam-home:/sandbox/home" in r and "ga-steam-games:/sandbox/home/.steam/debian-installation/steamapps" in r
    run = sandbox.run_argv("stardew", "img", "/g", image_uid=1000, uid=(1004, 1004))
    assert run[run.index("--user") + 1] == "1004:1004" and "HOME=/sandbox/home" in run
    sh = (sandbox.ROOT / "lab" / "images" / "common" / "install-steam.sh").read_text()
    assert "install -d -o player -g player /home/player/.steam /home/player/.steam/debian-installation " in sh
    assert "-m 1777 /sandbox/home/.steam" in sh


def test_lab_setup_image_pulls_first_then_builds(monkeypatch):
    """`lab setup --image GAME` pulls the published image and tags it; a failed pull (not logged in) falls back to the local chain
    build for the user's uid; --build skips the pull. A fake docker: only argv lists, nothing runs."""
    from gameanything import labdocker
    monkeypatch.setattr(sandbox, "PLATFORM", "linux/amd64")                         # an x86 computer (this test may run on a Mac)
    monkeypatch.setattr(sandbox, "player_uid", lambda: (1006, 1006))
    monkeypatch.setattr(labdocker, "_docker", lambda env=None: "docker")
    monkeypatch.setattr(labdocker, "image_store", lambda *a, **k: (None, None))     # not this machine's real disk
    seen = []
    assert labdocker.pull_images(["minecraft"], say=lambda *x: None, run=lambda argv: seen.append(argv) or 0) == 0
    assert seen == sandbox.pull_argvs("minecraft") and not any(a[1] == "build" for a in seen)          # pulled: nothing built
    seen.clear()
    fake = lambda argv: seen.append(argv) or (1 if argv[1] == "pull" else 0)                          # not logged in: pull fails
    assert labdocker.pull_images(["stardew"], say=lambda *x: None, run=fake) == 0
    builds = [a for a in seen if a[1] == "build"]
    assert seen[0][1] == "pull" and builds == sandbox.chain_argvs("stardew") and "PLAYER_UID=1006" in builds[0]
    assert labdocker.pull_images(["stardew"], say=lambda *x: None, run=fake, fallback=False) == 1
    seen.clear()
    assert labdocker.pull_images(["valheim"], build=True, say=lambda *x: None, run=lambda argv: seen.append(argv) or 0) == 0
    assert all(a[1] == "build" for a in seen) and len(seen) == 4
    assert labdocker.pull_images(["nms"], say=lambda *x: None, run=lambda argv: 0) == 2
    assert labdocker.build_images(["nms"], say=lambda *x: None, run=lambda argv: 0) == 2
    seen.clear()
    monkeypatch.setattr(labdocker, "pull_images", lambda games, say=print, build=False: seen.append((games, build)) or 0)
    assert labdocker.setup(["--image", "minecraft", "--yes"]) == 0 and seen == [(["minecraft"], False)]   # only the image was asked for
    assert labdocker.setup(["--image", "stardew", "--build", "--yes"]) == 0 and seen[-1] == (["stardew"], True)
    assert labdocker.setup(["--image", "stardew", "--steam", "--yes"]) == 0 and seen[-1] == (["stardew"], False)   # --steam: no-op


def test_lab_setup_image_on_apple_silicon_builds_the_arm64_chain(monkeypatch):
    """2026-10-31: no published arm64 images: an ARM computer builds the chain itself, for linux/arm64 (the Steam layer installs FEX
    there: install-steam.sh hands over to install-steam-fex.sh); games that cannot run under FEX are refused before any build."""
    from gameanything import labdocker
    monkeypatch.setattr(sandbox, "PLATFORM", "linux/arm64")
    monkeypatch.setattr(sandbox, "player_uid", lambda: (501, 20))
    monkeypatch.setattr(labdocker, "_docker", lambda env=None: "docker")
    seen = []
    assert labdocker.pull_images(["stardew"], say=lambda *x: None, run=lambda argv: seen.append(argv) or 0) == 0
    assert seen and all(a[1] == "build" and a[a.index("--platform") + 1] == "linux/arm64" for a in seen)     # no pull at all
    assert [a[a.index("-t") + 1] for a in seen][-1] == "gameanything-lab-stardew"
    for game in ("valheim", "minecraft", "sims4"):
        seen.clear()
        assert labdocker.pull_images([game], say=lambda *x: None, run=lambda argv: seen.append(argv) or 0) == 2 and seen == []
    steam = (sandbox.ROOT / "lab/images/common/install-steam.sh").read_text(encoding="utf-8")
    assert 'exec bash "$HERE/install-steam-fex.sh"' in steam
    assert "install-steam-fex.sh" in (sandbox.ROOT / "lab/images/steam/Dockerfile").read_text(encoding="utf-8")


def test_steam_layer_and_run_args(monkeypatch):
    """Sandbox plan task 5: every game that can come from Steam has the Steam layer in its image (CHAINS / STEAM_IN_IMAGE); its sandbox
    gets the Steam home and the game library as volumes, a 1 GB /dev/shm and only the seccomp/AppArmor profiles Steam's bubblewrap
    needs (no capability, no --privileged)."""
    monkeypatch.setattr(sandbox, "player_uid", lambda: (1006, 1006))
    monkeypatch.setattr(sandbox, "host_apparmor", lambda root="/": 4)
    a = sandbox.build_argv("stardew", steam=True)
    assert a == sandbox.build_argv("stardew") and "STEAM=1" not in a and "stardew" in sandbox.STEAM_IN_IMAGE
    assert "minecraft" not in sandbox.STEAM_IN_IMAGE and "sims4" not in sandbox.STEAM_IN_IMAGE
    r = sandbox.steam_run_args("/v/steam-home", "/v/games", image_uid=1006)       # an image built for her uid
    assert r[r.index("--shm-size") + 1] == "1g"
    assert any(x.startswith("seccomp=") and x.endswith("seccomp-steam.json") for x in r) and "apparmor=gameanything-steam" in r
    assert "/v/steam-home:/home/player" in r and "/v/games:/home/player/.steam/debian-installation/steamapps" in r
    assert "--privileged" not in r and "--cap-add" not in r
    assert "apparmor=gameanything-steam" not in sandbox.steam_run_args("a", "b", apparmor=False)     # Docker Desktop: no AppArmor
    assert "h:/sandbox/home" in sandbox.steam_run_args("h", "g", home="/sandbox/home")             # a pulled image run for her uid
    monkeypatch.setattr(sandbox, "host_apparmor", lambda root="/": None)
    assert "apparmor=gameanything-steam" not in sandbox.steam_run_args("a", "b")                    # auto: a host without AppArmor
    assert "apparmor=gameanything-steam" in sandbox.steam_run_args("a", "b", apparmor=True)
    common = sandbox.ROOT / "lab" / "images" / "common"
    for f in ("install-steam.sh", "ga-steam", "security/seccomp-steam.json", "security/gameanything-steam.apparmor",
              "security/gameanything-steam-u2204.apparmor"):
        assert (common / f).is_file(), f
    assert "install-steam.sh" in (sandbox.ROOT / "lab" / "images" / "steam" / "Dockerfile").read_text()
    assert "ga_need base java steam" in (sandbox.ROOT / "lab" / "images" / "sts" / "install.sh").read_text()


def test_ga_steam_reads_manifest_login_state_and_logon(tmp_path, monkeypatch):
    """ga-steam (stdlib, runs in the sandbox): the Linux depot from appmanifest, the UI login state, a fresh '[Logged On' line."""
    import importlib.machinery, importlib.util
    root = tmp_path / ".steam" / "debian-installation"
    (root / "steamapps").mkdir(parents=True); (root / "logs").mkdir()
    (root / "steamapps" / "appmanifest_413150.acf").write_text('"AppState"\n{\n\t"appid"\t\t"413150"\n\t"name"\t\t"Stardew Valley"\n'
        '\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Stardew Valley"\n\t"BytesDownloaded"\t\t"532939456"\n\t"BytesToDownload"\t\t"532939456"\n'
        '\t"InstalledDepots"\n\t{\n\t\t"413153"\n\t\t{\n\t\t\t"manifest"\t\t"6005910083361727734"\n\t\t\t"size"\t\t"708901690"\n\t\t}\n\t}\n}\n')
    (root / "logs" / "steamui_login.txt").write_text("[2026-10-29 11:37:27] [ WaitingForCredentials ] Received logon failure response\n")
    (root / "logs" / "connection_log.txt").write_text("[2026-10-29 10:00:00] [Logged On, 4, 7] [U:1:1] old\n"
                                                      "[2026-10-29 11:42:38] [Logged On, 4, 27] [U:1:1] RecvMsgClientLogOnResponse()\n")
    monkeypatch.setenv("GA_STEAM_ROOT", str(root))
    path = str(sandbox.ROOT / "lab" / "images" / "common" / "ga-steam")
    spec = importlib.util.spec_from_loader("ga_steam_t", importlib.machinery.SourceFileLoader("ga_steam_t", path))
    gs = importlib.util.module_from_spec(spec); spec.loader.exec_module(gs)
    a = gs.app_info(413150)
    assert a["state"] == "installed" and a["installed_depots"] == {"413153": {"manifest": "6005910083361727734", "size": "708901690"}}
    assert gs.login_state() == "WaitingForCredentials"
    assert gs.logged_on(0) == "2026-10-29 11:42:38"
    assert gs.logged_on(gs.ts_of("[2026-10-29 12:00:00]")) is None          # only a log-on after this start counts
    assert gs.app_info(1)["manifest"] is False


def test_the_ea_download_note_names_the_terms_of_play():
    zh, en = sandbox._verify_note("ea")
    assert "Terms of play" in zh and "Microsoft VC++" in en and "Steam" not in en    # a linked Steam account does not block it
    assert "Terms of play" not in sandbox._verify_note("microsoft")[1]


def test_the_sims4_wizard_option_for_the_ea_download_carries_the_terms_note():
    r = sandbox.sources("sims4", {"system": "linux", "arch": "x86_64", "docker": "ok", "mem_gb": 32})
    ea = next(o for o in r["options"] if o["source"] == "ea")
    assert "Terms of play" in ea["note_zh"] and "DOWNLOAD" in ea["note_en"]


@pytest.mark.parametrize("game", sorted(KIND))
def test_apple_silicon_offers_the_fex_sandbox_for_the_2d_steam_games(game):
    """2026-10-31 「把 FEX 镜像接进向导」: on Apple silicon the Steam download is offered (experimental, after native) for the 2D Steam
    games; 3D games, Minecraft and The Sims stay native only; native stays first and recommended."""
    r = sandbox.sources(game, sandbox.machine("mac", arch="arm64"))
    o = by_source(r)
    assert r["recommended"] == r["options"][0]["source"] == "native" and sum(x["recommended"] for x in r["options"]) == 1
    fex = game in sandbox.FEX_GAMES
    assert [x["source"] for x in r["options"] if x["available"]] == (["native", "steam"] if fex else ["native"])
    if fex:
        assert "实验性" in o["steam"]["reason_zh"] and "FEX" in o["steam"]["reason_en"]
        assert not o["mount"]["available"] and "Mac 版" in o["mount"]["reason_zh"]                  # her Mac build is no Linux build
        for docker in ("missing", "not_running"):                                                     # no Docker: greyed, says how
            d = by_source(sandbox.sources(game, sandbox.machine("mac", arch="arm64", docker=docker)))["steam"]
            assert not d["available"] and "Docker" in d["reason_zh"]
        assert ("不稳定" in o["steam"]["note_zh"] and "unstable" in o["steam"]["note_en"]) == (game == "terraria")
    assert sandbox.FEX_GAMES <= {g for g in KIND if g not in THREE_D}


def test_host_platform_is_arm64_on_apple_silicon():
    class P(sandbox.Probe):
        def __init__(self, pl, m, env=None): self.pl, self.m, self.e = pl, m, env or {}
        def platform(self): return self.pl
        def machine(self): return self.m
        def env(self): return self.e
        def run(self, argv, timeout=6): return None
    assert sandbox.host_platform(P("darwin", "arm64")) == "linux/arm64"
    assert sandbox.host_platform(P("linux", "aarch64")) == "linux/arm64"
    assert sandbox.host_platform(P("darwin", "x86_64")) == sandbox.host_platform(P("linux", "x86_64")) == "linux/amd64"
    assert sandbox.host_platform(P("darwin", "arm64", {"GAMEANYTHING_PLATFORM": "linux/amd64"})) == "linux/amd64"
