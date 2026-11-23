/* Projects, export / import and backup in the shell (D16): the project card's menu, the "别的项目" list, the backup state in the sidebar footer, and
   the dialogs (export progress + download, import, backup settings with its consent card; the new-project wizard is in onboard.js). Loaded before shell.js, uses its helpers
   ($, esc, icon, get, post, upload, toast) when called. All text goes through t(). */
"use strict";
const MB = n => n >= 2 ** 30 ? (n / 2 ** 30).toFixed(1) + " GB" : (n / 2 ** 20 >= 10 ? Math.round(n / 2 ** 20) : (n / 2 ** 20).toFixed(1)) + " MB";
const KIND_NAME = { memory: "回忆项目", feature: "功能项目", adaptation: "改编项目", gameplay: "玩法项目" };
const GAME_NAME = { stardew: "Stardew Valley", minecraft: "Minecraft", cities_skylines: "Cities: Skylines", slay_the_spire: "Slay the Spire", overcooked2: "Overcooked! 2", sims4: "The Sims 4", valheim: "Valheim" };
const GAME_DESC = {};      // {game id: description}: both filled from the server's game registry (games/<id>/game.yaml, plugins too)
/* the server's `game_info` ({games: {id: {title, desc, desc_en}}, texts: {中文: English}}, registry.ui_info()): every game it knows */
function useGames(info) {
  if (!info || !info.games) return;
  addTexts(info.texts);
  for (const [id, g] of Object.entries(info.games)) {
    GAME_NAME[id] = g.title || GAME_NAME[id] || id;
    if (g.desc) { GAME_DESC[id] = g.desc; if (g.desc_en) addTexts({ [g.desc]: g.desc_en }); }
  }
}

/* ---- sidebar pieces */
// gameanything hub: a menu item only for the roles that may use it (the server checks again)
const hubCan = m => { const H = SH.hub; if (!H) return true; return ({ export: H.can.edit, import: true, backup: H.can.owner, settings: H.can.admin, game: H.can.edit, mode: H.can.edit, launch: H.can.edit, remove: H.can.owner })[m] ?? true; };
const hubGo = url => { location.href = url; };
function projectCardHtml() {
  const k = KIND_NAME[SH.kind] || KIND_NAME.memory;
  return `<div class="projwrap"><button class="proj" id="projbtn" aria-haspopup="menu" title="${esc(SH.date || "")}">${SH.cover ? `<img src="${esc(SH.cover)}" alt="">` : `<span class="ph"></span>`}
    <div><b>${esc(SH.title)}</b><span>${esc(SH.game)} · ${t(k)}</span></div>${icon("more", "margin-left:auto;color:var(--mute)")}</button>
    <div class="menu" id="projmenu" role="menu" hidden>
      ${[["all", "home", "所有项目"], ["export", "down", "导出这个项目"], ["import", "upload", "导入一个项目"], ["backup", "shield", "备份设置"], ["settings", "more", "设置"], ["game", "play", "换游戏"], ["mode", "home", "在哪里做"], ["launch", "play", "什么时候开游戏"], ["remove", "trash", "删除这个项目"]]
        .filter(([m]) => hubCan(m)).map(([m, ic, lb]) => `<a data-m="${m}" role="menuitem">${icon(ic)}${t(lb)}</a>`).join("")}
      ${SH.hub ? `<a data-m="logout" role="menuitem">${icon("lock")}${t("退出登录")} · ${esc(SH.hub.display)}</a>` : ""}</div></div>`;
}
function otherProjectsHtml() {
  const others = (SH.projects || []).filter(p => !p.current && p.exists).slice(0, 5);
  return `<div class="sidelabel lbl2">${t("别的项目")}<a id="allproj">${t("全部")}</a></div>`
    + others.map(p => `<a class="run" data-pid="${esc(p.id)}" title="${esc(p.title)}"><span class="dot ${p.kind}"></span><div><b>${esc(p.title)}</b><small>${GAME_NAME[p.game] || GAME_NAME.stardew} · ${t(KIND_NAME[p.kind] || KIND_NAME.memory)}${p.last_opened ? " · " + fmtAt(p.last_opened) : ""}</small></div></a>`).join("")
    + `<a class="navi addproj" id="newproj">${icon("plus")}${t("新项目")}</a>`;
}
function backupFootHtml() {
  const b = SH.backup || { state: "off" };
  const txt = { off: t("备份关闭"), wait: t("备份已开启 · 等第一次"), running: t("备份中…"), ok: t("已备份 · {t}", { t: fmtHM(b.at) }), error: t("备份出错：{e}", { e: b.error || "" }) }[b.state];
  return `<a class="bk ${b.state}" id="bkstate" title="${esc(txt)}"><i></i><span>${esc(txt)}</span></a>`;
}
function wireManage() {
  const btn = $("#projbtn"), menu = $("#projmenu");
  btn.onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  $$("#projmenu a").forEach(a => a.onclick = () => { menu.hidden = true; ({ all: SH.hub ? () => hubGo("/") : showWelcome, logout: hubLogout, export: exportDialog, import: importDialog, backup: backupDialog, settings: settingsDialog, game: gameDialog, mode: modeDialog, launch: launchDialog, remove: removeDialog })[a.dataset.m](); });
  $$("#side [data-pid]").forEach(a => a.onclick = () => switchTo(a.dataset.pid));
  $("#newproj").onclick = () => newProjectDialog(); $("#allproj").onclick = SH.hub ? () => hubGo("/") : showWelcome; $("#bkstate").onclick = backupDialog;
}
document.addEventListener("click", () => { const m = $("#projmenu"); if (m) m.hidden = true; });
async function switchTo(id) {
  const r = await post("/api/projects/open", { id });
  if (!r.ok) return toast(r.error || t("没能发出去"));
  if (r.go) return hubGo(r.go);                          // the hub: every project has its own address
  location.hash = ""; location.reload();
}
async function hubLogout() { await post("/api/logout", {}); hubGo("/login"); }

/* ---- dialogs */
function dialog(html, wide = false) {
  const bg = document.createElement("div"); bg.className = "modal";
  bg.innerHTML = `<div class="mbox ${wide ? "wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { bg.remove(); document.removeEventListener("keydown", esc_); };
  const esc_ = e => { if (e.key === "Escape") close(); };
  bg.onclick = e => { if (e.target === bg) close(); };
  document.addEventListener("keydown", esc_); document.body.append(bg); bg.close = close; M2W.apply(bg);
  $$("[data-close]", bg).forEach(b => b.onclick = close);
  return bg;
}
const bar = (pct) => `<div class="pbar"><i style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>`;
const jobPct = j => j.total ? j.done / j.total * 100 : 0;
async function follow(url, on) {                         // poll a job record until it ends
  for (;;) {
    let j; try { j = await get(url); } catch (e) { await new Promise(r => setTimeout(r, 1500)); continue; }
    on(j); if (j.state !== "running") return j;
    await new Promise(r => setTimeout(r, 700));
  }
}

async function exportDialog() {
  const d = dialog(`<h3>${t("导出这个项目")}</h3><p class="sub">${t("把整个项目（素材整理结果、对话、形象、每一版的材料和录像）打成一个文件，不含游戏本体。在后台进行，可以先关掉这个窗口。")}</p>
    <div id="job"></div><div class="foot"><button class="btn ghost" data-close>${t("关闭")}</button></div>`);
  const r = await post("/api/export/start", {});
  if (!r.ok) { $("#job", d).innerHTML = `<div class="bad">${esc(r.error)}</div>`; return; }
  await follow("/api/export?id=" + r.job.id, j => {
    $("#job", d).innerHTML = j.state === "running" ? bar(jobPct(j)) + `<div class="st">${t("正在打包 {a} / {b} · {n} 个文件", { a: MB(j.done), b: MB(j.total), n: j.files })}</div>`
      : j.state === "error" ? `<div class="bad">${esc(j.error)}</div>`
      : bar(100) + `<div class="st ok">${icon("check", "width:13px;height:13px")}${t("已打包：{s} · {n} 个文件", { s: MB(j.bytes), n: j.files })}</div>
        <div class="foot"><a class="btn" href="${esc(j.url)}" download>${icon("down", "width:13px;height:13px")}${t("下载")}</a>${j.path ? `<span class="muted">${t("文件也留在这台电脑上：{p}", { p: j.path })}</span>` : ""}</div>`;
  });
}

function importDialog() {
  const d = dialog(`<h3>${t("导入一个项目")}</h3><p class="sub">${t("选一个之前导出的 .zip 文件。导入会新建一个项目，不会覆盖已有的项目；每个文件都会先校验。")}</p>
    <label class="drop" id="idrop"><input type="file" id="ifile" accept=".zip,application/zip" hidden>${icon("upload")}<span>${t("选择文件，或把它拖到这里")}</span></label>
    <div id="job"></div><div class="foot" id="ifoot"><button class="btn ghost" data-close>${t("关闭")}</button></div>`);
  const job = $("#job", d), drop = $("#idrop", d);
  async function go(f) {
    if (!f) return;
    if (!/\.zip$/i.test(f.name)) { job.innerHTML = `<div class="bad">${t("需要 GameAnything 导出的 .zip 文件")}</div>`; return; }
    drop.style.display = "none"; job.innerHTML = bar(0) + `<div class="st">${t("正在上传 {n}", { n: f.name })}</div>`;
    let path;
    try { path = await upload(f, p => { job.innerHTML = bar(p) + `<div class="st">${t("正在上传 {n} · {p}%", { n: f.name, p: Math.round(p) })}</div>`; }, "import"); }
    catch (e) { job.innerHTML = `<div class="bad">${esc(e.message)}</div>`; drop.style.display = ""; return; }
    const r = await post("/api/import/start", { path });
    if (!r.ok) { job.innerHTML = `<div class="bad">${esc(r.error)}</div>`; return; }
    const j = await follow("/api/import?id=" + r.job.id, j => {
      if (j.state === "running") job.innerHTML = bar(jobPct(j)) + `<div class="st">${t("正在检查并恢复 {a} / {b}", { a: MB(j.done), b: MB(j.total) })}</div>`;
    });
    if (j.state === "error") { job.innerHTML = `<div class="bad">${esc(j.error)}</div>`; drop.style.display = ""; return; }
    job.innerHTML = bar(100) + `<div class="st ok">${icon("check", "width:13px;height:13px")}${t("已导入「{n}」：{f} 个文件，校验全部通过", { n: j.title, f: j.files })}</div>`;
    $("#ifoot", d).innerHTML = `<button class="btn" id="iopen">${t("打开这个项目")}</button><button class="btn ghost" data-close>${t("留在这里")}</button>`;
    $("#iopen", d).onclick = () => switchTo(j.id); $$("[data-close]", d).forEach(b => b.onclick = d.close); loadShell();
  }
  $("#ifile", d).onchange = e => go(e.target.files[0]);
  ["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", ev => go(ev.dataTransfer.files[0]));
}

/* the new-project wizard (newProjectDialog) lives in onboard.js */

async function settingsDialog() {
  const S = await get("/api/settings");
  const d = dialog(`<h3>${t("设置")}</h3>
    <label class="fld">${t("最多同时进行几个项目")}<input class="inp" id="smax" type="number" min="1" max="10" value="${S.max_active_projects}"></label>
    <p class="sub">${t("agent 会自动接上来了消息的项目，同时最多这么多个；多出来的项目排队，有项目空出来（2 小时没有对话）就接上。")}</p>
    <label class="fld chkrow"><input type="checkbox" id="srec" ${S.record_builds ? "checked" : ""}> ${t("录下构建过程")}</label>
    <p class="sub">${t("每次构建时录下游戏画面，并每隔几分钟给代码存一次快照，方便回看和做宣传视频。只存在这台电脑上，不上传。")}</p>
    <div class="foot"><button class="btn" id="sgo">${t("保存")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`);
  $("#sgo", d).onclick = async () => {
    const n = parseInt($("#smax", d).value, 10);
    if (!(n >= 1 && n <= 10)) return toast(t("同时进行的项目要在 1 到 10 之间"));
    const r = await post("/api/settings", { max_active_projects: n, record_builds: $("#srec", d).checked });
    if (!r.ok) return toast(r.error || t("没能发出去"));
    toast(t("已保存")); d.close();
  };
}

function gameDialog() {
  let game = SH.game_id || "stardew";
  const opt = (g, k, sub) => `<div class="opt ${g === game ? "on" : ""}" data-game="${g}"><span class="k">${k}</span><div><b>${GAME_NAME[g]}</b><small>${t(sub)}</small></div></div>`;
  const d = dialog(`<h3>${t("换游戏")}</h3><p class="sub">${t("只有还没开始构建的项目能换；素材、人物和对话都不受影响。")}</p>
    ${Object.keys(GAME_NAME).map((g, i) => opt(g, String.fromCharCode(65 + i), GAME_DESC[g] || "")).join("")}
    <div class="foot"><button class="btn" id="ggo">${t("保存")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`);
  $$(".opt", d).forEach(o => o.onclick = () => { game = o.dataset.game; $$(".opt", d).forEach(x => x.classList.toggle("on", x === o)); });
  $("#ggo", d).onclick = async () => {
    $("#ggo", d).disabled = true;
    const r = await post("/api/projects/game", { id: SH.project_id, game });
    if (!r.ok) { $("#ggo", d).disabled = false; return toast(r.error || t("没能发出去")); }
    location.reload();
  };
}

// 「在哪里做」: the project's build_mode (buildmode.py); the choices come from /api/onboard/games (greyed ones say why)
async function modeDialog() {
  const d = dialog(`<div id="md"><h3>${t("在哪里做")}</h3><div class="chk wait"><span class="ring"></span>${t("正在检查这台电脑…")}</div></div>`);
  let C; try { C = await get("/api/onboard/games"); useGames(C.game_info); } catch (e) { C = null; }
  const G = C && C.games.find(x => x.id === (SH.game_id || "stardew")), M = G && G.modes;
  if (!M) { $("#md", d).innerHTML = `<h3>${t("在哪里做")}</h3><p class="sub">${t("服务没有回应（{s}）", { s: "onboard/games" })}</p>`; return; }
  let mode = SH.build_mode_source === "project" ? SH.build_mode : null;
  const draw = () => {
    $("#md", d).innerHTML = `<h3>${t("在哪里做")}</h3><p class="sub">${SH.build_mode_source === "project" ? t("构建和试玩在哪里进行。正在跑的构建不受影响，下一次构建起按新的来。")
        : t("这个项目还没选过，现在按这台电脑自动决定（{m}）。", { m: t(SH.build_mode === "lab" ? "沙箱（镜像）" : "我的电脑（本机）") })}</p>
      <div class="glist">${M.options.map(o => modeOptHtml(o, M, o.mode === mode)).join("")}</div>
      <div class="foot"><button class="btn" id="mgo" ${mode ? "" : "disabled"}>${t("保存")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`;
    $$(".opt.md", d).forEach(o => o.onclick = () => { if (o.classList.contains("off")) return; mode = o.dataset.mode; draw(); });
    $$("[data-close]", d).forEach(b => b.onclick = d.close);
    $("#mgo", d).onclick = async () => {
      $("#mgo", d).disabled = true;
      const r = await post("/api/projects/mode", { id: SH.project_id, mode });
      if (!r.ok) { $("#mgo", d).disabled = false; return toast(r.error || t("没能发出去")); }
      SH.build_mode = r.build_mode; SH.build_mode_source = "project"; toast(t("已保存")); d.close();
    };
  };
  draw();
}

// 「什么时候开游戏」: native mode opens HER game for tests; config/project.yaml native_launch (native/quiet.py): ask (default) | window | always
// | idle (「我没在用电脑时」, native_launch_idle_minutes), and native_drive: idle (default) | always (may agents press keys in the game window
// m2w opened while she is at the computer; native/hands.py), native_front: never (default) | away (「测试时允许把游戏切到前面」, Windows only,
// her decision 2026-11-01) and native_hands: agent (default) | self (「我自己点」), with the last 能不能操作屏幕 check (native/ready.py)
function readyHtml() {
  const R = SH.native_ready || {}, c = R.chat;
  const LV = { full: "能看、能点", look: "只能看，不能点", none: "不能看也不能点" };
  if (!c) return `<p class="sub">${t("还没查过（第一次开游戏前会查）")}</p>`;
  return `<p class="sub"><b class="${c.level === "full" ? "" : "bad"}">${t(LV[c.level] || c.level)}</b> · ${t("{who}，{t} 查的", { who: esc(c.who || ""), t: fmtAt(c.at) })}`
    + (c.fresh ? "" : `<br>${t("换了 agent 或模型：下次开游戏前会重新查")}`)
    + (c.level !== "full" && (c.fix || []).length ? `<br><small>${((M2W.lang === "en" && c.fix_en) || c.fix).map(esc).join("<br>")}</small>` : "") + `</p>`;
}
function launchDialog() {
  const L = SH.native_launch || { mode: "ask", window: "22:00-08:00", idle_minutes: 10, drive: "idle", front: "never", hands: "agent" };
  let mode = L.mode, hands = L.hands || "agent"; const [w0, w1] = (L.window || "22:00-08:00").split("-");
  const d = dialog(`<div id="ld"></div>`);
  const opt = (m, title, sub) => `<div class="opt md ${m === mode ? "on" : ""}" data-m="${m}"><span class="k">${m === mode ? icon("check", "width:12px;height:12px") : ""}</span><div><b>${t(title)}</b>${m === "ask" ? `<span class="rec">${t("建议")}</span>` : ""}<small>${t(sub)}</small></div></div>`;
  const draw = () => {
    const a = $("#lw0", d) ? $("#lw0", d).value : w0, b = $("#lw1", d) ? $("#lw1", d).value : w1;
    const mins = $("#lmin", d) ? $("#lmin", d).value : String(L.idle_minutes || 10), drv = $("#ldrv", d) ? $("#ldrv", d).checked : L.drive === "always";
    const frt = $("#lfrt", d) ? $("#lfrt", d).checked : L.front === "away";
    const hopt = (h, title, sub) => `<div class="opt hd ${h === hands ? "on" : ""}" data-h="${h}"><span class="k">${h === hands ? icon("check", "width:12px;height:12px") : ""}</span><div><b>${t(title)}</b><small>${t(sub)}</small></div></div>`;
    $("#ld", d).innerHTML = `<h3>${t("什么时候开游戏")}</h3><p class="sub">${t("在你自己的电脑上测试时，agent 要开、关你的游戏。选它什么时候可以开：")}</p>
      <div class="glist">${opt("ask", "每次先问我", "开游戏前在对话里发一张卡，你点「现在可以」才开（推荐）")}${opt("window", "只在这个时间段", "比如夜里你不用电脑的时候；其他时间不开，也不问你")}${opt("idle", "我没在用电脑时", "你离开电脑（不动鼠标键盘）这么久以后才开，不问你；你一回来，agent 就停下不操作游戏，等你再离开")}${opt("always", "随时可以", "不问你，直接开；两次之间至少隔 10 分钟，一轮尽量只开一次")}</div>
      <div class="row" ${mode === "window" ? "" : "hidden"}><label class="fld">${t("从")}<input class="inp" type="time" id="lw0" value="${esc(a)}"></label><label class="fld">${t("到")}<input class="inp" type="time" id="lw1" value="${esc(b)}"></label></div>
      <div class="row" ${mode === "idle" ? "" : "hidden"}><label class="fld">${t("分钟")}<input class="inp" type="number" min="1" max="720" id="lmin" value="${esc(mins)}"></label></div>
      <label class="chk"><input type="checkbox" id="ldrv" ${drv ? "checked" : ""}> ${t("我在用电脑时也可以操作游戏窗口")}</label><p class="sub">${t("按键只发给 agent 开的那个游戏窗口，不抢焦点、不动你别的程序；不勾的话，你在用电脑时 agent 不碰游戏（推荐不勾）")}</p>
      <label class="chk"><input type="checkbox" id="lfrt" ${frt ? "checked" : ""}> ${t("测试时允许把游戏切到前面")}</label><p class="sub">${t("只在 Windows 上用到：Windows 只把按键发给最前面的窗口。勾上后，你离开电脑（1 分钟不动鼠标键盘）时 agent 可以把它自己开的游戏切到前面再按；你一动鼠标键盘它就停下；你在用电脑时从来不切。macOS / Linux 不受影响")}</p>
      <div class="fld">${t("谁来点游戏")}</div><div class="glist">${hopt("agent", "agent 自己看、自己点", "agent 用 gameanything native shot / drive 看游戏、按键（要这台电脑允许，见下面的检查结果）")}${hopt("self", "我自己点", "agent 不操作游戏：每一轮在进度卡里写清楚要你点哪里，你点完说「好了」")}</div>
      <div class="fld">${t("agent 能不能看、点你的游戏")}</div>${readyHtml()}
      <p class="sub">${t("关游戏：只关 agent 自己开的那次；你自己开的游戏从来不关。")}<br>${t("只在「我的电脑（本机）」模式下用到；沙箱里的游戏不占你的屏幕和鼠标。")}</p>
      <div class="foot"><button class="btn" id="lgo">${t("保存")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`;
    $$(".opt.md", d).forEach(o => o.onclick = () => { mode = o.dataset.m; draw(); });
    $$(".opt.hd", d).forEach(o => o.onclick = () => { hands = o.dataset.h; draw(); });
    $$("[data-close]", d).forEach(x => x.onclick = d.close);
    $("#lgo", d).onclick = async () => {
      $("#lgo", d).disabled = true;
      const r = await post("/api/projects/launch", { id: SH.project_id, mode, window: `${$("#lw0", d).value}-${$("#lw1", d).value}`,
        minutes: $("#lmin", d).value, drive: $("#ldrv", d).checked ? "always" : "idle", front: $("#lfrt", d).checked ? "away" : "never", hands });
      if (!r.ok) { $("#lgo", d).disabled = false; return toast(r.error || t("没能发出去")); }
      SH.native_launch = r.native_launch; if (r.native_ready) SH.native_ready = r.native_ready; toast(t("已保存")); d.close();
    };
  };
  draw();
}

function removeDialog() {
  const d = dialog(`<h3>${t("删除这个项目")}</h3>
    <p class="sub">${t("「{n}」会从列表里拿掉，整个文件夹挪进数据目录的 .trash 里，不会真的删掉，需要时还能找回来。", { n: SH.title })}</p>
    <div class="foot"><button class="btn danger" id="rgo">${t("删除")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`);
  $("#rgo", d).onclick = async () => {
    $("#rgo", d).disabled = true;
    const r = await post("/api/projects/remove", { id: SH.project_id });
    if (!r.ok) { $("#rgo", d).disabled = false; return toast(r.error || t("没能发出去")); }
    if (r.go) return hubGo(r.go);
    location.hash = ""; location.reload();
  };
}

/* ---- backup settings */
async function backupDialog() {
  const d = dialog(`<div id="bk"></div>`, true);
  const draw = async () => {
    let s; try { s = await get("/api/backup"); } catch (e) { return; }
    SH.backup = s.brief; renderSide();
    const L = s.last, br = s.brief;
    const lastLine = !L ? t("还没有备份过") : L.ok ? t("{t} · 备份了 {n} 个文件（{s}）", { t: fmtAt(L.at), n: L.files, s: MB(L.bytes) }) : t("{t} · 出错：{e}", { t: fmtAt(L.at), e: br.error || L.error });
    $("#bk", d).innerHTML = `<h3>${t("备份设置")}</h3>
      <p class="sub">${t("默认关闭。开启后，这个项目会按间隔自动备份到你指定的地方：只复制新增或改动的文件，备份里的东西从不被删除。只有你能开启，agent 不能替你打开。")}</p>
      ${s.enabled ? `<div class="kv"><span>${t("备份到")}</span><b>${esc(s.target)}</b><span>${t("间隔")}</span><b>${t("每 {n} 分钟", { n: s.every_minutes })}</b>
          <span>${t("原始素材")}</span><b>${s.include_raw ? esc(s.raw_paths.join("、")) : t("不备份")}</b><span>${t("上次")}</span><b class="${L && !L.ok ? "bad" : ""}">${esc(lastLine)}</b>
          <span>${t("还没备份的改动")}</span><b>${t("{n} 个文件", { n: s.pending })}</b></div>
        <div class="foot"><button class="btn" id="bkrun" ${br.state === "running" ? "disabled" : ""}>${br.state === "running" ? t("备份中…") : t("立即备份")}</button><button class="btn ghost" id="bkoff">${t("关闭备份")}</button>
          <button class="btn ghost" data-close style="margin-left:auto">${t("关闭")}</button></div>`
      : `<div class="fld">${t("备份到")}</div>
        <div class="opt on" data-k="folder"><span class="k">A</span><div><b>${t("本地文件夹")}</b><small>${t("移动硬盘，或网盘同步的文件夹")}</small>
          <input class="inp" id="bkpath" placeholder="${esc(t("例如：/media/你的移动硬盘/m2w-backup"))}"></div></div>
        <div class="opt" data-k="hf"><span class="k">B</span><div><b>${t("我的 Hugging Face 私有数据集")}</b><small>${t("必须是 private；不存在时会替你新建一个私有的。token 不会出现在界面或命令行里。")}</small>
          <input class="inp" id="bkrepo" placeholder="owner/name">
          <small id="bktok" class="${s.token ? "" : "warn"}">${s.token ? t("已找到 token（{w}）", { w: t({ env: "环境变量 HF_TOKEN", keyring: "系统钥匙串", file: "0600 文件" }[s.token]) }) : t("还没有找到 Hugging Face 的 token。为了安全，token 不在网页里填写：在对话里问 agent 怎么设置")}</small></div></div>
        <label class="chk"><input type="checkbox" id="bkraw"> ${t("同时备份原始素材（照片、视频的原件，可能很大）")}</label>
        <textarea class="inp" id="bkrawp" rows="2" hidden placeholder="${esc(t("原始素材文件夹，一行一个"))}"></textarea>
        <label class="fld inl">${t("每")} <input class="inp num" id="bkmin" type="number" min="1" max="1440" value="30"> ${t("分钟检查一次")}</label>
        <div class="foot"><button class="btn" id="bkgo">${t("开启备份…")}</button><button class="btn ghost" data-close>${t("关闭")}</button></div>`}`;
    M2W.apply(d); $$("[data-close]", d).forEach(b => b.onclick = d.close);
    if (s.enabled) {
      $("#bkrun", d).onclick = async () => { const r = await post("/api/backup/run", {}); if (!r.ok) toast(r.error); setTimeout(draw, 400); };
      $("#bkoff", d).onclick = async () => { await post("/api/backup/disable", {}); draw(); };
      if (br.state === "running") setTimeout(() => d.isConnected && draw(), 1500);
    } else {
      let kind = "folder";
      $$(".opt", d).forEach(o => o.onclick = e => { kind = o.dataset.k; $$(".opt", d).forEach(x => x.classList.toggle("on", x === o)); if (e.target.tagName !== "INPUT") $("input", o).focus(); });
      $("#bkraw", d).onchange = e => $("#bkrawp", d).hidden = !e.target.checked;
      $("#bkgo", d).onclick = async () => {
        const body = { target: kind === "folder" ? { kind, path: $("#bkpath", d).value } : { kind, repo: $("#bkrepo", d).value }, include_raw: $("#bkraw", d).checked,
                       raw_paths: $("#bkrawp", d).value.split("\n"), every_minutes: +$("#bkmin", d).value || 30 };
        const p = await post("/api/backup/preview", body);
        if (!p.ok) return toast(p.error);
        consentDialog(p, body, draw);
      };
    }
  };
  await draw();
}
function consentDialog(p, body, done) {
  const d = dialog(`<div class="card perm" style="margin:0"><div class="ctype">${t("许可 · 开启前先问你")}</div><h4>${t("开启自动备份？")}</h4>
    <ul><li>${t("备份到：")}${esc(p.where)}${p.remote ? ` — ${t("文件会离开这台电脑，传到你在 Hugging Face 上的私有数据集")}` : ` — ${t("只复制到这台电脑能访问的这个文件夹")}`}</li>
      <li>${t("会备份：{n} 个文件，{s}", { n: p.files, s: MB(p.bytes) })}<ul>${p.folders.map(f => `<li><code>${f.name === "." ? t("项目根目录") : esc(f.name)}</code> · ${t("{n} 个文件", { n: f.files })} · ${MB(f.bytes)}</li>`).join("")}</ul></li>
      <li>${t("不会备份：游戏本体（*.xnb、Content (unpacked)、反编译的源码）、缓存和临时文件")}</li>
      <li>${t("方式：每 {n} 分钟检查一次，只复制新增或改动的文件；备份里的东西从不被删除", { n: p.every_minutes })}</li>
      ${p.remote ? `<li>${t("私有检查：每次备份前确认数据集是 private，否则不传")}</li>` : ""}
      <li>${t("每次备份都会记进 privacy_ledger.yaml（目的：备份）")}</li></ul>
    <div class="foot"><button class="btn" id="cyes">${t("同意并开启")}</button><button class="btn ghost" data-close>${t("取消")}</button></div></div>`, true);
  $("#cyes", d).onclick = async () => {
    $("#cyes", d).disabled = true;
    const r = await post("/api/backup/enable", { ...body, ack: true });
    if (!r.ok) { $("#cyes", d).disabled = false; return toast(r.error); }
    d.close(); toast(t("备份已开启")); done();
  };
}
