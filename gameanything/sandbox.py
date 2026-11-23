"""The user's own sandbox (decided 2026-10-29): which computer it runs on, and where the game comes from on that computer.

The recommended way is a Docker sandbox on the user's computer (images without game files: lab/images/). The game comes either from
the user's own game folder, mounted read-only (mods go into the sandbox's own layer), or from a download inside the sandbox with the
user's Steam, EA App or Microsoft account. Which of these work depends on the game and the computer's system:

    game kind (game.yaml `sandbox: build:`)        Linux                    Windows                     macOS
    linux   (Stardew, Terraria, Slay the Spire,    mount  recommended       mount  greyed (Windows      mount  greyed (Mac build)
             Overcooked 2, Cities, Civ VI,         steam  optional                 build installed)     steam  recommended
             Valheim, KSP)                                                  steam  recommended          (3D: native recommended, below)
    java    (Minecraft: the jar runs anywhere)     mount  recommended, microsoft optional, on every system. The sandbox starts the game
                                                   OFFLINE (a local player name, single-player): the Microsoft account option only
                                                   downloads the files, it is never needed to play or to test mods (decided 2026-10-29)
    windows (The Sims 4: the Windows build         mount  greyed (usually   mount  recommended          mount  greyed (Mac build)
             under Wine)                                  not installed)    ea     optional             ea     (3D: native recommended)
                                                   ea     recommended
    macOS: NO sandbox at all, native mode only (her decision 2026-10-30, 「Mac 只支持本机」): every sandbox option is greyed with the
    reason and native mode is the recommended option, listed first. Why: a game whose sandbox needs a GPU (game.yaml `sandbox: gpu:`
    required, e.g. Minecraft 26.x; recommended, the default of a 3D game) has none in Docker Desktop's VM (decided 2026-10-29); the 2D
    games come from Steam, and the 32-bit Steam client crashes under qemu-i386 in Docker Desktop on Apple silicon (tested 2026-10-30).
    Docker missing / not running: every sandbox option greyed, how to get Docker, native mode as the fallback. 3D game and less than 16 GB of
    memory: a warning only. Apple silicon (and other ARM computers): the images are linux/amd64, so a warning that it runs emulated.
    `sandbox: {offered: false}` (No Man's Sky) or no `sandbox:` block: not in the wizard.

    detect(env=None, hub=False, probe=None)   the computer the sandbox will run on: {system, arch, chip, wsl, docker, memory_gb, where,
                                              detected}. Under the hub that is the server (this process runs there), so its system decides.
                                              system None = detection failed: the wizard asks (SYSTEMS)
    sources(game, machine)                    {game, offered, system, options: [{source, available, recommended, reason_zh, reason_en,
                                              note_zh, note_en}], warnings: [{code, zh, en}], docker, fallback, recommended}; the
                                              recommended option first (source "native" only on a Mac for a game that needs a GPU)
    facts(game)                               the game.yaml `sandbox:` block with its defaults
    player_uid() / build_argv() / run_argv()  the user's own uid passed to every image build (--build-arg PLAYER_UID) and, for an image
                                              built for another uid, at run time (--user): private mounted files (Minecraft's 0600
                                              level.dat) stay readable. `gameanything lab setup --image GAME` uses them

Every text has a Chinese (the source) and an English version. Read-only: nothing is installed or started here.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import games as registry

SYSTEMS = ("linux", "windows", "mac")
SOURCES = ("mount", "steam", "ea", "microsoft")
GPUS = ("none", "recommended", "required")     # game.yaml sandbox.gpu; default: recommended for a 3D game, else none
BUILDS = ("linux", "java", "windows")
DOWNLOAD_OF = {"linux": "steam", "java": "microsoft", "windows": "ea"}
MEMORY_3D_GB = 16
SYS_ZH = {"linux": "Linux", "windows": "Windows", "mac": "Mac"}
STORE = {"steam": ("Steam", "Steam"), "ea": ("EA App", "the EA App"), "microsoft": ("微软账号", "a Microsoft account")}


def facts(game: str) -> dict:
    """{offered, build, download, three_d, gpu} from the game's game.yaml `sandbox:` block. No block = not offered."""
    return facts_of(registry.games().get(game) or {}, game)


def facts_of(spec, game=None) -> dict:
    """facts() of one game.yaml dict (also one not registered yet: `gameanything game check`)."""
    game = game or spec.get("id")
    b = spec.get("sandbox")
    if not isinstance(b, dict) or b.get("offered") is False:
        return {"offered": False, "build": None, "download": None, "three_d": False, "gpu": "none"}
    build = b.get("build")
    if build not in BUILDS: raise ValueError(f"{game}: game.yaml sandbox.build must be one of {', '.join(BUILDS)}, not {build!r}")
    dl = b.get("download") or DOWNLOAD_OF[build]
    if dl not in SOURCES[1:]: raise ValueError(f"{game}: game.yaml sandbox.download must be steam, ea or microsoft, not {dl!r}")
    three_d = bool(b.get("three_d", False))
    gpu = b.get("gpu") or ("recommended" if three_d else "none")
    if gpu not in GPUS: raise ValueError(f"{game}: game.yaml sandbox.gpu must be one of {', '.join(GPUS)}, not {gpu!r}")
    return {"offered": True, "build": build, "download": dl, "three_d": three_d, "gpu": gpu}


def offered() -> list:
    """The game ids the wizard offers a sandbox for (registry order)."""
    return [g for g in registry.games() if facts(g)["offered"]]


# ---------------------------------------------------------------- the computer
class Probe:
    """What detect() looks at; the tests pass a fake."""
    def platform(self): return sys.platform
    def machine(self): return platform.machine()
    def env(self): return dict(os.environ)

    def run(self, argv, timeout=6):
        try: r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError): return None
        return r.stdout.strip() if r.returncode == 0 else None

    def which(self, name): return shutil.which(name)

    def read(self, path):
        try: return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError: return None

    def windows_memory(self):
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                            ("ae", ctypes.c_ulonglong)]
            m = MS(); m.len = ctypes.sizeof(MS)
            return m.total if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else None
        except (AttributeError, OSError, ValueError): return None


def _system(p: Probe):
    pl = p.platform()
    if pl == "darwin": return "mac"
    if pl.startswith("win") or pl == "cygwin": return "windows"
    if pl.startswith("linux"): return "linux"
    return None


def _arch(p: Probe, system):
    m = (p.machine() or "").lower()
    e = p.env()
    if system == "windows": m = (e.get("PROCESSOR_ARCHITEW6432") or e.get("PROCESSOR_ARCHITECTURE") or m).lower()
    if m in ("x86_64", "amd64", "x64", "i686", "i386", "x86"): arch = "x86_64"
    elif m in ("arm64", "aarch64", "armv8", "armv8l", "arm64e"): arch = "arm64"
    else: arch = m or None
    if system == "mac" and arch == "x86_64" and p.run(["sysctl", "-n", "sysctl.proc_translated"]) == "1":
        arch = "arm64"                                  # an x86_64 Python under Rosetta on Apple silicon
    return arch


def _wsl(p: Probe):
    v = (p.read("/proc/version") or "").lower()
    return "microsoft" in v or "wsl" in v


def _memory_gb(p: Probe, system):
    b = None
    if system == "linux":
        for line in (p.read("/proc/meminfo") or "").splitlines():
            if line.startswith("MemTotal:"):
                try: b = int(line.split()[1]) * 1024
                except (IndexError, ValueError): pass
    elif system == "mac":
        v = p.run(["sysctl", "-n", "hw.memsize"]); b = int(v) if v and v.isdigit() else None
    elif system == "windows": b = p.windows_memory()
    return round(b / 2 ** 30, 1) if b else None


def _docker(p: Probe):
    """'ok' (the engine answers) | 'not_running' (a client, no engine) | 'missing', and the engine's own memory (Docker Desktop's VM)."""
    d = p.env().get("GAMEANYTHING_DOCKER") or p.which("docker")
    if not d: return "missing", None
    out = p.run([d, "info", "--format", "{{.MemTotal}}"], timeout=8)
    if out is None: return "not_running", None
    try: mem = int(out)
    except ValueError: return "ok", None
    if mem <= 0: return "not_running", None        # some clients (27.x) print 0 and exit 0 when the engine does not answer
    return "ok", round(mem / 2 ** 30, 1)


def _gpus(p: Probe, system):
    """The NVIDIA GPUs' names (nvidia-smi on the host), [] when there is none or no driver; the Mac has no CUDA."""
    if system not in ("linux", "windows") or not p.which("nvidia-smi"): return []
    out = p.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=8)
    return [l.strip() for l in (out or "").splitlines() if l.strip()]


def detect(env=None, hub=False, probe=None) -> dict:
    """The computer the sandbox runs on. hub=True: this process runs on the hub server, and the server's system decides for everyone."""
    p = probe or Probe()
    if env is not None and probe is None:
        p.env = lambda: dict(env)
    system = _system(p)
    arch = _arch(p, system) if system else None
    chip = ("apple" if arch == "arm64" else "intel") if system == "mac" else None
    docker, docker_mem = _docker(p)
    mem = _memory_gb(p, system) if system else None
    return {"system": system, "arch": arch, "chip": chip, "wsl": system == "linux" and _wsl(p), "docker": docker,
            "memory_gb": docker_mem or mem, "host_memory_gb": mem, "gpus": _gpus(p, system) if system else [], "where": _where(p, system, hub), "detected": system is not None}


def _where(p, system, hub) -> str:
    """server | this_computer. The hub, a Linux without a display (a server nobody sits at: QA2 2026-10-30 the single-user UI on a
    headless server said 「你电脑上的沙箱」), or GAMEANYTHING_WHERE=server; else her own computer."""
    e = p.env(); w = (e.get("GAMEANYTHING_WHERE") or "").strip().lower()
    if w in ("server", "this_computer"): return w
    if hub: return "server"
    if system == "linux" and not (e.get("DISPLAY") or e.get("WAYLAND_DISPLAY")) and not _wsl(p): return "server"
    return "this_computer"


def machine(system, arch="x86_64", docker="ok", memory_gb=32, where="this_computer") -> dict:
    """A machine dict as detect() returns it, for a system the user picked by hand (detection failed) and for the tests."""
    if system not in SYSTEMS: raise ValueError(f"system must be one of {', '.join(SYSTEMS)}")
    return {"system": system, "arch": arch, "chip": ("apple" if arch == "arm64" else "intel") if system == "mac" else None, "wsl": False,
            "docker": docker, "memory_gb": memory_gb, "host_memory_gb": memory_gb, "gpus": [], "where": where, "detected": False}


# ---------------------------------------------------------------- the rules table
def _mount_cell(build, system):
    """(available, recommended, reason_zh, reason_en) of 'mount my game folder'."""
    s = SYS_ZH[system]
    if build == "java":
        if system != "linux":                   # her launcher has only its own system's native jars (and Java): the sandbox adds the Linux ones
            return True, True, "Minecraft 的游戏文件（jar）在哪个系统上都一样：直接用你电脑上的，只读挂载，不改你的游戏和存档；" \
                "沙箱第一次会补下几个 Linux 用的小文件（官方公开下载，不用登录）。" + MC_OFFLINE[0], \
                "Minecraft's game files (the jar) are the same on every system: your own copy is mounted read-only, your game and saves stay " \
                "as they are; the first time, the sandbox downloads a few small Linux files (public, no login). " + MC_OFFLINE[1]
        return True, True, "Minecraft 的游戏文件（jar）在哪个系统上都一样：直接用你电脑上的，只读挂载，不改你的游戏和存档。" + MC_OFFLINE[0], \
            "Minecraft's game files (the jar) are the same on every system: your own copy is mounted read-only, your game and saves stay " \
            "as they are. " + MC_OFFLINE[1]
    if build == "linux":
        if system == "linux":
            return True, True, "用你电脑上已经装好的游戏：只读挂载，mod 写在沙箱自己的一层，不改你的游戏和存档", \
                "Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are"
        return False, False, f"你电脑上装的是 {s} 版，沙箱要的是 Linux 版", f"Your computer has the {system_en(system)} build; the sandbox needs the Linux build"
    # windows build under Wine (The Sims 4)
    if system == "windows":
        return True, True, "用你电脑上已经装好的游戏：只读挂载，mod 写在沙箱自己的一层，不改你的游戏和存档", \
            "Uses the game already on your computer: mounted read-only, mods go into the sandbox's own layer, your game and saves stay as they are"
    if system == "mac":
        return False, False, "你电脑上装的是 Mac 版，沙箱要的是 Windows 版（用 Wine 运行）", \
            "Your computer has the Mac build; the sandbox needs the Windows build (it runs under Wine)"
    return False, False, "Linux 上一般没装这个游戏（沙箱要的是 Windows 版，用 Wine 运行）", \
        "This game is usually not installed on Linux (the sandbox needs the Windows build, run under Wine)"


# Minecraft in the sandbox (decided 2026-10-29, the product behaviour): started offline with a local player name, single-player; no
# Microsoft login to develop and test mods. The Microsoft account option only downloads the game files.
MC_OFFLINE = ("沙箱里用离线玩家名直接进单人存档，开发和测试 mod 都不用登录微软账号",
              "In the sandbox the game starts offline with a local player name, in single-player: developing and testing mods needs no "
              "Microsoft login")


def _download_cell(build, system, store):
    """(available, recommended, reason_zh, reason_en) of 'log in and download in the sandbox'."""
    zh, en = STORE[store]
    rec = not _mount_cell(build, system)[0]                    # recommended exactly where the mount cannot work
    if store == "microsoft":                                   # the account only fetches the files: playing needs none (MC_OFFLINE)
        return True, rec, "电脑上还没有 Minecraft 时：用微软账号登录，只用来下载一次游戏文件，存在你电脑上以后复用。" \
            "登录在你自己的手机或电脑上做（打开 microsoft.com/link 输入沙箱显示的代码），沙箱里不输入密码；" \
            "玩和测试 mod 不需要它，沙箱里用离线玩家名玩单人", \
            "When Minecraft is not on your computer yet: sign in with a Microsoft account only to download the game files once (kept " \
            "on your computer and reused). You sign in on your own phone or computer (microsoft.com/link and the code the sandbox " \
            "shows); no password is typed into the sandbox. Playing and testing mods do not need it, the sandbox plays single-player " \
            "offline with a local player name"
    if rec:
        return True, True, f"在沙箱里登录你自己的 {zh}，下载一次存在你电脑上，以后复用", \
            f"Log in to your own {en} inside the sandbox; the game is downloaded once, kept on your computer and reused"
    return True, False, f"也可以在沙箱里登录 {zh} 另外下载一份（要多占硬盘，第一次下载要一阵子）", \
        f"You can also log in to {en} inside the sandbox and download a separate copy (more disk space, the first download takes a while)"


def system_en(system): return {"linux": "Linux", "windows": "Windows", "mac": "Mac"}[system]


def _verify_note(store):
    zh, en = STORE[store]
    z, e = (f"第一次登录 {zh} 可能要手机或邮箱里的验证码，准备好手机",
            f"The first login to {en} may ask for a code from your phone or email: keep your phone at hand")
    if store == "ea":                     # lab 2026-10-29: download = EA's own "Terms of play" (EA + Microsoft VC++ agreements)
        z += "；下载前 EA App 会显示「Terms of play」（EA 用户协议 + 微软 VC++ 运行库协议），点 DOWNLOAD 就是同意，由你自己决定"
        e += ("; before the download the EA App shows 'Terms of play' (EA User Agreement + Microsoft VC++ runtime agreements): clicking "
              "DOWNLOAD agrees to them, your decision")
    return z, e


DOCKER_HELP = {
    "linux": ("这台电脑没装 Docker：装 Docker Engine（sudo apt install docker.io），把自己加进 docker 组（sudo usermod -aG docker $USER），重新登录后再来",
              "Docker is not installed: install Docker Engine (sudo apt install docker.io), add yourself to the docker group "
              "(sudo usermod -aG docker $USER), log in again and come back"),
    "windows": ("这台电脑没装 Docker：装 Docker Desktop（https://www.docker.com/products/docker-desktop/，选 WSL 2），装好打开它再来",
                "Docker is not installed: install Docker Desktop (https://www.docker.com/products/docker-desktop/, with WSL 2), start it and come back"),
    "mac": ("这台电脑没装 Docker：装 Docker Desktop（https://www.docker.com/products/docker-desktop/，按你的芯片选 Apple 或 Intel 版），装好打开它再来",
            "Docker is not installed: install Docker Desktop (https://www.docker.com/products/docker-desktop/, the Apple or Intel build for your "
            "chip), start it and come back"),
}
DOCKER_DOWN = ("Docker 装了但没在运行：打开 Docker Desktop（Linux：sudo systemctl start docker）再来",
               "Docker is installed but not running: start Docker Desktop (Linux: sudo systemctl start docker) and come back")
# macOS: Docker Desktop's Linux VM has no GPU. A game whose sandbox needs one is not supported in a Mac sandbox: native mode instead.
GPU_MAC = {
    "required": ("Mac 上不支持：这个游戏一定要显卡，Mac 上的沙箱没有显卡，游戏开不了窗口；请用本机模式",
                 "Not supported on a Mac: this game needs a graphics card, and the sandbox on a Mac has none, so the game cannot open its "
                 "window; use native mode"),
    "minecraft": ("Mac 上不支持：新版 Minecraft（26.x）一定要显卡，Mac 上的沙箱没有显卡，游戏开不了窗口；请用本机模式",
                  "Not supported on a Mac: newer Minecraft (26.x) needs a graphics card, and the sandbox on a Mac has none, so the game "
                  "cannot open its window; use native mode"),
    "recommended": ("Mac 上不支持：这是 3D 游戏，要显卡，Mac 上的沙箱没有显卡；请用本机模式",
                    "Not supported on a Mac: this 3D game needs a graphics card, and the sandbox on a Mac has none; use native mode"),
}
# macOS, any game (her decision 2026-10-30 after the Docker Desktop test on Apple silicon): the Steam client in the sandbox is a 32-bit
# x86 program; Rosetta for Linux translates only 64-bit code, so it runs under qemu-i386 and crashes ("uncaught target signal 11") right
# after its self-update, every time. Every 2D game here comes from Steam, so a Mac has no sandbox: native mode only.
MAC_NO_SANDBOX = ("Mac 上不支持沙箱：沙箱里的 Steam 客户端在 Mac 上跑不起来（实测会崩溃）；请用本机模式，直接用你电脑上的游戏",
                  "No sandbox on a Mac: the Steam client inside the sandbox cannot run on a Mac (it crashes, tested); use native mode, "
                  "with the game on your computer")
# Apple silicon, the 2D Steam games (her go-ahead 2026-10-31, 「把 FEX 镜像接进向导」): the arm64 images run Steam and the game under
# FEX-Emu (lab/images/common/install-steam-fex.sh; sandbox-hiccups.md F1-F9). EXPERIMENTAL: built on her computer (no published arm64
# image), much slower than native mode, so native mode stays the recommended option and the Steam download is offered after it.
FEX_GAMES = {"slay_the_spire", "stardew", "terraria"}
FEX_TESTED = {"slay_the_spire": "smoke mod reached the menu under FEX (2026-10-31, the lab/images/fex prototype)",
              "stardew": "smoke mod reached the menu under FEX (2026-10-31, the lab/images/fex prototype)",
              "terraria": "UNSTABLE: tModLoader (.NET 8) crashed under FEX in 6 of 7 starts, mods or not (2026-10-31)"}
# Terraria under FEX (2026-10-31, her Mac): without mods 1 of 3 starts reached the menu, with the smoke mod 0 of 4; the others died
# reading the game's own assets (AccessViolation in LzxDecoder, "Failed to load asset Fonts/..."), though the files read back the same:
# .NET 8 computes wrong under FEX. Offered anyway (her decision, 「把这3个游戏接入向导」) with this warning.
FEX_NOTE = {"terraria": ("注意：Terraria（tModLoader，.NET 8）在 FEX 下很不稳定：实测 7 次启动只有 1 次（不带 mod）进到主菜单，"
                         "其余都在读游戏资源时崩溃。要测 mod 请用本机模式",
                         "Note: Terraria (tModLoader, .NET 8) is unstable under FEX: 1 of 7 starts (without mods) reached the menu "
                         "in the test, the others crashed reading the game's assets. To test mods use native mode")}
MAC_FEX = ("实验性：沙箱里登录你自己的 Steam 下载 Linux 版，Steam 和游戏用 FEX 把 x86 翻译成 ARM 运行。比本机模式慢很多（8 GB 内存的 Mac "
           "启动要几分钟），镜像要在你电脑上构建（约 15 分钟、4-6 GB）",
           "Experimental: log in to your own Steam inside the sandbox and download the Linux build; Steam and the game run under FEX "
           "(x86 translated to ARM). Much slower than native mode (minutes to start on an 8 GB Mac); the image is built on your computer "
           "(about 15 minutes, 4-6 GB)")
MAC_INTEL = ("Mac 上不支持：Intel 芯片的 Mac 上沙箱还没测试过；请用本机模式，直接用你电脑上的游戏",
             "Not supported on a Mac: sandboxes on an Intel Mac are not tested yet; use native mode, with the game on your computer")
NATIVE_MAC = ("推荐：Mac 上用本机模式，直接用你电脑上的游戏和显卡（先备份存档，只改 Mods 文件夹）",
              "Recommended: on a Mac use native mode, with the game and graphics card on your computer (saves are backed up first, only the "
              "Mods folder changes)")
NATIVE_FALLBACK = ("也可以用本机模式：直接装进你电脑上的游戏（先备份存档，只改 Mods 文件夹）",
                   "Or use native mode: install straight into the game on your computer (saves are backed up first, only the Mods folder changes)")


def _warnings(f, m):
    out = []
    mem = m.get("memory_gb")
    if f["three_d"] and mem is not None and mem < MEMORY_3D_GB:
        out.append({"code": "low_memory", "zh": f"这是 3D 游戏，建议至少 {MEMORY_3D_GB} GB 内存，这台电脑（给 Docker 的）只有 {mem:g} GB：可以试，但可能很卡或闪退",
                    "en": f"This is a 3D game: at least {MEMORY_3D_GB} GB of memory is recommended and this computer (Docker) has {mem:g} GB. "
                          "You can try, but it may be slow or crash"})
    if f["gpu"] != "none" and m["system"] == "mac":
        if f["gpu"] == "required":
            out.append({"code": "mac_no_gpu", "zh": "Mac 上的沙箱没有显卡，这个游戏一定要显卡，在沙箱里开不了：建议本机模式",
                        "en": "Sandboxes on a Mac have no graphics card and this game needs one, so it cannot start there: use native mode"})
        else:
            out.append({"code": "mac_no_gpu", "zh": "Mac 上的沙箱没有显卡，3D 游戏不支持在沙箱里跑：请用本机模式",
                        "en": "Sandboxes on a Mac have no graphics card: 3D games are not supported in the sandbox; use native mode"})
    if m.get("arch") == "arm64":
        out.append({"code": "emulated", "zh": "这台电脑是 ARM 芯片（如 Apple 芯片）：沙箱里的 Steam 和游戏是 x86 程序，用 FEX 翻译运行（实验性），"
                                              f"比本机慢很多，建议至少 {MEMORY_3D_GB} GB 内存",
                    "en": "This computer has an ARM chip (e.g. Apple silicon): Steam and the game in the sandbox are x86 programs and run "
                          f"under FEX (experimental), much slower than native; at least {MEMORY_3D_GB} GB of memory is recommended"})
    return out


def sources(game: str, m: dict) -> dict:
    """The wizard's 「游戏从哪来」 options for one game on machine m (detect() or machine()). The recommended option comes first;
    options that cannot work stay in the list, greyed (available False) with the reason."""
    f = facts(game)
    out = {"game": game, "offered": f["offered"], "system": m.get("system"), "where": m.get("where", "this_computer"), "docker": m.get("docker"),
           "options": [], "warnings": [], "fallback": None, "ask_system": False}
    if not f["offered"]:
        out["reason_zh"], out["reason_en"] = "这个游戏不在沙箱向导里（用本机模式）", "This game is not in the sandbox wizard (use native mode)"
        out["fallback"] = "native"; return out
    system = m.get("system")
    if system not in SYSTEMS:
        out["ask_system"] = True                        # detection failed: the wizard asks which system this is
        return out
    opts = []
    a, r, zh, en = _mount_cell(f["build"], system)
    opts.append({"source": "mount", "available": a, "recommended": r, "reason_zh": zh, "reason_en": en, "note_zh": "", "note_en": ""})
    a, r, zh, en = _download_cell(f["build"], system, f["download"])
    nz, ne = _verify_note(f["download"])
    opts.append({"source": f["download"], "available": a, "recommended": r, "reason_zh": zh, "reason_en": en, "note_zh": nz, "note_en": ne})
    if m.get("docker") != "ok":
        hz, he = DOCKER_HELP[system] if m.get("docker") == "missing" else DOCKER_DOWN
        for o in opts: o.update(available=False, recommended=False, reason_zh=hz, reason_en=he)
        out["fallback"] = "native"
        out["fallback_zh"], out["fallback_en"] = NATIVE_FALLBACK
    opts.sort(key=lambda o: 0 if _mount_cell(f["build"], system)[1] == (o["source"] == "mount") else 1)   # the table's recommended one first
    if system == "mac":                                  # her decision 2026-10-30: 「Mac 只支持本机」: every sandbox option greyed
        fex = m.get("chip") == "apple" and game in FEX_GAMES and f["gpu"] == "none"      # 2026-10-31: the 2D Steam games under FEX
        if f["gpu"] != "none": gz, ge = GPU_MAC[game] if f["gpu"] == "required" and game in GPU_MAC else GPU_MAC[f["gpu"]]
        elif m.get("chip") == "apple": gz, ge = MAC_NO_SANDBOX
        else: gz, ge = MAC_INTEL
        for o in opts:
            if fex and o["source"] == "mount": o.update(recommended=False)     # its own reason: the Mac build is installed, not Linux
            elif fex and o["source"] == "steam":                               # without Docker it keeps the how-to-get-Docker reason
                if m.get("docker") == "ok": o.update(available=True, recommended=False, reason_zh=MAC_FEX[0], reason_en=MAC_FEX[1])
                if game in FEX_NOTE: o.update(note_zh=FEX_NOTE[game][0] + "；" + o["note_zh"], note_en=FEX_NOTE[game][1] + "; " + o["note_en"])
            else: o.update(available=False, recommended=False, reason_zh=gz, reason_en=ge)
        nz, ne = NATIVE_MAC
        opts.insert(0, {"source": "native", "available": True, "recommended": True, "reason_zh": nz, "reason_en": ne, "note_zh": "", "note_en": ""})
        out["fallback"] = "native"
        out["fallback_zh"], out["fallback_en"] = NATIVE_MAC
    out["options"] = opts
    out["recommended"] = next((o["source"] for o in opts if o["recommended"]), None)
    out["warnings"] = _warnings(f, m)
    return out


def all_sources(m: dict) -> dict:
    return {g: sources(g, m) for g in registry.games()}


# ---------------------------------------------------------------- the images: always built (and run) for the user's own uid
# A mounted save can be private to its owner (a Minecraft world's level.dat is 0600), and the game in the sandbox runs as `player`.
# So every build passes --build-arg PLAYER_UID=<the user's uid>, and an image built for another uid (a pulled one: uid 1000) is run
# with --user <uid>:<gid> instead. Nobody types this by hand.
#   Linux (and WSL 2: the files in the distro keep their Linux owner): the uid of the user running GameAnything (id -u).
#   Mac (Docker Desktop shares the files through its VM): the Mac uid (501 ...) is passed the same way; the VM's file sharing shows the
#        files as readable to the container, so a mismatch does no harm there either.
#   Windows without WSL (C:\ shared into the VM): Windows has no uid, and shared drives appear as root, mode 0777, readable by every
#        user: nothing is passed, the image keeps uid 1000.
ROOT = Path(__file__).resolve().parents[1]
IMAGES = {"stardew": "stardew", "minecraft": "minecraft", "ksp": "ksp", "slay_the_spire": "sts", "terraria": "terraria",
          "valheim": "valheim", "overcooked2": "overcooked2", "cities_skylines": "cities", "civ6": "civ6", "sims4": "sims4"}   # game -> lab/images/<dir>
IMAGE_UID = 1000                                  # the Dockerfiles' default PLAYER_UID (the published images)
UID_LABEL = "org.gameanything.player-uid"         # each image records the uid it was built for
# The shared layers (lab/images/<layer>/Dockerfile), in build order, under each game's own layer (docs/sandbox-images.md):
#   base (Ubuntu 24.04 by digest, apt pinned to one snapshot day, screen + viewer + sound + Python) -> steam (the Steam bootstrap)
#   -> dotnet (.NET SDK 8 + Unity / FNA libraries);  base -> java (OpenJDK 25);  base -> wine (Wine 11.19 + DXVK + CPython 3.7).
# Slay the Spire adds the Steam layer in its own image (the shared Steam layer sits under .NET, not under Java).
CHAINS = {"stardew": ("base", "steam", "dotnet"), "ksp": ("base", "steam", "dotnet"), "terraria": ("base", "steam", "dotnet"),
          "valheim": ("base", "steam", "dotnet"), "overcooked2": ("base", "steam", "dotnet"), "cities_skylines": ("base", "steam", "dotnet"),
          "civ6": ("base", "steam"), "minecraft": ("base", "java"), "slay_the_spire": ("base", "java"), "sims4": ("base", "wine")}
STEAM_IN_IMAGE = {g for g, c in CHAINS.items() if "steam" in c} | {"slay_the_spire"}
def host_platform(probe=None) -> str:
    """The images' platform on this computer, said on every pull / build / run: linux/amd64, and linux/arm64 on an ARM computer
    (Apple silicon, 2026-10-31): there the chain is built locally for arm64 and the Steam layer brings FEX-Emu (install-steam-fex.sh),
    because the x86 images under Rosetta fell to qemu-i386 for the 32-bit Steam client, which crashed (sandbox-hiccups.md M5).
    GAMEANYTHING_PLATFORM overrides it."""
    p = probe or Probe()
    v = (p.env().get("GAMEANYTHING_PLATFORM") or "").strip()
    if v in ("linux/amd64", "linux/arm64"): return v
    s = _system(p)
    return "linux/arm64" if s and _arch(p, s) == "arm64" else "linux/amd64"


PLATFORM = host_platform()
ARM_IMAGES = FEX_GAMES     # what an arm64 build can run (the 2D Steam games under FEX); there are no published arm64 images
REGISTRY = "ghcr.io/aetherlabsai"                  # the published images: PRIVATE packages for now (docker login ghcr.io with a read:packages PAT)
# The published image of each game, by digest (x86_64 only). `lab setup --image` pulls this and tags it as image_tag(game); a game
# without an entry pulls :latest. All of them, layers included, were rebuilt from base on 2026-10-30 from commit 3b2ecb0 (tags
# :20261030c, :3b2ecb0, :latest): every RUN with umask 022 + ga-readable, so the player (any uid) can read /opt/gameanything, /game,
# /saves, /usr/local/lib/gameanything, and /etc/passwd + /etc/group stay 666 for galab.ensure_account (a --user uid gets its line);
# with the plain-Docker tester's fixes of 124c14f, df83d2f, 81666bb (docs/sandbox-images.md "How they were built and pushed").
# civ6 and terraria were re-published alone from add7bc8 (tags :20261030d, :add7bc8, :latest) on the same published base/steam/dotnet:
# civ6 with ENV SCREEN=1600x900x24, terraria's layer writing /sandbox/saves/config.json (sandbox-hiccups.md #36-#37).
# sims4 was re-published alone from c31790a (tags :20261030e, :c31790a, :latest) on the same published base/wine: ga-sims4 run waits
# on the EA App's sign-in window (wait_signed_in, c61d40f) instead of stopping after 30 s (sandbox-hiccups.md #38).
# Then ALL fifteen were rebuilt from base again from 41de0a2 (tags :20261030g, :41de0a2, :latest; sandbox-hiccups.md #44-#47):
# galab.fit_output (the pointer reaches the whole Xorg screen), Noto Sans CJK + Droid Sans Fallback in base (+86 MB compressed),
# `rec` records the game's sound (rec.monitor), ga-ea gives the EA App the PulseAudio socket, ga-valheim names Steam Cloud saves.
# valheim and sims4 were then re-published alone from 656e75a (tags :20261031a, :656e75a, :latest) on the same published
# base/steam/dotnet and base/wine (sandbox-hiccups.md #49, #54): ga-valheim's help / run / stop text says Valheim 1.0 has no Cloud
# save tick (create, then Manage saves > Move to local, Remove the _backup_auto copy); ga-sims4 run closes TS4_Launcher_x64.exe when
# it alone is left (no TS4_x64.exe), waits 60 s and tries once more.
# stardew was re-published alone from bd340f4 (tags :20261101a, :bd340f4, :latest) on the same published base/steam/dotnet
# (e04f90d): the pinned Content Patcher 2.9.1 source + its offline NuGet packages + Ubuntu's .NET SDK 10; ga-sdv layer builds
# Content Patcher into the layer's Mods/ (1041 -> 1312 MB compressed).
# stardew was re-published alone again from 31120bb (tags :20261102a, :31120bb, :latest) on the same published base/steam/dotnet:
# only the bundled gameanything changed (a539a8a, sandbox-hiccups.md #57): `lab sandbox build` (= native build --install in the
# sandbox) stages a Content Patcher content pack (manifest.json with ContentPackFor, no .cs) instead of refusing it. Same size.
PUBLISHED = {
    "stardew": f"{REGISTRY}/gameanything-lab-stardew@sha256:45bc1cd4cd5185de82d450eb45a72d3d42cbfafd968a6d966b38e45edb3fccd4",
    "slay_the_spire": f"{REGISTRY}/gameanything-lab-sts@sha256:dc6e25fc7c3f31c1305c195b39711e5dac060b894a0a244545fd1b84c7fd7c8b",
    "minecraft": f"{REGISTRY}/gameanything-lab-minecraft@sha256:c414edbfe61b5df66abe71084a2366502fd655034f9cf7cebc187ce05e6dbfcf",
    "ksp": f"{REGISTRY}/gameanything-lab-ksp@sha256:dc3e726da95e0a7053fb138933ba201a536943e0b9b7302499003423e66cad4b",
    "terraria": f"{REGISTRY}/gameanything-lab-terraria@sha256:4bb09516f61e5c51293e0ae34f94e542605df417cc5afa435a43b81e512c12f6",
    "valheim": f"{REGISTRY}/gameanything-lab-valheim@sha256:b84ae6591c545b77e62e871baf02002f413a0ba4ed9d6ce4ffc4060377f3268a",
    "overcooked2": f"{REGISTRY}/gameanything-lab-overcooked2@sha256:69e0dc1fc214fa0eaf8bf87d204af77cf293b28e435854a77fac9bc7cd4c9bd6",
    "cities_skylines": f"{REGISTRY}/gameanything-lab-cities@sha256:5dd084ec176d2ccde3245a3723ef569125010f97646facf57c00259a1c6d0b89",
    "civ6": f"{REGISTRY}/gameanything-lab-civ6@sha256:5cdb7f382640c85590b688ce81cce2a01fe0d20a3f2701a5200113b6bf583de2",
    "sims4": f"{REGISTRY}/gameanything-lab-sims4@sha256:3031be7b1c03c837c3e68e4cede807b5f2795ca0f7310bb947a23f6dc7857afb",
}
IMAGE_TESTED = {"stardew", "slay_the_spire", "minecraft", "ksp", "terraria", "valheim", "overcooked2", "cities_skylines", "civ6", "sims4"}
# ^ the published image ran the game's smoke mod on plain Docker Engine (Ubuntu 22.04, NVIDIA; docs/sandbox-hiccups.md, 2026-10-29/30)
LAYERS_PUBLISHED = {          # the shared layers, for a maintainer building one game layer on top (build_argv runtime=)
    "base": f"{REGISTRY}/gameanything-lab-base@sha256:25c47851a4453354c0ce978fdf9fcaa9d283d4069153f333f2d058ef9f3508cd",
    "steam": f"{REGISTRY}/gameanything-lab-steam@sha256:e968d1cbe48783b6382e248a51d3b468c6e1744b5a11d5e181c1a5d45a117a2f",
    "dotnet": f"{REGISTRY}/gameanything-lab-dotnet@sha256:022104728f8758728e9b836eb87e157e25d14f6f1515680fccc9c0b7f42b1dc6",
    "java": f"{REGISTRY}/gameanything-lab-java@sha256:88156ab5b1c18ec5b4ea5ed16e7f12a23007bd9a5ddf11fa1ab27f48df9db81e",
    "wine": f"{REGISTRY}/gameanything-lab-wine@sha256:d317ee4f6b1737aa6844b74a2c0d14e7bf2f55967a3d87aa1ad0b0783c7621d4",
}


def player_uid():
    """(uid, gid) of the user running GameAnything, or None where none is needed (native Windows, root)."""
    getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)       # POSIX only: none on native Windows
    if getuid is None or getgid is None: return None
    uid = getuid()
    if uid == 0: return None                          # root reads every file anyway; the image keeps its own player (uid 1000)
    return uid, getgid()


def image_tag(game): return f"gameanything-lab-{IMAGES[game]}"
def layer_tag(layer): return f"gameanything-lab-{layer}"


def published_ref(game) -> str:
    """What `lab setup --image GAME` pulls: the pinned digest, else the package's :latest."""
    if game not in IMAGES: raise ValueError(f"no sandbox image for {game!r} yet (images: {', '.join(IMAGES)})")
    return PUBLISHED.get(game) or f"{REGISTRY}/{image_tag(game)}:latest"


def pull_argvs(game, docker="docker") -> list:
    """[docker pull <published>, docker tag <published> gameanything-lab-<game>]: the pulled image under the local name every other
    command uses (run_argv, the doctor)."""
    ref = published_ref(game)
    return [[docker, "pull", "--platform", PLATFORM, ref], [docker, "tag", ref, image_tag(game)]]


def dockerfile(game, root=None) -> Path:
    return Path(root or ROOT) / "lab" / "images" / IMAGES[game] / "Dockerfile"


def build_argv(game, tag=None, docker="docker", root=None, uid="auto", steam=False, runtime=None) -> list:
    """`docker build` of the game's own layer, always with the user's own uid (PLAYER_UID), on its runtime image (runtime: default
    the local gameanything-lab-<last layer of CHAINS[game]>). steam is kept for old callers: every game that can come from Steam has
    the Steam layer in its image now (STEAM_IN_IMAGE)."""
    if game not in IMAGES: raise ValueError(f"no sandbox image for {game!r} yet (images: {', '.join(IMAGES)})")
    u = player_uid() if uid == "auto" else uid
    argv = [docker, "build", "--platform", PLATFORM, "-f", str(dockerfile(game, root)), "-t", tag or image_tag(game)]
    if u is not None: argv += ["--build-arg", f"PLAYER_UID={u[0]}"]
    argv += ["--build-arg", f"RUNTIME={runtime or layer_tag(CHAINS[game][-1])}"]
    return argv + [str(Path(root or ROOT))]


def chain_argvs(game, docker="docker", root=None, uid="auto") -> list:
    """Every `docker build` of a local build from scratch, in order: the shared layers of CHAINS[game] (base gets PLAYER_UID; each next
    one --build-arg BASE=<the previous local tag>), then the game's own layer (build_argv). Layers already built are rebuilt from
    Docker's cache, so building a second game is quick."""
    if game not in IMAGES: raise ValueError(f"no sandbox image for {game!r} yet (images: {', '.join(IMAGES)})")
    u = player_uid() if uid == "auto" else uid
    r = Path(root or ROOT); out = []; prev = None
    for layer in CHAINS[game]:
        a = [docker, "build", "--platform", PLATFORM, "-f", str(r / "lab" / "images" / layer / "Dockerfile"), "-t", layer_tag(layer)]
        if layer == "base" and u is not None: a += ["--build-arg", f"PLAYER_UID={u[0]}"]
        if prev: a += ["--build-arg", f"BASE={layer_tag(prev)}"]
        out.append(a + [str(r)]); prev = layer
    return out + [build_argv(game, docker=docker, root=root, uid=uid)]


# The Steam client in a sandbox (wizard source "Steam download", sandbox plan task 5). Facts (2026-10-29):
# - Steam's bubblewrap check (pivot_root) needs user + mount namespaces. A container under the default AppArmor can make a user namespace
#   but not a mount namespace (docker-rt pod, 2026-10-29: `unshare --user --mount` -> Permission denied). Docker's default seccomp blocks unshare/mount/pivot_root and, on Ubuntu 24.04 hosts
#   (kernel.apparmor_restrict_unprivileged_userns=1), only an AppArmor profile with a `userns` rule may create one. Minimum, no capability,
#   no --privileged: the seccomp profile lab/images/common/security/seccomp-steam.json (Docker's default + unshare setns clone clone3 mount
#   umount2 pivot_root) and, on an AppArmor host, the profile gameanything-steam (Docker's default + userns, mount, pivot_root; loaded once
#   with sudo). Steam's web UI also needs a bigger /dev/shm than Docker's 64 MB.
# - the login cache lives in HOME (~/.steam/registry.vdf, config/loginusers.vdf, config/config.vdf) and the games in steamapps/: both are
#   volumes, so a new sandbox with the same volumes starts logged in and with its games (tested 2026-10-29 with a fresh Steam home: auto log-on in 61 s, no code, no new download).
# - native Stardew does not need Steam's runtime container: the game runs from the downloaded folder with or without the client.
STEAM_SHM = "1g"
# The AppArmor profile file to load (once, with sudo) on a Linux host with AppArmor. Both files define the same profile name
# (gameanything-steam), so the `docker run` option is the same; only the file differs with the host's AppArmor version:
#   AppArmor 4 (Ubuntu 24.04 and later: /etc/apparmor.d/abi/4.0 exists)  gameanything-steam.apparmor        (with the `userns` rule)
#   AppArmor 3 (Ubuntu 22.04, Debian 12: abi/3.0 only)                   gameanything-steam-u2204.apparmor  (no `userns` rule: 22.04 does
#                                                                         not restrict unprivileged user namespaces; tested 2026-10-29)
#   no AppArmor (Docker Desktop on Windows / Mac, Fedora / RHEL with SELinux)  nothing to load, no apparmor= option
APPARMOR_PROFILE = "gameanything-steam"
APPARMOR_FILES = {4: "gameanything-steam.apparmor", 3: "gameanything-steam-u2204.apparmor"}


def security_folder() -> Path:
    """lab/images/common/security: in the checkout, or in an installed package's _bundle (shipped.BUNDLED; a `uv tool install`ed
    gameanything has no lab/ folder: the first `lab sandbox up` of a Steam game failed on the missing seccomp file, 2026-10-30)."""
    from . import shipped
    for r in (ROOT, shipped.ROOT):
        d = r / "lab" / "images" / "common" / "security"
        if (d / "seccomp-steam.json").is_file(): return d
    return ROOT / "lab" / "images" / "common" / "security"


def host_apparmor(root="/"):
    """The host's AppArmor ABI for the Steam profile: 4, 3, or None when the kernel has no AppArmor enabled (this must run on the
    Docker host itself; Docker Desktop's VM has none)."""
    r = Path(root)
    try: enabled = (r / "sys/module/apparmor/parameters/enabled").read_text(encoding="utf-8").strip().upper().startswith("Y")
    except OSError: enabled = False
    if not enabled: return None
    return 4 if (r / "etc/apparmor.d/abi/4.0").exists() else 3


def apparmor_profile_file(abi=None, security_dir=None):
    """The profile file for the host's AppArmor (abi 4 / 3, default: host_apparmor()), None when there is no AppArmor."""
    abi = host_apparmor() if abi == "auto" or abi is None else abi
    if abi is None: return None
    sec = Path(security_dir or security_folder())
    return sec / APPARMOR_FILES[4 if int(abi) >= 4 else 3]


def apparmor_load_commands(abi=None, security_dir=None) -> list:
    """The two sudo commands that load the right profile once ([] without AppArmor)."""
    f = apparmor_profile_file(abi, security_dir)
    if f is None: return []
    return [["sudo", "install", "-m", "644", str(f), f"/etc/apparmor.d/{APPARMOR_PROFILE}"],
            ["sudo", "apparmor_parser", "-r", "-W", f"/etc/apparmor.d/{APPARMOR_PROFILE}"]]


def steam_home(image_uid=None, uid="auto") -> str:
    """The sandbox user's HOME, where the Steam volumes go: /home/player when the image was built for the user's uid (or no uid is
    passed: Windows, root), /sandbox/home when a pulled image (uid 1000) runs for another uid with --user (run_user_args)."""
    return "/sandbox/home" if run_user_args(image_uid, uid) else "/home/player"


def steam_run_args(home_volume, games_volume, security_dir=None, apparmor="auto", home=None, image_uid=None, uid="auto") -> list:
    """The extra `docker run` arguments for an image with the Steam layer: the user's Steam home and game library as volumes, a 1 GB
    /dev/shm, and the minimum security options Steam's bubblewrap needs (seccomp profile; AppArmor profile where the host has AppArmor).
    apparmor: "auto" (default) adds apparmor=gameanything-steam when this host has AppArmor (host_apparmor; load the file of
    apparmor_profile_file() first), True / False force it. home: default steam_home(image_uid, uid): /sandbox/home for a pulled image
    run for another uid, else /home/player (the image has ~/.steam/debian-installation/steamapps for both, owned or writable)."""
    sec = Path(security_dir or security_folder())
    if apparmor == "auto": apparmor = host_apparmor() is not None
    home = home or steam_home(image_uid, uid)
    argv = ["--shm-size", STEAM_SHM, "--security-opt", f"seccomp={sec / 'seccomp-steam.json'}"]
    if apparmor: argv += ["--security-opt", f"apparmor={APPARMOR_PROFILE}"]
    return argv + ["-v", f"{home_volume}:{home}", "-v", f"{games_volume}:{home}/.steam/debian-installation/steamapps"]


def image_player_uid(image, docker="docker"):
    """The uid an image was built for (its label), IMAGE_UID for an image without the label, None when docker cannot say."""
    try: r = subprocess.run([docker, "image", "inspect", "--format", "{{index .Config.Labels \"%s\"}}" % UID_LABEL, image],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError): return None
    if r.returncode != 0: return None
    v = r.stdout.strip()
    return int(v) if v.isdigit() else IMAGE_UID


def run_user_args(image_uid, uid="auto") -> list:
    """The run-time equivalent: an image built for another uid runs as the user (--user uid:gid, HOME on the writable volume)."""
    u = player_uid() if uid == "auto" else uid
    if u is None or int(image_uid if image_uid is not None else IMAGE_UID) == u[0]: return []
    return ["--user", f"{u[0]}:{u[1]}", "-e", "HOME=/sandbox/home", "-e", "JAVA_TOOL_OPTIONS=-Duser.home=/sandbox/home"]


# The viewer (noVNC, and with it the Steam / EA sign-in window) is published on the loopback address only. On a server: an SSH tunnel
# (ssh -L 6080:127.0.0.1:6080 <server>), then http://localhost:6080/vnc.html on your own computer. bind="0.0.0.0" opens it to every
# interface: never on a machine with a public address.
VIEWER_BIND = "127.0.0.1"


def port_arg(port=6080, bind=VIEWER_BIND) -> str:
    return f"{bind}:{port}:6080" if bind else f"{port}:6080"


def run_argv(game, image, game_dir, saves_dir=None, name=None, gpu=False, image_uid=None, uid="auto", docker="docker", port=6080,
             extra=(), bind=VIEWER_BIND) -> list:
    """`docker run` of a sandbox: the game folder (and saves) read-only, the sandbox's own volume, the viewer port (on 127.0.0.1 only),
    the user's uid."""
    n = name or f"ga-{IMAGES.get(game, game)}"
    argv = [docker, "run", "-d", "--platform", PLATFORM, "--name", n, "-p", port_arg(port, bind), *run_user_args(image_uid, uid)]
    if gpu: argv += ["--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=all"]
    argv += ["-v", f"{game_dir}:/game:ro"]
    if saves_dir: argv += ["-v", f"{saves_dir}:/saves:ro"]
    for host, inside in extra: argv += ["-v", f"{host}:{inside}:ro"]          # e.g. Slay the Spire's Workshop folder at /workshop
    return argv + ["-v", f"{n}:/sandbox", image]


# ---------------------------------------------------------------- the whole `docker run` of a project's sandbox (labsandbox.py)
# The user's own sandbox on plain Docker, no gamebench (2026-10-30, sandbox-hiccups.md #27): one container per game (ga-<image>, the name
# `lab login` looks for), labelled with the project; per project its own /sandbox volume (the game layer, the mods, logs); the store
# volumes are shared by every project of the user, so a sign-in and a download happen once.
TOOLS = {"stardew": "ga-sdv", "minecraft": "ga-mc", "ksp": "ga-ksp", "slay_the_spire": "ga-sts", "terraria": "ga-terraria",
         "valheim": "ga-valheim", "overcooked2": "ga-oc2", "cities_skylines": "ga-cities", "civ6": "ga-civ6", "sims4": "ga-sims4"}
# the game's folder in the Steam library (steamapps/common/<folder>), as Steam installs it
STEAM_FOLDER = {"stardew": "Stardew Valley", "slay_the_spire": "SlayTheSpire", "ksp": "Kerbal Space Program", "terraria": "tModLoader",
                "valheim": "Valheim", "overcooked2": "Overcooked! 2", "cities_skylines": "Cities_Skylines", "civ6": "Sid Meier's Civilization VI"}
STEAM_IN_PLACE = {"terraria"}          # run from the library itself (GA_GAME): tModLoader looks for Steam's workshop next to its folder
WORKSHOP_APP = {"slay_the_spire": 646570}   # ModTheSpire + BaseMod come from her Workshop subscriptions: read-only at /workshop
STORE_VOLUMES = {"steam": {"home": "ga-steam-home", "games": "ga-steam-games"},
                 "ea": {"ga-ea": "/sandbox/ea"},
                 "microsoft": {"ga-mc-account": "/sandbox/account", "ga-mc-game": "/sandbox/minecraft"}}
PROJECT_LABEL = "org.gameanything.project"
MEMORY = {False: "4g", True: "8g"}     # 2D / 3D (linux-sandbox.md "Resources"; Stardew's measured peak 1.5 GB)
MEMORY_FEX = "5g"                      # arm64: Steam + the game under FEX took ~3 GB in the 2026-10-31 test (Docker Desktop had 6 GB)


def container_name(game) -> str: return f"ga-{IMAGES[game]}"


def sandbox_volume(game, project_id) -> str:
    """The project's own /sandbox volume: ga-<image>-<project id> (Docker names: [a-zA-Z0-9][a-zA-Z0-9_.-]*)."""
    pid = re.sub(r"[^a-z0-9_.-]+", "-", str(project_id).lower()).strip("-.") or "project"
    return f"ga-{IMAGES[game]}-{pid}"[:120]


def volume_mount(volume, inside, subpath=None, readonly=False) -> list:
    """--mount of a named volume; subpath (Docker Engine 26+) mounts one folder of it (a game Steam downloaded in the sandbox)."""
    m = f"type=volume,src={volume},dst={inside}" + (f",volume-subpath={subpath}" if subpath else "") + (",readonly" if readonly else "")
    return ["--mount", m]


def default_source(game) -> str:
    """steam | ea | microsoft: the download inside the sandbox the game.yaml names (the user's own folder is `folder`)."""
    return facts(game)["download"] or "steam"


def sandbox_argv(game, project_id, image=None, source=None, game_dir=None, saves_dir=None, project_dir=None, gpu=False, memory=None,
                 image_uid=None, uid="auto", docker="docker", port=6080, bind=VIEWER_BIND, apparmor="auto", security_dir=None,
                 steam_home_dir=None) -> list:
    """`docker run -d` of one project's sandbox. source: "folder" (game_dir mounted read-only at /game, saves_dir at /saves), "steam"
    (the Steam volumes, the game's library folder read-only at /game by volume subpath; Terraria from the library itself), "ea" (the EA
    App and its download on the ga-ea volume) or "microsoft" (the Microsoft sign-in and the Minecraft download on their volumes).
    project_dir: the project folder, read-only at /project (the builder's mod sources). Every option the plain-Docker test needed
    (docs/sandbox-hiccups.md): --user for a pulled image, Steam's seccomp / AppArmor / shm, the GPU, a memory limit, the viewer on 127.0.0.1.
    steam_home_dir: where the Steam home volume goes (default steam_home(): /sandbox/home for a pulled image run for another uid); Steam
    keeps absolute library paths, so a home volume made at /home/player stays there."""
    if game not in IMAGES: raise ValueError(f"no sandbox image for {game!r} yet (images: {', '.join(IMAGES)})")
    source = source or default_source(game)
    if source not in ("folder", *STORE_VOLUMES): raise ValueError(f"source must be folder, steam, ea or microsoft, not {source!r}")
    if source == "folder" and not game_dir: raise ValueError("source folder needs the game folder (game_dir)")
    if source == "steam" and game not in STEAM_FOLDER: raise ValueError(f"{game} does not come from Steam")
    n = container_name(game); user = run_user_args(image_uid, uid)
    argv = [docker, "run", "-d", "--platform", PLATFORM, "--name", n, "--label", f"{PROJECT_LABEL}={project_id}", "-p", port_arg(port, bind), *user,
            "--memory", memory or (MEMORY_FEX if PLATFORM == "linux/arm64" else MEMORY[facts(game)["three_d"]])]
    if gpu: argv += ["--gpus", "all", "-e", "NVIDIA_DRIVER_CAPABILITIES=all"]
    argv += volume_mount(sandbox_volume(game, project_id), "/sandbox")
    if source == "folder":
        argv += ["-v", f"{game_dir}:/game:ro"] + (["-v", f"{saves_dir}:/saves:ro"] if saves_dir else [])
    elif source == "steam":
        v = STORE_VOLUMES["steam"]; home = steam_home_dir or steam_home(image_uid, uid)
        argv += steam_run_args(v["home"], v["games"], security_dir=security_dir, apparmor=apparmor, home=home)
        if steam_home_dir: argv += ["-e", f"HOME={home}"]          # also without --user: Steam's links in the volume name this HOME
        if game in STEAM_IN_PLACE: argv += ["-e", f"GA_GAME={home}/.steam/debian-installation/steamapps/common/{STEAM_FOLDER[game]}"]
        else: argv += volume_mount(v["games"], "/game", f"common/{STEAM_FOLDER[game]}", readonly=True)
        if game in WORKSHOP_APP: argv += volume_mount(v["games"], "/workshop", f"workshop/content/{WORKSHOP_APP[game]}", readonly=True)
    else:
        for vol, inside in STORE_VOLUMES[source].items(): argv += volume_mount(vol, inside)
        if source == "microsoft": argv += ["-e", "GA_GAME=/sandbox/minecraft"]
    if project_dir: argv += ["-v", f"{project_dir}:/project:ro"]
    return argv + [image or image_tag(game)]
