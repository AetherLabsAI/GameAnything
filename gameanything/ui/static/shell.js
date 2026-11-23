/* Conversation shell: sidebar (/api/shell), the thread (/api/thread, polled every 2 s) with interactive cards, the composer, and the
   workspace iframe (the app pages with ?embed=1). Everything is local; the page loads no fonts or scripts from outside.
   UI text goes through t() (i18n.js); the agent's and the user's own words are shown as written. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (n, st = "") => `<svg class="i" style="${st}"><use href="#i-${n}"/></svg>`;
const fmtT = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const hhmm = fmtHM;
const LH = () => ({ "X-Lang": M2W.lang });         // the server builds some sentences: tell it the language
// the project this tab is bound to: pages live at /p/<id>/ (the server puts window.M2W_BASE in and prefixes fetch / XHR with it); links get it here
const BASE = window.M2W_BASE || "";
const at = u => typeof u === "string" && u[0] === "/" && u[1] !== "/" && BASE && u.indexOf(BASE + "/") !== 0 ? BASE + u : u;
const get = async u => { const r = await fetch(u, { headers: LH() }); if (!r.ok) throw new Error(u + " " + r.status); return r.json(); };
async function post(u, b) {
  const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json", ...LH() }, body: JSON.stringify(b) });
  try { return await r.json(); } catch (e) { return { ok: false, error: t("服务没有回应（{s}）", { s: r.status }) }; }
}
function toast(t) { const e = $("#toast"); e.textContent = t; e.style.display = "block"; clearTimeout(e._t); e._t = setTimeout(() => e.style.display = "none", 2400); }

/* ------------------------------------------------------------ workspace */
const TABS = [["gather", "upload", "素材"], ["home", "day", "这一天"], ["people", "people", "人物"], ["plan", "plan", "方案"], ["play", "play", "试玩"], ["status", "status", "开发状态"], ["keep", "home", "带回家"]];
const tabs = () => KIND_TABS[SH && SH.kind] || TABS;
const frame = () => $("#wsf");
const curRoute = () => { try { return frame().contentWindow.location.hash || ""; } catch (e) { return ""; } };
// how: {initial} the first page (no flash, no toast), {pop} the address bar / back / forward asked for it (no new history entry)
function ws(route, how = {}) {
  route = String(route || "").replace(/^#/, "") || "home";
  const f = frame(), cur = curRoute().replace(/^#/, "");
  // the workspace's own hash is replaced, never pushed: the history entry is the shell's (#route in the address bar), so back / forward
  // go through the pages once (QA 2026-10-29: the address bar and back / forward did not switch the workspace)
  if (f.dataset.ready && cur !== route) {          // an absolute address: a relative one would resolve against THIS page (the shell)
    const L = f.contentWindow.location;
    try { L.replace(L.href.split("#")[0] + "#" + route); } catch (e) { L.hash = route; }
  }
  else if (!f.dataset.ready) { if (window.GA_DEMO) f.src = window.GA_DEMO.map("/?embed=1#" + route); else f.src = BASE + "/?embed=1#" + route; f.dataset.ready = 1; }   // a demo (demo.js): app.html in its folder
  else { try { f.contentWindow.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) {} }   // already open: still show that something happened
  if (location.hash.slice(1) !== route) {
    try { if (how.initial) history.replaceState(null, "", "#" + route); else if (!how.pop) history.pushState(null, "", "#" + route); } catch (e) {}
  }
  if (!how.initial) {
    const box = f.closest(".ws") || f.parentElement; box.classList.remove("flash"); void box.offsetWidth; box.classList.add("flash");
    if (isPhone()) mview("ws"); else if (!how.pop && typeof toast === "function") toast(t("已在右边打开"));
  }
  markTab(route);
}
window.addEventListener("hashchange", () => {
  if (!SH || SH.no_project || !frame().dataset.ready) return;
  const r = location.hash.slice(1); if (r && r !== curRoute().replace(/^#/, "")) ws(r, { pop: true });
});
/* phones: one column; the bar at the top switches between the conversation and the workspace, the sidebar is a drawer (shell.html) */
const PHONE = window.matchMedia ? matchMedia("(max-width: 760px)") : { matches: false };
const isPhone = () => PHONE.matches;
function mview(v) {
  const b = document.body;
  if (v === "side") { b.classList.add("m-side"); return; }
  b.classList.remove("m-side"); if (v === "chat" || v === "ws") b.classList.toggle("m-ws", v === "ws");
  renderMbar();
}
function renderMbar() {
  const bar = $("#mbar"); if (!bar) return;
  if (!SH || SH.no_project) { bar.innerHTML = ""; return; }
  const w = document.body.classList.contains("m-ws"), n = pending();
  bar.innerHTML = `<button class="mb-menu" id="mbmenu" title="${esc(t("菜单"))}" aria-label="${esc(t("菜单"))}">${icon("menu")}</button><span class="mb-title">${esc(SH.title || "")}</span>
    <div class="mb-seg"><button data-mv="chat" class="${w ? "" : "on"}">${t("对话")}${n ? `<span class="cnt">${n}</span>` : ""}</button><button data-mv="ws" class="${w ? "on" : ""}">${t("工作区")}</button></div>`;
  $("#mbmenu", bar).onclick = () => mview("side");
  $$("[data-mv]", bar).forEach(x => x.onclick = () => mview(x.dataset.mv));
}
$("#mscrim").onclick = () => mview(document.body.classList.contains("m-ws") ? "ws" : "chat");
// the page the project is at: the flow's current step (a reload with no #page in the address opens it, not always 这一天)
function startRoute() {
  const F = SH && SH.flow, st = F && (F.steps || []).find(x => x.state === "current" || x.state === "run");
  const r = st && st.route; return r && r !== "chat" ? r : "home";
}
function markTab(route) {
  const k = (route || "").split("/")[0], tab = tabOf(SH && SH.kind, k);
  $$("[data-w]").forEach(a => a.classList.toggle("cur", a.dataset.w === tab));
}
setInterval(() => {                     // the workspace moved by itself (a link in the page): the tab and the address bar follow
  const r = curRoute().replace(/^#/, ""); if (!r) return; markTab(r);
  if (SH && !SH.no_project && location.hash.slice(1) !== r) { try { history.replaceState(null, "", "#" + r); } catch (e) {} }
}, 600);

/* ------------------------------------------------------------ sidebar */
let SH = null;
let UI_V = null;
async function loadShell() {
  let s; try { s = await get("/api/shell"); } catch (e) { renderBadFiles((e && e.files) || []); return; }
  if (s.no_project) { SH = s; if (!WELCOME) showWelcome(); return; }          // no project yet (or the last one was removed): the welcome page
  const first = !SH || SH.no_project; SH = s; useGames(s.game_info);
  M2W.kind = SH.kind;
  if (UI_V === null) UI_V = SH.ui_version;
  else if (SH.ui_version && SH.ui_version !== UI_V && !$("#uiupd")) {       // the page's own code changed on the server: offer a reload
    const b = document.createElement("div"); b.id = "uiupd"; b.className = "uiupd";
    b.innerHTML = `${t("页面有更新")} <button class="btn">${t("点这里刷新")}</button>`; b.querySelector("button").onclick = () => location.reload();
    document.body.append(b);
  }
  renderSide(); renderPills(); renderHub(); loadModels(); renderBadFiles(SH.bad_files || []);
  if (first && (!SH.hub || SH.hub.can.edit)) maybeCoach();
}
/* gameanything hub (several users): the role on this project. Below comment: read only (the composer is off); below edit: cards can't be answered.
   The banner says so and offers 「申请权限」 (a card in the owner's conversation; the owner's answer sets the role). */
const ROLE_NAME = { view: "查看", comment: "评论", edit: "编辑", owner: "所有者" };
const ROLE_ORDER = ["view", "comment", "edit"];
function renderHub() {
  const H = SH && SH.hub; if (!H) return;
  const th = $("#thread"); th.classList.toggle("ro", !H.can.cards);
  const msg = $("#msg"), send = $("#send");
  msg.disabled = send.disabled = !H.can.chat;
  msg.placeholder = H.can.chat ? t("随时说：补充、纠正、新的想法……也可以把文件拖进来") : t("只读：申请评论或编辑权限后才能在这里说话");
  let bar = $("#hubbar"); if (!bar) { bar = document.createElement("div"); bar.id = "hubbar"; $("#offline").before(bar); }
  const r = H.request, wants = ROLE_ORDER.filter(x => ROLE_ORDER.indexOf(x) > ROLE_ORDER.indexOf(H.role));
  const who = H.owner_name ? t("所有者：{n}", { n: H.owner_name }) : "";
  if (H.role === "owner" || H.role === "edit") { bar.innerHTML = H.role === "edit" ? `<div class="hubbar">${esc(t("你可以编辑这个项目"))} · ${esc(who)}<small>${esc(t("你在这里说的话由所有者的 Claude 额度回答"))}</small></div>` : ""; return; }
  const pend = r && r.state === "pending" ? `<small>${esc(t("已申请「{r}」权限，等所有者同意", { r: t(ROLE_NAME[r.role]) }))}</small>`
    : r && r.state === "denied" ? `<small>${esc(t("所有者没有同意你上次的申请"))}</small>` : "";
  bar.innerHTML = `<div class="hubbar ro"><b>${esc(H.role === "comment" ? t("可以评论") : t("只读"))}</b> · ${esc(who)}${wants.length ? ` <button class="btn sm" id="askrole">${esc(t("申请权限"))}</button>` : ""}${pend}</div>`;
  const b = $("#askrole"); if (b) b.onclick = () => accessDialog(wants);
}
function accessDialog(wants) {
  let role = wants[wants.length - 1];
  const sub = { view: "只能看对话和工作区", comment: "能在对话里说话、留意见，不能回答卡片或开工", edit: "能说话、回答卡片、开工和改设置；不能删项目、不能改成员" };
  const opt = r => `<div class="opt role ${r === role ? "on" : ""}" data-role="${r}"><div><b>${esc(t(ROLE_NAME[r]))}</b><small>${esc(t(sub[r]))}</small></div></div>`;
  const d = dialog(`<h3>${t("申请权限")}</h3><p class="sub">${t("所有者会在自己的对话里看到一张卡片，同意后你就有这个权限。你说的话由所有者的 Claude 额度回答。")}</p>
    ${wants.map(opt).join("")}<textarea class="inp" id="anote" rows="2" placeholder="${esc(t("想对所有者说一句（可选）"))}"></textarea>
    <div class="foot"><button class="btn" id="ago">${t("发送申请")}</button><button class="btn ghost" data-close>${t("取消")}</button></div>`);
  $$(".opt", d).forEach(o => o.onclick = () => { role = o.dataset.role; $$(".opt", d).forEach(x => x.classList.toggle("on", x === o)); });
  $("#ago", d).onclick = async () => {
    $("#ago", d).disabled = true;
    const r = await post("/api/access/request", { project: SH.project_id, role, note: $("#anote", d).value });
    if (!r.ok) { $("#ago", d).disabled = false; return toast(r.error || t("没能发出去")); }
    d.close(); toast(t("申请已发给所有者")); loadShell();
  };
}
function renderSide() {
  const open = r => r.state === "live" ? "home" : r.play ? `play/${r.m}` : "";
  const n = pending();
  $("#side").innerHTML = `<div class="brand"><span class="logo"><i></i></span><span>Game<b>Anything</b></span></div>
    ${projectCardHtml()}
    <a class="navi cur" id="gochat">${icon("chat")}${t("对话")}${n ? `<span class="cnt">${n}</span>` : ""}</a>
    <div class="sidelabel">${t("工作区")}</div>
    ${tabs().map(([k, ic, lb]) => `<a class="navi" data-w="${k}">${icon(ic)}${t(lb)}${k === "people" && SH.people_new ? `<span class="cnt">${SH.people_new}</span>` : ""}</a>`).join("")}
    <div class="sidelabel" data-coach="rounds">${t("每一版")}</div>
    ${SH.rounds.map(r => `<a class="run ${r.state === "live" ? "live" : r.state === "done" ? "done" : r.status === "next" ? "next" : ""}" data-open="${esc(open(r))}"><span class="dot"></span><div><b>${esc(r.name)}</b><small>${esc(r.sub)}</small></div></a>`).join("")
      || `<div class="run"><div><small>${t("还没有计划好的版本")}</small></div></div>`}
    ${otherProjectsHtml()}
    <div class="sidefoot">${icon("lock", "width:13px;height:13px")}${t("照片只在这台电脑上")}<br>${t("发送明细 {n} 次", { n: SH.footer.requests })}${SH.footer.image_cost_usd ? ` · ${t("生图")} $${SH.footer.image_cost_usd.toFixed(2)}` : ""}<br>${backupFootHtml()}</div>`;
  wireManage();
  $$("#side [data-w]").forEach(a => a.onclick = () => ws(a.dataset.w));
  $$("#side [data-open]").forEach(a => a.onclick = () => { if (a.dataset.open) ws(a.dataset.open); else if (isPhone()) mview(document.body.classList.contains("m-ws") ? "ws" : "chat"); });
  $("#gochat").onclick = () => { const t = $("#thread"); if (isPhone()) mview("chat"); t.scrollTop = t.scrollHeight; $("#msg").focus(); };
  markTab(curRoute());
  $("#wtabs").innerHTML = tabs().map(([k, ic, lb]) => `<a data-w="${k}" title="${esc(t(lb))}">${icon(ic)}<span>${t(lb)}</span></a>`).join("") + langSwitchHtml();
  $$("#wtabs a").forEach(a => a.onclick = () => ws(a.dataset.w)); wireLangSwitch($("#wtabs"));
  markTab(curRoute()); renderFlow(); renderMbar();
}
let AGENT = { online: false };
let BUILD = [];                  // running builds of this project (/api/thread `build`): the banner at the top of the chat
const daemonUp = () => !!(AGENT.agentd && AGENT.agentd.alive);
// why a message waits in the queue, in plain words (the projects that hold the slots, when the server names them)
const queueWhy = q => t("排队中：已经有 {n} 个项目在同时进行（最多 {c} 个，可以在设置里改）。有项目空出来，agent 会自动接上这个项目；你照样可以说，话会排队。", { n: q.active, c: q.cap })
  + ((q.projects || []).length ? " " + t("正在进行：{p}", { p: q.projects.join(t("、")) }) : "");
function renderPills() {
  if (!SH || SH.no_project) return;
  const ow = AGENT.owner && AGENT.owner.session ? " · " + t("会话 {s}", { s: AGENT.owner.session }) : "";
  // backed off (login / key, usage limit, its sandbox) or gave up on her last words: never the green 「随叫随到」 (QA2 2026-10-30)
  const paused = !AGENT.online && AGENT.backoff, gaveUp = !AGENT.online && !paused && AGENT.failed && AGENT.phase === "failed";
  const onCall = !AGENT.online && !AGENT.queued && daemonUp() && !paused && !gaveUp;   // nobody here right now, but the supervisor calls one at the first word
  const pill = AGENT.server_down ? t("连不上 GameAnything 服务") : AGENT.online ? t("agent 在线") : AGENT.queued ? t("排队中")
    : paused ? t("agent 暂停中") : gaveUp ? t("agent 没能回复") : onCall ? t("agent 随叫随到") : t("agent 不在");
  const tip = AGENT.server_down ? t("这个页面连不上 GameAnything 服务（它停了或在重启）：恢复后会自动接上") : AGENT.online ? t("agent 刚刚在看这个对话") + esc(ow)
    : paused ? esc(t("大约 {t} 自动再试", { t: M2W.lang === "en" ? paused.until_hm_en : paused.until_hm }))
    : gaveUp ? esc(t("再说一句会重新叫 agent")) : onCall ? t("后台调度在运行：你一说话，就会叫一个 agent 过来") : t("agent 最近没有来看");
  $("#pills").innerHTML = `<span class="live ${(AGENT.online || onCall) && !paused && !gaveUp ? "" : "off"}" title="${tip}"><i></i>${pill}</span>`
    + (SH.status.live ? `<span class="live run"><i></i>${esc(SH.status.text)}</span>` : "") + notifyBtn();
  wireNotify();
  const two = (AGENT.sessions || []).length > 1 ? `<div class="offline warn">${t("有两个 agent 会话在用这个对话")}${t("：")}${esc(AGENT.sessions.join(t("、")))}</div>` : "";
  const q = AGENT.queued;
  // only an honest reason: the queue, or the supervisor being down (then nobody comes until the coordinator starts it)
  const away = q ? queueWhy(q)
    : AGENT.server_down ? t("连不上 GameAnything 服务：页面上的状态可能不是最新的。服务恢复后会自动接上。")
    : !AGENT.online && !daemonUp() && !AGENT.owner_live && AGENT.phase !== "working"
      ? t("后台调度没有运行，暂时没有 agent 来读新消息。你照样可以说，话会排队；调度恢复后会自动接上。") : "";
  $("#offline").innerHTML = two + (away ? `<div class="offline">${away}</div>` : "");
  renderBuild();
}
/* files the pages read that are broken (/api/shell bad_files, filecheck.py): a list above the chat, so a bad file never blanks the
   workspace without saying which one (QA2 2026-10-30) */
function renderBadFiles(fs) {
  let el = $("#badfiles");
  if (!el) { const o = $("#offline"); if (!o) return; el = document.createElement("div"); el.id = "badfiles"; o.parentNode.insertBefore(el, o); }
  el.innerHTML = fs.length ? `<div class="offline warn"><b>${t("这些文件有问题，有的页面可能显示不全：")}</b><ul class="errfiles">${fs.map(f => `<li><code>${esc(f.file)}</code> <span>${esc(f.problem)}</span></li>`).join("")}</ul>${t("请 agent 改好（gameanything flow check 会列出来）")}</div>` : "";
}
/* browser notifications (opt-in per browser and project; this tab must stay open): the build is done / stopped, it is stuck or paused,
   or a card waits for her. Only while the tab is not in front: in front she sees it in the chat anyway. */
const NOTIFY_KEY = "m2w.notify." + (BASE || "/");
const NOTIFY_LIVE = new Set(["build_end", "build_pause", "build_stall", "build_auth", "resident_pause", "resident_stall", "gen_stall"]);
const notifyOn = () => { try { return "Notification" in window && Notification.permission === "granted" && localStorage.getItem(NOTIFY_KEY) === "1"; } catch (e) { return false; } };
const notifyBtn = () => !("Notification" in window) ? "" : `<button class="live nbell ${notifyOn() ? "" : "off"}" id="nbell" title="${esc(t(notifyOn() ? "点一下关掉浏览器通知" : "构建做好、卡住、或者有卡片等你时，浏览器通知你（这个页面要开着）"))}"><i></i>${t(notifyOn() ? "通知已开" : "开启通知")}</button>`;
function wireNotify() {
  const b = $("#nbell"); if (!b) return;
  b.onclick = async () => {
    try {
      if (notifyOn()) localStorage.setItem(NOTIFY_KEY, "0");
      else if ((Notification.permission === "granted" ? "granted" : await Notification.requestPermission()) === "granted") localStorage.setItem(NOTIFY_KEY, "1");
      else toast(t("浏览器没有允许通知：可以在地址栏左边的网站设置里打开"));
    } catch (e) { /* storage blocked */ }
    renderPills();
  };
}
function notifyFor(evs) {
  if (!notifyOn() || !document.hidden) return;
  const title = (SH && SH.title) || "GameAnything";
  for (const e of evs) {
    let body = null, tag = null;
    if (e.type === "status" && NOTIFY_LIVE.has(e.live)) { body = e.text; tag = e.live; }
    else if (e.type === "card" && ANSWERABLE.has(e.card.kind) && e.from !== "user") { body = t("有一张卡在等你：{t}", { t: e.card.title || "" }); tag = "card-" + (e.card.key || e.id); }
    if (!body) continue;
    try { const n = new Notification(title, { body, tag }); n.onclick = () => { window.focus(); n.close(); }; } catch (e2) { /* not allowed here */ }
  }
}
/* "background build" banner: shown while a milestone is building, whether or not an agent is online */
const hmin = n => { n = Math.round(n || 0); const h = Math.floor(n / 60), mm = n % 60; return h ? t("{h} 小时 {m} 分", { h, m: String(mm).padStart(2, "0") }) : t("{m} 分", { m: mm }); };
function renderBuild() {
  const el = $("#building"); if (!el) return;
  el.innerHTML = (BUILD || []).map(b => {
    const bits = [b.name];
    if (b.round) bits.push(b.max_rounds ? t("第 {k} 轮 / 最多 {n} 轮", { k: b.round, n: b.max_rounds }) : t("第 {k} 轮", { k: b.round }));
    else if (b.max_rounds) bits.push(t("还没开始试玩（最多 {n} 轮）", { n: b.max_rounds }));
    if (b.elapsed_min != null) bits.push(t("已进行 {t}", { t: hmin(b.elapsed_min) }));
    const upd = b.updated ? t("更新于 {t}", { t: hhmm(b.updated) }) : "";
    return `<div class="building" data-ws="now" title="${esc(t("打开工作台"))}" style="cursor:pointer"><span class="ring"></span><div><b>${t("后台构建中")}${t("：")}</b>${esc(bits.join(" · "))}${b.step || upd ? `<small>${esc([b.step, upd].filter(Boolean).join(" · "))}</small>` : ""}</div></div>`;
  }).join("");
  el.onclick = e => { const a = e.target.closest("[data-ws]"); if (a) ws(a.dataset.ws); };
}

/* ------------------------------------------------------------ thread state */
let EV = [];                    // all events, in file order
let slots = new Map();          // card event id -> {el, sig}: every card has its own place in the thread
let lastDay = "", lastId = null, firstLoad = true;
const edit = new Set();         // card ids the user is re-answering
const draft = new Map();        // card id -> draft state of an unanswered card (survives re-renders)

// A card sent again under a key that was used before (the next round's questions under the same key): the new one is the live card, at its
// own place (the bottom); the older one stays where it was, read-only, with its own answers and "updated, see below" (c.newer = the newer
// card's id). Answers belong to the card id they were given to, never to the newer card. Thread.cards() (conversation.py) agrees: it keeps
// only the newest card of a key, so an answer to an older one is refused. A progress card is the exception: only the newest is shown.
// Only the newest is shown when the older one was never answered: a progress card, or the same task sent again while it was still open
// (one card, updated, not two; QA 2026-10-29).
const cardState = () => {
  const cards = new Map(), byKey = new Map(), answered = new Set();
  for (const e of EV) if (e.type === "answer") answered.add(e.card_id);
  for (const e of EV) {
    if (e.type !== "card") continue;
    const k = e.card.key, prev = k && byKey.get(k);
    if (prev && cards.has(prev)) { if (e.card.kind === "progress" || !answered.has(prev)) cards.delete(prev); else cards.get(prev).newer = e.id; }
    if (k) byKey.set(k, e.id);
    for (const o of e.supersedes || []) if (cards.has(o)) { if (!answered.has(o)) cards.delete(o); else cards.get(o).newer = e.id; }   // an older go card of the same version (conversation.py _superseded_go)
    cards.set(e.id, { slot: e.id, ev: e, answers: [] });
  }
  for (const e of EV) if (e.type === "answer" && cards.has(e.card_id)) cards.get(e.card_id).answers.push(e);
  return cards;
};
const ANSWERABLE = new Set(["permission", "questions", "understanding", "options", "candidates", "go", "task"]);
const pending = () => [...cardState().values()].filter(c => ANSWERABLE.has(c.ev.card.kind) && !c.newer && !c.answers.length).length;

/* tiny markdown for the agent's words: **bold**, `code`, [text](url), "- " lists */
function md(s) {
  // links: [text](url) and bare http(s) URLs or /conv/ /media/ /build/ paths; a /conv/ file downloads
  const link = (a, u) => `<a href="${esc(at(u))}" ${u[0] === "#" ? `data-ws="${esc(u)}"` : `target="_blank" rel="noopener"${u.startsWith("/conv/") ? " download" : ""}`}>${esc(a)}</a>`;
  const inl = t => {
    const L = [], keep = h => (L.push(h), `\u0000${L.length - 1}\u0000`);
    t = String(t).replace(/\[([^\]]+)\]\(((?:https?:\/\/|#|\/)[^)\s]*)\)/g, (_, a, u) => keep(link(a, u)))
      .replace(/https?:\/\/[^\s<>"'）)，。]+|(?<![\w\/.])\/(?:conv|media|build)\/[^\s<>"'）)，。]+/g, u => keep(link(u, u)));
    return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\u0000(\d+)\u0000/g, (_, i) => L[+i]);
  };
  const out = []; let list = false;
  for (const ln of String(s || "").split("\n")) {
    const m = /^\s*[-*]\s+(.*)$/.exec(ln);
    if (m) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inl(m[1])}</li>`); continue; }
    if (list) { out.push("</ul>"); list = false; }
    if (ln.trim()) out.push(`<p>${inl(ln)}</p>`);
  }
  if (list) out.push("</ul>");
  return out.join("");
}

/* ------------------------------------------------------------ messages */
const convUrl = p => p && p.startsWith("conversation/files/") ? "/conv/" + p.slice(19) : p;
function ctxChip(c) {
  if (c.kind === "video") {
    const fr = c.frame ? `<img class="fr zoomable" src="${esc(convUrl(c.frame))}" alt="" data-zoom="${esc(convUrl(c.frame))}">` : "";
    const n = String(c.m || "").replace(/\D/g, "");
    return `<span class="ctx">${fr}${t("试玩 · 第 {n} 版 · {t}", { n: n || c.m, t: fmtT(+c.t || 0) })}</span>`;
  }
  if (c.kind === "file") return `<span class="ctx f">${icon("clip", "width:12px;height:12px")}${esc((c.path || "").split("/").pop())}</span>`;
  const kl = { person: "人物 · ", check: "检查 · ", region: "画面框选 · ", plan: "方案 · ", adaptation: "", gameplay: "", feature: "" }[c.kind] ?? "时刻 · ";
  return `<span class="ctx f">${t(kl)}${esc(c.label || c.id)}</span>`;
}
function userMsg(e) {
  const el = document.createElement("div"); el.className = "msg me"; el.dataset.id = e.id;
  const ctx = (e.context || []).map(ctxChip).join(" ");
  const by = e.author && SH && SH.hub ? `<div class="metaline by">${esc(e.author === SH.hub.user ? t("你") : e.author_name || e.author)}</div>` : "";
  const meta = e.auto ? t("页面操作（不是你写的话）") : e.source === "import" ? t("导入自 answers.md") + (e.round ? " · " + e.round : "") : e.source === "terminal" ? t("在终端里说的") : (e.context || []).some(c => c.kind === "video") ? t("在试玩里对着录像说的，也进对话") : "";
  el.innerHTML = `<div class="col">${by}<div class="bubble">${ctx ? ctx + (e.text ? "<br>" : "") : ""}${esc(e.text)}</div>${meta ? `<div class="metaline" style="margin:3px 0 0">${esc(meta)}</div>` : ""}</div>`;
  return el;
}
// download buttons for files the agent attached (`gameanything chat say --attach`)
const files = e => (e.files || []).length ? `<div class="files">${e.files.map(n => `<a class="btn ghost" href="${esc(at("/conv/" + encodeURIComponent(n)))}" download="${esc(n)}">⬇ ${esc(t("下载"))} ${esc(n)}</a>`).join("")}</div>` : "";
function agentMsg(e, body) {
  const el = document.createElement("div"); el.className = "msg ai";
  el.innerHTML = `<div class="av">G</div><div class="body"><div class="who"><b>agent</b>${hhmm(e.at)}</div>${body}</div>`;
  return el;
}
function addDay(e) {
  const d = dayKey(e.at);
  if (d && d !== lastDay) { lastDay = d; const x = document.createElement("div"); x.className = "day"; x.textContent = fmtDay(e.at); $("#thread").append(x); }
}

/* ------------------------------------------------------------ cards */
const KIND_LABEL = new Proxy({ permission: "许可 · 发送前先问你", questions: "问题", understanding: "我的理解 · 可以直接改", result: "成果", options: "方案 · 可以多选，可以加一句话", candidates: "候选 · 试听后挑一个，也可以都不要", go: "开工", progress: "进行中", task: "任务 · 请你在工作区里做" },
  { get: (o, k) => t(o[k]) });
const last = c => c.answers[c.answers.length - 1];
const redone = c => c.answers.length > 1 ? `<span class="tag-edit">${t("改过")}</span>` : "";
const doneBtn = (txt, cls = "done") => `<button class="btn ${cls}" disabled>${icon("check", "width:13px;height:13px")}${esc(txt)}</button>`;
const reBtn = id => `<button class="lnk" data-act="redo" data-id="${id}">${t("改答案")}</button>`;
const noteBox = (v = "", ph = "想补充一句（可选）") => `<textarea class="inp note" rows="1" placeholder="${esc(t(ph))}">${esc(v)}</textarea>`;
const openBtn = (c, txt) => c.open ? `<button class="btn ghost" data-open="${esc(c.open)}">${t(txt)}</button>` : "";
const letter = (it, i) => String(it.key).length <= 2 ? String(it.key).toUpperCase() : String.fromCharCode(65 + i);

// how long, in words: under an hour in minutes ([0.01, 0.05] h was shown as 「0.01–0.05 小时」, QA 2026-10-29)
function hoursText(w) {
  if (!Array.isArray(w) || w.length !== 2) return "";
  if (w[1] < 1) { const m = w.map(x => Math.max(1, Math.round(x * 60))); return t("{m} 分钟", { m: m[0] === m[1] ? m[0] : `${m[0]}–${m[1]}` }); }
  return t("{h} 小时", { h: w[0] === w[1] ? w[0] : `${w[0]}–${w[1]}` });
}
// a go card that starts a build of a version (the build model, playtest rounds), not e.g. drawing preview pictures
// (flow_step is on the event, `chat card --flow-step`; QA2 2026-10-30: the preview go card still showed the build model)
const isBuildGo = (k, ev) => !["preview", "perceive"].includes(k.flow_step || (ev && ev.flow_step)) && (((SH && SH.rounds) || []).some(r => r.m === k.milestone) || /^m\d+[a-z]?$/i.test(String(k.milestone || "")));
// one item of a go card: a line, or {title / text / what, desc}: never raw JSON (QA2 2026-10-30)
function goItem(x) {
  if (x == null || typeof x !== "object") return String(x ?? "");
  const head = x.title || x.text || x.what || x.name || "", tail = x.desc || x.detail || x.why || "";
  return [head, tail].filter(Boolean).join(" — ") || Object.values(x).filter(v => typeof v === "string" || typeof v === "number").join(" · ");
}
// the permission card a go card depends on (the same step's 「许可」: preview-permission + preview-go): its 不同意 / no answer keeps 开工 off
function permFor(ev) {
  const k = ev.card, fs = k.flow_step || ev.flow_step, stem = String(k.key || "").replace(/[-_]?go$/i, "");
  let hit = null;
  for (const x of cardState().values()) {
    const pk = x.ev.card; if (x.newer || pk.kind !== "permission" || x.ev.id === ev.id) continue;
    const pstem = String(pk.key || "").replace(/[-_]?(permission|perm)$/i, ""), pfs = pk.flow_step || x.ev.flow_step;
    if ((stem && pstem && stem === pstem) || (!isBuildGo(k, ev) && fs && pfs === fs)) hit = x;      // the newest one
  }
  return hit;
}
// an OLDER go card with runners: the runner whose estimate is shown (its build model's, else the recommended one). Builds ignore runners.
const goDefault = RS => RS.find(r => r.build_default) || RS.find(r => r.recommended) || RS[0] || {};
const RENDER = {
  permission(c, st) {
    const k = c.card, a = last(st), ed = !a || edit.has(c.ev.id);
    return `<div class="card perm"><div class="ctype">${KIND_LABEL.permission}</div><h4>${esc(k.title)}</h4>
      <ul><li>${t("发给：")}${esc(k.to)}</li>${(k.will_send || []).map(x => `<li>${t("会发：")}${esc(x)}</li>`).join("")}${(k.will_not_send || []).map(x => `<li>${t("不会发：")}${esc(x)}</li>`).join("")}
        ${k.cost_usd ? `<li>${t("约 {c}", { c: "$" + (+k.cost_usd).toFixed(2) })}</li>` : ""}</ul>
      ${ed ? `${noteBox(a ? (a.answer.note || "") : "")}<div class="foot"><button class="btn" data-act="yes">${t("同意")}</button><button class="btn ghost" data-act="no">${t("不同意")}</button>${a ? `<button class="lnk" data-act="cancel">${t("取消")}</button>` : ""}</div>`
        : `<div class="foot">${doneBtn(a.answer.decision === "yes" ? t("你同意了") : t("你没同意"), a.answer.decision === "yes" ? "done" : "ghost")}<span class="time">${hhmm(a.at)}</span>${redone(st)}${reBtn(c.ev.id)}</div>
          ${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  questions(c, st) {
    const k = c.card, ans = {}, skipped = new Set(); st.answers.forEach(a => { Object.assign(ans, a.answer.answers || {}); (a.answer.skipped || []).forEach(n => skipped.add(String(n))); });
    const dr = draft.get(c.ev.id) || {}, done = k.items.filter(i => String(ans[i.n] ?? "").trim()).length;
    const cnt = {}; st.answers.forEach(a => Object.keys(a.answer.answers || {}).forEach(n => cnt[n] = (cnt[n] || 0) + 1));
    return `<div class="card"><div class="ctype">${t("问题 · {n} 个", { n: k.items.length })}${st.answers.length ? t("，你答了 {n} 个", { n: done }) : ""}</div><h4>${esc(k.title)}</h4>
      ${k.items.map(i => { const n = String(i.n), mine = String(ans[n] ?? ""), sk = ((dr.skip || {})[n] ?? skipped.has(n)) && !mine.trim();
        return `<div class="q ${sk ? "skip" : ""}" data-n="${esc(n)}">${i.image ? `<img class="zoomable" src="${esc(convUrl(i.image))}" alt="" data-zoom="${esc(convUrl(i.image))}" title="${esc(t("看大图"))}">` : `<div></div>`}<div class="t">${esc(n)}. ${esc(i.text)}${i.hint ? `<small><br>${esc(i.hint)}</small>` : ""}
          ${mine.trim() && !edit.has(c.ev.id + ":" + n) ? `<div class="answered">${esc(mine)}${cnt[n] > 1 ? `<span class="tag-edit">${t("改过")}</span>` : ""} <button class="sk" data-act="reanswer" data-n="${esc(n)}">${t("改")}</button></div>`
            : `<textarea class="inp" rows="2" placeholder="${t(sk ? "已跳过；想答再写" : "你的回答（不确定可以跳过）")}">${esc(mine)}</textarea>`}
          ${mine.trim() && !edit.has(c.ev.id + ":" + n) ? "" : `<button class="sk" data-act="skip" data-n="${esc(n)}">${t(sk ? "取消跳过" : "跳过这个")}</button>`}</div></div>`; }).join("")}
      <div class="foot"><button class="btn" data-act="submit">${t(st.answers.length ? "提交新的回答" : "提交已答的")}</button><span class="muted">${t("可以只答一部分，剩下的以后再答")}</span></div></div>`;
  },
  understanding(c, st) {
    const k = c.card, a = last(st), edits = {}; st.answers.forEach(x => Object.assign(edits, x.answer.edits || {}));
    const ok = a && a.answer.ok && !Object.keys(a.answer.edits || {}).length, ed = !a || edit.has(c.ev.id), dr = draft.get(c.ev.id) || {};
    const pt = p => { const id = String(p.id), cur = dr[id] ?? edits[id]; return `<li data-id="${esc(id)}" class="${cur != null ? "chg" : ""}"><span class="ed" ${ed ? `tabindex="0" data-act="editpt"` : ""}>${esc(cur ?? p.text)}</span></li>`; };
    return `<div class="card"><div class="ctype">${KIND_LABEL.understanding}</div><h4>${esc(k.title)}</h4><ul class="und">${k.points.map(pt).join("")}</ul>
      ${ed ? `${noteBox(a ? (a.answer.note || "") : "", "改动之外还想说什么（可选）")}<div class="foot"><button class="btn" data-act="ok">${t(Object.keys(dr).length ? "提交修改" : "都对")}</button>
          <span class="muted">${t("点一条就能直接改")}</span></div>`
        : `<div class="foot">${doneBtn(ok ? t("你确认了") : Object.keys(edits).length ? t("你改了 {n} 条", { n: Object.keys(edits).length }) : t("你提了意见"))}<span class="time">${hhmm(a.at)}</span>${redone(st)}${reBtn(c.ev.id)}</div>${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  result(c) {
    const k = c.card;
    const rn = ((SH && SH.rounds) || []).find(r => r.m === k.milestone), img = k.image ? esc(convUrl(k.image)) : "";
    return `<div class="card"><div class="ctype">${t("成果")} · ${esc(rn ? rn.name : k.milestone)}</div><div class="res">${img ? `<img class="px zoomable" src="${img}" alt="" data-zoom="${img}" title="${esc(t("看大图"))}">` : `<div></div>`}
      <div><h4 style="margin:0 0 4px">${esc(k.title)}</h4><div class="st">${(k.stats || []).map(s => `<span>${esc(s)}</span>`).join("")}</div>
        <div class="foot" style="margin-top:8px">${img ? `<button class="btn ghost" data-zoom="${img}">${t("看大图")}</button>` : ""}${k.open ? `<button class="btn" data-open="${esc(k.open)}">${t("打开试玩页")}</button>` : ""}</div></div></div></div>`;
  },
  options(c, st) {
    const k = c.card, a = last(st), ed = !a || edit.has(c.ev.id), dr = draft.get(c.ev.id) || {};
    const picked = new Set((dr.picked ?? (a ? a.answer.picked : defaultPicked(c))).map(String));
    const names = [...picked].map(x => (k.items.find(i => String(i.key) === x) || { title: x }).title);   // titles, not 「ch1 + ch2」
    return `<div class="card"><div class="ctype">${k.multi === false ? t("方案 · 选一个") : KIND_LABEL.options}</div><h4>${esc(k.title)}</h4>
      ${k.items.map((i, n) => `<div class="opt ${picked.has(String(i.key)) ? "on" : ""} ${ed ? "" : "dis"}" data-k="${esc(i.key)}"><span class="k">${esc(letter(i, n))}</span><div><b>${esc(i.title)}</b>${i.recommended ? `<span class="rec">${t("建议")}</span>` : ""}${i.cost ? `<span class="rec" style="color:var(--warn);background:#FFFBEB">${esc(i.cost)}</span>` : ""}<small>${esc(i.desc || "")}</small></div></div>`).join("")}
      ${ed ? `${noteBox(dr.note ?? (a ? a.answer.note || "" : ""), "想补充一句（可选）")}<div class="foot"><button class="btn" data-act="submit">${t("发送")}</button><span class="muted">${names.map(x => esc(x)).join(" + ") || t("还没选")}</span></div>`
        : `<div class="foot">${doneBtn(t("已发送"))}<span class="muted" style="margin-left:0">${names.map(x => esc(x)).join(" + ") || t("没选")}</span>${redone(st)}${reBtn(c.ev.id)}</div>${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  candidates(c, st) {
    const k = c.card, a = last(st), ed = !a || edit.has(c.ev.id), dr = draft.get(c.ev.id) || {};
    const picked = new Set((dr.picked ?? (a ? a.answer.picked : [])).map(String));
    const med = i => k.media === "audio" ? `<audio controls preload="none" src="${esc(convUrl(i.url))}"></audio>` : `<img class="zoomable" src="${esc(convUrl(i.url))}" alt="" loading="lazy" data-zoom="${esc(convUrl(i.url))}">`;
    return `<div class="card"><div class="ctype">${KIND_LABEL.candidates}</div><h4>${esc(k.title)}</h4>
      ${k.items.map(i => `<div class="cand ${picked.has(String(i.key)) ? "on" : ""} ${ed ? "" : "dis"}" data-k="${esc(i.key)}"><div><b>${esc(i.title)}</b><small>${esc(i.desc || "")}</small>${med(i)}</div>
        ${ed ? `<button class="btn ${picked.has(String(i.key)) ? "done" : "ghost"}" data-act="pick" data-k="${esc(i.key)}">${picked.has(String(i.key)) ? t("选了") : t("选这个")}</button>` : picked.has(String(i.key)) ? `<button class="btn done" disabled>${t("选了")}</button>` : ""}</div>`).join("")}
      ${ed ? `${noteBox(dr.note ?? (a ? a.answer.note || "" : ""), "都不喜欢？说说想要什么样的")}<div class="foot"><button class="btn" data-act="submit">${picked.size ? t("发送") : t("都不要，发送")}</button>
          <span class="muted">${t("{a}；都不要的话请写一句原因", { a: k.multi ? t("可以多选") : t("选一个") })}</span></div>`
        : `<div class="foot">${doneBtn(picked.size ? t("已选") : t("都不要"))}<span class="time">${hhmm(a.at)}</span>${redone(st)}${reBtn(c.ev.id)}</div>${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  go(c, st) {
    const k = c.card, a = last(st), ed = !a || edit.has(c.ev.id), dr = draft.get(c.ev.id) || {};
    const RS = k.runners || [], R = RS.find(r => r.id === (a && a.answer.runner)) || goDefault(RS);
    const E = k.estimate || (R && R.estimate), rg = r => r[0] === r[1] ? `${r[0]}` : `${r[0]}–${r[1]}`, api = E && E.account === "api", money = api && E.cost_usd ? "$" + rg(E.cost_usd) : "";
    const rn = ((SH && SH.rounds) || []).find(r => r.m === k.milestone), build = isBuildGo(k, c.ev);
    const P = permFor(c.ev), pa = P && last(P), blocked = ed && P && !(pa && pa.answer.decision === "yes");
    const sum = [!E && k.eta_hours && t("预计 {n} 小时", { n: k.eta_hours }), !E && k.cost_usd && t("约 {c}", { c: "$" + k.cost_usd }), k.max_images && t("最多 {n} 张图", { n: k.max_images })].filter(Boolean).join(" · ");
    const est = E ? `<div class="est ${api ? "api" : "sub"}"><div class="row"><span><small>${t("预计时间")}</small><b>${hoursText(E.wall_h)}</b></span>
      <span><small>${api ? t("预计花费") : t("额度")}</small><b>${api ? (money ? t("约 {c}", { c: money }) : t("估不出来")) : t("用你的订阅额度")}</b></span></div>
      <p>${api ? t("按你的 API key 计费。这是估计，不是报价。") : t("一期大约要连续跑 {h} 小时，可能用完你这几个小时的额度。额度用完时这一期可能停在中途，需要你之后再开一次。", { h: rg(E.wall_h) })}</p>
      ${E.note ? `<small class="enote">${esc(E.note)}</small>` : ""}<small class="enote">${t("你点了开工才会开始。")}</small></div>` : "";
    const runners = build ? goModelHtml(k, ed && !c.newer, MODELS) : "";      // a go card that is not a build (preview pictures): no build model
    const gate = blocked ? `<div class="gperm">${pa ? t("你没同意上面的许可（{p}），所以这一步不能开工。改主意的话，先在许可卡上点「改答案」。", { p: esc(P.ev.card.title) })
      : t("先回答上面的许可卡（{p}），才能开工。", { p: esc(P.ev.card.title) })}</div>` : "";
    return `<div class="card go"><div class="ctype">${t("开工")} · ${esc(rn ? rn.name : k.milestone)}</div><h4>${esc(k.title)}</h4><ol>${k.items.map(x => `<li>${esc(goItem(x))}</li>`).join("")}</ol>
      ${runners}${k.playtest_rounds ? `<div class="rounds">${t("最多")} ${ed ? `<input class="inp rnd" type="number" min="1" max="10" value="${esc(String(dr.rounds ?? (a && a.answer.playtest_rounds) ?? k.playtest_rounds))}">` : `<b>${esc(String((a && a.answer.playtest_rounds) || k.playtest_rounds))}</b>`} ${t("轮试玩评审")}${k.wall_hours ? ` · ${t("最多 {h} 小时", { h: k.wall_hours })}` : ""}<small>${t("构建 agent 每做完一版就请试玩评审看一次、再改；轮数越多越细，花费和时间也越多。")}</small></div>` : ""}${est}${sum ? `<p class="sum">${esc(sum)}</p>` : ""}
      ${gate}${ed ? `${noteBox(a ? a.answer.note || "" : "", "想补充一句（可选）")}<div class="foot"><button class="btn" data-act="start"${blocked ? " disabled" : ""}>${money ? t("开工（约 {c}）", { c: money }) : t("开工")}</button><button class="btn ghost" data-act="wait">${t("再等等")}</button>${openBtn(k, "看完整方案")}</div>`
        : `<div class="foot">${doneBtn(a.answer.decision === "start" ? t("已开工 {t}", { t: hhmm(a.at) }) : t("你说再等等"), a.answer.decision === "start" ? "done" : "ghost")}${redone(st)}${reBtn(c.ev.id)}${openBtn(k, "看完整方案")}</div>${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  task(c, st) {
    const k = c.card, a = last(st), ed = !a || edit.has(c.ev.id), go = openBtn(k, "去做").replace('class="btn ghost"', 'class="btn"');
    return `<div class="card task"><div class="ctype">${KIND_LABEL.task}${k.estimate ? `<span class="est">${esc(k.estimate)}</span>` : ""}</div><h4>${esc(k.title)}</h4>
      <p class="tbody">${esc(k.body)}</p>${k.done_hint ? `<p class="thint">${t("做好的样子：")}${esc(k.done_hint)}</p>` : ""}
      ${ed ? `${noteBox(a ? a.answer.note || "" : "", "做完想补一句（可选）")}<div class="foot">${go}<button class="btn ghost" data-act="taskdone">${icon("check", "width:13px;height:13px")}${t("做好了")}</button><button class="btn ghost" data-act="tasklater">${t("稍后")}</button>${a ? `<button class="lnk" data-act="cancel">${t("取消")}</button>` : ""}</div>`
        : `<div class="foot">${doneBtn(a.answer.done ? t("你做好了") : t("你说稍后"), a.answer.done ? "done" : "ghost")}<span class="time">${hhmm(a.at)}</span>${redone(st)}${reBtn(c.ev.id)}${a.answer.done ? "" : go}</div>${a.answer.note ? `<div class="answered">${esc(a.answer.note)}</div>` : ""}`}</div>`;
  },
  progress(c) {
    const k = c.card, m = k.meter;
    const hm = n => { n = Math.round(n || 0); const h = Math.floor(n / 60), mm = n % 60; return h ? (mm ? t("{h} 小时 {m} 分", { h, m: mm }) : t("{h} 小时", { h })) : t("{m} 分", { m: mm }); };
    const meter = m ? `<div class="meter">
        <div class="mrow"><span class="mlab">${t("试玩评审")}</span><span class="dots">${Array.from({ length: m.max_rounds || 0 }, (_, i) =>
          `<i class="${i < (m.round || 0) - (m.done ? 0 : 1) ? "d" : i === (m.round || 0) - 1 && !m.done ? "c" : ""}"></i>`).join("")}</span>
          <b>${m.round ? t("第 {k} / {n} 轮", { k: m.round, n: m.max_rounds }) : t("还没开始（最多 {n} 轮）", { n: m.max_rounds })}</b></div>
        <div class="mrow"><span class="mlab">${t("时间")}</span><span class="bar"><i style="width:${Math.min(100, (m.elapsed_min || 0) / (m.wall_min || 1) * 100)}%"></i></span>
          <b>${t("{a} / 最多 {b}", { a: hm(m.elapsed_min), b: hm(m.wall_min) })}</b></div>
        ${m.est_h ? `<small>${m.est_h[0] === m.est_h[1] ? t("开工卡上的预计：{a} 小时", { a: m.est_h[0] }) : t("开工卡上的预计：{a}–{b} 小时", { a: m.est_h[0], b: m.est_h[1] })}</small>` : ""}
        ${m.runner ? `<small>${esc(m.runner)}</small>` : ""}</div>` : "";
    // agentd's live build card (live.py): what the builder does right now, a banner when it is stuck / paused, the newest pictures
    const EN_ = M2W.lang === "en", al = k.alert;
    const alert = al ? `<div class="lalert ${esc(al.kind)}">${esc(EN_ && al.text_en ? al.text_en : al.text)}</div>` : "";
    const nowl = k.now ? `<div class="lnow"><span class="ring"></span><span>${esc(EN_ && k.now_en ? k.now_en : k.now)}</span>${k.now_at ? `<span class="time">${hhmm(k.now_at)}</span>` : ""}</div>` : "";
    const shots = (k.images || []).length ? `<div class="lshots">${k.images.map(u => `<img class="zoomable" src="${esc(u)}" data-zoom="${esc(u)}" loading="lazy" alt="">`).join("")}</div>` : "";
    return `<div class="card ${k.live ? "livecard" : ""}"><div class="ctype" style="color:var(--violet-deep)">${esc(!k.title || k.title === "进行中" ? t("进行中") : k.title)} · ${esc(k.milestone)}</div>${alert}${nowl}${meter}
      <ul class="prog">${k.steps.map(s => `<li class="${s.state === "done" ? "d" : s.state === "current" ? "c" : ""}">${esc(s.text)}</li>`).join("")}</ul>${shots}
      ${k.open ? `<div class="foot">${openBtn(k, k.live ? "看工作台" : "打开")}</div>` : ""}</div>`;
  },
};

function cardEl(c) {
  const el = document.createElement("div"); el.className = "msg ai"; el.dataset.id = c.ev.id;
  paintCard(el, c); wireCard(el, c.slot); return el;
}
function paintCard(el, c) {
  const e = c.ev;
  el.classList.toggle("old", !!c.newer);     // superseded by a newer card of the same key: read-only (shell.html hides its inputs)
  const upd = c.newer ? `<div class="newer"><button class="lnk" data-newer="${esc(c.newer)}">${t("已更新，见下方")}</button></div>` : "";
  el.innerHTML = `<div class="av">G</div><div class="body"><div class="who"><b>${e.from === "system" ? "GameAnything" : "agent"}</b>${hhmm(e.at)}</div>${e.text ? `<div class="md">${md(e.text)}</div>` : ""}${RENDER[c.card ? c.card.kind : e.card.kind]({ ...c, card: e.card }, c)}${upd}</div>`;
}

/* gathering what the user typed into a card */
const val = (el, sel) => { const x = $(sel, el); return x ? x.value : ""; };
function wireCard(el, slot) {
  el.oninput = ev => {                                    // an understanding card: a typed note turns "都对" into "提交修改"
    if (!ev.target.matches("textarea.note")) return;
    const b = $(".foot [data-act=ok]", el), c = cardState().get(slot); if (!b || !c) return;
    const d = draft.get(c.ev.id) || {}, n = Object.keys(d).filter(x => x !== "picked" && x !== "skip").length;
    b.textContent = t(n || ev.target.value.trim() ? "提交修改" : "都对");
  };
  el.onclick = async ev => {
    const c = cardState().get(slot); if (!c) return;
    const nw = ev.target.closest("[data-newer]");
    if (nw) { const x = $(`#thread .msg[data-id="${CSS.escape(nw.dataset.newer)}"]`); if (x) x.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    const tg = ev.target.closest("[data-act],[data-open],.opt,[data-ws]"); if (!tg) return;
    if (c.newer && !tg.dataset.open && !tg.dataset.ws) return;             // an older version: nothing to answer any more
    const id = c.ev.id, kind = c.ev.card.kind, k = c.ev.card;
    if (tg.dataset.ws) { ev.preventDefault(); return ws(tg.dataset.ws); }
    if (tg.dataset.open) return ws(tg.dataset.open);
    const d = draft.get(id) || {}; draft.set(id, d);
    const note = () => val(el, "textarea.note").trim();
    const send = async a => { const r = await post("/api/thread/answer", { card_id: id, answer: a }); if (!r.ok) return toast(r.error || t("没能发出去")); edit.delete(id); draft.delete(id); await poll(); };
    if (tg.classList.contains("opt") && !tg.dataset.act) {
      if (!$(".foot [data-act=submit]", el)) return;
      const key = tg.dataset.k, s = new Set((d.picked ?? lastPicked(c)).map(String));
      if (k.multi === false) { s.clear(); s.add(key); } else s.has(key) ? s.delete(key) : s.add(key);
      d.picked = [...s]; return refresh(c);
    }
    switch (tg.dataset.act) {
      case "redo": edit.add(id); return refresh(c);
      case "cancel": edit.delete(id); draft.delete(id); return refresh(c);
      case "yes": return send({ decision: "yes", note: note() });
      case "no": return send({ decision: "no", note: note() });
      case "start": {                            // no runner: builds run on the project's build model only (builds.py)
        if (tg.disabled) return;
        const ri = $("input.rnd", el), pr = ri ? parseInt(ri.value, 10) : null;
        if (ri && !(pr >= 1 && pr <= 10)) return toast(t("试玩轮数要在 1 到 10 之间"));
        return send({ decision: "start", note: note(), ...(pr ? { playtest_rounds: pr } : {}) }); }
      case "wait": return send({ decision: "wait", note: note() });
      case "taskdone": return send({ done: true, note: note() });
      case "tasklater": return send({ later: true, note: note() });
      case "pick": { const key = tg.dataset.k, s = new Set((d.picked ?? lastPicked(c)).map(String));
        if (!k.multi) { const was = s.has(key); s.clear(); if (!was) s.add(key); } else s.has(key) ? s.delete(key) : s.add(key);
        d.picked = [...s]; return refresh(c); }
      case "submit":
        if (kind === "questions") {
          const answers = {}, skipped = [], prev = {}; c.answers.forEach(a => Object.assign(prev, a.answer.answers || {}));
          $$(".q", el).forEach(q => { const n = q.dataset.n, ta = $("textarea", q); const v = ta ? ta.value.trim() : "";
            if (v && v !== String(prev[n] ?? "").trim()) answers[n] = v; else if (!v && q.classList.contains("skip")) skipped.push(n); });
          if (!Object.keys(answers).length && !skipped.length) return toast(t("还没写任何回答"));
          return send({ answers, skipped });
        }
        if (kind === "options") { const p = d.picked ?? lastPicked(c); if (!p.length && !note()) return toast(t("先选一个，或者写一句话")); return send({ picked: p, note: note() }); }
        if (kind === "candidates") { const p = d.picked ?? lastPicked(c); if (!p.length && !note()) return toast(t("都不要的话，请写一句原因")); return send({ picked: p, note: note() }); }
        return;
      case "skip": { const q = tg.closest(".q"), dq = d.skip || (d.skip = {}); dq[q.dataset.n] = !q.classList.contains("skip"); return refresh(c); }
      case "reanswer": edit.add(id + ":" + tg.dataset.n); return refresh(c);
      case "editpt": { const li = tg.closest("li"), pid = li.dataset.id;
        const inp = document.createElement("input"); inp.className = "inp"; inp.value = tg.textContent; tg.replaceWith(inp); inp.focus();
        // leaving the field puts the text back in place WITHOUT repainting the card: a repaint between mousedown and click (the blur) ate
        // the click on 「提交修改」 / another point (QA 2026-10-29)
        const done = () => {
          if (!inp.isConnected) return;
          const v = inp.value.trim(), orig = k.points.find(p => String(p.id) === pid).text; d[pid] = v; if (!v || v === orig) delete d[pid];
          tg.textContent = d[pid] ?? orig; inp.replaceWith(tg); li.classList.toggle("chg", d[pid] != null);
          const b = $(".foot [data-act=ok]", el), n = Object.keys(d).filter(x => x !== "picked" && x !== "skip").length;
          if (b) b.textContent = t(n || note() ? "提交修改" : "都对");
        };
        inp.onblur = done; inp.onkeydown = e2 => { if (e2.key === "Enter") { e2.preventDefault(); inp.blur(); } if (e2.key === "Escape") { inp.value = tg.textContent; inp.blur(); } }; return; }
      case "ok": {
        const open_ = $("ul.und input.inp", el); if (open_) open_.blur();            // a point still being typed counts
        const edits = { ...d }; delete edits.picked; delete edits.skip;
        return Object.keys(edits).length ? send({ edits, note: note() }) : note() ? send({ note: note() }) : send({ ok: true });
      }
    }
  };
}
// an options card not answered yet starts with its recommended items ticked (the units card says 「默认已勾好」, QA2 2026-10-30)
// called with the render argument ({ev, card}) AND with the card state ({ev, answers}, the click handlers): read the card from either
const cardOf = c => (c && (c.card || (c.ev && c.ev.card))) || {};
const defaultPicked = c => { const k = cardOf(c); return k.kind === "options" && k.multi !== false ? (k.items || []).filter(i => i.recommended).map(i => String(i.key)) : []; };
const lastPicked = c => { const a = (c.answers || [])[(c.answers || []).length - 1]; return a ? (a.answer.picked || []) : defaultPicked(c); };
function refresh(c) {
  const slot = slots.get(c.slot); if (!slot) return;
  const cur = cardState().get(c.slot); if (!cur) return;
  // keep what the user is typing: textareas are read by key before the repaint and written back after
  const key = t => { const q = t.closest(".q"); return q ? "q" + q.dataset.n : "note"; };
  const vals = new Map($$("textarea", slot.el).filter(t => t.value).map(t => [key(t), t.value]));
  paintCard(slot.el, cur);
  $$("textarea", slot.el).forEach(t => { if (vals.has(key(t))) t.value = vals.get(key(t)); });
}

/* ------------------------------------------------------------ read receipt + "working" line */
let stateSig = "";
function renderState() {
  const th = $("#thread"), ids = EV.map(e => e.id), ci = AGENT && AGENT.cursor ? ids.indexOf(AGENT.cursor) : -1;
  const mine = EV.map((e, i) => [e, i]).filter(([e]) => e.from === "user" && (e.type === "text" || e.type === "answer") && e.source === "ui");
  const lastUser = mine.length ? mine[mine.length - 1] : null, lastRead = mine.filter(([, i]) => i <= ci).pop();
  const agentAfter = lastUser && EV.slice(lastUser[1] + 1).some(e => e.from === "agent");
  // the server's `phase` (conversation.phase): sent -> calling -> working -> the reply; or queued / failed / down. Shown whether or not
  // an agent is online, so a message never sits there without a word about what happens to it.
  let line = AGENT && AGENT.phase || "";
  if (!line && lastUser && !agentAfter && AGENT && AGENT.online) {             // an older server without `phase`
    const ni = AGENT.noticed ? ids.indexOf(AGENT.noticed) : -1; line = lastUser[1] <= Math.max(ci, ni) ? "working" : "sent";
  }
  if (!line && AGENT && AGENT.busy) line = "working";
  const sig = JSON.stringify([lastRead && lastRead[0].id, AGENT && AGENT.read_at, line, line === "queued" && AGENT.queued, M2W.lang]);
  const foot = $("#thstate");
  if (sig === stateSig && foot && foot === th.lastElementChild) return;
  stateSig = sig;
  const stick = th.scrollHeight - th.scrollTop - th.clientHeight < 80;
  $$(".seen", th).forEach(x => x.remove()); if (foot) foot.remove();
  if (lastRead) {
    const col = $(`.msg.me[data-id="${lastRead[0].id}"] .col`, th);
    if (col) { const x = document.createElement("div"); x.className = "seen"; x.textContent = t("已读") + (AGENT.read_at ? " " + hhmm(AGENT.read_at) : ""); col.append(x); }
  }
  const dots = `<span class="dots"><i></i><i></i><i></i></span>`, ring = `<span class="ring"></span>`;
  const LINE = { working: [ring, "agent 正在处理…"], sent: [dots, "已送达，等 agent 读取"], calling: [ring, "已送达 · 正在叫 agent，大约半分钟"],
    queued: [dots, "已送达 · 排队中"], paused: [dots, "已送达 · agent 暂停中，到时候自动再试"], failed: [dots, "agent 这次没能回复。再说一句会重新叫 agent"], down: [dots, "已送达，但后台调度没有运行，暂时没有 agent 来读"] };
  if (line === "failed" && AGENT.failed && AGENT.failed.reason === "auth") LINE.failed = [dots, "Claude 登录过期：命令行要单独登录一次，让桌面 App 里的 Claude 替你运行 claude auth login"];
  const why = AGENT.failed && (M2W.lang === "en" ? AGENT.failed.text_en : AGENT.failed.text);
  if (line === "failed" && why) LINE.failed = [dots, why];                      // the server's reason (login, the agent cannot work here, a crash, a loop)
  const bo = AGENT.backoff;
  if (line === "paused" && bo) LINE.paused = [dots, t("agent 暂停中，大约 {t} 自动再试", { t: M2W.lang === "en" ? bo.until_hm_en : bo.until_hm })];
  if (LINE[line]) {
    const x = document.createElement("div"); x.id = "thstate"; x.className = "thstate" + (line === "failed" || line === "down" || line === "paused" ? " bad" : "");
    x.innerHTML = LINE[line][0] + esc(t(LINE[line][1])) + (line === "queued" && AGENT.queued ? `<small>${esc(t("（最多同时 {c} 个项目）", { c: AGENT.queued.cap }))}</small>` : "");
    th.append(x);
  }
  if (stick) th.scrollTop = th.scrollHeight;
}

/* ------------------------------------------------------------ render the thread */
function toBottom(th, jump) {   // jump: no smooth animation (opening a long thread scrolled from the very top for seconds)
  if (!jump) { th.scrollTop = th.scrollHeight; return; }
  th.style.scrollBehavior = "auto"; th.scrollTop = th.scrollHeight; th.style.scrollBehavior = "";
}
function render(newEvents) {
  const th = $("#thread"), stick = firstLoad || th.scrollHeight - th.scrollTop - th.clientHeight < 80;
  const cards = cardState();
  for (const e of newEvents) {
    if (e.type === "text") {
      addDay(e); th.append(e.from === "user" ? userMsg(e) : agentMsg(e, `<div class="md">${md(e.text)}</div>${files(e)}`));
    } else if (e.type === "status") {
      const x = document.createElement("div"); x.className = "sys" + (e.live ? " lv " + String(e.live).replace(/[^a-z_]/g, "") : ""); x.textContent = e.text || ""; th.append(x);
    } else if (e.type === "card") {
      const k = e.card.key, prog = k && e.card.kind === "progress";
      const slotId = e.id;                                          // a new card under an old key: here, at the bottom (cardState)
      if (prog) for (const [id, s] of [...slots]) if (id !== slotId && s.el.dataset.pkey === k) { s.el.remove(); slots.delete(id); }   // the older version moves down
      if (!slots.has(slotId)) { const cc = cards.get(slotId); if (!cc) continue; addDay(e); const el = cardEl(cc); if (prog) el.dataset.pkey = k; th.append(el); slots.set(slotId, { el, sig: sig(cc) }); }
    }
  }
  for (const [id, s] of slots) {                                  // updated cards (answers; an older version that became read-only)
    const cc = cards.get(id); if (!cc) continue; const g = sig(cc);
    if (g !== s.sig) { s.sig = g; refresh(cc); }
  }
  if (!EV.length && firstLoad) th.innerHTML = `<div class="empty">${emptyText()}</div>`;
  else { const em = $(".empty", th); if (em && EV.length) em.remove(); }
  if (stick) {
    toBottom(th, firstLoad);
    // images and audio load after the first render and push the bottom down: keep following until they settle
    if (firstLoad && !th._follow) {           // media load after the first render and push the bottom down: follow it for a few seconds
      const stop = () => { clearInterval(th._follow); th.removeEventListener("wheel", stop); th.removeEventListener("touchstart", stop); };
      th._follow = setInterval(() => toBottom(th, true), 150); setTimeout(stop, 5000);
      th.addEventListener("wheel", stop, { passive: true }); th.addEventListener("touchstart", stop, { passive: true });
    }
  }
  const n = pending(); const cnt = $("#gochat .cnt");
  if (SH && (cnt ? +cnt.textContent : 0) !== n) renderSide();
  for (const [id, s] of [...slots]) if (!cards.has(id)) { s.el.remove(); slots.delete(id); }     // replaced by a newer card of its key (cardState)
}
const sig = c => { const P = c.ev.card.kind === "go" ? permFor(c.ev) : null;           // a go card also follows its permission card's answer
  return JSON.stringify([c.ev.id, c.ev.card, c.answers.map(a => a.id), c.newer || null, P ? [P.ev.id, P.answers.map(a => a.id)] : null]); };
// an empty thread: a brand-new project is greeted by the supervisor by itself (agentd), so say what is happening
const emptyText = () => AGENT.run || AGENT.busy ? `<span class="ring"></span>${t("agent 正在过来和你打招呼…")}`
  : daemonUp() ? t("agent 马上会来和你打个招呼。你也可以先在下面说说你的想法。")
  : t("还没有对话。在下面说说你的想法；后台调度没有运行，agent 暂时不会来，话会排队。");

let busy = false;
let pollFails = 0;
async function poll() {
  if (busy) return; busy = true;
  try {
    const r = await get("/api/thread" + (lastId ? "?after=" + encodeURIComponent(lastId) : ""));
    if (JSON.stringify(r.agent) !== JSON.stringify(AGENT)) { AGENT = r.agent; renderPills(); const em = $("#thread .empty"); if (em) em.innerHTML = emptyText(); }
    if (JSON.stringify(r.build || []) !== JSON.stringify(BUILD)) { BUILD = r.build || []; renderBuild(); }
    if (r.events.length && !firstLoad) notifyFor(r.events);
    if (r.events.length || firstLoad) { EV = EV.concat(r.events); if (r.events.length) lastId = r.events[r.events.length - 1].id; render(r.events); firstLoad = false; }
    renderState(); pollFails = 0;
  } catch (e) {                                  // server restarting / stopped: after two failed polls the page stops claiming 「agent 在线」
    if (++pollFails >= 2 && !AGENT.server_down) { AGENT = { ...AGENT, online: false, server_down: true }; renderPills(); }
  }
  busy = false;
}

/* ------------------------------------------------------------ composer */
let ctx = [];                  // context chips {kind, id|m|t|frame_data, label}
const sending = { files: [] };   // uploaded attachment paths (inbox-relative)
let uploads = 0;
function renderChips() {
  $("#chips").innerHTML = ctx.map((c, i) => `<span class="chip">${c.frame_data ? `<img src="${esc(c.frame_data)}" alt="">` : icon("at", "width:12px;height:12px")}${esc(chipLabel(c))}<button data-i="${i}" title="${t("去掉")}">×</button></span>`).join("")
    + sending.files.map((f, i) => `<span class="chip">${icon("clip", "width:12px;height:12px")}${esc(f.split("/").pop())}<button data-f="${i}" title="${t("去掉")}">×</button></span>`).join("");
  $$("#chips button").forEach(b => b.onclick = () => { if (b.dataset.i != null) ctx.splice(+b.dataset.i, 1); else sending.files.splice(+b.dataset.f, 1); renderChips(); });
}
const chipLabel = c => c.kind === "video" ? t("试玩 · 第 {n} 版 · {t}", { n: String(c.m).replace(/\D/g, "") || c.m, t: fmtT(+c.t || 0) }) : (c.kind === "person" ? t("人物 · ") : t("时刻 · ")) + (c.label || c.id);
window.addEventListener("message", ev => {
  if (ev.origin !== location.origin || !ev.data || ev.data.type !== "m2w-context") return;
  const add = (ev.data.context || []).filter(c => c && c.kind);
  ctx = ctx.filter(o => !add.some(n => n.kind === o.kind && (n.kind === "video" || n.id === o.id)));
  ctx.push(...add); renderChips();
  const ta = $("#msg"); if (ev.data.text && !ta.value) ta.value = ev.data.text;
  if (isPhone()) mview("chat");
  msgLen(); ta.focus();
});
const MSG_MAX = 20000;            // the server's cap (conversation.MSG_MAX): longer text goes in as an attached file
function msgLen() {               // a counter from 80 % of the cap, red past it
  const n = $("#msg").value.trim().length, el = $("#mlen"); if (!el) return n;
  el.className = "mlen" + (n > MSG_MAX ? " over" : n > MSG_MAX * 0.8 ? " near" : "");
  el.textContent = n > MSG_MAX * 0.8 ? `${n.toLocaleString()} / ${MSG_MAX.toLocaleString()}` : "";
  el.title = n > MSG_MAX ? t("太长了：一条最多 {n} 个字。长的内容请存成文件，用回形针附上。", { n: MSG_MAX }) : "";
  $("#cbox").classList.toggle("toolong", n > MSG_MAX); return n;
}
$("#msg").addEventListener("input", msgLen);
let inFlight = false;            // one send at a time: a second Enter / click while the first is on its way does nothing (QA: double Enter sent twice)
async function sendMsg() {
  if (inFlight) return;
  const ta = $("#msg"), text = ta.value.trim();
  if (uploads) return toast(t("文件还在上传，等一下"));
  if (!text && !sending.files.length) return;
  if (text.length > MSG_MAX) return toast(t("太长了：一条最多 {n} 个字。长的内容请存成文件，用回形针附上。", { n: MSG_MAX }));
  inFlight = true; $("#send").disabled = true;
  let r;
  try { r = await post("/api/thread", { text, context: ctx, attachments: sending.files }); }
  catch (e) { r = { ok: false }; }
  finally { inFlight = false; $("#send").disabled = false; }
  if (!r.ok) return toast(r.error || t("没能发出去"));
  ta.value = ""; msgLen(); ctx = []; sending.files = []; renderChips(); firstLoad = true; await poll(); toBottom($("#thread"), true);
}
$("#send").onclick = sendMsg;
$("#coachbtn").onclick = () => startCoach();
$("#msg").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); sendMsg(); } });
$("#pick").onchange = e => { attach([...e.target.files]); e.target.value = ""; };
const cb = $("#cbox");
["dragenter", "dragover"].forEach(e => cb.addEventListener(e, ev => { ev.preventDefault(); cb.classList.add("over"); }));
["dragleave", "drop"].forEach(e => cb.addEventListener(e, ev => { ev.preventDefault(); cb.classList.remove("over"); }));
cb.addEventListener("drop", ev => attach([...ev.dataTransfer.files]));
$("#thread").addEventListener("click", e => { const a = e.target.closest("[data-ws]"); if (a) { e.preventDefault(); ws(a.dataset.ws); } });

/* attachments go through the chunked upload into 0_inbox, then are referenced in the message as files */
const CHUNK = 8 * 1024 * 1024, rnd = () => "u" + [...crypto.getRandomValues(new Uint8Array(12))].map(x => x.toString(16).padStart(2, "0")).join("");
function attach(files) {
  if (!SH || SH.no_project) { if (files.length) toast(t("先建一个项目，再把文件放进来")); return; }   // no project: /api/upload would answer 409
  for (const f of files) {
    const row = document.createElement("div"); row.className = "u"; row.innerHTML = `<i style="width:0"></i><span>${esc(f.name)} · 0%</span>`; $("#ups").append(row);
    uploads++;
    upload(f, p => { $("i", row).style.width = p + "%"; $("span", row).textContent = `${f.name} · ${Math.round(p)}%`; })
      .then(path => { sending.files.push(path); row.remove(); renderChips(); })
      .catch(err => { row.classList.add("err"); $("span", row).textContent = `${f.name} · ${err.message}`; setTimeout(() => row.remove(), 6000); })
      .finally(() => uploads--);
  }
}
async function upload(file, onp, target) {
  if (!file.size) throw new Error(t("空文件"));
  const uid = rnd(); let at = 0, res = {};
  while (at < file.size) {
    const b = Math.min(at + CHUNK, file.size);
    res = await new Promise((ok, bad) => {
      const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
      x.setRequestHeader("X-Upload-Id", uid); x.setRequestHeader("X-Lang", M2W.lang); x.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
      if (target) x.setRequestHeader("X-Upload-Target", target);
      x.setRequestHeader("Content-Range", `bytes ${at}-${b - 1}/${file.size}`); x.setRequestHeader("Content-Type", "application/octet-stream");
      x.upload.onprogress = e => onp((at + e.loaded) / file.size * 100);
      x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {} x.status === 200 ? ok(j) : bad(new Error(j.error || t("上传失败（{s}）", { s: x.status }))); };
      x.onerror = () => bad(new Error(t("连接断了"))); x.send(file.slice(at, b));
    });
    at = b;
  }
  onp(100); return res.path;
}

/* ------------------------------------------------------------ models: the 「对话 / 构建」 chips next to the input (/api/models, models.py)
   Which agent CLI and model answers this chat and which one builds. Only the owner changes them (a viewer sees them read only); the menu
   lists only the agents the owner can run, each with a short model list and a one-line hint. Another agent for the chat = a new session. */
let MODELS = null;
const modelText = (role, x) => t(role === "chat" ? "对话：{a} · {m}" : "构建：{a} · {m}", { a: x.agent_name, m: x.model_shown || t("默认") });
function modelChipsHtml(M) {
  if (!M || !M.chat) return "";
  return ["chat", "build"].map(r => `<button class="mchip ${M.can_edit ? "" : "ro"}" data-mrole="${r}" title="${esc(M.can_edit
    ? t(r === "chat" ? "换回答这个对话的 agent 和模型" : "换构建用的 agent 和模型（后台构建只用它）")
    : t("只有项目的所有者能换模型"))}">${esc(modelText(r, M[r]))}${M.can_edit ? " ▾" : ""}</button>`).join("");
}
function modelMenuHtml(role, M, sel) {
  const cur = { ...M[role], model: M[role].model_shown || "" }, s = sel || { agent: cur.agent, model: cur.model };   // '' = the CLI default (Claude Code: sonnet)
  const isOn = (a, m) => s.agent === a && (s.model || "") === (m || "");
  const picked = ((M.agents || []).find(g => g.id === s.agent) || { models: [] }).models.find(m => (m.id || "") === (s.model || ""));
  // Fable: very expensive, she confirms it. Also when its name is typed for another agent (OpenCode anthropic/claude-fable-…)
  const typedWarn = !picked && s.model ? ((M.expensive || []).find(x => { try { return new RegExp(x.pattern, "i").test(s.model); } catch (e) { return false; } }) || {}).warn : "";
  const dear = (picked && picked.warn || typedWarn) && !isOn(cur.agent, cur.model) ? (picked && picked.warn) || typedWarn : "";
  const grp = g => {
    if (g.unavailable) return `<div class="mgrp">${esc(g.name)}</div><div class="opt na" aria-disabled="true" title="${esc(t(g.unavailable))}"><div><b>${esc(g.name)}</b><span class="rec">${t("不可用")}</span><small>${esc(t(g.unavailable))}</small></div></div>`;
    const known = g.models.some(m => isOn(g.id, m.id)), typed = s.agent === g.id && !known ? s.model : "";
    return `<div class="mgrp">${esc(g.name)}</div>` + g.models.map(m => `<div class="opt ${isOn(g.id, m.id) ? "on" : ""}" data-ma="${esc(g.id)}" data-mm="${esc(m.id)}">
      <div><b>${esc(m.label === "默认" ? t("默认") : m.label)}</b>${m.warn ? `<span class="rec dear">${t("很贵")}</span>` : ""}${g.id === cur.agent && (cur.model || "") === (m.id || "") ? `<span class="rec">${t("现在用的")}</span>` : ""}<small>${esc(t(m.hint))}</small></div></div>`).join("")
      + (g.free ? `<div class="mfree"><input class="inp" data-mfree="${esc(g.id)}" placeholder="${esc(g.placeholder || "")}" value="${esc(typed)}"><button class="btn ghost sm" data-mtype="${esc(g.id)}" ${typed ? "" : "disabled"} title="${esc(t("先在左边写模型名"))}">${t("用这个")}</button></div><small class="mnow">${esc(t(g.free_hint || ""))}</small>` : "");
  };
  const warn = role === "chat" && s.agent !== cur.agent ? `<div class="mwarn">${t("换成另一个 agent 会开一个新会话：它会先读最近的对话再接着做，但之前会话里的细节会丢一部分。")}</div>` : "";
  const sub = role === "chat" ? t("回答这个对话的驻场 agent 用哪个。同一个 agent 换模型会接着原来的会话。") : t("后台构建只用这一个。开工卡上写着它；开工前在这里换都算数。");
  return `<div class="mmenu"><h3>${t(role === "chat" ? "对话用的模型" : "构建用的模型")}</h3><p class="sub">${sub}</p>
    ${(M.agents || []).length ? M.agents.map(grp).join("") : `<p class="mnow">${t("项目所有者还没有可用的 agent：先在「我的 agent」里登录或填 key。")}</p>`}
    ${warn}${dear ? `<div class="mwarn">${t(dear)}</div>` : ""}<div class="foot"><button class="btn" data-msave ${isOn(cur.agent, cur.model) ? "disabled" : ""}>${t(dear ? "知道很贵，还是用它" : warn ? "换 agent 并保存" : "保存")}</button><button class="btn ghost" data-mdefault>${t("恢复默认")}</button><button class="btn ghost" data-close>${t("取消")}</button></div></div>`;
}
// the go card's read-only line: builds run ONLY on the project's build model. Unanswered (live): the model the build will use now (the
// 「构建」 chip), with a pointer to the chip and a note when the estimate was made for another one; answered: the one the card named.
function goModelHtml(k, live, M) {
  const B = M && M.build, now = B ? B.agent_name + (B.model_shown ? " · " + B.model_shown : "") : "", was = (k.build_model || {}).label || "";
  const L = live ? now || was : was;
  if (!L) return "";
  const stale = live && now && was && now !== was;
  return `<div class="bmodel"><div class="row"><small>${t("构建用的模型")}</small><b>${esc(L)}</b></div>${live ? `<small>${t("要换的话，点输入框旁边的「构建」（开工前换都算数）")}</small>` : ""}
    ${stale ? `<small class="enote">${t("下面的估算是按 {m} 算的；你换了构建模型，可以请 agent 重新估一下。", { m: was })}</small>` : ""}${live && B && B.warn ? `<div class="bwarn">${t(B.warn)}</div>` : ""}</div>`;
}
/* ------------------------------------------------------------ end models */
function renderModels() {
  const b = $("#mchips"); if (!b) return; b.innerHTML = modelChipsHtml(MODELS); $$("[data-mrole]", b).forEach(x => x.onclick = () => MODELS.can_edit && openModelMenu(x.dataset.mrole));
  try { const cs = cardState(); cs.forEach(c => { if (c && c.ev && c.ev.card && c.ev.card.kind === "go") refresh(c); }); } catch (e) { /* no thread yet */ }   // the go cards name the build model
}
async function loadModels() { try { MODELS = await get("/api/models"); } catch (e) { return; } renderModels(); }
function openModelMenu(role) {
  let sel = null;
  const d = dialog(modelMenuHtml(role, MODELS), true), box = $(".mbox", d);
  const save = async body => {
    const r = await post("/api/models", { role, ...body });
    if (!r.ok) return toast(r.error || t("没能保存"));
    MODELS = r.models; renderModels(); d.close(); toast(t("已保存"));
  };
  const wire = () => {
    $$("[data-ma]", box).forEach(o => o.onclick = () => { sel = { agent: o.dataset.ma, model: o.dataset.mm }; paint(); });
    $$("[data-mtype]", box).forEach(b => {               // an empty name: the button stays off (it did nothing before, QA 2026-10-29)
      const inp = $(`[data-mfree="${CSS.escape(b.dataset.mtype)}"]`, box);
      const upd = () => { b.disabled = !inp.value.trim(); };
      inp.oninput = upd; upd();
      inp.onkeydown = e => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); b.click(); } };
      b.onclick = () => { const v = inp.value.trim(); if (!v) { toast(t("先在左边写模型名")); return inp.focus(); } sel = { agent: b.dataset.mtype, model: v }; paint(); };
    });
    const sv = $("[data-msave]", box); if (sv) sv.onclick = () => sel && save(sel);
    $("[data-mdefault]", box).onclick = () => save({ agent: "default" });
    $$("[data-close]", box).forEach(b => b.onclick = d.close);
  };
  const paint = () => { box.innerHTML = modelMenuHtml(role, MODELS, sel); wire(); };
  wire();
}

/* ------------------------------------------------------------ start */
M2W.apply();
loadShell().then(() => {                       // no project yet: only the welcome page (no workspace, no polling of a thread)
  if (SH && SH.no_project) return;
  ws(location.hash.slice(1) || startRoute(), { initial: true }); poll(); setInterval(poll, 2000);
});
setInterval(loadShell, 20000);
// the workspace page tells the shell it moved (the stepper may have advanced), or asks for the conversation (a 下一步 that happens there)
window.addEventListener("message", ev => {
  if (ev.origin !== location.origin || !ev.data) return;
  if (ev.data.type === "m2w-nav") { clearTimeout(window._navT); window._navT = setTimeout(loadShell, 300); }
  if (ev.data.type === "m2w-chat") goRoute("chat");
  if (ev.data.type === "m2w-event") {          // 开发状态 「在对话里看」: open the conversation at that message of hers
    goRoute("chat");
    const m = $(`.msg[data-id="${CSS.escape(String(ev.data.id || ""))}"]`);
    if (m) { m.scrollIntoView({ block: "center", behavior: "smooth" }); m.classList.remove("flash"); void m.offsetWidth; m.classList.add("flash"); }
    else toast(t("这条话在更早的对话里"));
  }
});


// ---- language switch: repaint the chrome and the thread, re-fetch the server-built sentences, tell the workspace
async function resetThread() {              // the server sends the agent's words and cards in the chosen language: fetch the whole thread again
  const th = $("#thread"), top = th.scrollTop;
  try {
    const r = await get("/api/thread"); EV = r.events; lastId = EV.length ? EV[EV.length - 1].id : null;
    th.innerHTML = ""; slots = new Map(); lastDay = ""; render(EV); stateSig = ""; renderState(); th.scrollTop = top;
  } catch (e) { /* the next poll shows the old language until the server answers */ }
}
M2W.onLang(l => {
  if (WELCOME) WELCOME.paint();
  if (SH && SH.no_project) return;
  renderChips(); renderPills(); loadShell(); if (EV.length) resetThread(); else if (!firstLoad) $("#thread").innerHTML = `<div class="empty">${emptyText()}</div>`;
  try { frame().contentWindow.postMessage({ type: "m2w-lang", lang: l }, location.origin); } catch (e) {}
});
window.addEventListener("message", ev => { if (ev.origin === location.origin && ev.data && ev.data.type === "m2w-lang") M2W.set(ev.data.lang, false); });

// ---- draggable divider: the conversation column's width, remembered per browser
(() => {
  const app = document.querySelector(".app"), col = document.getElementById("chatcol"), h = document.getElementById("split");
  if (!app || !col || !h) return;
  const MIN = 320, WS_MIN = 360, DEF = 460;
  const clamp = w => Math.max(MIN, Math.min(w, window.innerWidth - col.getBoundingClientRect().left - WS_MIN));
  const set = w => app.style.setProperty("--chat-w", Math.round(clamp(w)) + "px");
  try { const w = +localStorage.getItem("m2w.chatWidth"); if (w) set(w); } catch (e) {}
  h.addEventListener("pointerdown", e => {
    e.preventDefault(); h.setPointerCapture(e.pointerId); document.body.classList.add("dragging");
    const left = col.getBoundingClientRect().left;
    const move = ev => set(ev.clientX - left);
    const up = ev => {           // pointerup, or the capture lost some other way (pointercancel, window lost focus): never stay "dragging"
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(t => h.removeEventListener(t, up)); h.removeEventListener("pointermove", move);
      if (!document.body.classList.contains("dragging")) return; document.body.classList.remove("dragging");
      try { localStorage.setItem("m2w.chatWidth", parseInt(getComputedStyle(app).getPropertyValue("--chat-w")) || DEF); } catch (e) {}
    };
    h.addEventListener("pointermove", move); ["pointerup", "pointercancel", "lostpointercapture"].forEach(t => h.addEventListener(t, up));
  });
  h.addEventListener("dblclick", () => { set(DEF); try { localStorage.removeItem("m2w.chatWidth"); } catch (e) {} });
  window.addEventListener("resize", () => { const w = parseInt(getComputedStyle(app).getPropertyValue("--chat-w")); if (w) set(w); });
})();


// ---- a picture in a card opens large (the result card's screenshot)
document.addEventListener("click", ev => {
  const z = ev.target.closest("[data-zoom]"); if (!z) return;
  ev.preventDefault(); ev.stopPropagation();
  const box = document.createElement("div"); box.className = "lightbox";
  box.innerHTML = `<img src="${z.dataset.zoom}" alt=""><span>${t("点任意处关闭")}</span>`;
  const close = () => { box.remove(); document.removeEventListener("keydown", esc_); };
  const esc_ = e => { if (e.key === "Escape") close(); };
  box.onclick = close; document.addEventListener("keydown", esc_); document.body.append(box);
}, true);
