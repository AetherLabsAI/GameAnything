"""The KNOWN situations of account logins, game downloads and launches inside a sandbox, as data (watchdog.py matches them). Stdlib only:
the sandbox tools (ga-steam, ga-mc, galab) import it inside the image too.

Every entry comes from a real hiccup (evidence: _agent/logs/2026-10-29/user-sandbox-steam/HICCUPS.md and user-sandbox-mcdl/HICCUPS.md).

    KNOWN    the situations. Each entry:
        id          short name (unique)
        flows       which waits it belongs to: "steam" (client start, login, install, launch) | "microsoft" (sign-in) | "minecraft"
                    (download, launch)
        phases      the phases it can happen in (None = all): check, start, login, ownership, install, launch, download
        when        the detector: every key is a fact of watchdog.facts() and must hold. A value is compared for equality, or a dict
                    {"re": regex} (str value / any item of a list), {"min": n}, {"max": n}, {"in": [...]}, {"not": v}; several keys in one dict must
                    all hold ({"min": 15, "max": 900})
        min_stall_s the observed state must also have been unchanged this long (0 = at once; a dialog is acted on as soon as it shows)
        kind        "auto"   a safe automatic action (`action`: a name in watchdog.ACTIONS), at most `tries` times (default 1)
                    "tell"   tell the user (progress or something they do in the viewer), keep waiting
                    "ask"    stop and ask the user; nothing is done for them (`license: True` entries can never be "auto")
                    "ignore" known noise: never reported as a problem
        say         {"zh", "en"}: the exact words for the user; {name} fields are filled from the facts (and from `eula` for licences)
        max_wait_s  how long the situation may last before the watchdog escalates with `then` (or tells the user it is stuck)
        then        optional {kind, action, say}: what to do when it is still there after max_wait_s
        license     True: a licence / EULA. Never clicked for the user on a plain yes (record_consent only notes it; they click
                    Accept themselves in the viewer). Exception (Wenyi, 2026-10-29): a FRESH (<= 15 min) click_for_me consent for this
                    same agreement, with the user's words ("同意，帮我点"), lets the watchdog run `accept_action` once, logged with a
                    screenshot of the dialog and the consent record. kind is never "auto" for a licence.
        accept_action   (licences only) the ACTIONS script that clicks its accept button, used only for that exception
        source      where it was seen
    EULAS    the publisher agreements Steam shows in the Install flow (appid -> publisher, agreement, url), seen 2026-10-28/29
    PHASES   the normal duration of each phase, for the progress lines ("usually 5-20 min")

Adding a hiccup = ONE entry in KNOWN (plus a fact in watchdog.facts() if no existing fact detects it, plus a fixture test in
tests/test_watchdog.py). See docs/sandbox-images.md "Adding a known situation".
"""

# ---------------------------------------------------------------- publisher agreements in Steam's Install flow
EULAS = {
    255710: {"game": "Cities: Skylines", "publisher": "Paradox Interactive", "agreement": "Paradox User Agreement + Privacy Policy",
             "url": "https://legal.paradoxplaza.com/eula", "seen": "2026-10-29"},
    289070: {"game": "Sid Meier's Civilization VI", "publisher": "Take-Two Interactive",
             "agreement": "Take-Two LIMITED SOFTWARE WARRANTY AND LICENSE AGREEMENT (2019-07-13)", "url": "https://www.take2games.com/eula",
             "seen": "2026-10-29"},
    1281930: {"game": "tModLoader", "publisher": "the tModLoader team", "agreement": "tModLoader EULA", "url": "shown in Steam's dialog",
              "seen": "2026-10-28"},
}

# the EA App's own agreement (its installer's first page; key "ea" in consents.json)
EULAS["ea"] = {"game": "EA App", "publisher": "Electronic Arts", "agreement": "EA User Agreement",
               "url": "https://tos.ea.com/legalapp/WEBTERMS/US/en/PC/", "seen": "2026-10-29"}
# The Sims 4's "Terms of play" before its download (key "ea_ts4_terms")
EULAS["ea_ts4_terms"] = {"game": "The Sims 4", "publisher": "Electronic Arts + Microsoft",
                         "agreement": "Electronic Arts User Agreement; Microsoft Visual C++ 2015 and 2019 Runtime Agreements",
                         "url": "https://game-metadata-service.juno.ea.com/eula/OFB-EAST:109552299/", "seen": "2026-10-29"}

# ---------------------------------------------------------------- normal timings (the progress lines say them)
PHASES = {
    "check": {"zh": "检查沙箱", "en": "checking the sandbox", "normal_zh": "几秒", "normal_en": "a few seconds", "max_s": 60},
    "start": {"zh": "启动 Steam", "en": "starting Steam", "normal_zh": "已装好的 Steam 30–60 秒", "normal_en": "30-60 s once Steam is installed",
              "max_s": 300},
    "updating": {"zh": "Steam 第一次自我更新", "en": "Steam's first self-update",
                 "normal_zh": "约 500 MB，一般 5–20 分钟（本地 SSD 更快，网络盘上约 20 分钟）",
                 "normal_en": "about 500 MB, usually 5-20 min (faster on a local SSD, about 20 min on a network disk)", "max_s": 2400},
    "login": {"zh": "等你登录", "en": "waiting for you to sign in", "normal_zh": "1–6 分钟（含手机上的 Steam 令牌确认）",
              "normal_en": "1-6 min (including Steam Guard on your phone)", "max_s": 2400},
    "auto_logon": {"zh": "用保存的登录自动登录", "en": "signing in with the saved login", "normal_zh": "30–60 秒", "normal_en": "30-60 s",
                   "max_s": 300},
    "ownership": {"zh": "检查游戏是否在你的账号里", "en": "checking the game is in your account", "normal_zh": "几秒", "normal_en": "a few seconds",
                  "max_s": 120},
    "install": {"zh": "下载游戏", "en": "downloading the game",
                "normal_zh": "看网速：星露谷 676 MB 约 3 分钟，英灵神殿 4 GB 约 6 分钟；网络盘上「安装文件」还要更久",
                "normal_en": "depends on the network: Stardew 676 MB about 3 min, Valheim 4 GB about 6 min; on a network disk "
                             "'installing files' takes longer", "max_s": 7200},
    "ms_code": {"zh": "等你在手机上输入代码", "en": "waiting for you to enter the code", "normal_zh": "约 1 分钟；代码 15 分钟后过期，会自动换新的",
                "normal_en": "about 1 min; the code expires after 15 min and a new one comes by itself", "max_s": 1800},
    "mc_download": {"zh": "下载 Minecraft 文件", "en": "downloading the Minecraft files",
                    "normal_zh": "约 2 分钟（700 MB，5000 多个素材文件）", "normal_en": "about 2 min (700 MB, 5000+ asset files)", "max_s": 1800},
    "ea_start": {"zh": "安装或启动 EA App", "en": "installing or starting the EA App",
                 "normal_zh": "第一次：Wine 1–2 分钟 + 你点 LET'S GO 后安装约 20 秒；以后 10–30 秒",
                 "normal_en": "first time: Wine 1-2 min + about 20 s of install after you click LET'S GO; later 10-30 s", "max_s": 1800},
    "ea_login": {"zh": "等你登录 EA", "en": "waiting for you to sign in to EA", "normal_zh": "1–5 分钟（含邮件或手机验证码）",
                 "normal_en": "1-5 min (including an e-mail or phone code)", "max_s": 2400},
    "ea_install": {"zh": "下载模拟人生 4", "en": "downloading The Sims 4", "normal_zh": "看网速，基础游戏几十 GB", "normal_en": "depends on the network; the base game is tens of GB",
                   "max_s": 14400},
    "launch": {"zh": "启动游戏", "en": "starting the game", "normal_zh": "几秒到 1 分钟", "normal_en": "a few seconds to 1 min", "max_s": 300},
}

# ---------------------------------------------------------------- the known situations
KNOWN = [
    # ---- Steam: before and during the first start
    {"id": "steam_namespaces_denied", "flows": ["steam"], "phases": ["check", "start"], "when": {"ns_mount_ok": False}, "kind": "ask",
     "say": {"zh": "这个沙箱不允许 Steam 需要的「挂载命名空间」，Steam 开不起来。请用这些参数重新创建沙箱：--security-opt seccomp=lab/images/common/security/seccomp-steam.json、"
                   "（有 AppArmor 的 Linux）--security-opt apparmor=gameanything-steam（先用 sudo 加载一次：Ubuntu 24.04 起用 gameanything-steam.apparmor，Ubuntu 22.04 用 gameanything-steam-u2204.apparmor）、--shm-size 1g。不用 --privileged。",
             "en": "This sandbox does not allow the mount namespace Steam needs, so Steam cannot start. Re-create it with: --security-opt "
                   "seccomp=lab/images/common/security/seccomp-steam.json, on a Linux host with AppArmor --security-opt apparmor=gameanything-steam "
                   "(load it once with sudo: gameanything-steam.apparmor on Ubuntu 24.04+, gameanything-steam-u2204.apparmor on Ubuntu 22.04), and --shm-size 1g. No --privileged."},
     "max_wait_s": 0, "source": "steam HICCUPS #1"},
    {"id": "steam_crashes_under_qemu", "flows": ["steam"], "phases": ["start", "updating", "login"], "when": {"qemu_segv": True}, "kind": "ask",
     "say": {"zh": "Steam 在这个沙箱里崩溃了（qemu 段错误）：这是 Apple 芯片的 Mac，沙箱里的 Steam 是 32 位程序，Rosetta 不翻译它，"
                   "用 qemu 模拟就会崩。Mac 上不支持沙箱：请把项目改成本机模式（gameanything project set-mode <项目> native），直接用你电脑上的游戏。",
             "en": "Steam crashed in this sandbox (a qemu segmentation fault): this is an Apple silicon Mac, the Steam client in the sandbox is "
                   "a 32-bit program that Rosetta does not translate, and under qemu it crashes. A Mac has no sandbox: switch the project to "
                   "native mode (gameanything project set-mode <project> native) and use the game on your computer."},
     "max_wait_s": 0, "source": "her Mac (M3, Docker Desktop + Rosetta) 2026-10-30: console-linux.txt, signal 11 ~10 s after each start"},
    {"id": "sandbox_out_of_memory", "flows": ["steam", "microsoft", "minecraft", "ea"], "phases": None, "when": {"oom_new": True}, "kind": "ask",
     "say": {"zh": "沙箱内存不够：系统停掉了沙箱里的一个程序（这个沙箱最多只能用 {mem_limit_gb} GB，docker run --memory）。你的电脑不受影响。"
                   "请用更大的 --memory 重新创建沙箱（Stardew 和 Steam 一般 4g 够用，模拟人生 4 和 EA App 要 8g），再试一次。",
             "en": "The sandbox ran out of memory: the system stopped a program in it (this sandbox may use only {mem_limit_gb} GB, docker run "
                   "--memory). Your computer is not affected. Create the sandbox again with a larger --memory (4g is usually enough for "
                   "Stardew and Steam; The Sims 4 with the EA App needs 8g) and try again."},
     "max_wait_s": 0, "source": "plain Docker on Linux, docs/sandbox-hiccups.md (linux-docker test): --memory 700m, SMAPI killed (code 137)"},
    # not in "check": before this flow starts Steam, /sandbox/logs/steam.log (the project volume) is a run before; 2026-10-31 a stale line
    # from a sandbox created at the wrong HOME stopped the login of the re-created, fixed one before Steam started
    {"id": "steam_home_not_writable", "flows": ["steam"], "phases": ["start", "updating", "login"],
     "when": {"last_log": {"re": r"\.steam\S*'?: Permission denied"}}, "kind": "ask",
     "say": {"zh": "Steam 写不进自己的文件夹（~/.steam 属于 root）：这个镜像是旧版本，steamapps 卷挂在 HOME 卷里面，Docker 把中间的文件夹建成了 root 的。"
                   "请重新拉取镜像（gameanything lab setup --image <游戏>，2026-10-30 起发布的镜像已修好；或加 --build 在本机重建），删掉这两个新建的空卷（ga-steam-home、ga-steam-games）再重新创建沙箱。",
             "en": "Steam cannot write its own folder (~/.steam belongs to root): the image is an old one, and with the steamapps volume inside the "
                   "HOME volume Docker made the folders in between as root. Pull the image again (gameanything lab setup --image <game>: "
                   "the images published since 2026-10-30 have the folders; or add --build to rebuild it here), remove the two new empty volumes (ga-steam-home, ga-steam-games) and create the sandbox again."},
     "max_wait_s": 0, "source": "plain Docker on Linux, docs/sandbox-hiccups.md (linux-docker test) #8"},
    {"id": "steam_installer_dialog", "flows": ["steam"], "phases": ["start", "updating", "login"], "when": {"installer_dialog": True},
     "kind": "auto", "action": "click_installer_install",
     "say": {"zh": "第一次启动：Debian 的「Steam installer」说明框出来了，我点了 Install（这只是打包方的说明，不是许可协议）。",
             "en": "First start: Debian's 'Steam installer' notice showed up; I clicked Install (it is the packager's notice, not a licence)."},
     "max_wait_s": 60,
     "then": {"kind": "tell", "say": {"zh": "「Steam installer」框还在：请在查看器里点右下角的 Install（不要按回车，回车是 Cancel）。",
                                      "en": "The 'Steam installer' box is still there: please click Install at its bottom right in the viewer "
                                            "(not Return: Return is Cancel)."}},
     "source": "steam HICCUPS #2"},
    {"id": "steam_installer_cancelled", "flows": ["steam"], "phases": ["start", "updating", "login"],
     "when": {"installer_cancelled": True, "steam_running": False}, "kind": "auto", "action": "steam_start",
     "say": {"zh": "Steam 的安装说明框被取消了，Steam 退出了：我重新启动 Steam。", "en": "The Steam installer notice was cancelled and Steam exited: starting Steam again."},
     "max_wait_s": 120, "source": "steam HICCUPS #2"},
    {"id": "steam_client_downloading", "flows": ["steam"], "phases": ["start", "updating", "login"], "when": {"bootstrap_stage": "downloading"},
     "kind": "tell",
     "say": {"zh": "Steam 第一次在自我更新（约 500 MB，一般 5–20 分钟），已下载 {bootstrap_pct}%。之后会出登录窗口，现在不用点任何东西。",
             "en": "Steam is updating itself the first time (about 500 MB, usually 5-20 min): {bootstrap_pct}% downloaded. The sign-in "
                   "window comes after that; you do not need to click anything yet."},
     "max_wait_s": 1500, "source": "steam HICCUPS #3, #6"},
    {"id": "steam_client_extracting", "flows": ["steam"], "phases": ["start", "updating", "login"],
     "when": {"bootstrap_stage": {"in": ["extracting", "installing"]}}, "kind": "tell",
     "say": {"zh": "Steam 在解压、安装自己的更新（第一次会来两轮，网络盘上每轮约 5 分钟）。之后会出登录窗口。",
             "en": "Steam is extracting and installing its update (the first start does this twice, about 5 min each on a network disk). "
                   "The sign-in window comes after that."},
     "max_wait_s": 1500, "source": "steam HICCUPS #3, #6"},
    {"id": "steam_updater_window", "flows": ["steam"], "phases": ["start", "updating", "login"],
     "when": {"updater_window": True, "login_window": False}, "kind": "tell",
     "say": {"zh": "屏幕上那个叫「Steam」的小窗口是更新进度，不是登录窗口：还在更新，请再等等。",
             "en": "The small window called 'Steam' is the updater's progress, not the sign-in window: still updating, please wait."},
     "max_wait_s": 1500, "source": "steam HICCUPS #5"},
    {"id": "steam_small_shm", "flows": ["steam"], "phases": ["start", "updating", "login"],
     "when": {"small_shm": True, "webhelper_shm_flag": False}, "kind": "auto", "action": "steam_webhelper_no_shm",
     "say": {"zh": "这个沙箱的共享内存（/dev/shm）只有 {shm_mb} MB，Steam 自己就占掉大半，登录窗口会一直崩、出不来。我让 Steam 的网页组件改用普通临时目录"
                   "（--disable-dev-shm-usage），并重启了它（只重启网页组件，Steam 不退出）。",
             "en": "This sandbox's shared memory (/dev/shm) is only {shm_mb} MB and Steam itself fills most of it, so the sign-in window keeps "
                   "crashing and never shows. I told Steam's web helper to use the normal temp folder instead (--disable-dev-shm-usage) and "
                   "restarted only the web helper (Steam keeps running)."},
     "max_wait_s": 120, "source": "steam HICCUPS #26"},
    {"id": "steam_login_window", "flows": ["steam"], "phases": ["start", "updating", "login"], "when": {"login_window": True}, "kind": "tell",
     "say": {"zh": "Steam 的登录窗口出来了：请在查看器 {viewer} 里登录你自己的账号，勾上「记住我」，然后在手机 Steam 令牌里确认。你输入的内容我看不到，也不会保存。",
             "en": "Steam's sign-in window is up: please sign in to your own account in the viewer {viewer}, tick 'Remember me', then "
                   "approve it in Steam Guard on your phone. I cannot see what you type and nothing of it is saved."},
     "max_wait_s": 2400, "source": "steam HICCUPS #7"},
    {"id": "steam_logon_poll_noise", "flows": ["steam"], "phases": ["login"], "when": {"login_window": True, "logon_failure_noise": True},
     "kind": "ignore", "say": {"zh": "登录前 Steam 日志里的「logon failure / Transport Error」是正常的轮询，不是登录失败。",
                               "en": "'logon failure / Transport Error' in Steam's log before you type anything is normal polling, not a failed login."},
     "max_wait_s": 2400, "source": "steam HICCUPS #8"},
    {"id": "steam_friends_window", "flows": ["steam"], "when": {"friends_window": True}, "kind": "auto", "action": "close_friends_window",
     "say": {"zh": "Steam 弹出了好友窗口（里面有好友名字）：我把它关掉了，截图里不会有。", "en": "Steam opened the Friends window (with your friends' names): I closed it, so no screenshot shows it."},
     "max_wait_s": 60, "source": "steam HICCUPS #13"},
    # ---- Steam: installing a game
    {"id": "steam_network_disk", "flows": ["steam"], "phases": ["install"], "when": {"network_disk": True}, "kind": "tell", "once": True,
     "say": {"zh": "游戏库在网络盘（{library_fs}）上：下载后「安装文件」会很慢（几千个小文件一个个挪）。能的话把 steamapps 放到本地 SSD。",
             "en": "The game library is on a network disk ({library_fs}): after the download, 'installing files' is slow (thousands of small "
                   "files moved one by one). Put steamapps on a local SSD if you can."},
     "max_wait_s": 0, "source": "steam HICCUPS #19, #20"},
    {"id": "steam_publisher_eula", "flows": ["steam"], "phases": ["install"], "license": True,
     "when": {"eula_known": True, "app_manifest": False, "install_requested_s": {"min": 15}}, "kind": "ask",
     "say": {"zh": "Steam 先显示 Install 窗口（点蓝色的 Install），然后是「{publisher}」的协议：{agreement}（{url}）。协议要你自己决定：请在查看器里读一下，"
                   "同意就点 Accept，不同意就点 Cancel。我不会替你点。",
             "en": "Steam first shows its Install window (click the blue Install), then {publisher}'s agreement: {agreement} ({url}). The "
                   "agreement is your decision: read it in the viewer and click Accept if you agree, or Cancel. I will not click it for you."},
     "max_wait_s": 1800, "source": "steam HICCUPS #17, #25"},
    {"id": "steam_install_dialog", "flows": ["steam"], "phases": ["install"],
     "when": {"eula_known": False, "app_installed": False, "app_downloading": False, "install_requested_s": {"min": 15, "max": 900},
              "app_bytes_dl": {"max": 0}},
     "kind": "tell",
     "say": {"zh": "Steam 弹出了 Install 窗口：请在查看器里点蓝色的 Install 按钮（如果是带价格的商店页面，说明这个账号里没有这个游戏）。如果是许可协议，请自己读了再决定。",
             "en": "Steam shows its Install window: please click the blue Install button in the viewer. (A store page with a price means "
                   "this account does not own the game; a licence agreement is yours to read and decide.)"},
     "max_wait_s": 900, "source": "steam HICCUPS #9, #16"},
    {"id": "steam_not_owned", "flows": ["steam"], "phases": ["ownership", "install"], "when": {"app_no_license": True}, "kind": "ask",
     "say": {"zh": "Steam 说这个账号没有这个游戏的许可（No licenses）：{game} 不在你登录的 Steam 账号里。请换成买了它的账号，或者先在 Steam 里买/领取。",
             "en": "Steam says this account has no licence for it (No licenses): {game} is not in the Steam account you signed in with. "
                   "Sign in with the account that owns it, or get it in Steam first."},
     "max_wait_s": 0, "source": "steam HICCUPS #16 (10-26 'No licenses')"},
    {"id": "steam_reserving_space", "flows": ["steam"], "phases": ["install"],
     "when": {"app_downloading": True, "app_bytes_dl": {"max": 0}, "install_requested_s": {"max": 900}}, "kind": "tell",
     "say": {"zh": "Steam 先在预留硬盘空间（Reserving Space），这时显示 0 字节是正常的，网络盘上可能要 10 分钟。",
             "en": "Steam reserves disk space first (Reserving Space); 0 bytes is normal now, up to 10 min on a network disk."},
     "max_wait_s": 900, "source": "steam HICCUPS #18"},
    {"id": "steam_download_stalled", "flows": ["steam"], "phases": ["install"],
     "when": {"app_downloading": True, "rate_zero_minutes": {"min": 5}}, "min_stall_s": 300, "kind": "auto", "action": "steam_open_downloads",
     "say": {"zh": "下载停在 0 bps 已经 5 分钟：我打开了 Steam 的下载页。请在查看器里点一下暂停，再点继续（上次这样就恢复了）。",
             "en": "The download has been at 0 bps for 5 min: I opened Steam's Downloads page. Please click pause, then resume, in the "
                   "viewer (that fixed it last time)."},
     "max_wait_s": 600,
     "then": {"kind": "auto", "action": "steam_restart",
              "say": {"zh": "暂停/继续后还是 0 bps：我重启了 Steam（约 30 秒，用保存的登录，不用重新输入）。",
                      "en": "Still 0 bps after pause/resume: I restarted Steam (about 30 s, with the saved login, nothing to type)."}},
     "source": "steam HICCUPS #19"},
    {"id": "steam_committing_files", "flows": ["steam"], "phases": ["install"],
     "when": {"app_downloading": True, "app_download_complete": True}, "kind": "tell",
     "say": {"zh": "已经下载完，Steam 在把文件挪进游戏文件夹（安装文件），网络盘上可能要 20 分钟；这不是卡住。",
             "en": "The download is done; Steam is moving the files into the game folder (installing files), which can take 20 min on a "
                   "network disk. It has not hung."},
     "max_wait_s": 2400, "source": "steam HICCUPS #19"},
    {"id": "steam_manifest_stale", "flows": ["steam"], "phases": ["install"],
     "when": {"app_installed": False, "app_files_complete": True}, "min_stall_s": 120, "kind": "auto", "action": "steam_restart",
     "say": {"zh": "游戏文件其实已经齐了，但 Steam 的记录没更新：我重启了 Steam（约 30 秒）让它刷新。",
             "en": "The game files are complete but Steam's record did not update: I restarted Steam (about 30 s) so it refreshes."},
     "max_wait_s": 300, "source": "steam HICCUPS #21"},
    {"id": "steam_ghost_running", "flows": ["steam"], "phases": ["install", "launch"],
     "when": {"ghost_running": True}, "min_stall_s": 30, "kind": "auto", "action": "steam_restart",
     "say": {"zh": "游戏已经停了，但 Steam 还以为它在运行（这时下载和卸载都不动）：我重启了 Steam（约 30 秒，不用登录）。",
             "en": "The game has stopped but Steam still thinks it is running (downloads and uninstalls stall then): I restarted Steam "
                   "(about 30 s, no login)."},
     "max_wait_s": 300, "source": "steam HICCUPS #22"},
    # ---- Steam: before the first launch
    {"id": "steam_shader_precache_on", "flows": ["steam"], "phases": ["launch"], "when": {"shader_precache": True}, "kind": "auto",
     "action": "shader_precache_off",
     "say": {"zh": "启动前我关掉了 Steam 的着色器预缓存（它在沙箱里很吃内存，以前把沙箱搞崩过）。", "en": "Before the first launch I turned off Steam's shader pre-caching (it uses a lot of memory in a sandbox and once crashed one)."},
     "max_wait_s": 120, "source": "steam HICCUPS #15"},
    {"id": "steam_shader_processing", "flows": ["steam"], "phases": ["install", "launch"], "when": {"fossilize": {"min": 1}}, "kind": "tell",
     "say": {"zh": "Steam 在后台处理着色器（fossilize_replay，{fossilize} 个进程），很吃内存；等它结束再开游戏。",
             "en": "Steam is processing shaders in the background (fossilize_replay, {fossilize} processes), which uses a lot of memory; "
                   "wait for it before starting the game."},
     "max_wait_s": 900, "source": "steam HICCUPS #15"},
    # ---- Microsoft account (Minecraft)
    {"id": "ms_two_logins", "flows": ["microsoft"], "phases": ["login"], "when": {"mc_login_procs": {"min": 2}}, "kind": "auto",
     "action": "mc_keep_newest_login",
     "say": {"zh": "沙箱里同时有两个登录在等，会出两个代码：我停掉了旧的，只有最新的代码有效。",
             "en": "Two sign-ins were waiting in the sandbox (two codes): I stopped the older one; only the newest code counts."},
     "max_wait_s": 60, "source": "mcdl HICCUPS #3"},
    {"id": "ms_code_waiting", "flows": ["microsoft"], "phases": ["login"], "when": {"mc_code": {"re": "."}, "mc_code_expired": False},
     "kind": "tell",
     "say": {"zh": "请在你自己的手机或电脑上打开 {mc_url}，输入代码 {mc_code}，用买了 Minecraft 的微软账号登录。沙箱里什么都不用输入。",
             "en": "On your own phone or computer open {mc_url}, enter the code {mc_code} and sign in with the Microsoft account that bought "
                   "Minecraft. Nothing is typed into the sandbox."},
     "max_wait_s": 1800, "source": "mcdl HICCUPS #1"},
    {"id": "ms_code_expired", "flows": ["microsoft"], "phases": ["login"], "when": {"mc_code_expired": True, "mc_login_procs": 0},
     "kind": "auto", "action": "mc_login_again",
     "say": {"zh": "代码过期了，我重新要了一个新代码。", "en": "The code expired; I asked for a new one."},
     "max_wait_s": 120, "source": "mcdl HICCUPS (codes expire after 15 min)"},
    {"id": "ms_not_owned", "flows": ["microsoft"], "phases": ["ownership"], "when": {"mc_checked": True, "mc_owns_java": False}, "kind": "ask",
     "say": {"zh": "登录成功了，但这个微软账号里没有 Minecraft: Java 版（也没有 Game Pass）。请换成买了它的账号再登录一次。",
             "en": "Signed in, but this Microsoft account does not own Minecraft: Java Edition (nor Game Pass). Sign in again with the account that bought it."},
     "max_wait_s": 0, "source": "msauth ownership check"},
    # ---- Minecraft: the game
    {"id": "mc_world_not_found", "flows": ["minecraft"], "phases": ["launch"], "when": {"mc_world_missing": True}, "kind": "tell",
     "say": {"zh": "刚下载的游戏还没有存档，直接进世界失败了（Could not find a world）。请在查看器里点「Back to World List」，再点左下角「Create New World」，只要一次；以后会直接进。",
             "en": "A fresh download has no world yet, so quick play failed (Could not find a world). In the viewer click 'Back to World "
                   "List', then 'Create New World' at the bottom left, once; next time it opens by itself."},
     "max_wait_s": 600, "source": "mcdl HICCUPS #6"},
    # ---- EA App (The Sims 4) under Wine (seen 2026-10-29, evidence user-sandbox-ea/HICCUPS.md)
    {"id": "wine_mono_dialog", "flows": ["ea"], "phases": ["check", "ea_start"], "when": {"wine_mono_dialog": True}, "kind": "auto",
     "action": "wine_mono_install",
     "say": {"zh": "Wine 第一次建环境时问要不要装 Mono（EA 安装程序要用）：我点了安装。", "en": "Wine asked to install Mono on its first start (the EA installer needs it): I clicked Install."},
     "max_wait_s": 120, "source": "ea HICCUPS #3"},
    {"id": "ea_user_agreement", "flows": ["ea"], "phases": ["check", "ea_start"], "license": True, "consent_key": "ea", "button": "LET'S GO",
     "accept_action": "ea_click_lets_go",
     "when": {"ea_installer_eula": True},
     "kind": "ask",
     "say": {"zh": "EA App 安装程序第一页是「{publisher}」的协议：{agreement}（{url}），点「LET'S GO」就是同意。这要你自己决定：请在查看器 {viewer} 里读一下，同意就自己点「LET'S GO」（不要点 CUSTOMIZE SETUP），不同意就点右上角 ×。我不会替你点。",
             "en": "The EA App installer's first page is {publisher}'s {agreement} ({url}); clicking LET'S GO accepts it. This is your "
                   "decision: read it in the viewer {viewer} and click LET'S GO yourself if you agree (not CUSTOMIZE SETUP), or the x to "
                   "stop. I will not click it for you."},
     "max_wait_s": 1800, "source": "ea HICCUPS #4"},    {"id": "ea_login_window", "flows": ["ea"], "phases": ["ea_start", "ea_login"], "when": {"ea_login_window": True}, "kind": "tell",
     "say": {"zh": "EA 的登录窗口出来了：请在查看器 {viewer} 里用你的 EA 账号登录；邮箱、密码和验证码都由你自己输入，我看不到，也不截图。勾上「记住我」。",
             "en": "EA's sign-in window is up: sign in with your EA account in the viewer {viewer}; you type the e-mail, password and any "
                   "code yourself; I cannot see them and take no screenshot. Tick 'Remember me'."},
     "max_wait_s": 2400, "source": "ea HICCUPS (login 19:18-19:21, 2026-10-29)"},
    {"id": "ea_login_page_failed", "flows": ["ea"], "phases": ["ea_start", "ea_login"], "when": {"ea_login_page_failed": True}, "kind": "tell",
     "say": {"zh": "EA 的登录页没加载出来（网络或 EA 服务器）：请在查看器里看一眼；我等一会儿再重开 EA App。",
             "en": "EA's sign-in page did not load (network or EA's servers): please look at the viewer; I will restart the EA App if it stays."},
     "max_wait_s": 120, "then": {"kind": "auto", "action": "ea_restart",
                                 "say": {"zh": "登录页还是没出来：我重开了 EA App（约 20 秒）。", "en": "The sign-in page still did not load: I restarted the EA App (about 20 s)."}},
     "source": "ea: EADesktop.log 'Login page load failed'"},
    {"id": "gui_misclick_suspected", "flows": ["ea"], "phases": ["ownership", "ea_install"], "when": {"ea_browser_opened": {"min": 1}},
     "kind": "auto", "action": "ea_normalize_window", "once": True,
     "say": {"zh": "点击之后意外打开了一个浏览器链接：多半是点错了位置（不是游戏或账号的问题）。我把 EA App 窗口恢复成默认大小，请重新截图确认目标再点。",
             "en": "A browser link opened after a click: most likely a misclick (not a problem with the game or the account). I put the "
                   "EA App window back to its default size; take a fresh screenshot and check the target before clicking again."},
     "max_wait_s": 0, "source": "ea HICCUPS #11 (maximised window, offset clicks, banner link)"},
    {"id": "ea_terms_of_play", "flows": ["ea"], "phases": ["ownership", "ea_install"], "license": True, "consent_key": "ea_ts4_terms",
     "button": "DOWNLOAD", "accept_action": "ea_click_terms_download", "when": {"ea_terms_of_play": True}, "kind": "ask",
     "say": {"zh": "下载前 EA App 显示了 {game} 的「Terms of play」：点「DOWNLOAD」就是同意 Electronic Arts User Agreement、Microsoft Visual C++ 2015 和 2019 Runtime Agreement（链接在对话框里）。这要你自己决定：同意就在查看器 {viewer} 里自己点「DOWNLOAD」，不同意点 CANCEL。我不会替你点。",
             "en": "Before the download the EA App shows {game}'s 'Terms of play': clicking DOWNLOAD agrees to the Electronic Arts User "
                   "Agreement and the Microsoft Visual C++ 2015 and 2019 Runtime Agreements (links in the dialog). Your decision: click "
                   "DOWNLOAD yourself in the viewer {viewer} if you agree, or CANCEL. I will not click it for you."},
     "max_wait_s": 1800, "source": "ea HICCUPS #12"},
    {"id": "ea_steam_owned", "flows": ["ea"], "phases": ["ownership", "ea_install"], "when": {"ea_external_owned": True}, "kind": "ask",
     "say": {"zh": "你的{game} 是在 {ea_store_name} 上拿到的，EA App 会把下载交给 {ea_store_name}。请改用「在沙箱里登录 {ea_store_name} 下载」（Windows 版，用 Wine 跑），之后用这个已登录的 EA App 启动。",
             "en": "Your {game} came from {ea_store_name}, so the EA App hands its download to {ea_store_name}. Use 'sign in to "
                   "{ea_store_name} in the sandbox and download' instead (the Windows version, run with Wine), then start it with this "
                   "signed-in EA App."},
     "max_wait_s": 0, "source": "ea HICCUPS #7"},
]

UNKNOWN_SAY = {"zh": "已经 {stalled} 秒没有变化，这不是我认识的情况。现在看到的：窗口 {windows}；最后的日志：{last_log}。截图：{shot}",
               "en": "Nothing has changed for {stalled} s and this is not a situation I know. What I see: windows {windows}; last log line: "
                     "{last_log}. Screenshot: {shot}"}
HEARTBEAT_SAY = {"zh": "还在{phase}（已 {elapsed}，正常 {normal}）。", "en": "Still {phase} ({elapsed} so far, normally {normal})."}
SHOT_PRIVATE = {"zh": "（登录窗口开着，为了不拍到你输入的东西，没截图）", "en": "(the sign-in window is open: no screenshot, so nothing you type is captured)"}


def entry(id_):
    return next(e for e in KNOWN if e["id"] == id_)


def validate(known=None) -> list:
    """Problems in the table (tests run it): unique ids, the fields, and no licence entry with an automatic action."""
    out, seen = [], set()
    for e in known if known is not None else KNOWN:
        i = e.get("id")
        if not i or i in seen: out.append(f"duplicate or missing id {i!r}")
        seen.add(i)
        if e.get("kind") not in ("auto", "tell", "ask", "ignore"): out.append(f"{i}: kind {e.get('kind')!r}")
        if e.get("kind") == "auto" and not e.get("action"): out.append(f"{i}: auto without an action")
        if e.get("license") and (e.get("kind") == "auto" or (e.get("then") or {}).get("kind") == "auto"):
            out.append(f"{i}: a licence can never be accepted automatically")
        if e.get("accept_action") and not e.get("license"): out.append(f"{i}: accept_action only for a licence")
        if not isinstance(e.get("when"), dict) or not e["when"]: out.append(f"{i}: no detector")
        for k in ("zh", "en"):
            if not (e.get("say") or {}).get(k): out.append(f"{i}: no {k} words")
        if "max_wait_s" not in e: out.append(f"{i}: no max_wait_s")
        if not e.get("flows"): out.append(f"{i}: no flows")
    return out
