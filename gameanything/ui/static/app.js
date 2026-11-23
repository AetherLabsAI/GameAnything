if (new URLSearchParams(location.search).has("embed")) document.documentElement.classList.add("embed");
/* GameAnything single-page app: hash routes #gather #home #board #people #plan #play[/<build>[/<moment>]] #keep.
   Every number and picture comes from the project through /api/*; the server is local (127.0.0.1) and nothing here calls out.
   UI text goes through t() (i18n.js, language zh | en); names, quotes, titles and the agent's sentences are shown as written. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const size = b => b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : b > 1e6 ? (b / 1e6).toFixed(b > 1e8 ? 0 : 1) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB";
const CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];
const cn = n => n <= 10 ? CN[n] : n < 20 ? "十" + CN[n - 10] : n < 100 ? CN[Math.floor(n / 10)] + "十" + (n % 10 ? CN[n % 10] : "") : String(n);
const cnCount = n => n === 2 ? "两" : cn(n);          // a count before 个: 「两个时刻」, not 「二个时刻」
const icon = (n, st = "") => `<svg class="i" style="${st}"><use href="#i-${n}"/></svg>`;
const LH = () => ({ "X-Lang": M2W.lang });         // the server builds some sentences: tell it the language
// a failed GET throws an Error that carries the server's JSON (ui/__init__.py data_error: {error, files: [{file, problem}]}) when there is one
const get = async u => {
  const r = await fetch(u, { headers: LH() });
  if (!r.ok) {
    let j = null; try { j = await r.json(); } catch (e) {}
    const err = new Error((j && j.error) || u + " " + r.status); err.status = r.status; err.files = (j && Array.isArray(j.files)) ? j.files : []; err.server = !!(j && j.error);
    throw err;
  }
  return r.json();
};
// a page that could not open: the server's sentence, and the files it names as a list (QA 2026-10-29: one long line)
function errHtml(e) {
  const fs = (e && e.files) || [];
  if (!fs.length) return `<div class="errbar">${t("这一页没能打开：{m}", { m: esc(e && e.message) })}</div>`;
  return `<div class="errbar"><b>${t("这一页要的数据读不出来：下面这些文件有问题")}</b>
    <ul class="errfiles">${fs.map(f => `<li><code>${esc(f.file)}</code><span>${esc(f.problem)}</span></li>`).join("")}</ul>
    <div class="errhint">${t("请 agent 改好这些文件（它可以跑 gameanything flow check 看到同样的清单），改好后刷新这一页。")}</div>
    ${EMBED ? `<button class="btn sm" data-chat>${t("去对话里告诉 agent")}</button>` : ""}</div>`;
}
async function post(u, b) {
  const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json", ...LH() }, body: JSON.stringify(b) });
  let j; try { j = await r.json(); } catch (e) { j = { ok: false, error: t("服务没有回应（{s}）", { s: r.status }) }; }
  return j;
}
function toast(t) { const e = $("#toast"); e.textContent = t; e.style.display = "block"; clearTimeout(e._t); e._t = setTimeout(() => e.style.display = "none", 2200); }

let SH = null, navId = 0;                     // SH = /api/shell
const topbar = (crumb, right = "") => `<div class="top"><div class="crumb">${esc(SH.title)} / ${crumb}</div><div class="sp"></div>${right}${EMBED ? "" : langSwitchHtml()}</div>`;
const pill = () => SH.status.live ? `<div class="status"><i></i>${esc(SH.status.text)}</div>` : `<div class="status idle"><i></i>${esc(SH.status.text)}</div>`;
/* embedded in the conversation shell: "在对话里说" hands the thing the user is pointing at to the composer (the shell shows it as a chip) */
const EMBED = window.parent !== window;
const tellChat = (context, text) => window.parent.postMessage({ type: "m2w-context", context, text }, location.origin);
document.addEventListener("click", e => {
  const b = e.target.closest(".say"); if (!b) return; e.preventDefault(); e.stopPropagation();
  tellChat([{ kind: "moment", id: b.dataset.id, label: b.dataset.t }]);
}, true);
const money = v => "$" + (+v).toFixed(2);
/* the ONE 下一步 of an empty page: the flow's next action (/api/shell `flow`, onboard.py); a step that happens in the conversation asks the
   shell to open it; while the agent is at work, a line saying so and the way to the conversation */
function nextStep(here) {
  const n = SH && SH.flow && SH.flow.next; if (!n || !n.route) return "";
  const chat = n.route === "chat" || n.route === here;
  const label = chat && !n.wait && n.route !== "chat" ? t("去对话里看看") : (n.wait ? "" : t("下一步：")) + t(n.label);
  const btn = chat ? (EMBED ? `<button class="btn sm" data-chat>${esc(label)} ${icon("arrow", "width:14px;height:14px")}</button>` : `<a class="btn sm" href="/">${esc(label)} ${icon("arrow", "width:14px;height:14px")}</a>`)
    : `<a class="btn sm" href="#${esc(n.route)}">${esc(label)} ${icon("arrow", "width:14px;height:14px")}</a>`;
  return `<div class="nextstep">${n.hint ? `<span class="muted">${esc(t(n.hint))}</span>` : ""}${btn}</div>`;
}
document.addEventListener("click", e => { if (e.target.closest("[data-chat]")) { e.preventDefault(); window.parent.postMessage({ type: "m2w-chat" }, location.origin); } });

/* ------------------------------------------------------------ sidebar */
const NAV = [["gather", "upload", "素材"], ["home", "day", "这一天"], ["people", "people", "人物"], ["plan", "plan", "方案"], ["play", "play", "试玩"], ["status", "status", "开发状态"], ["keep", "home", "带回家"]];
function renderSide(cur) {
  const sc = tabOf(SH.kind, cur);
  const href = r => r.state === "live" ? "#home" : r.play ? `#play/${r.m}` : "";
  $("#side").innerHTML = `<div class="brand"><span class="logo"><i></i></span><span>Game<b>Anything</b></span></div>
    <div class="proj">${SH.cover ? `<img src="${esc(SH.cover)}" alt="">` : `<span class="ph"></span>`}<div><b>${esc(SH.title)}</b><span>${esc(SH.game)}${SH.date ? " · " + esc(SH.date) : ""}</span></div></div>
    ${(KIND_TABS[SH.kind] || NAV).map(([k, ic, lb]) => `<a class="navi ${sc === k ? "cur" : ""}" href="#${k}">${icon(ic)}${t(lb)}${k === "people" && SH.people_new ? `<span class="cnt">${SH.people_new}</span>` : ""}</a>`).join("")}
    <div class="sidelabel">${t("每一版")}</div>
    ${SH.rounds.map(r => { const h = href(r); return `<${h ? `a href="${h}"` : "div"} class="run ${r.state === "live" ? "live" : r.state === "done" ? "done" : ""}"><span class="dot"></span><div><b>${esc(r.name)}</b><small>${esc(r.sub)}</small></div></${h ? "a" : "div"}>`; }).join("") || `<div class="run"><div><small>${t("还没有计划好的版本")}</small></div></div>`}
    <div class="sidefoot">${icon("lock", "width:13px;height:13px")}${t("照片只在这台电脑上")}<br>${t("发送明细 {n} 次", { n: SH.footer.requests })}${SH.footer.image_cost_usd ? ` · ${t("生图")} ${money(SH.footer.image_cost_usd)}` : ""}</div>`;
}
async function loadShell() { SH = await get("/api/shell"); M2W.kind = SH.kind; }

/* ------------------------------------------------------------ router */
const SCREENS = {};
async function route() {
  const my = ++navId; const [name = "home", ...args] = (location.hash || "#home").slice(1).split("/");
  const fn = SCREENS[name] || SCREENS.home;
  try {
    await loadShell(); if (my !== navId) return;
    if (EMBED) window.parent.postMessage({ type: "m2w-nav", route: name }, location.origin);      // the shell refreshes its stepper
    renderSide(SCREENS[name] ? name : "home");
    await fn(args, () => my === navId);
    if (my === navId) wireLangSwitch($("#screen"));            // standalone page: the top bar's 中 | EN
  } catch (e) {
    if (my !== navId) return;
    $("#screen").innerHTML = `<div class="page">${errHtml(e)}</div>`; console.error(e);
  }
  if (my === navId) window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
/* language: switched here (standalone page) or in the shell (embedded: storage event / postMessage); repaint the current screen */
M2W.onLang(() => route());
window.addEventListener("message", ev => { if (ev.origin === location.origin && ev.data && ev.data.type === "m2w-lang") M2W.set(ev.data.lang, false); });

/* ------------------------------------------------------------ 这一天 */
SCREENS.home = async (_, live) => {
  if (SH.kind === "adaptation") return SCREENS.scenes(_, live);
  if (SH.kind === "gameplay") return SCREENS.mechanics(_, live);
  if (SH.kind === "feature") return SCREENS.spec(_, live);
  const D = await get("/api/day"); if (!live()) return;
  const R = D.round, ask = D.todo[0];
  const steps = R ? R.steps.slice(0, 6) : [];
  $("#screen").innerHTML = topbar(`<b>${t("这一天")}</b>`, pill()) + `<div class="page">
    <div class="hero ${D.hero ? "" : "ph"}">${D.hero ? `<img src="${esc(D.hero)}" alt="">` : ""}
      <div class="ov"><div><div class="eyebrow">Memory · ${esc(D.game || "Stardew Valley")}</div><h1>${esc(D.title)}</h1>
        <div class="meta">${esc(fmtDate(D.date))}${D.place ? " · " + esc(D.place) : ""}</div></div>
        <div class="chips"><span>${t("{n} 份素材", { n: D.items })}</span>${D.people ? `<span>${t("{n} 个人", { n: D.people })}</span>` : ""}${D.moment_total ? `<span>${t("{n} 个时刻", { n: D.moment_total })}</span>` : ""}</div></div></div>
    <div class="row2">
      <div class="card ask"><span class="tag">${ask ? t("等你看看 · {n}", { n: D.todo.length + D.more_todo }) : t("没有要你看的")}</span>
        ${ask ? `${D.faces.length ? `<div class="faces">${D.faces.map(f => `<img class="px" src="${esc(f.url)}" title="${esc(f.name)}">`).join("")}</div>` : `<div style="height:14px"></div>`}
          <b>${esc(ask.text)}</b><p>${D.faces.length ? esc(D.faces.map(f => f.name).join(t("、"))) : ""}${D.todo.length > 1 ? (D.faces.length ? t("；") : "") + t("另外：") + esc(D.todo.slice(1).map(x => x.text).join(t("；"))) : ""}</p>
          <a class="btn sm" href="${esc(ask.href)}">${t("去看看")} ${icon("arrow")}</a>`
        : `<div style="height:14px"></div><b>${t("现在没有要你看的东西")}</b><p>${t("有新的形象、录像或要确认的内容时，会在这里告诉你。")}</p><a class="btn ghost sm" href="#board">${t("调整这一天的时刻")} ${icon("arrow")}</a>`}</div>
      <div class="card prog">${R ? `<div class="hd"><span style="width:8px;height:8px;border-radius:50%;background:var(--violet)"></span><b>${esc(R.name)}</b>
          <span class="when">${[R.at && t("{d}开工", { d: R.at }), R.eta_hours && t("预计 {n} 小时", { n: R.eta_hours }), R.cost_usd && t("约 {c}", { c: money(R.cost_usd) })].filter(Boolean).map(esc).join(" · ")}</span></div>
        <div class="bar ${R.progress == null ? "none" : ""}"><i style="width:${Math.round((R.progress || 0) * 100)}%"></i></div>
        <ul class="steps" style="${R.progress == null ? "margin-top:12px" : ""}">${steps.map(s => `<li class="${s.state === "done" ? "done" : s.state === "cur" ? "cur" : "plain"}"><span class="c"></span>${esc(s.text)}</li>`).join("")}
          ${R.steps.length > steps.length ? `<li class="more plain">${t("…另外 {n} 项", { n: R.steps.length - steps.length })}</li>` : ""}</ul>
        ${R.steps_real ? "" : `<div class="fine p">${t("这里列的是这一版计划里的事项；agent 还没有报告做到哪一步，所以不显示进度。")}</div>`}`
        : `<div class="hd"><b>${t("现在没有在进行的版本")}</b></div><p class="muted" style="margin:10px 0 0">${t("开始新的一版以后，这里会列出它要做的事。")}</p>`}</div>
    </div>
    <h2 class="h">${t("{c}个时刻", { c: M2W.lang === "zh" ? cnCount(D.moments.length) : D.moments.length, n: D.moments.length })} <span class="muted">${t("大图是那天，右下角是游戏里")}</span></h2>
    ${D.moments.length ? `<div class="moments">${D.moments.map((m, i) => `<a class="card mo" href="${m.play ? `#play/${m.play}/${m.id}` : "#board"}"><div class="pic">
        ${m.real ? `<img class="real" src="${esc(m.real)}" loading="lazy">` : `<div class="none">${t("没有照片")}</div>`}
        ${m.game ? `<img class="game px" src="${esc(m.game)}" loading="lazy">` : `<div class="nogame">${t("还没有画面")}</div>`}</div>
      <div class="tx"><div class="n">${String(i + 1).padStart(2, "0")}</div><h4>${esc(m.title)}</h4><div class="st ${m.edit ? "edit" : ""}">${esc(m.status)}</div></div>
        ${EMBED ? `<button class="say" data-id="${esc(m.id)}" data-t="${esc(m.title)}" title="${t("在对话里说这个时刻")}">${icon("chat", "width:13px;height:13px")}${t("在对话里说")}</button>` : ""}</a>`).join("")}</div>`
      : `<div class="card empty">${t(gathered() ? "素材已经放进来了：agent 正在整理这一天的时刻，好了会出现在这里。" : "还没有整理出这一天的时刻。先在“素材”里放进你的回忆。")}${nextStep("home")}</div>`}
    ${D.skipped.length ? `<p class="note-line">${t("另有 {n} 个时刻你选择不放进游戏：{list}。", { n: D.skipped.length, list: esc(D.skipped.join(t("、"))) })}<a href="#board" style="color:var(--violet)">${t("调整")}</a></p>` : ""}
  </div>`;
};

/* ------------------------------------------------------------ 素材 (chunked, resumable upload into 0_inbox) */
const CHUNK = 8 * 1024 * 1024, ALLOWED_RE = () => new RegExp("\\.(" + (G ? G.allowed : []).join("|") + ")$", "i");
let G = null; const queue = [];             // queue rows: {el, file, rel, state}
const KIND = n => /\.(jpe?g|heic|png|webp)$/i.test(n) ? "IMG" : /\.(mp4|mov|m4v)$/i.test(n) ? "VID" : /\.(mp3|m4a|wav|ogg|flac|aac)$/i.test(n) ? "AUD" : /\.pdf$/i.test(n) ? "PDF" : "DOC";
SCREENS.gather = async (_, live) => {
  G = await get("/api/gather"); if (!live()) return;
  const ib = G.inbox;
  $("#screen").innerHTML = topbar(`<b>${t("素材")}</b>`, `<div class="status" style="box-shadow:none">${icon("shield", "width:14px;height:14px;color:var(--ok)")}${t("只在这台电脑上")}</div>`) + `<div class="page">
    <div class="eyebrow">Step 1 · Gather</div><h1 class="t">${t("放进你的回忆")}</h1>
    <p class="lede">${t("照片、视频、请柬、致辞稿，拖进来就行。所有东西都留在这台电脑上，整理也在这台电脑上完成。")}</p>
    <div class="gwrap"><div>
      <div class="drop" id="drop"><div class="ic">${icon("upload")}</div><h3>${t("把文件或整个文件夹拖到这里")}</h3>
        <p>${t("也可以手动选择。视频再大也没关系，会分块传进来，断了能接着传。")}</p>
        <label class="btn"><input type="file" multiple hidden id="pick">${t("选择文件")}</label><label class="btn ghost" style="margin-left:6px"><input type="file" webkitdirectory hidden id="pickdir">${t("选择文件夹")}</label>
        <div class="types">${G.allowed.map(x => x.toUpperCase()).join(" · ")} · ${t("单个文件最大 {n} GB", { n: Math.round(G.max_bytes / 2 ** 30) })}</div></div>
      <div class="files" id="files"></div>
      <div id="inbox"></div></div>
      <div><div class="card sumcard"><h2 class="h" style="font-size:14px">${t("已经放进来的")} <span class="muted">${t("{n} 份", { n: G.items })} · ${size(G.bytes)}</span></h2>
          ${G.thumbs.length ? `<div class="thumbs">${G.thumbs.map(u => `<img src="${esc(u)}" loading="lazy">`).join("")}</div>` : ""}
          ${G.photo ? `<div class="kv"><span>${t("照片")}</span><span>${t("{n} 张", { n: G.photo })}</span></div>` : ""}
          ${G.video ? `<div class="kv"><span>${t("视频")}</span><span>${t("{n} 段", { n: G.video })}${G.transcribed ? " · " + t("已转成文字") : ""}</span></div>` : ""}
          ${G.document ? `<div class="kv"><span>${t("文档")}</span><span>${t("{n} 份", { n: G.document })}</span></div>` : ""}
          ${G.people ? `<div class="kv"><span>${t("照片里认出的人")}</span><span>${t("{n} 位", { n: G.people })}</span></div>` : ""}
          ${G.items ? "" : `<div class="muted" style="font-size:13px">${t("还没有素材。")}</div>`}</div>
        ${G.steps.length ? `<div class="card sumcard" style="margin-top:14px"><h2 class="h" style="font-size:14px">${t("整理")}</h2><ul class="steps">${G.steps.map(s => `<li class="done"><span class="c"></span>${esc(s)}</li>`).join("")}</ul></div>` : ""}
        <div class="priv">${icon("shield")}<div>${t("到这一步，没有任何东西离开过这台电脑。下一步要看图时，会先告诉你发什么、发给谁，等你同意。")}</div></div>
        <div style="margin-top:16px"><a class="btn" href="#board">${t("下一步：整理成这一天")} ${icon("arrow", "width:14px;height:14px")}</a></div></div></div></div>`;
  paintInbox();
  const dz = $("#drop");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", async e => addFiles(await collect(e.dataTransfer)));
  $("#pick").onchange = e => { addFiles([...e.target.files].map(f => ({ file: f, rel: f.name }))); e.target.value = ""; };
  $("#pickdir").onchange = e => { addFiles([...e.target.files].map(f => ({ file: f, rel: f.webkitRelativePath || f.name }))); e.target.value = ""; };
  queue.forEach(q => { if (q.state !== "done") q.el = null; });
  $("#files").append(...queue.filter(q => q.state !== "done").map(q => (q.el = rowEl(q))));
};
/* drop: expand folders (entries must be taken synchronously, the event data expires) */
async function collect(dt) {
  const entries = [...dt.items].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean), out = [];
  const walk = async (en, path) => {
    if (en.isFile) { const f = await new Promise((res, rej) => en.file(res, rej)); out.push({ file: f, rel: path + en.name }); }
    else { const rd = en.createReader(); let all = [];
      for (;;) { const part = await new Promise((res, rej) => rd.readEntries(res, rej)); if (!part.length) break; all = all.concat(part); }
      for (const c of all) await walk(c, path + en.name + "/"); }
  };
  if (entries.length) for (const en of entries) await walk(en, "");
  else [...dt.files].forEach(f => out.push({ file: f, rel: f.name }));
  return out;
}
function rowEl(q) {
  const el = document.createElement("div"); el.className = "card file";
  el.innerHTML = `<div class="fi">${KIND(q.rel)}</div><div><b title="${esc(q.rel)}">${esc(q.rel)}</b><small>${size(q.file.size)} · ${t("等待上传")}</small><div class="pb"><i></i></div></div><span class="muted" style="font-size:12px">0%</span>`;
  return el;
}
function addFiles(list) {
  const ok = ALLOWED_RE(), skipped = [];
  list.forEach(x => {
    const base = x.rel.split("/").pop();
    if (base.startsWith(".") || x.rel.split("/").some(p => p.startsWith("."))) return;           // .DS_Store and friends: not memories
    if (!ok.test(base)) { skipped.push(x.rel); return; }
    if (!x.file.size) { skipped.push(t("{f}（空文件）", { f: x.rel })); return; }
    const q = { ...x, state: "wait", sent: 0 }; q.el = rowEl(q); queue.push(q); $("#files").prepend(q.el);
  });
  if (skipped.length) toast(t("跳过了 {n} 个不支持的文件：{list}", { n: skipped.length, list: skipped.slice(0, 2).join(t("、")) + (skipped.length > 2 ? "…" : "") }));
  pump();
}
let pumping = false;
async function pump() {
  if (pumping) return; pumping = true;
  try { for (let q; (q = queue.find(x => x.state === "wait"));) await sendFile(q); } finally { pumping = false; }
  if (!queue.some(x => x.state === "wait")) { try { G = await get("/api/gather"); paintInbox(); } catch (e) {} }
}
async function sha(s) {
  if (crypto.subtle) { const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)); return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, "0")).join("").slice(0, 40); }
  let h = 5381; for (const c of s) h = ((h << 5) + h + c.charCodeAt(0)) >>> 0; return "u" + h.toString(16).padStart(8, "0") + s.length.toString(16).padStart(8, "0");
}
function paintRow(q, text, pct, cls) {
  if (!q.el) return; const set = (sel, fn) => { const e = $(sel, q.el); if (e) fn(e); };
  set("small", e => e.textContent = text); set(".pb i", e => e.style.width = pct + "%");
  set(":scope > span", e => { e.className = cls === "ok" ? "ok" : "muted"; e.style.fontSize = "12px"; e.textContent = cls === "ok" ? t("已收到") : Math.round(pct) + "%"; });
  q.el.classList.toggle("err", cls === "err");
}
function chunkXhr(uid, q, a, b) {
  return new Promise((res, rej) => {
    const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
    x.setRequestHeader("X-Upload-Id", uid); x.setRequestHeader("X-Lang", M2W.lang); x.setRequestHeader("X-File-Name", encodeURIComponent(q.rel));
    x.setRequestHeader("Content-Range", `bytes ${a}-${b - 1}/${q.file.size}`); x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = e => { q.sent = a + e.loaded; paintRow(q, `${size(q.file.size)} · ${t("正在放进项目")}`, q.sent / q.file.size * 100); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {} x.status === 200 ? res(j) : rej(Object.assign(new Error(j.error || t("上传失败（{s}）", { s: x.status })), { server: true, status: x.status, j })); };
    x.onerror = () => rej(new Error(t("连接断了"))); x.send(q.file.slice(a, b));
  });
}
async function sendFile(q) {
  q.state = "run"; const uid = await sha(`${q.rel}|${q.file.size}|${q.file.lastModified}`);
  let tries = 0;
  for (;;) {
    try {
      const st = await get("/api/upload?id=" + uid); let at = st.received || 0;
      if (at >= q.file.size) at = 0;
      paintRow(q, `${size(q.file.size)} · ${at ? t("接着上次传") : t("正在放进项目")}`, at / q.file.size * 100);
      let last = {};
      for (; at < q.file.size; at = last.received) { last = await chunkXhr(uid, q, at, Math.min(at + CHUNK, q.file.size)); tries = 0; }
      q.state = "done"; paintRow(q, `${size(q.file.size)} · ${t("已放进收件箱，等整理")}`, 100, "ok"); return;
    } catch (e) {
      if (e.server && e.status !== 409 && e.status !== 400) { q.state = "err"; paintRow(q, e.message, q.sent / q.file.size * 100, "err"); retryBtn(q); return; }
      if (++tries > 4) { q.state = "err"; paintRow(q, e.message + t("（可以重试，会接着传）"), q.sent / q.file.size * 100, "err"); retryBtn(q); return; }
      await new Promise(r => setTimeout(r, 800 * tries));
    }
  }
}
function retryBtn(q) {
  if (!q.el) return; const b = document.createElement("button"); b.className = "rt"; b.textContent = t("重试");
  b.onclick = () => { b.remove(); q.state = "wait"; paintRow(q, t("等待上传"), 0); pump(); }; q.el.lastElementChild.replaceWith(b);
}
function paintInbox() {
  const ib = G.inbox, el = $("#inbox"); if (!el) return;
  const rq = ib.request, fresh = ib.new;
  el.innerHTML = ib.files.length ? `<div class="card sumcard" style="margin-top:16px"><h2 class="h" style="font-size:14px">${t("收件箱")} <span class="muted">${t("{n} 个文件", { n: ib.files.length })} · ${size(ib.bytes)}</span></h2>
    ${ib.files.slice(0, 6).map(f => `<div class="kv"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px" title="${esc(f.path)}">${esc(f.path)}</span><span>${size(f.bytes)}${f.ingested ? ` · <span class="muted">${t("已整理")}</span>` : f.asked ? "" : ` · <b style="color:var(--violet)">${t("新")}</b>`}</span></div>`).join("")}
    ${ib.files.length > 6 ? `<div class="kv"><span class="muted">${t("…还有 {n} 个", { n: ib.files.length - 6 })}</span><span></span></div>` : ""}
    <div class="inb">${fresh ? `<button class="btn sm" id="ingest">${t("整理新文件")}</button><span class="ghostline">${t("{n} 个新文件还没交给 agent", { n: fresh })}</span>`
      : ib.ingested >= ib.files.length ? `<span class="tag ok">${t("都已整理进素材")}</span>`
      : `<span class="tag">${t("已收到，等 agent 整理")}</span><span class="ghostline">${rq ? t("{at} 交出", { at: esc(fmtAt(rq.at)) }) : ""}</span>`}</div>
    <div class="fine">${t("文件原样放在项目的 0_inbox 文件夹里。把新文件并进已有素材会改动素材编号，所以由 agent 来整理，整理好之后这里的数字会更新。")}</div></div>` : "";
  const b = $("#ingest"); if (b) b.onclick = async () => {
    b.disabled = true; const r = await post("/api/ingest_request", {});
    if (r.ok) { toast(t("已交给 agent")); G = await get("/api/gather"); paintInbox(); } else { toast(r.error || t("没能交出")); b.disabled = false; }
  };
}

/* ------------------------------------------------------------ 确认这一天 */
const IMP = { must_preserve: "一定要有", important: "重要", optional: "可有可无", skip: "不放" };      // zh source; shown through t()
SCREENS.board = async (_, live) => {
  if (SH.kind === "adaptation") return SCREENS.scenes(_, live);
  if (SH.kind === "gameplay") return SCREENS.mechanics(_, live);
  if (SH.kind === "feature") return SCREENS.spec(_, live);
  const B = await get("/api/board"); if (!live()) return;
  let order = B.moments.map(m => m.id); const st = {}; B.moments.forEach(m => st[m.id] = { importance: m.importance, segment: m.segment, m });
  const segName = Object.fromEntries(B.segments.map(s => [s.id, s.label]));
  const conf = B.review && B.review.state === "confirmed";
  const draw = () => {
    let html = "", last = null;
    order.forEach(id => {
      const x = st[id], m = x.m;
      if (x.segment !== last) { html += `<div class="segh segdrop" data-seg="${esc(x.segment)}">${esc(segName[x.segment] || x.segment)}</div>`; last = x.segment; }
      html += `<div class="card bm ${x.importance === "skip" ? "skip" : ""}" draggable="true" data-id="${esc(id)}"><div class="hd">⋮⋮</div>
        ${m.img ? `<img class="bimg" src="${esc(m.img)}" loading="lazy">` : `<div class="bimg"></div>`}
        <div><h4>${esc(m.title)}</h4><p>${esc(m.what)}</p>${m.gaps ? `<span class="gap">${t("缺：")}${esc(m.gaps)}</span>` : ""}</div>
        <div class="seg">${B.importances.map(k => `<a class="${k === "must_preserve" ? "must" : ""} ${x.importance === k ? "cur" : ""}" data-k="${k}">${t(IMP[k])}</a>`).join("")}</div></div>`;
    });
    $("#bmoments").innerHTML = html || `<div class="card empty">${t("回忆板里还没有时刻。")}${nextStep("board")}</div>`;
    const c = k => order.filter(i => st[i].importance === k).length;
    $("#cnt").style.gridTemplateColumns = `repeat(${B.importances.length}, 1fr)`;
    $("#cnt").innerHTML = B.importances.map(k => `<div><b>${c(k)}</b><span>${t(k === "skip" ? "不放进游戏" : IMP[k])}</span></div>`).join("");
    $$(".bm .seg a").forEach(a => a.onclick = () => { st[a.closest(".bm").dataset.id].importance = a.dataset.k; draw(); });
    let from = null;
    $$(".bm").forEach(el => {
      el.ondragstart = e => { from = el.dataset.id; el.classList.add("drag"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", from); };
      el.ondragend = () => el.classList.remove("drag");
      el.ondragover = e => { e.preventDefault(); el.classList.add("over"); }; el.ondragleave = () => el.classList.remove("over");
      el.ondrop = e => { e.preventDefault(); const to = el.dataset.id; if (!from || from === to) return;
        const t = order.indexOf(to); order.splice(order.indexOf(from), 1); st[from].segment = st[to].segment; order.splice(t, 0, from); draw(); };
    });
    $$(".segh.segdrop").forEach(el => {
      el.ondragover = e => { e.preventDefault(); el.classList.add("over"); }; el.ondragleave = () => el.classList.remove("over");
      el.ondrop = e => { e.preventDefault(); if (!from) return; const seg = el.dataset.seg; order.splice(order.indexOf(from), 1); st[from].segment = seg;
        const first = order.findIndex(i => st[i].segment === seg); first < 0 ? order.push(from) : order.splice(first, 0, from); draw(); };
    });
  };
  $("#screen").innerHTML = topbar(`${t("这一天")} / <b>${t("确认")}</b>`, conf ? `<span class="tag ok">${t("已确认 · {at}", { at: esc(fmtAt(B.review.at)) })}</span>` : B.status === "confirmed" && !B.review ? `<span class="tag grey">${t("已确认过 · 可以再调整")}</span>` : `<span class="tag">${t("等你确认")}</span>`) + `<div class="page">
    <div class="eyebrow">Step 2 · Remember</div><h1 class="t">${t("这一天，对吗？")}</h1>
    <p class="lede">${t("根据你的素材和回答，整理出 {n} 个时刻。拖动可以调整顺序；每个时刻选一下它在游戏里有多重要。", { n: B.moments.length })}</p>
    <div class="bwrap"><div id="bmoments"></div>
      <div class="card bside"><h2 class="h" style="font-size:14px">${t("一共 {n} 个时刻", { n: B.moments.length })}</h2><div class="cnt3" id="cnt"></div>
        <div class="lbl" style="margin-top:0">${t("还想补充什么？")}</div><textarea id="bnote" placeholder="${esc(t("比如：敬酒时妈妈哭了，这个也想要"))}">${esc(B.review ? B.review.note : "")}</textarea>
        <div class="acts"><button class="btn" id="bok">${t("确认这一天")}</button><button class="btn ghost sm" id="bdraft">${t("先存草稿")}</button></div>
        <div class="fine" id="bfine">${t("确认之后，agent 会把你的修改应用到回忆板，再根据这一天写一份方案给你看。之后还可以回来改。")}</div></div></div></div>`;
  draw(); let rev = B.rev;
  const send = async state => {
    const r = await post("/api/board_review", { rev, state, order, note: $("#bnote").value, moments: Object.fromEntries(order.map(i => [i, { importance: st[i].importance, segment: st[i].segment }])) });
    if (!r.ok) { toast(r.error || t("没能保存")); if (r.stale) $("#bfine").innerHTML = `<span style="color:#B91C1C">${esc(r.error)} <a href="#board" onclick="location.reload()" style="text-decoration:underline">${t("刷新")}</a></span>`; return; }
    rev = r.rev; toast(t(state === "confirmed" ? "已确认，交给 agent 了" : "草稿已存"));
    $("#bfine").textContent = t("{a}（{at}）。", { a: t(state === "confirmed" ? "已确认" : "草稿已存"), at: fmtAt(r.at) }) + (r.changes.length ? t("你改了 {n} 处，agent 会应用到回忆板。", { n: r.changes.length }) : t("和回忆板一致，没有改动。"));
  };
  $("#bok").onclick = () => send("confirmed"); $("#bdraft").onclick = () => send("draft");
};

/* ------------------------------------------------------------ 人物 */
const PRES = [["event_only", "只在那一天出现", "过场里的临时角色，不进存档"], ["visits", "之后偶尔来做客", "特定的日子出现在镇上，不进存档"], ["villager", "成为镇上的村民", "有日程、好感度、可以送礼；会进存档"]];
const VARIANT = { license: "领证那天" };
let PEO = null, pf = { kind: "all" }, psel = null, pvar = {};
SCREENS.people = async (args, live) => {
  if (SH.kind === "adaptation") return SCREENS.characters(args, live);
  if (SH.kind === "gameplay") return SCREENS.content(args, live);
  if (SH.kind === "feature") return SCREENS.spec(args, live);
  if (args[0] === "tag") return tagScreen(args, live);       // tag.js: the photo tagging tool
  PEO = await get("/api/looks"); if (!live()) return;
  const draw = () => {
    const bases = {}; PEO.people.forEach(p => (bases[p.base] ||= []).push(p));
    const pick = ls => pf.kind === "variant" ? ls.find(l => l.variant === pf.v) : pvar[ls[0].base] != null ? ls.find(l => l.variant === pvar[ls[0].base]) || ls[0] : ls.find(l => !l.variant) || ls[0];
    const unseen = l => !l.no_look && (l.review.status || "todo") === "todo";
    const inGroup = (b, g) => (g.members || []).includes(b);
    const chips = [{ k: "all", label: t("全部"), n: Object.keys(bases).length }];
    [...new Set(PEO.people.map(p => p.variant).filter(Boolean))].forEach(v => chips.push({ k: "variant", v, label: VARIANT[v] ? t(VARIANT[v]) : v, n: Object.values(bases).filter(ls => ls.some(l => l.variant === v)).length }));
    const nu = Object.values(bases).filter(ls => ls.some(unseen)).length; if (nu) chips.push({ k: "new", label: t("还没看"), n: nu, cls: "new" });
    PEO.groups.forEach(g => { const n = Object.keys(bases).filter(b => inGroup(b, g)).length; if (n) chips.push({ k: "group", g: g.id, label: g.name, n }); });
    const on = c => pf.kind === c.k && (c.v ? pf.v === c.v : c.g ? pf.g === c.g : true);
    const shown = Object.entries(bases).filter(([b, ls]) => pf.kind === "all" || (pf.kind === "variant" && ls.some(l => l.variant === pf.v)) || (pf.kind === "new" && ls.some(unseen))
      || (pf.kind === "group" && inGroup(b, PEO.groups.find(g => g.id === pf.g) || {}))).map(([b, ls]) => pick(ls));
    if (!shown.some(l => l.base === psel)) psel = shown.length ? shown[0].base : null;
    $("#pchips").innerHTML = chips.map(c => `<button class="chip ${on(c) ? "cur" : ""} ${c.cls || ""}" data-i="${chips.indexOf(c)}">${esc(c.label)}<span>${c.n}</span></button>`).join("");
    $$("#pchips .chip").forEach(b => b.onclick = () => { const c = chips[+b.dataset.i]; pf = { kind: c.k, v: c.v, g: c.g }; draw(); });
    $("#cast").innerHTML = shown.map(l => `<div class="card p ${l.base === psel ? "sel" : ""}" data-b="${esc(l.base)}"><div class="duo">
        ${l.face ? `<img class="real" src="${esc(l.face)}" loading="lazy" style="object-position:50% 18%">` : ""}${portraitOf(l) ? `<img class="pxp px" src="${esc(portraitOf(l))}">` : ""}
        ${unseen(l) ? `<span class="new">${t("新")}</span>` : ""}${l.no_look && !l.face ? `<span class="nolook">${t("还没有形象")}</span>` : ""}</div><div class="tx"><b>${esc(l.person_name)}</b><div class="r">${esc(l.role || (l.persona && l.persona.player ? t("你自己 · 由你来扮演") : "") || l.groups[0] || "　")}</div></div></div>`).join("")
      || `<div class="card empty" style="grid-column:1/-1">${t("这一类里还没有人物。")}</div>`;
    $$("#cast .p").forEach(e => e.onclick = () => { psel = e.dataset.b; draw(); });
    const cur = shown.find(l => l.base === psel); $("#detail").style.display = cur ? "" : "none"; if (cur) detail(bases[cur.base], cur);
    const nl = Object.values(bases).filter(ls => ls.every(l => l.no_look)).length;
    $("#plede").textContent = t("{n} 个人。照片是那天的样子，右下角是游戏里的头像。", { n: Object.keys(bases).length }) + (nl ? " " + t("其中 {n} 个还没有游戏里的形象。", { n: nl }) : "");
  };
  const portraitOf = l => { const p = l.portraits.find(x => x.expr === "neutral") || l.portraits[0]; return p ? p.url : null; };
  const detail = (ls, l) => {
    if (l.no_look) {               // someone the project knows (people.yaml) who has no game look yet: who they are, and how to get one
      $("#detail").innerHTML = `${l.groups[0] ? `<span class="tag">${esc(l.groups[0])}</span>` : ""}<h3>${esc(l.person_name)}</h3><div class="r">${esc(l.role || "")}</div>
        ${l.face ? `<div class="cmp"><figure><img src="${esc(l.face)}" style="object-position:50% 20%"><figcaption>${t("那天的照片")}</figcaption></figure></div>` : ""}
        ${l.persona && l.persona.note ? `<p class="muted" style="font-size:13px">${esc(l.persona.note)}</p>` : ""}
        <div class="pend">${t("还没有游戏里的形象。agent 做形象的时候会先问你，做好后会出现在这里。")}</div>
        <div class="acts"><a class="btn ghost sm" href="#people/tag">${t("标记照片里的人")}</a>${EMBED ? `<button class="btn ghost sm" id="pchat">${t("在对话里说")}</button>` : ""}</div>`;
      if ($("#pchat")) $("#pchat").onclick = () => tellChat([{ kind: "person", id: l.base, label: l.person_name }], "");
      return;
    }
    const pr = l.persona || {}, rq = l.review.portrait_request;
    $("#detail").innerHTML = `${l.variant ? `<span class="tag">${esc(VARIANT[l.variant] ? t(VARIANT[l.variant]) : l.variant)}</span>` : l.groups[0] ? `<span class="tag">${esc(l.groups[0])}</span>` : ""}<h3>${esc(l.person_name)}</h3><div class="r">${esc(l.role || (pr.player ? t("你自己 · 由你来扮演") : ""))}</div>
      <div class="cmp"><figure>${l.face ? `<img src="${esc(l.face)}" style="object-position:50% 20%">` : `<div class="nopic">${t("没有参考照片")}</div>`}<figcaption>${t(l.variant === "license" ? "请柬里的照片" : "那天的照片")}</figcaption></figure>
        <figure>${portraitOf(l) ? `<div class="pxbox"><img class="px" src="${esc(portraitOf(l))}"></div>` : `<div class="nopic">${t("头像还在生成")}</div>`}<figcaption>${t("游戏里的头像 · 64×64")}</figcaption></figure></div>
      ${l.walk ? `<div class="walks">${[0, 1, 2, 3].map(r => `<div class="walk" style="background-image:url('${esc(l.walk)}');background-position-y:-${r * 96}px"></div>`).join("")}</div>` : `<div class="walks none">${t("还没有行走图")}</div>`}
      ${ls.length > 1 ? `<div class="lbl">${t("穿着")}</div><div class="seg" id="outfit">${ls.map(x => `<button data-v="${esc(x.variant)}" class="${x.id === l.id ? "cur" : ""}">${x.variant ? esc(VARIANT[x.variant] ? t(VARIANT[x.variant]) : x.variant) : t("婚礼当天")}</button>`).join("")}</div>` : ""}
      <div class="lbl">${t("在游戏里")}</div>
      ${pr.player ? `<div class="opts dis"><div class="opt cur"><span class="rd"></span><div>${t("你自己 · 由你来扮演")}<small>${esc(pr.note || "")}</small></div></div></div>`
        : `<div class="opts" id="pers">${PRES.map(([k, a, b]) => `<button class="opt ${pr.npc && (pr.presence || "event_only") === k ? "cur" : ""}" data-k="${k}"><span class="rd"></span><div>${t(a)}<small>${t(b)}</small></div></button>`).join("")}
          ${pr.presence === "spouse" ? `<div class="opt cur"><span class="rd"></span><div>${t("配偶")}<small>${t("已在方案里定为配偶")}</small></div></div>` : ""}</div>`}
      <div class="lbl">${t("想改的地方")}</div><textarea id="pnote" placeholder="${esc(t("比如：头发再长一点，裙子是白色的"))}">${esc(l.review.note || "")}</textarea>
      <div class="acts"><button class="btn sm" id="pok">${icon("check")}${t("就这样")}</button>${EMBED ? `<button class="btn ghost sm" id="pchat">${t("在对话里说")}</button>` : ""}<button class="btn ghost sm" id="predo">${icon("redo")}${t("按意见重画")}</button></div>
      ${rq && rq.state === "pending" ? `<div class="pend">${t("已请求重画头像，等 agent 处理。")}</div>` : ""}
      <div class="fine">${t("重画会把这张裁出的脸发给画图模型，约 $0.04，记进发送明细。")}${l.review.status === "ok" ? " " + t("你已经确认过这个形象。") : ""} <a href="/looks-old" style="color:var(--violet)">${t("调整行走图的颜色（旧页面）")}</a></div>`;
    $$("#outfit button").forEach(b => b.onclick = () => { pvar[l.base] = b.dataset.v; draw(); });
    $$("#pers .opt").forEach(b => b.onclick = async () => {
      const s = await get("/api/state"); const p = s.people.find(x => x.id === l.base); if (!p) return toast(t("找不到这个人"));
      p.persona = { ...(p.persona || {}), npc: true, presence: b.dataset.k }; delete p.persona.player;
      const r = await post("/api/save", { rev: s.rev, people: s.people, groups: s.groups, tags: s.tags, note: "persona: " + l.base });
      if (!r.ok) return toast(r.error || t("没能保存"));
      PEO.people.filter(x => x.base === l.base).forEach(x => x.persona = p.persona); toast(t("已记下")); draw();
    });
    const rv = async (status, extra = {}) => {
      const note = $("#pnote").value; const r = await post("/api/review", { id: l.id, status, note, ...extra });
      if (!r.ok) return toast(r.error || t("没能保存"));
      l.review = { ...l.review, status, note, ...(extra.portrait_request ? { portrait_request: { state: "pending" } } : {}) }; toast(t("已记下")); draw(); loadShell().then(() => renderSide("people"));
    };
    $("#pok").onclick = () => rv("ok");
    if ($("#pchat")) $("#pchat").onclick = () => { tellChat([{ kind: "person", id: l.base, label: l.person_name }], $("#pnote").value.trim()); $("#pnote").value = l.review.note || ""; };
    $("#predo").onclick = () => {
      if (!$("#pnote").value.trim()) return toast(t("先写下想怎么改（比如：头发再长一点）"));
      if (!confirm(t("请 GameAnything 重新生成“{name}”的头像？\n\n会把这个人的参考照片（脸部裁剪图）和你的意见发给生图模型 Seedream（通过 OpenRouter，字节跳动的模型），约 $0.035 / 张。\n确认后这条请求会交给 GameAnything 处理。", { name: l.person_name }))) return;
      rv("change", { portrait_request: true });
    };
  };
  $("#screen").innerHTML = topbar(`<b>${t("人物")}</b>`, pill()) + `<div class="page"><div style="display:flex;align-items:center;gap:12px"><h1 class="t" style="flex:1">${t("人物")}</h1>
      <button class="btn ghost sm" id="paddb">${t("加一个人")}</button><a class="btn ghost sm" href="#people/tag" title="${esc(t("在照片上框出每个人、起名字、拖动分组、写台词"))}">${t("标记照片里的人")}</a></div><p class="lede" id="plede"></p>
    <form class="card padd" id="padd" style="display:${PEO.people.length ? "none" : "flex"};gap:8px;flex-wrap:wrap;align-items:center;padding:12px 14px">
      <span class="muted" style="flex-basis:100%">${t("照片里没认出来、或者没有照片的人，可以在这里先写上名字；agent 会接着用。")}</span>
      <input class="inp" name="n" maxlength="60" placeholder="${esc(t("名字"))}" style="flex:1;min-width:120px"><input class="inp" name="r" maxlength="60" placeholder="${esc(t("和你的关系（可选）"))}" style="flex:1;min-width:120px">
      <button class="btn sm">${t("加上")}</button></form>
    <div class="chips" id="pchips"></div><div class="peep"><div class="grid" id="cast"></div><div class="card detail" id="detail"></div></div></div>`;
  $("#paddb").onclick = () => { const f = $("#padd"); f.style.display = "flex"; f.n.focus(); };
  $("#padd").onsubmit = async ev => {                    // someone she names by hand (QA2 2026-10-30: no way to add one without photos)
    ev.preventDefault(); const f = ev.target, r = await post("/api/people/add", { name: f.n.value, role: f.r.value });
    if (!r.ok) { toast(r.error || t("没加上")); return; } toast(t("加上了")); route();
  };
  draw();
};

/* ------------------------------------------------------------ 方案 */
const CH = [["do", "照着做"], ["hold", "先放着"], ["change", "改一下"]];
const PERS = [["once", "只发生一次", "做完就过去了，存档里不多任何东西"], ["replay", "之后可以重温（建议）", "比如通过相册或纪念物重播；具体对存档和卸载的影响，会在这一版做完、实际测过之后写在这里"],
  ["stay", "留在世界里，可以再去", "布置和地点长期存在；对存档和卸载的影响，同样要实际测过之后才写明"]];
SCREENS.plan = async (_, live) => {
  const P = await get("/api/plan"); if (!live()) return;
  if (!P.round) { $("#screen").innerHTML = topbar(`<b>${t("方案")}</b>`) + `<div class="page"><div class="doc"><div class="eyebrow">Plan · ${t("下一版")}</div><h1 class="t">${t("方案")}</h1><div class="card empty">${t("现在没有等你确认的方案。下一版的方案写好之后会出现在这里。")}${nextStep("plan")}</div><div class="hist">${(P.history || []).map(h => { const st = { built: "已完成", accepted: "已完成", planned: "计划中", building: "进行中", next: "待确认" }[h.status] || h.status || "", meta = [h.eta_hours ? t("约 {h} 小时", { h: h.eta_hours }) : "", h.cost_usd ? `$${h.cost_usd}` : ""].filter(Boolean).join(" · ");
      return `<details class="card hrow"><summary><b>${esc(h.name)}</b><span class="hst${h.status === "built" || h.status === "accepted" ? " done" : ""}">${esc(t(st))}</span></summary><div class="hbody">${h.what ? `<p>${esc(h.what)}</p>` : ""}${meta ? `<p class="muted">${esc(meta)}</p>` : ""}${(h.items || []).length ? `<ol>${h.items.map(i => `<li><b>${esc(i.title)}</b>${i.desc ? `<div>${esc(i.desc)}</div>` : ""}${i.quote ? `<div class="muted">“${esc(i.quote)}”</div>` : ""}</li>`).join("")}</ol>` : `<p class="muted">${t("没有更详细的条目。")}</p>`}</div></details>`; }).join("")}</div></div></div>`; return; }
  const R = P.round, rv = P.review || {}, sel = {}, notes = {}; let pers = rv.persistence || "replay", rev = P.rev, open = false;
  P.items.forEach(i => { const e = (rv.items || {})[i.n]; sel[i.n] = e ? e.choice : "do"; notes[i.n] = e ? e.note || "" : ""; });
  const building = R.status === "building", N = P.items.length, FOLD = 8;
  const draw = () => {
    const vis = open ? P.items : P.items.slice(0, FOLD);
    $("#items").innerHTML = vis.map(i => `<div class="card item ${sel[i.n] === "hold" ? "hold" : ""}"><div class="i">${i.n}</div>
      <div><h4>${esc(i.title)}</h4>${i.desc ? `<p>${esc(i.desc)}</p>` : ""}${i.quote ? `<q>${esc(i.quote)}</q>` : ""}</div>
      <div class="seg">${CH.map(([k, l]) => `<button data-n="${i.n}" data-k="${k}" class="${sel[i.n] === k ? "cur" : ""}">${t(l)}</button>`).join("")}</div>
      ${sel[i.n] === "change" ? `<textarea data-note="${i.n}" placeholder="${esc(t("想怎么改？"))}">${esc(notes[i.n])}</textarea>` : ""}</div>`).join("")
      + (N > FOLD ? `<div class="card more">${open ? "" : `<span class="muted">+ ${N - FOLD}</span>${t("还有 {n} 条", { n: N - FOLD })}`}<a href="#plan" id="fold">${t(open ? "收起" : "展开")}</a></div>` : "");
    $$("#items .seg button").forEach(b => b.onclick = () => { sel[b.dataset.n] = b.dataset.k; draw(); });
    $$("#items [data-note]").forEach(t => t.oninput = () => notes[t.dataset.note] = t.value);
    const f = $("#fold"); if (f) f.onclick = e => { e.preventDefault(); open = !open; draw(); };
    $$("#pers .opt").forEach(o => o.className = "opt" + (o.dataset.k === pers ? " cur" : ""));
    const c = k => Object.values(sel).filter(x => x === k).length;
    $("#sumc").innerHTML = t("共 <b>{n}</b> 条：<b>{a}</b> 条照着做 · <b>{b}</b> 条先放着 · <b>{c}</b> 条要改", { n: N, a: c("do"), b: c("hold"), c: c("change") })
      + [R.eta_hours && " · " + t("预计 <b>{n} 小时</b>", { n: R.eta_hours }), R.cost_usd && " · " + t("约 <b>{c}</b>", { c: money(R.cost_usd) }), R.max_images && " · " + t("最多 {n} 张图", { n: R.max_images })].filter(Boolean).join("");
  };
  const status = rv.state === "confirmed" ? `<span class="tag ok">${t("已选好 · {at}", { at: esc(fmtAt(rv.at)) })}</span>` : rv.state === "draft" ? `<span class="tag grey">${t("草稿 · {at}", { at: esc(fmtAt(rv.at)) })}</span>` : building ? `<span class="tag grey">${t("已经在做")}</span>` : `<span class="tag">${t("等你确认")}</span>`;
  $("#screen").innerHTML = topbar(`<b>${t("方案")}</b>`, status) + `<div class="page"><div class="doc"><div class="eyebrow">Plan · ${t(building ? "进行中的一版" : "下一版")}</div>
    <h1 class="t">${t("{title}：这一版会做什么", { title: esc(R.title) })}</h1>
    <p class="lede">${N ? `${t("一共 {n} 条。", { n: N })}${t(building ? "这一版已经开工，你现在的选择会交给 agent，能调整的地方会照做。" : "不想做的先放着，想改的直接写。确认之后 agent 才开工。")}` : t("这一版的条目还没有写出来。")}${P.source === "brief" && M2W.lang === "zh" ? "（条目是 agent 的方案原文，所以是英文。）" : ""}</p>
    <div id="items"></div>
    ${N ? `<div class="card keep"><h4>${t("做完之后，留在你的存档里的")}</h4><div class="opts" id="pers">${PERS.map(([k, a, b]) => `<button class="opt" data-k="${k}"><span class="rd"></span><div>${t(a)}<small>${t(b)}</small></div></button>`).join("")}</div></div>
    <div class="card sum"><button class="btn" id="pok">${t("就按这个做")}</button><span class="c" id="sumc"></span><span class="sp"></span><button class="btn ghost" id="pdraft">${t("先存草稿")}</button></div>
    <div class="fine" id="pfine"></div>` : ""}</div></div>`;
  if (!N) return; draw();
  $$("#pers .opt").forEach(o => o.onclick = () => { pers = o.dataset.k; draw(); });
  const send = async state => {
    const r = await post("/api/plan_review", { rev, m: R.m, state, persistence: pers, items: Object.fromEntries(P.items.map(i => [i.n, { choice: sel[i.n], note: notes[i.n] }])) });
    if (!r.ok) return toast(r.error || t("没能保存"));
    rev = r.rev; toast(t(state === "confirmed" ? "已记下，交给 agent 了" : "草稿已存")); $("#pfine").textContent = t("{a}（{at}）。", { a: t(state === "confirmed" ? "已确认" : "草稿已存"), at: fmtAt(r.at) });
  };
  $("#pok").onclick = () => send("confirmed"); $("#pdraft").onclick = () => send("draft");
};

/* ------------------------------------------------------------ 试玩 */
const VL = { ok: "做到了", partial: "部分做到", no: "没做到", unknown: "没法确认" }, VI = { ok: ["", "✓"], partial: ["p", "!"], no: ["n", "✕"], unknown: ["u", "?"] };   // VL: zh source, shown through t()
let PL = null, cur = 0, vidDur = 0;
// what the recording is, only as play.yaml states it (independent_replay / real_input: true); nothing claimed by default (QA 2026-10-29)
const playTag = P => { const b = [P.independent_replay && t("独立回放"), P.real_input && t("真实键盘输入")].filter(Boolean); return b.length ? `<span class="tag">${b.join(" · ")}</span>` : ""; };
SCREENS.play = async ([m, mom], live) => {
  PL = await get("/api/play" + (m ? "?m=" + encodeURIComponent(m) : "")); if (!live()) return;
  PL.play = PL.play || {}; if (!Array.isArray(PL.play.chapters)) PL.play.chapters = [];                       // a build folder without play.yaml: no chapters, not a crash
  if (window.M2W_BASE && PL.base && PL.base.indexOf(window.M2W_BASE + "/") !== 0) PL.base = window.M2W_BASE + PL.base;     // the build files of this tab's project
  if (!PL.m) { $("#screen").innerHTML = topbar(`<b>${t("试玩")}</b>`) + `<div class="page"><div class="card empty">${t("还没有可以看的录像。第一版做好之后会在这里。")}${nextStep("play")}</div></div>`; return; }
  const P = PL.play, ch = P.chapters || [], rounds = SH.rounds, rn = rounds.find(r => r.m === PL.m) || { name: PL.m, title: PL.m };
  cur = Math.max(0, mom ? ch.findIndex(c => c.moment === mom) : 0); vidDur = 0;
  const switcher = `<div class="seg" style="min-width:260px;white-space:nowrap">${rounds.filter(r => r.state !== "planned").reverse().map(r => r.play ? `<button data-m="${esc(r.m)}" class="${r.m === PL.m ? "cur" : ""}">${esc(r.name.split(" · ")[0])}</button>` : `<button disabled style="opacity:.45;cursor:default;white-space:nowrap">${esc(r.title)}</button>`).join("")}</div>`;
  $("#screen").innerHTML = topbar(`${t("试玩")} / <b>${esc(rn.name.split(" · ")[0])}</b>`, switcher) + `<div class="page" style="max-width:none"><div class="room"><div>
      <div class="vhead"><h1>${esc(rn.title)}</h1>${playTag(P)}<span class="muted" id="vlen" style="font-size:12.5px"></span></div>
      ${P.video ? `<div class="vwrap"><video id="vid" src="${esc(PL.base + P.video)}" controls preload="metadata"></video></div>` : `<div class="vwrap none">${t("这一版没有录像")}</div>`}
      <div class="scrub" id="scrub"></div><div class="strip" id="strip"></div>
      <div id="cbox" class="cbox"></div>
      <div class="under" id="under"></div></div><div class="pside" id="pside"></div></div></div>`;
  $$("#screen .top .seg button[data-m]").forEach(b => b.onclick = () => { location.hash = "#play/" + b.dataset.m; });
  const v = $("#vid");
  if (v) {
    v.addEventListener("loadedmetadata", () => { vidDur = v.duration; $("#vlen").textContent = t("{m} 分 {s} 秒", { m: Math.floor(vidDur / 60), s: Math.round(vidDur % 60) }); scrubDraw();
      if (ch[cur] && mom) v.currentTime = ch[cur].t + .5; });
    v.addEventListener("timeupdate", () => {
      const t = v.currentTime; let i = ch.findIndex((c, k) => t >= c.t && t < (ch[k + 1] ? ch[k + 1].t : 1e9)); if (i < 0) i = 0;
      const ta = $("#cnote"); if (i !== cur && !(ta && (ta.value || document.activeElement === ta))) { cur = i; scrubDraw(); sideDraw(); }
      const ph = $("#ctime"); if (ph) ph.textContent = fmt(t);
    });
  }
  scrubDraw(); sideDraw(); underDraw();
};
const chEnd = i => { const c = PL.play.chapters; return c[i + 1] ? c[i + 1].t : (vidDur || (c[i].t + 60)); };
function scrubDraw() {
  const ch = PL.play.chapters, dur = vidDur || (ch.length ? chEnd(ch.length - 1) : 1), R = PL.review;
  if (!ch.length) { $("#scrub").innerHTML = ""; $("#strip").innerHTML = `<div class="ghostline">${t("这一版没有章节")}</div>`; return; }
  const pins = R.notes.filter(n => n.kind === "time" && n.t != null);
  $("#scrub").innerHTML = `<div class="segs">${ch.map((c, i) => `<i data-i="${i}" class="${i === cur ? "cur" : ""}" style="flex:${Math.max(chEnd(i) - c.t, 8)}" title="${esc(c.title)}"></i>`).join("")}</div>
    ${pins.map(p => `<div class="pin" data-t="${p.t}" style="left:${Math.min(99, p.t / dur * 100)}%" title="${esc(t("你在 {t} 留了言", { t: fmt(p.t) }))}"></div>`).join("")}
    <div class="lab" style="left:${Math.min(80, ch[cur].t / dur * 100)}%">${fmt(ch[cur].t)} · ${esc(ch[cur].title)}</div>`;
  $("#strip").innerHTML = ch.map((c, i) => { const g = gameOf(c.moment);
    return `<a data-i="${i}" class="${i === cur ? "cur" : ""}">${g ? `<img class="px" src="${esc(g)}" loading="lazy">` : `<div class="nopic">${t("没有画面")}</div>`}${esc(c.title)}<span class="tm">${fmt(c.t)}</span></a>`; }).join("");
  const sc = $(".strip a.cur"); if (sc) $("#strip").scrollLeft = sc.offsetLeft - $("#strip").offsetLeft - 160;
  $$("#scrub .segs i, #strip a").forEach(e => e.onclick = () => { cur = +e.dataset.i; const v = $("#vid"); if (v) v.currentTime = ch[cur].t + .5; scrubDraw(); sideDraw(); });
  $$("#scrub .pin").forEach(e => e.onclick = () => { const v = $("#vid"); if (v) v.currentTime = +e.dataset.t; });
}
const gameOf = mid => { const sc = (PL.play.scenes || []).find(x => x.moment === mid); return sc ? PL.base + sc.file : PL.game_by_moment[mid] || null; };
const realOf = mid => PL.real_by_moment[mid] || null;
async function fb(body) { const r = await post("/api/play_feedback", { m: PL.m, ...body }); if (r.review) PL.review = r.review; if (!r.ok) toast(r.error || t("没能保存")); return r; }
function commentsOf(i) {
  const ch = PL.play.chapters, c = ch[i], R = PL.review, out = [];
  const mine = R.moments[c.moment]; if (mine && (mine.note || mine.status === "change")) out.push({ t: null, text: mine.note || t("（标了要改）"), kind: "moment", note: mine.note });
  R.notes.forEach(n => { const inside = n.t != null && n.t >= c.t && n.t < chEnd(i); if (inside || n.moment === c.moment) out.push({ t: n.t, text: n.note, frame: n.frame, kind: n.kind, note: n.note }); });
  return out;
}
const handed = note => { const nr = PL.next_round; return !!(nr && note && (nr.items || []).some(x => x.note === note || (x.note || "").includes(note))); };
function sideDraw() {
  const ch = PL.play.chapters, el = $("#pside"); if (!ch.length) { el.innerHTML = ""; if ($("#cbox")) $("#cbox").innerHTML = ""; return; }
  const c = ch[cur], R = PL.review, g = gameOf(c.moment), rl = realOf(c.moment), mine = R.moments[c.moment] || {};
  const cks = (PL.play.checks || []).filter(x => x.moment === c.moment), cm = commentsOf(cur);
  const items = myItems(), hasReq = !!PL.next_round;
  el.innerHTML = `<div class="card"><div class="eyebrow">${t("{t} · 第 {n} 段", { t: fmt(c.t), n: cur + 1 })}</div><h2 class="h" style="margin:6px 0 12px">${esc(c.title)}</h2>
      ${g || rl ? `<div class="ba" id="ba">${g ? `<img class="px" src="${esc(g)}">` : ""}${rl ? `<img id="baTop" src="${esc(rl)}" style="${g ? "clip-path:inset(0 0 0 50%)" : ""}">` : ""}
        ${g && rl ? `<div class="line" id="baLine"></div><div class="knob" id="baKnob"></div><span class="tg" style="left:8px">${t("游戏里")}</span><span class="tg" style="right:8px">${t("那天")}</span><input type="range" min="0" max="100" value="50" id="baIn">` : `<span class="tg" style="left:8px">${t(g ? "游戏里" : "那天")}</span>`}</div>`
        : `<div class="empty" style="padding:18px">${t("这个时刻没有可以对比的画面，请看录像")}</div>`}
      <div class="vbar"><button class="btn sm ghost ${mine.status === "ok" ? "on" : ""}" data-st="ok">${t("满意")}</button><button class="btn sm ghost ${mine.status === "change" ? "on change" : ""}" data-st="change">${t("要改")}</button>
        ${g ? `<button class="btn sm ghost" id="boxbtn">${t("在游戏画面上框出问题")}</button>` : ""}</div>
      <textarea id="mnote" style="margin-top:10px;min-height:44px" placeholder="${esc(t("对这个时刻的意见"))}">${esc(mine.note || "")}</textarea></div>
    <div class="card"><h2 class="h" style="font-size:14px">${t("检查")} <span class="muted">${t(PL.play.independent_replay ? "独立回放 + 审阅" : "审阅")}</span></h2>
      ${cks.length ? cks.map(ckRow).join("") : `<div class="ghostline">${t("这个时刻没有单独的检查项。")}</div>`}</div>
    <div class="card decide"><b>${t("这一版可以吗？")}</b><p>${items.length ? t("你在这一版留了 {n} 条意见。可以接着看，也可以现在交给下一版。", { n: items.length }) : t("还没有意见。看完觉得都满意，就点“这一版可以了”。")}${hasReq ? `<br><span class="muted">${t("已提交（{at}，{n} 条，状态：{state}）", { at: esc(fmtAt(PL.next_round.at)), n: PL.next_round.items.length, state: PL.next_round.state === "pending" ? t("等 agent 开始") : esc(PL.next_round.state) })}</span>` : ""}</p>
      <div class="acts"><button class="btn sm" id="allok">${t("这一版可以了")}</button><button class="btn ghost sm" id="nextbtn" ${items.length ? "" : "disabled"}>${t("按意见做下一版")}</button></div></div>`;
  $("#cbox").innerHTML = `<div class="card"><h2 class="h" style="font-size:14px">${t("留言")}</h2>
      ${cm.map(x => `<div class="cm">${x.t != null ? "“" : ""}${esc(x.text)}${x.t != null ? "”" : ""}<small>${x.t != null ? fmt(x.t) + " · " : ""}${t(handed(x.note) ? "已交给下一版" : "还没交给下一版")}${x.frame ? " · " + t("附了画面") : ""}</small></div>`).join("") || `<div class="ghostline" style="margin-bottom:8px">${t("这一段你还没有留言。")}</div>`}
      <textarea id="cnote" placeholder="${esc(t("在 {t} 留一句话，会连同这一帧一起记下", { t: fmt($("#vid") ? $("#vid").currentTime : c.t) }))}"></textarea>
      <div class="acts"><button class="btn sm" id="cbtn">${t("在 {t} 留言", { t: `<span id="ctime">${fmt($("#vid") ? $("#vid").currentTime : c.t)}</span>` })}</button>${EMBED ? `<button class="btn sm ghost" id="cchat">${t("在对话里说")}</button>` : ""}</div></div>`;
  const inp = $("#baIn"); if (inp) inp.oninput = () => { $("#baTop").style.clipPath = `inset(0 0 0 ${inp.value}%)`; $("#baLine").style.left = $("#baKnob").style.left = inp.value + "%"; };
  $$("#pside [data-st]").forEach(b => b.onclick = async () => { await fb({ kind: "moment", moment: c.moment, status: b.dataset.st, note: $("#mnote").value }); toast(t("已记下")); scrubDraw(); sideDraw(); underDraw(); });
  $("#mnote").onchange = async () => { await fb({ kind: "moment", moment: c.moment, status: (PL.review.moments[c.moment] || {}).status || "change", note: $("#mnote").value }); toast(t("已记下")); sideDraw(); underDraw(); };
  $$("#pside .ck").forEach(wireCk);
  const bb = $("#boxbtn"); if (bb) bb.onclick = () => boxMode(g, c.moment);
  $("#cbtn").onclick = async () => {
    const v = $("#vid"), note = $("#cnote").value.trim(); if (!note) return toast(t("先写下意见"));
    let frame = null; if (v && v.videoWidth) { try { const cv = document.createElement("canvas"); cv.width = v.videoWidth; cv.height = v.videoHeight; cv.getContext("2d").drawImage(v, 0, 0); frame = cv.toDataURL("image/png"); } catch (e) {} }
    const tt = v ? +v.currentTime.toFixed(1) : c.t; await fb({ kind: "time", t: tt, note, frame }); toast(t("已记下（{t}）", { t: fmt(tt) })); scrubDraw(); sideDraw(); underDraw();
  };
  if ($("#cchat")) $("#cchat").onclick = () => {
    const v = $("#vid"), tt = v ? +v.currentTime.toFixed(1) : c.t; let frame_data;
    if (v && v.videoWidth) { try { const cv = document.createElement("canvas"); cv.width = Math.min(v.videoWidth, 1280); cv.height = Math.round(cv.width * v.videoHeight / v.videoWidth); cv.getContext("2d").drawImage(v, 0, 0, cv.width, cv.height); frame_data = cv.toDataURL("image/jpeg", .85); } catch (e) {} }
    tellChat([{ kind: "moment", id: c.moment, label: c.title }, { kind: "video", m: PL.m, t: tt, ...(frame_data ? { frame_data } : {}) }], $("#cnote").value.trim());
    $("#cnote").value = "";
  };
  $("#allok").onclick = async () => {
    const todo = ch.filter(x => !(PL.review.moments[x.moment] || {}).status); if (todo.length) await fb({ kind: "all_ok", moments: todo.map(x => x.moment) });
    toast(todo.length ? t("已记下：{n} 个时刻满意", { n: todo.length }) : t("每个时刻你都表过态了")); scrubDraw(); sideDraw(); underDraw();
  };
  $("#nextbtn").onclick = nextRound;
}
function boxMode(file, moment) {
  const ba = $("#ba"); if (!ba) return; const rel = file.replace(PL.base, "");
  ba.classList.add("draw"); ba.innerHTML = `<img class="px" src="${esc(file)}"><div class="ov"></div><span class="tg" style="left:8px">${t("拖动框出有问题的地方")}</span>`;
  const ov = $(".ov", ba); let st = null, el = null;
  ov.onmousedown = e => { const r = ov.getBoundingClientRect(); st = { r, x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; el = document.createElement("div"); el.className = "bx"; ov.appendChild(el); };
  ov.onmousemove = e => { if (!st) return; const x = (e.clientX - st.r.left) / st.r.width, y = (e.clientY - st.r.top) / st.r.height;
    Object.assign(el.style, { left: Math.min(x, st.x) * 100 + "%", top: Math.min(y, st.y) * 100 + "%", width: Math.abs(x - st.x) * 100 + "%", height: Math.abs(y - st.y) * 100 + "%" }); };
  ov.onmouseup = async e => {
    if (!st) return; const x = (e.clientX - st.r.left) / st.r.width, y = (e.clientY - st.r.top) / st.r.height;
    const box = [Math.min(x, st.x), Math.min(y, st.y), Math.max(x, st.x), Math.max(y, st.y)].map(v => +v.toFixed(3)); st = null;
    if (box[2] - box[0] < 0.02) { el.remove(); return; }
    const note = prompt(t("框出来的地方有什么问题？")); if (!note) { el.remove(); return; }
    await fb({ kind: "box", moment, box, note, t: null, frame: null, id: rel }); toast(t("已记下")); sideDraw(); underDraw();
  };
}
function ckRow(c) {
  const mine = PL.review.checks[c.id] || {}, v = c.verdict, ic = VI[v] || ["u", "?"];
  return `<div class="ck" data-id="${esc(c.id)}"><span class="k ${ic[0]}">${ic[1]}</span><span>${esc(c.item)}<small><b style="font-weight:600">${VL[v] ? t(VL[v]) : esc(v)}</b> · ${esc(c.note)}</small>
    ${mine.verdict || mine.note ? "" : `<a class="chg" style="color:var(--violet);cursor:pointer;font-size:11.5px">${t("我不同意")}</a>`}<span class="ov" style="${mine.verdict || mine.note ? "" : "display:none"}"><select data-ck><option value="">${t("同意这个结论")}</option>${Object.entries(VL).map(([k, l]) => `<option value="${k}" ${mine.verdict === k ? "selected" : ""}>${t("我觉得是：{l}", { l: t(l) })}</option>`).join("")}</select>
    <input data-cn placeholder="${esc(t("为什么（可不写）"))}" value="${esc(mine.note || "")}"></span></span></div>`;
}
function wireCk(row) {
  const id = row.dataset.id; const chg = $(".chg", row); if (chg) chg.onclick = () => { $(".ov", row).style.display = ""; chg.remove(); };
  row.querySelectorAll("[data-ck],[data-cn]").forEach(e => e.onchange = async () => {
    await fb({ kind: "check", id, verdict: $("[data-ck]", row).value, note: $("[data-cn]", row).value }); toast(t("已记下")); sideDraw(); underDraw(); });
}
function myItems() {
  const R = PL.review, P = PL.play, items = [];
  Object.entries(R.moments).forEach(([m, e]) => e.status === "change" && items.push({ kind: "moment", what: PL.moment_titles[m] || m, note: e.note }));
  Object.entries(R.checks).forEach(([id, e]) => e.verdict && items.push({ kind: "check", what: (P.checks.find(c => c.id === id) || {}).item || id, note: t("改判为“{v}”", { v: t(VL[e.verdict]) }) + (e.note ? t("：") + e.note : "") }));
  Object.entries(R.sounds).forEach(([f, e]) => e.status === "change" && items.push({ kind: "sound", what: t("声音 {f}", { f: f.split("/").pop() }), note: e.note }));
  R.notes.forEach(n => items.push({ kind: n.kind, what: n.kind === "time" ? t("录像 {t}", { t: fmt(n.t || 0) }) : t("截图上框出的地方"), note: n.note, frame: n.frame }));
  return items;
}
async function nextRound() {
  const items = myItems(); if (!items.length) return toast(t("还没有意见"));
  if (!confirm(t("把这 {n} 条意见交给 GameAnything，写成下一轮的修改要求？", { n: items.length }) + "\n\n" + items.map(x => "· " + x.what + t("：") + (x.note || "")).join("\n") + "\n\n" + t("下一轮会在这一期的基础上修改，预计几个小时（按第 1 期的经验，一轮约 5 小时、约 40 美元）。GameAnything 开始前会先告诉你。"))) return;
  const r = await post("/api/next_round", { m: PL.m, items }); if (r.next_round) PL.next_round = r.next_round; toast(r.ok ? t("已提交") : (r.error || t("没能提交"))); sideDraw(); underDraw();
}
function underDraw() {
  const P = PL.play, R = PL.review, items = myItems(), el = $("#under"); if (!el) return;
  el.innerHTML = `${(P.checks || []).length ? `<div class="card"><h2 class="h" style="font-size:14px">${t("全部检查")} <span class="muted">${t("{n} 项 · GameAnything 的结论，你觉得不对可以改判", { n: P.checks.length })}</span></h2>${P.checks.map(ckRow).join("")}</div>` : ""}
    <div class="card"><h2 class="h" style="font-size:14px">${t("声音试听")} <span class="muted">${t("开发 agent 和 GameAnything 都听不到声音，只有你能判断")}</span></h2>
      ${(P.sounds || []).map(x => { const s = R.sounds[x.file] || {}; return `<div class="snd"><audio controls preload="none" src="${esc(PL.base + x.file)}"></audio><div class="tx"><b>${esc(x.used_for)}</b><small>${esc(x.note || "")}</small></div>
        <button class="btn sm ghost ${s.status === "ok" ? "on" : ""}" data-snd="${esc(x.file)}" data-v="ok">${t("没问题")}</button><button class="btn sm ghost ${s.status === "change" ? "on change" : ""}" data-snd="${esc(x.file)}" data-v="change">${t("听着不对")}</button></div>`; }).join("") || `<div class="ghostline">${t("这一版没有单独的声音文件。")}</div>`}
      <div class="fine">${t("游戏自带的音效在录像里能听到；有问题就在录像那一刻留言。")}</div></div>
    <div class="card"><h2 class="h" style="font-size:14px">${t("自己玩")}</h2>
      ${P.install ? `<a class="btn ghost sm" href="${esc(PL.base + P.install)}" download>${t("下载这一版的 mod（zip）")}</a>
      <ol class="how"><li>${t("先备份存档（Windows：%AppData%\\StardewValley\\Saves；Mac/Linux：~/.config/StardewValley/Saves）。")}</li>
      <li>${t("装好 SMAPI，把 zip 解压到游戏的 Mods 文件夹，用 SMAPI 启动；新开一个存档，把角色捏成你自己的样子。")}</li>
      <li>${t("要卸载时：先在 SMAPI 控制台运行 mod 说明里的卸载准备命令，再删掉 Mods 里的文件夹。")}</li></ol>` : `<div class="ghostline">${t("这一版还没有可安装的包。")}</div>`}</div>
    <div class="card mine"><h2 class="h" style="font-size:14px">${t("我的意见")} <span class="muted">${t("{n} 条", { n: items.length })}</span></h2>
      ${items.length ? `<ul>${items.map(x => `<li><b>${esc(x.what)}</b>${t("：")}${esc(x.note || t("（没写说明）"))}${x.frame ? ` <span class="muted">${t("[附画面]")}</span>` : ""}</li>`).join("")}</ul>` : `<div class="ghostline">${t("还没有意见。看完觉得都满意，就不用交给下一版。")}</div>`}</div>`;
  $$("#under .ck").forEach(wireCk);
  $$("#under [data-snd]").forEach(b => b.onclick = async () => {
    const note = b.dataset.v === "change" ? (prompt(t("哪里不对？（比如：像猪叫）")) || "") : "";
    await fb({ kind: "sound", id: b.dataset.snd, status: b.dataset.v, note }); toast(t("已记下")); sideDraw(); underDraw(); });
}

/* ------------------------------------------------------------ 带回家 */
SCREENS.keep = async () => {
  $("#screen").innerHTML = topbar(`<b>${t("带回家")}</b>`, `<span class="tag grey">${t("收尾交付那一期开放")}</span>`) + `<div class="page"><div class="kwrap">
    <div class="eyebrow">Step 5 · Keep</div><h1 class="t">${t("带回家")}</h1>
    <p class="lede">${t("把做好的世界装进你自己的 {g}。装之前先备份你的存档，随时可以还原。", { g: SH.game })}</p>
    <div class="card ks"><div class="n">1</div><div><h4>${t("找到你的游戏")}</h4><p>${t("收尾那一期，这里会找到你电脑上的 {g}，并告诉你版本和 mod 是否装好、能不能用。", { g: SH.game })}</p></div></div>
    <div class="card ks"><div class="n">2</div><div><h4>${t("备份你的存档")}</h4><p>${t("把你现在所有的存档打包成一份备份（只在这台电脑上），之后可以一键还原，还原本身也能撤销。")}</p>
      <div class="acts"><button class="btn ghost sm" disabled>${t("备份全部存档")}</button><span class="muted" style="font-size:12px">${t("收尾交付那一期开放")}</span></div></div></div>
    <div class="card ks"><div class="n">3</div><div><h4>${t("装进哪里")}</h4><div class="opts dis" style="margin-top:10px">
      <div class="opt cur"><span class="rd"></span><div>${t("新开一个存档（建议）")}<small>${t("从头开始，最干净，也最好测试")}</small></div></div>
      <div class="opt"><span class="rd"></span><div>${t("装进已有的存档")}<small>${t("已有的进度不受影响；婚礼会安排在方案里定的那一天")}</small></div></div></div></div></div>
    <div class="card ks"><div class="n">4</div><div><h4>${t("装好之后，你的存档里会多")}</h4><p>${SH.persistent ? t("按现在的方案：{x}。", { x: esc(SH.persistent) }) : t("按你在“方案”里的选择。")}${t("具体多什么，以收尾那一期实际装出来的为准。")}</p></div></div>
    <div class="card ks"><div class="n">5</div><div><h4>${t("想卸载的时候")}</h4><p>${t("怎么卸载、卸载以后存档会怎样，会在收尾那一期实际测过之后写在这里；还原备份永远可以回到装之前。")}</p></div></div>
    <div class="card sum" style="position:static"><button class="btn" disabled>${t("备份并安装")}</button><span class="c">${t("收尾交付那一期开放")}</span></div></div></div>`;
};


/* ------------------------------------------------------------ 改编项目：场景 / 地点 / 角色 (kind: adaptation; 3_remember/adaptation.yaml) */
const GR = { explicit: ["作品有依据", "gx"], implied: ["推断", "gi"], invented: ["发明", "gv"] };
const RCH = [["keep", "保留"], ["skip", "先不做"], ["change", "要改"]];
let AD = null, adTab = "scenes";
const adKey = (k, id) => `${k}:${id}`;
const quotesHtml = qs => qs.length ? `<div class="adq">${qs.map(q => `<blockquote>${esc(q.text)}${q.tr ? `<div class="muted">${esc(q.tr)}</div>` : ""}${q.where ? `<cite>${esc(q.where)}</cite>` : ""}</blockquote>`).join("")}</div>` : "";
function reviewHtml(key) {
  const e = AD.review.items[key] || {}, ch = e.choice || "keep";
  return `<div class="adrv" data-key="${esc(key)}"><div class="seg">${RCH.map(([v, l]) => `<a data-ch="${v}" class="${ch === v ? "cur" : ""}">${t(l)}</a>`).join("")}</div>
    <textarea class="inp" rows="1" placeholder="${esc(t("想改什么、补什么，写在这里（会原话转给 agent）"))}">${esc(e.note || "")}</textarea></div>`;
}
async function adSave(items, state, stateChars) {
  const r = await post("/api/adaptation_review", { rev: AD.rev, items, ...(state ? { state } : {}), ...(stateChars ? { state_characters: stateChars } : {}) });
  if (!r.ok) { toast(r.error || t("没能保存")); if (r.stale) route(); return false; }
  AD.rev = r.rev; Object.entries(items).forEach(([k, e]) => AD.review.items[k] = { ...(AD.review.items[k] || {}), ...e }); if (state) AD.review.state = state; if (stateChars) AD.review.state_characters = stateChars;
  toast(t("已记下")); return true;
}
function wireReview(root) {
  $$(".adrv", root).forEach(box => {
    const key = box.dataset.key, ta = $("textarea", box);
    $$("[data-ch]", box).forEach(a => a.onclick = async () => {
      if (await adSave({ [key]: { choice: a.dataset.ch, note: ta.value } })) { $$("[data-ch]", box).forEach(x => x.classList.toggle("cur", x === a)); box.closest(".adc").dataset.ch = a.dataset.ch; }
    });
    ta.onchange = () => adSave({ [key]: { choice: (AD.review.items[key] || {}).choice || (ta.value.trim() ? "change" : "keep"), note: ta.value } });
  });
}
// the work is in (the flow's first step is done, or files wait in the inbox): the empty page says the agent is extracting, not 「put it in」
const gathered = () => { const st = ((SH && SH.flow && SH.flow.steps) || []).find(x => x.key === "gather"); return !!(st && st.state === "done"); };
function adEmpty(title) {
  const msg = gathered() ? (title === "角色" ? "作品已经放进来了：agent 正在从里面找出角色，好了会列在这里。" : "作品已经放进来了：agent 正在从里面抽取场景和地点，好了会列在这里。")
    : (title === "角色" ? "还没有抽取出角色。先在“作品”里放进你要改编的内容。" : "还没有抽取出场景和地点。先在“作品”里放进你要改编的内容。");
  return topbar(`<b>${t(title)}</b>`) + `<div class="page"><div class="doc"><div class="eyebrow">Step 2 · Extract</div><h1 class="t">${t(title)}</h1>
    <div class="card empty">${t(msg)}${nextStep(title === "角色" ? "people" : "home")}</div></div></div>`;
}
SCREENS.scenes = async (_, live) => {
  AD = await get("/api/adaptation"); if (!live()) return;
  if (badPage("场景", AD)) { $("#screen").innerHTML = badPage("场景", AD); return; }
  if (!AD.exists) { $("#screen").innerHTML = adEmpty("场景"); return; }
  const W = AD.work, c = AD.counts, conf = AD.review.state === "confirmed";
  const sceneCard = s => `<div class="card adc" data-ch="${esc((AD.review.items[adKey("scene", s.id)] || {}).choice || "keep")}">
      <div class="adh">${s.unit ? `<span class="tag">${esc(s.unit)}</span>` : ""}<h3>${esc(s.title)}</h3></div>
      ${s.what ? `<p>${esc(s.what)}</p>` : ""}
      <div class="admeta">${s.characters.map(x => `<span class="chip">${esc(x)}</span>`).join("")}${s.time ? `<span class="muted">${esc(s.time)}</span>` : ""}</div>
      ${(s.frames || []).length ? `<div class="adframes">${s.frames.map(f => `<a href="/media/${esc(f.file)}" target="_blank"><img src="/media/${esc(f.file)}" alt=""${f.t != null ? ` title="${esc(String(f.t))}s"` : ""}></a>`).join("")}</div>` : ""}
      ${quotesHtml(s.quotes)}${reviewHtml(adKey("scene", s.id))}</div>`;
  const placeCard = p => `<div class="card adc" data-ch="${esc((AD.review.items[adKey("place", p.id)] || {}).choice || "keep")}">
      <div class="adh"><h3>${esc(p.name)}</h3>${p.aliases.length ? `<span class="muted">${t("也叫")} ${p.aliases.map(esc).join("、")}</span>` : ""}</div>
      ${p.described.length ? `<div class="adl">${t("作品里写了")}</div>${quotesHtml(p.described)}` : ""}
      ${p.not_described.length ? `<div class="adl">${t("作品没写（要发明，或者问你）")}</div><div class="admeta">${p.not_described.map(x => `<span class="chip new">${esc(x)}</span>`).join("")}</div>` : ""}
      ${p.build.length ? `<div class="adl">${t("要建的东西")}</div><ul class="adb">${p.build.map(b => `<li><span class="gr ${GR[b.grounding][1]}">${t(GR[b.grounding][0])}</span><b>${esc(b.name)}</b>${b.quote ? `<div class="muted">“${esc(b.quote)}”</div>` : ""}${b.note ? `<div class="muted">${esc(b.note)}</div>` : ""}</li>`).join("")}</ul>` : ""}
      ${reviewHtml(adKey("place", p.id))}</div>`;
  const draw = () => {
    $("#screen").innerHTML = topbar(`<b>${t("场景")}</b>`, conf ? `<span class="tag ok">${t("已确认 · {at}", { at: esc(fmtAt(AD.review.at)) })}</span>` : "") + `<div class="page"><div class="doc">
      <div class="eyebrow">Step 2 · Extract</div><h1 class="t">${esc(W.title || t("场景和地点"))}</h1>
      <p class="lede">${AD.units.length ? esc(AD.units.join(" · ")) + " · " : ""}${t("{s} 个场景，{p} 个地点", { s: AD.scenes.length, p: AD.places.length })}${W.source ? ` · ${t("底本")}：${esc(W.source)}` : ""}${W.source_license ? `（${esc(W.source_license)}）` : ""}</p>
      <div class="adsum"><span class="gr gx">${t("作品有依据")} ${c.explicit}</span><span class="gr gi">${t("推断")} ${c.implied}</span><span class="gr gv">${t("发明")} ${c.invented}</span>
        <span class="muted">${t("发明的部分会在方案里单独列出，你可以改")}</span></div>
      <div class="seg adtabs"><a data-tab="scenes" class="${adTab === "scenes" ? "cur" : ""}">${t("场景")} ${AD.scenes.length}</a><a data-tab="places" class="${adTab === "places" ? "cur" : ""}">${t("地点")} ${AD.places.length}</a></div>
      <div class="adlist">${adTab === "scenes" ? AD.scenes.map(sceneCard).join("") : AD.places.map(placeCard).join("")}</div>
      <div class="card adconf"><div><b>${t(conf ? "场景表已确认" : "场景、地点都看完了？")}</b><p class="muted">${t("确认之后，agent 会把你的修改应用到场景表，再写一份改编方案给你看；方案确认后会先出预览图。之后还可以回来改。")}</p></div>
        <button class="btn" id="adok"${conf ? " disabled" : ""}>${t(conf ? "已确认" : "确认场景和地点")}</button></div></div></div>`;
    $$(".adtabs [data-tab]").forEach(a => a.onclick = () => { adTab = a.dataset.tab; draw(); });
    wireReview($("#screen"));
    const ok = $("#adok"); if (ok) ok.onclick = async () => { if (await adSave({}, "confirmed")) route(); };
  };
  draw();
};
SCREENS.characters = async (_, live) => {
  AD = await get("/api/adaptation"); if (!live()) return;
  if (badPage("角色", AD)) { $("#screen").innerHTML = badPage("角色", AD); return; }
  if (!AD.exists) { $("#screen").innerHTML = adEmpty("角色"); return; }
  const title = id => (AD.scenes.find(s => s.id === id) || {}).title || id, cconf = AD.review.state_characters === "confirmed";
  $("#screen").innerHTML = topbar(`<b>${t("角色")}</b>`, cconf && AD.review.at_characters ? `<span class="tag ok">${t("已确认 · {at}", { at: esc(fmtAt(AD.review.at_characters)) })}</span>` : "") + `<div class="page"><div class="doc">
    <div class="eyebrow">Characters</div><h1 class="t">${t("作品里的角色")}</h1>
    <p class="lede">${t("角色从作品里抽取；外貌和台词都标了出处。哪里不对、想补什么，直接写。")}</p>
    <div class="adgrid">${AD.characters.map(ch => `<div class="card adc" data-ch="${esc((AD.review.items[adKey("char", ch.id)] || {}).choice || "keep")}">
      <div class="adh">${ch.image ? `<img class="adimg" src="/media/${esc(ch.image)}" alt="">` : `<span class="adav">${esc(ch.name.slice(0, 1))}</span>`}<div><h3>${esc(ch.name)}</h3>${ch.aliases.length ? `<span class="muted">${ch.aliases.map(esc).join("、")}</span>` : ""}</div></div>
      ${ch.role ? `<p>${esc(ch.role)}</p>` : ""}
      ${ch.looks.length ? `<div class="adl">${t("外貌")}</div>${quotesHtml(ch.looks)}` : ""}
      ${ch.lines.length ? `<div class="adl">${t("台词")}</div>${quotesHtml(ch.lines)}` : ""}
      ${(ch.frames || []).length ? `<div class="adframes">${ch.frames.map(f => `<a href="/media/${esc(f.file)}" target="_blank"><img src="/media/${esc(f.file)}" alt=""${f.t != null ? ` title="${esc(String(f.t))}s"` : ""}></a>`).join("")}</div>` : ""}
      ${ch.scenes.length ? `<div class="adl">${t("出场 {n} 个场景", { n: ch.scenes.length })}</div><div class="admeta">${ch.scenes.slice(0, 8).map(id => `<span class="chip">${esc(title(id))}</span>`).join("")}${ch.scenes.length > 8 ? `<span class="muted">+${ch.scenes.length - 8}</span>` : ""}</div>` : ""}
      ${reviewHtml(adKey("char", ch.id))}</div>`).join("")}</div>
    <div class="card adconf"><div><b>${t(cconf ? "人物已确认" : "人物都看完了？")}</b><p class="muted">${t("确认之后，agent 会按你的修改整理人物，再写改编方案。之后还可以回来改。")}</p></div>
      <button class="btn" id="adcok"${cconf ? " disabled" : ""}>${t(cconf ? "已确认" : "确认人物")}</button></div></div></div>`;
  wireReview($("#screen"));
  const ok = $("#adcok"); if (ok) ok.onclick = async () => { if (await adSave({}, null, "confirmed")) route(); };
};


/* ------------------------------------------------------------ 功能项目：需求 (kind: feature; 3_remember/feature.yaml, feedback/feature_review.yaml) */
let FT = null;
function ftReview(key) {
  const e = FT.review.items[key] || {}, ch = e.choice || "keep";
  return `<div class="adrv" data-key="${esc(key)}"><div class="seg">${GCH.map(([v, l]) => `<a data-ch="${v}" class="${ch === v ? "cur" : ""}">${t(l)}</a>`).join("")}</div>
    <textarea class="inp" rows="1" placeholder="${esc(t("想改什么、补什么，写在这里（会原话转给 agent）"))}">${esc(e.note || "")}</textarea></div>`;
}
async function ftSave(items, confirm) {
  const r = await post("/api/feature_review", { rev: FT.rev, items, ...(confirm ? { state: "confirmed" } : {}) });
  if (!r.ok) { toast(r.error || t("没能保存")); if (r.stale) route(); return false; }
  FT.rev = r.rev; Object.entries(items).forEach(([k, e]) => FT.review.items[k] = { ...(FT.review.items[k] || {}), ...e }); if (confirm) { FT.review.state = "confirmed"; FT.review.at = r.at; }
  toast(t("已记下")); return true;
}
SCREENS.spec = async (_, live) => {
  FT = await get("/api/feature"); if (!live()) return;
  if (badPage("需求", FT)) { $("#screen").innerHTML = badPage("需求", FT); return; }
  if (!FT.exists) { $("#screen").innerHTML = topbar(`<b>${t("需求")}</b>`) + `<div class="page"><div class="doc"><h1 class="t">${t("需求")}</h1>
    <div class="card empty">${t("还没有需求单。在对话里告诉 agent 你想加什么（放在哪、怎么玩、素材从哪来），它会先问几个问题，再把需求写在这里给你确认。")}${nextStep("spec")}</div></div></div>`; return; }
  const conf = FT.review.state === "confirmed";
  // an agent's 「none」 / 「无」 (nothing goes into the save, …) in words, not the raw value (QA 2026-10-29)
  const NONE = /^\s*(none|null|nothing|no|n\/a|无|没有|不会|空)\s*[.。]?\s*$/i;
  const row = (l, v) => v ? `<div class="adl">${t(l)}</div><p>${NONE.test(String(v)) ? `<span class="muted">${t(l === "存档里会多什么" ? "什么都不会多" : "没有")}</span>` : esc(v)}</p>` : "";
  $("#screen").innerHTML = topbar(`<b>${t("需求")}</b>`, conf ? `<span class="tag ok">${t("已确认 · {at}", { at: esc(fmtAt(FT.review.at)) })}</span>` : "") + `<div class="page"><div class="doc">
    <div class="eyebrow">Step 2 · Spec · ${esc(FT.game)}</div><h1 class="t">${esc(FT.title || t("需求"))}</h1>
    ${FT.goal ? `<p class="lede">${esc(FT.goal)}</p>` : ""}
    ${FT.open_questions.length ? `<div class="card gbox"><div class="adl">${t("还没定的")}</div><ul class="adb">${FT.open_questions.map(q => `<li>${esc(q)}</li>`).join("")}</ul></div>` : ""}
    <h2 class="h">${t("要做的事")} <span class="muted">${t("{n} 条", { n: FT.items.length })}</span></h2>
    <div class="adlist">${FT.items.map(x => `<div class="card adc" data-ch="${esc((FT.review.items["item:" + x.id] || {}).choice || "keep")}">
        <h3>${esc(x.what || x.id)} ${x.status === "confirmed" ? `<span class="tag ok">${t("已定")}</span>` : `<span class="tag grey">${t("待定")}</span>`}</h3>
        ${row("怎么用", x.how)}${row("怎样算做好", x.done_when)}${row("存档里会多什么", x.saves)}${ftReview("item:" + x.id)}</div>`).join("") || `<div class="card empty">${t("需求单里还没有条目，agent 还在问你问题。")}</div>`}</div>
    <div class="card adconf"><div><b>${t(conf ? "需求已确认" : "需求都看完了？")}</b><p class="muted">${t("确认之后，agent 会按这份需求定方案、开工。之后还可以回来改。")}</p></div>
      <button class="btn" id="ftok"${conf || !FT.items.length ? " disabled" : ""}>${t(conf ? "已确认" : "确认需求")}</button></div></div></div>`;
  $$(".adrv", $("#screen")).forEach(box => {
    const key = box.dataset.key, ta = $("textarea", box);
    $$("[data-ch]", box).forEach(a => a.onclick = async () => {
      if (await ftSave({ [key]: { choice: a.dataset.ch, note: ta.value } })) { $$("[data-ch]", box).forEach(x => x.classList.toggle("cur", x === a)); box.closest(".adc").dataset.ch = a.dataset.ch; }
    });
    ta.onchange = () => ftSave({ [key]: { choice: (FT.review.items[key] || {}).choice || (ta.value.trim() ? "change" : "keep"), note: ta.value } });
  });
  const ok = $("#ftok"); if (ok) ok.onclick = async () => { if (await ftSave({}, true)) route(); };
};

/* ------------------------------------------------------------ 玩法项目：机制映射 / 内容 / 平衡 (kind: gameplay; 3_remember/gameplay.yaml, 5_build/<m>/balance/report.yaml) */
const GKIND = { resource: "资源", card: "卡牌", relic: "遗物", enemy: "敌人", event: "事件", boss: "Boss", rule: "规则" };
const GCH = [["keep", "保留"], ["change", "要改"], ["drop", "不要"]];
const CTYPE = { attack: "攻击", skill: "技能", power: "能力" };
const GGROUPS = [["card", "cards", "卡牌"], ["relic", "relics", "遗物"], ["enemy", "enemies", "敌人"], ["event", "events", "事件"], ["boss", "bosses", "Boss"]];
let GP = null, gpKind = "all", gpGroup = "card", gpType = "all", gpArch = "all", balM = null;
function gpReview(key) {
  const e = GP.review.items[key] || {}, ch = e.choice || "keep";
  return `<div class="adrv" data-key="${esc(key)}"><div class="seg">${GCH.map(([v, l]) => `<a data-ch="${v}" class="${ch === v ? "cur" : ""}">${t(l)}</a>`).join("")}</div>
    <textarea class="inp" rows="1" placeholder="${esc(t("想改什么、补什么，写在这里（会原话转给 agent）"))}">${esc(e.note || "")}</textarea></div>`;
}
async function gpSave(items, stage) {
  const r = await post("/api/gameplay_review", { rev: GP.rev, items, ...(stage ? { stage, state: "confirmed" } : {}) });
  if (!r.ok) { toast(r.error || t("没能保存")); if (r.stale) route(); return false; }
  GP.rev = r.rev; Object.entries(items).forEach(([k, e]) => GP.review.items[k] = { ...(GP.review.items[k] || {}), ...e }); Object.assign(GP.review, r.review);
  toast(t("已记下")); return true;
}
function gpWire(root) {
  $$(".adrv", root).forEach(box => {
    const key = box.dataset.key, ta = $("textarea", box);
    $$("[data-ch]", box).forEach(a => a.onclick = async () => {
      if (await gpSave({ [key]: { choice: a.dataset.ch, note: ta.value } })) { $$("[data-ch]", box).forEach(x => x.classList.toggle("cur", x === a)); box.closest(".adc").dataset.ch = a.dataset.ch; }
    });
    ta.onchange = () => gpSave({ [key]: { choice: (GP.review.items[key] || {}).choice || (ta.value.trim() ? "change" : "keep"), note: ta.value } });
  });
}
const gpCh = key => esc((GP.review.items[key] || {}).choice || "keep");
const gpConfTag = st => st.state === "confirmed" ? `<span class="tag ok">${t("已确认 · {at}", { at: esc(fmtAt(st.at)) })}</span>` : "";
// the page's own file could not be read (a YAML syntax error, the wrong shape): name it, never 「还没有…」 (QA2 2026-10-30; filecheck.py)
function badPage(title, X) {
  if (!X || X.exists || !X.bad || !X.bad.length) return "";             // a page it could read shows what it has (flow check lists the rest)
  return topbar(`<b>${t(title)}</b>`) + `<div class="page">${errHtml({ files: X.bad })}</div>`;
}
function gpEmpty(title, msg) {
  return topbar(`<b>${t(title)}</b>`) + `<div class="page"><div class="doc"><h1 class="t">${t(title)}</h1>
    <div class="card empty">${t(msg)}${nextStep(location.hash.slice(1).split("/")[0] || "home")}</div></div></div>`;
}
SCREENS.mechanics = async (_, live) => {
  GP = await get("/api/gameplay"); if (!live()) return;
  if (badPage("机制映射", GP)) { $("#screen").innerHTML = badPage("机制映射", GP); return; }
  if (!GP.mapping.length && !GP.core.fantasy) { $("#screen").innerHTML = gpEmpty("机制映射", "还没有机制映射。先在“经历”里写下这段经历，或者在对话里讲给 agent 听；agent 会先问几个问题，再画出“经历 → 机制”的映射。"); return; }
  const C = GP.core, st = GP.review.mapping, conf = st.state === "confirmed";
  const kinds = [...new Set(GP.mapping.map(r => r.kind))];
  const loop = Array.isArray(C.loop) ? (C.loop.length ? `<ol class="gloop">${C.loop.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "") : C.loop ? `<p>${esc(C.loop)}</p>` : "";
  const draw = () => {
    const rows = GP.mapping.filter(r => gpKind === "all" || r.kind === gpKind);
    $("#screen").innerHTML = topbar(`<b>${t("机制映射")}</b>`, gpConfTag(st)) + `<div class="page"><div class="doc">
      <div class="eyebrow">Step 2 · Mapping · ${esc(GP.game)}</div><h1 class="t">${esc(GP.title || t("机制映射"))}</h1>
      ${C.fantasy ? `<p class="lede gfan">${esc(C.fantasy)}</p>` : ""}
      <div class="gcore">
        ${C.character ? `<div class="card gbox"><div class="adl">${t("主角")}</div><h3>${esc(C.character.name)}</h3><div class="admeta">${C.character.hp ? `<span class="chip">HP ${esc(C.character.hp)}</span>` : ""}${C.character.gold ? `<span class="chip">${t("金币")} ${esc(C.character.gold)}</span>` : ""}</div>${C.character.start ? `<p class="muted">${esc(C.character.start)}</p>` : ""}${C.character.note ? `<p>${esc(C.character.note)}</p>` : ""}</div>` : ""}
        ${C.resources.length ? `<div class="card gbox gwide"><div class="adl">${t("资源")}</div><table class="gtab"><thead><tr><th>${t("名字")}</th><th>${t("现实里是什么")}</th><th>${t("怎么获得")}</th><th>${t("怎么花掉")}</th></tr></thead>
          <tbody>${C.resources.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${esc(r.meaning)}</td><td>${esc(r.gain)}</td><td>${esc(r.spend)}</td></tr>`).join("")}</tbody></table></div>` : ""}
        ${loop ? `<div class="card gbox gwide"><div class="adl">${t("核心循环")}</div>${loop}</div>` : ""}
      </div>
      ${C.archetypes.length ? `<h2 class="h">${t("流派")} <span class="muted">${t("{n} 种打法", { n: C.archetypes.length })}</span></h2><div class="garch">${C.archetypes.map(a => `<div class="card gbox"><h3>${esc(a.name)}</h3><p>${esc(a.idea)}</p>${a.key_cards.length ? `<div class="admeta">${a.key_cards.map(k => `<span class="chip">${esc(k)}</span>`).join("")}</div>` : ""}</div>`).join("")}</div>` : ""}
      <h2 class="h">${t("经历 → 机制")} <span class="muted">${t("{n} 条", { n: GP.mapping.length })}</span></h2>
      <div class="chips">${[["all", t("全部"), GP.mapping.length], ...kinds.map(k => [k, t(GKIND[k]), GP.mapping.filter(r => r.kind === k).length])].map(([k, l, n]) => `<button class="chip ${gpKind === k ? "cur" : ""}" data-k="${k}">${esc(l)}<span>${n}</span></button>`).join("")}</div>
      <div class="adlist">${rows.map(r => `<div class="card adc gmap" data-ch="${gpCh("map:" + r.id)}"><div class="gm"><div><div class="adl">${t("现实里")}</div><b>${esc(r.experience)}</b></div><div class="garrow">→</div>
          <div><div class="adl">${t("游戏里")} <span class="gk gk-${esc(r.kind)}">${t(GKIND[r.kind])}</span></div><b>${esc(r.mechanic)}</b></div></div>
          ${r.note ? `<p class="muted">${esc(r.note)}</p>` : ""}${gpReview("map:" + r.id)}</div>`).join("") || `<div class="card empty">${t("这一类里还没有条目。")}</div>`}</div>
      <div class="card adconf"><div><b>${t(conf ? "机制映射已确认" : "映射都看完了？")}</b><p class="muted">${t("确认之后，agent 会按你的修改定下第一版的范围，再展开卡牌、遗物、敌人和事件。之后还可以回来改。")}</p></div>
        <button class="btn" id="gpok"${conf ? " disabled" : ""}>${t(conf ? "已确认" : "确认机制映射")}</button></div></div></div>`;
    $$(".chips [data-k]").forEach(b => b.onclick = () => { gpKind = b.dataset.k; draw(); });
    gpWire($("#screen"));
    const ok = $("#gpok"); if (ok) ok.onclick = async () => { if (await gpSave({}, "mapping")) route(); };
  };
  draw();
};
// an archetype as she reads it: the skill writes ids (`archetype: steady`) that name an entry of core.archetypes; its name is shown, never the id
const gpArchName = v => { const s = String(v || ""), l = s.toLowerCase(); const a = ((GP && GP.core && GP.core.archetypes) || []).find(a => a.id === s || a.name === s || (a.id && a.id.toLowerCase() === l) || (a.name && a.name.toLowerCase() === l)); return a && a.name ? a.name : s; };
const artHtml = (x, label) => x.art ? `<img class="gart" src="${esc(x.art)}" alt="" loading="lazy">` : `<div class="gart ph"><span>${esc(label)}</span></div>`;
function tileHtml(kind, x) {
  const key = `${kind}:${x.id}`;
  if (kind === "card") return `<div class="card adc gtile gc-${esc(x.type || "skill")}" data-ch="${gpCh(key)}">
      <div class="gtop">${x.cost !== "" ? `<span class="gcost">${esc(x.cost)}</span>` : ""}<h3>${esc(x.name)}</h3></div>${artHtml(x, t(CTYPE[x.type] || x.type || "卡牌"))}
      <div class="gline">${[CTYPE[x.type] ? t(CTYPE[x.type]) : x.type, x.rarity].filter(Boolean).map(esc).join(" · ")}${x.archetype ? ` <span class="chip">${esc(gpArchName(x.archetype))}</span>` : ""}</div>
      <p class="gtext">${esc(x.text)}</p>${x.upgrade ? `<p class="gup">${t("升级：")}${esc(x.upgrade)}</p>` : ""}${x.note ? `<p class="muted">${esc(x.note)}</p>` : ""}${gpReview(key)}</div>`;
  if (kind === "relic") return `<div class="card adc gtile" data-ch="${gpCh(key)}"><div class="gtop"><h3>${esc(x.name)}</h3></div>${artHtml(x, t("遗物"))}
      <div class="gline">${esc(x.rarity)}${x.archetype ? ` <span class="chip">${esc(gpArchName(x.archetype))}</span>` : ""}</div><p class="gtext">${esc(x.text)}</p>${x.note ? `<p class="muted">${esc(x.note)}</p>` : ""}${gpReview(key)}</div>`;
  if (kind === "enemy" || kind === "boss") return `<div class="card adc gtile${kind === "boss" ? " gboss" : ""}" data-ch="${gpCh(key)}"><div class="gtop"><h3>${esc(x.name)}</h3>${x.hp ? `<span class="ghp">HP ${esc(x.hp)}</span>` : ""}</div>${artHtml(x, t(kind === "boss" ? "Boss" : "敌人"))}
      <div class="gline">${x.act ? esc(x.act) : ""}</div>${x.mechanic ? `<p class="gtext">${esc(x.mechanic)}</p>` : ""}
      ${x.moves.length ? `<div class="adl">${t("招式")}</div><ul class="adb">${x.moves.map(m => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}${x.note ? `<p class="muted">${esc(x.note)}</p>` : ""}${gpReview(key)}</div>`;
  return `<div class="card adc gtile gevent" data-ch="${gpCh(key)}"><div class="gtop"><h3>${esc(x.name)}</h3></div>${artHtml(x, t("事件"))}<p class="gtext">${esc(x.text)}</p>
      ${x.options.length ? `<div class="adl">${t("选项")}</div><ul class="adb">${x.options.map(o => `<li><b>${esc(o.label)}</b>${o.effect ? `<span class="muted">${esc(o.effect)}</span>` : ""}</li>`).join("")}</ul>` : ""}${x.note ? `<p class="muted">${esc(x.note)}</p>` : ""}${gpReview(key)}</div>`;
}
SCREENS.content = async (_, live) => {
  GP = await get("/api/gameplay"); if (!live()) return;
  if (badPage("内容", GP)) { $("#screen").innerHTML = badPage("内容", GP); return; }
  if (!GP.has_content) { $("#screen").innerHTML = gpEmpty("内容", GP.mapping.length ? "还没有展开内容。机制映射确认、第一版的范围定下来之后，agent 会在这里列出卡牌、遗物、敌人和事件。" : "还没有内容。先在“经历”里写下这段经历，agent 会先画出机制映射，和你确认后再展开内容。"); return; }
  const C = GP.content, st = GP.review.content, conf = st.state === "confirmed", sc = GP.scope;
  if (!C[(GGROUPS.find(g => g[0] === gpGroup) || GGROUPS[0])[1]].length) gpGroup = (GGROUPS.find(g => C[g[1]].length) || GGROUPS[0])[0];
  const draw = () => {
    const [kind, key] = GGROUPS.find(g => g[0] === gpGroup);
    // the filter is what the cards / relics of this group say (an agent often writes ids like `steady` there and names like 稳健护理 in the
    // archetype list): one chip per value used, named by the archetype with that id or name (QA 2026-10-29: chips matched nothing, count 0)
    const archs = (kind === "card" || kind === "relic") ? [...new Set(C[key].map(c => c.archetype).filter(Boolean))] : [];
    if (gpArch !== "all" && !archs.includes(gpArch)) gpArch = "all";
    const types = [...new Set(C.cards.map(c => c.type).filter(Boolean))];
    let list = C[key];
    if (kind === "card" && gpType !== "all") list = list.filter(c => c.type === gpType);
    if ((kind === "card" || kind === "relic") && gpArch !== "all") list = list.filter(c => c.archetype === gpArch);
    const tgt = k => sc[k] ? `<small>${t("目标")} ${sc[k][0] === sc[k][1] ? sc[k][0] : sc[k].join("–")}</small>` : "";
    $("#screen").innerHTML = topbar(`<b>${t("内容")}</b>`, gpConfTag(st)) + `<div class="page" style="max-width:1180px">
      <div class="eyebrow">Step 3 · Content · ${esc(GP.game)}</div><h1 class="t">${esc(GP.title || t("内容"))}</h1>
      <p class="lede">${t("第一版要做的卡牌、遗物、敌人和事件。每一张都可以保留、要改或不要；要改的写一句，会原话转给 agent。")}</p>
      <div class="gcount">${GGROUPS.map(([k, ky, l]) => `<a class="card ${gpGroup === k ? "cur" : ""}" data-g="${k}"><b>${C[ky].length}</b><span>${t(l)}</span>${tgt(ky)}</a>`).join("")}</div>
      ${kind === "card" && types.length > 1 ? `<div class="chips">${[["all", t("全部类型")], ...types.map(x => [x, CTYPE[x] ? t(CTYPE[x]) : x])].map(([k, l]) => `<button class="chip ${gpType === k ? "cur" : ""}" data-t="${esc(k)}">${esc(l)}<span>${k === "all" ? C.cards.length : C.cards.filter(c => c.type === k).length}</span></button>`).join("")}</div>` : ""}
      ${(kind === "card" || kind === "relic") && archs.length ? `<div class="chips">${[["all", t("全部流派")], ...archs.map(a => [a, gpArchName(a)])].map(([k, l]) => `<button class="chip ${gpArch === k ? "cur" : ""}" data-a="${esc(k)}">${esc(l)}<span>${k === "all" ? C[key].length : C[key].filter(c => c.archetype === k).length}</span></button>`).join("")}</div>` : ""}
      <div class="ggrid">${list.map(x => tileHtml(kind, x)).join("") || `<div class="card empty" style="grid-column:1/-1">${t("这一类里还没有条目。")}</div>`}</div>
      <div class="card adconf"><div><b>${t(conf ? "内容表已确认" : "卡牌、遗物、敌人、事件都看完了？")}</b><p class="muted">${t(GP.review.mapping.state === "confirmed" ? "确认之后，agent 会按你的修改定稿，再问你要不要画卡图（会先说明发什么、发给谁），然后写开工单。" : "机制映射还没确认：建议先回“机制映射”页确认，再确认内容。")}</p></div>
        <button class="btn" id="gcok"${conf ? " disabled" : ""}>${t(conf ? "已确认" : "确认内容")}</button></div></div>`;
    $$(".gcount [data-g]").forEach(a => a.onclick = () => { gpGroup = a.dataset.g; gpType = "all"; gpArch = "all"; draw(); });
    $$(".chips [data-t]").forEach(b => b.onclick = () => { gpType = b.dataset.t; draw(); });
    $$(".chips [data-a]").forEach(b => b.onclick = () => { gpArch = b.dataset.a; draw(); });
    gpWire($("#screen"));
    const ok = $("#gcok"); if (ok) ok.onclick = async () => { if (await gpSave({}, "content")) route(); };
  };
  draw();
};
const pct = v => v == null ? "–" : Math.round(v * 100) + "%";
const num = v => v == null ? "–" : (Math.round(v * 10) / 10).toString();
const hbar = (v, max, cls = "") => `<span class="gbar ${cls}"><i style="width:${v == null || !max ? 0 : Math.max(2, Math.min(100, v / max * 100))}%"></i></span>`;
SCREENS.balance = async ([m], live) => {
  const B = await get("/api/balance" + (m || balM ? "?m=" + encodeURIComponent(m || balM) : "")); if (!live()) return;
  if (!B.m) { $("#screen").innerHTML = topbar(`<b>${t("平衡")}</b>`) + `<div class="page"><div class="doc"><div class="eyebrow">Balance</div><h1 class="t">${t("平衡")}</h1>
    <div class="card empty">${t("还没有平衡数据。构建时，实验室会让 agent 自动打很多局（模拟器），把胜率、每张卡的选取和出场、每个敌人要打几回合写在这里。")}${nextStep("balance")}</div></div></div>`; return; }
  balM = B.m;
  const sw = B.rounds.length > 1 ? `<div class="seg" style="white-space:nowrap">${B.rounds.map(r => `<button data-m="${esc(r.m)}" class="${r.m === B.m ? "cur" : ""}">${esc(r.name.split(" · ")[0])}</button>`).join("")}</div>` : "";
  const W = B.win_rate, cards = [...B.cards].sort((a, b) => (b.win_rate ?? -1) - (a.win_rate ?? -1));
  const flag = c => c.win_rate == null || W == null ? "" : c.win_rate - W >= .15 ? `<span class="gflag hi">${t("偏强")}</span>` : W - c.win_rate >= .15 ? `<span class="gflag lo">${t("偏弱")}</span>` : "";
  const pick = v => v == null ? "–" : v <= 1 ? pct(v) : num(v);
  const maxT = Math.max(0, ...B.enemies.map(e => e.avg_turns || 0)), maxD = Math.max(0, ...B.enemies.map(e => e.avg_damage_taken || 0));
  $("#screen").innerHTML = topbar(`<b>${t("平衡")}</b>`, sw) + `<div class="page"><div class="doc gdoc" style="max-width:980px">
    <div class="eyebrow">Balance · ${esc((B.rounds.find(r => r.m === B.m) || {}).name || B.m)}</div><h1 class="t">${t("平衡测试")}</h1>
    <p class="lede">${t("agent 用模拟器自动打的结果；数字说明哪里太强、太弱，最后还是要你自己玩一下手感。")}${B.at ? " · " + esc(fmtAt(B.at)) : ""}</p>
    <div class="gkpi"><div class="card"><b>${B.runs == null ? "–" : Math.round(B.runs)}</b><span>${t("模拟局数")}</span></div><div class="card"><b>${pct(W)}</b><span>${t("通关率")}</span></div>
      ${B.boss ? `<div class="card"><b>${pct(B.boss.win_rate)}</b><span>${t("打赢 {b} 的比例", { b: esc(B.boss.name || "Boss") })}</span></div><div class="card"><b>${num(B.boss.avg_turns)}</b><span>${t("Boss 战平均回合")}</span></div>` : ""}</div>
    ${cards.length ? `<h2 class="h">${t("卡牌")} <span class="muted">${t("按“在牌组里时的胜率”排序；竖线是整体通关率")}</span></h2>
    <div class="card"><table class="gtab gbal"><thead><tr><th>${t("卡牌")}</th><th>${t("被选进牌组")}</th><th>${t("每局打出")}</th><th>${t("在牌组里时的胜率")}</th></tr></thead><tbody>
      ${cards.map(c => `<tr><td><b>${esc(c.name)}</b> ${flag(c)}</td><td>${pick(c.picked)}</td><td>${num(c.played)}</td><td><span class="gwr">${hbar(c.win_rate, 1)}${W != null ? `<em style="left:${W * 100}%"></em>` : ""}</span>${pct(c.win_rate)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${B.enemies.length ? `<h2 class="h">${t("敌人")}</h2><div class="card"><table class="gtab gbal"><thead><tr><th>${t("敌人")}</th><th>${t("平均回合")}</th><th>${t("平均掉血")}</th></tr></thead><tbody>
      ${B.enemies.map(e => `<tr><td><b>${esc(e.name)}</b></td><td>${hbar(e.avg_turns, maxT)}${num(e.avg_turns)}</td><td>${hbar(e.avg_damage_taken, maxD, "warn")}${num(e.avg_damage_taken)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${B.notes.length ? `<h2 class="h">${t("说明")}</h2><div class="card gbox"><ul class="gnotes">${B.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}</div></div>`;
  $$("#screen .top .seg button[data-m]").forEach(b => b.onclick = () => { location.hash = "#balance/" + b.dataset.m; });
};

/* ------------------------------------------------------------ 开发状态 (every kind; 5_build/STATUS.yaml through /api/devstatus; read only: the agents write it with `gameanything status …`) */
const DS_STATE = { done: ["做到了", "ok"], partial: ["部分做到", "part"], todo: ["还没做", "todo"], broken: ["坏了", "bad"], regressed: ["以前好的，现在坏了", "bad"] };
const DS_SEV = { high: "严重", medium: "一般", low: "轻微" };
const DS_FB = { open: "还没处理", answered: "已回答", handled: "已处理" };
const DS_BY = { builder: "构建 agent 自查", playtester: "试玩 agent 验证过" };
let dsFilter = "all";
SCREENS.status = async (_, live) => {
  const D = await get("/api/devstatus"); if (!live()) return;
  let NB = ""; try { NB = typeof nowHtml === "function" ? nowHtml(await get("/api/now"), false) : ""; } catch (e) { NB = ""; }      // 「现在」 on top
  let FB = null; try { FB = await get("/api/feedback"); } catch (e) { FB = null; }                                                  // 「反馈和改进」
  if (!live()) return;
  const FP = fbPanel(FB);
  if (!D.exists) { $("#screen").innerHTML = topbar(`<b>${t("开发状态")}</b>`) + `<div class="page"><div class="doc dsdoc"><div class="eyebrow">Status</div><h1 class="t">${t("开发状态")}</h1>
    ${NB ? `<h2 class="h">${t("现在")}</h2>${NB}` : ""}<div class="card empty">${t("还没有开发状态。第一版开工时，agent 会把你提的每条要求列在这里，每一版做完后更新：做到了没有、谁验证的、有什么已知问题。")}${nextStep("status")}</div>${FP}</div></div>`;
    wireFb(); return; }
  const C = D.counts, chip = st => `<span class="dschip ds-${DS_STATE[st] ? DS_STATE[st][1] : "todo"}">${t(DS_STATE[st] ? DS_STATE[st][0] : st)}</span>`;
  const bad = C.broken + C.regressed;
  const fs = [["all", "全部", C.total], ["done", "做到了", C.done], ["partial", "部分做到", C.partial], ["todo", "还没做", C.todo], ["bad", "坏了", bad]].filter(([k, , n]) => k === "all" || n);
  if (!fs.some(([k]) => k === dsFilter)) dsFilter = "all";
  const shown = D.items.filter(x => dsFilter === "all" || (dsFilter === "bad" ? ["broken", "regressed"].includes(x.state) : x.state === dsFilter));
  const openFb = D.open_feedback.filter(f => f.state === "open");
  const rcDone = D.recheck.filter(x => x.this_round).length;
  $("#screen").innerHTML = topbar(`<b>${t("开发状态")}</b>`, D.updated ? `<span class="tag grey">${t("更新于 {t}", { t: esc(fmtAt(D.updated)) })}</span>` : "") + `<div class="page"><div class="doc dsdoc">
    <div class="eyebrow">Status${D.build ? " · " + esc(D.build) : ""} · ${esc(D.game)}</div><h1 class="t">${t("开发状态")}</h1>
    <p class="lede">${t("你提的每条要求现在做到哪了。agent 每一版做完后更新这一页；这里只能看，想改什么在对话里说。")}</p>
    ${NB ? `<h2 class="h">${t("现在")}</h2>${NB}` : ""}
    ${D.problems.length ? `<div class="errbar">${t("状态文件有 {n} 处格式问题，agent 会修好：", { n: D.problems.length })}${D.problems.map(esc).join(t("；"))}</div>` : ""}
    <div class="gkpi dskpi"><div class="card"><b>${C.done}/${C.total}</b><span>${t("做到了")}</span></div>
      <div class="card"><b>${C.partial + C.todo}</b><span>${t("还在做")}</span></div>
      <div class="card ${bad ? "dsbad" : ""}"><b>${bad}</b><span>${t("坏了 / 回归")}</span></div>
      <div class="card"><b>${C.issues}</b><span>${t("已知问题")}</span></div>
      ${D.recheck.length ? `<div class="card"><b>${rcDone}/${D.recheck.length}</b><span>${t("这一版复查过")}</span></div>` : ""}</div>
    <h2 class="h">${t("你的要求")} <span class="muted">${t("{n} 条", { n: C.total })}</span></h2>
    ${D.items.length ? `<div class="chips">${fs.map(([k, l, n]) => `<button class="chip ${dsFilter === k ? "cur" : ""}" data-f="${k}">${t(l)}<span>${n}</span></button>`).join("")}</div>
    <div class="adlist">${shown.map(x => `<div class="card adc dsitem ds-${DS_STATE[x.state] ? DS_STATE[x.state][1] : "todo"}"><div class="dsrow">${chip(x.state)}<b>${esc(x.text)}</b></div>
        <div class="gline">${x.since ? `<span>${t("从 {b} 起", { b: esc(x.since) })}</span>` : ""}${x.verified_by ? `<span class="chip">${t(DS_BY[x.verified_by])}</span>` : x.state === "done" ? `<span class="chip">${t("还没独立验证")}</span>` : ""}</div>
        ${x.evidence ? `<div class="adl">${t("依据")}</div><p>${esc(x.evidence)}</p>` : ""}</div>`).join("")}</div>` : `<div class="card empty">${t("还没列出要求。")}</div>`}
    ${D.regressions.length ? `<h2 class="h">${t("回归")} <span class="muted">${t("以前好的、后来坏了的")}</span></h2><div class="adlist">${D.regressions.map(g => `<div class="card adc ${g.fixed_in ? "" : "dsbadc"}">
        <div class="dsrow">${g.fixed_in ? `<span class="dschip ds-ok">${t("{b} 修好了", { b: esc(g.fixed_in) })}</span>` : `<span class="dschip ds-bad">${t("还没修好")}</span>`}<b>${esc(g.what)}</b></div>
        <div class="gline">${g.broke_in ? `<span>${t("在 {b} 坏的", { b: esc(g.broke_in) })}</span>` : ""}</div>${g.cause ? `<div class="adl">${t("原因")}</div><p>${esc(g.cause)}</p>` : ""}</div>`).join("")}</div>` : ""}
    ${D.known_issues.length ? `<h2 class="h">${t("已知问题")}</h2><div class="adlist">${D.known_issues.map(x => `<div class="card adc"><div class="dsrow"><span class="dschip ds-sev-${esc(x.severity)}">${t(DS_SEV[x.severity])}</span><b>${esc(x.text)}</b></div>
        <div class="gline">${x.since ? `<span>${t("从 {b} 起", { b: esc(x.since) })}</span>` : ""}</div>${x.plan ? `<div class="adl">${t("打算怎么办")}</div><p>${esc(x.plan)}</p>` : ""}</div>`).join("")}</div>` : ""}
    ${D.recheck.length ? `<h2 class="h">${t("每一版都要复查")} <span class="muted">${D.build ? t("{b}：{d}/{n} 复查过", { b: esc(D.build), d: rcDone, n: D.recheck.length }) : ""}</span></h2>
      <div class="card gbox"><ul class="dsrc">${D.recheck.map(x => `<li class="${x.this_round ? (x.last_result === "fail" ? "fail" : "pass") : "wait"}"><span class="c"></span><div><b>${esc(x.text)}</b>
        <small>${x.this_round ? t(x.last_result === "fail" ? "这一版没通过" : "这一版通过") : x.last_build ? t("上次在 {b} 复查", { b: esc(x.last_build) }) : t("还没复查过")}${x.note ? " · " + esc(x.note) : ""}</small></div></li>`).join("")}</ul></div>` : ""}
    ${D.open_feedback.length ? `<h2 class="h">${t("你说过的话")} <span class="muted">${openFb.length ? t("{n} 条还没处理", { n: openFb.length }) : t("都处理了")}</span></h2>
      <div class="adlist">${D.open_feedback.map(f => `<div class="card adc dsfb"><div class="dsrow"><span class="dschip ${f.state === "open" ? "ds-part" : "ds-ok"}">${t(DS_FB[f.state])}</span><span class="muted">${esc(fmtAt(f.at))}</span>
        ${EMBED && f.event ? `<button class="btn ghost sm" data-ev="${esc(f.event)}">${t("在对话里看")}</button>` : ""}</div><p>${esc(f.text)}</p></div>`).join("")}</div>` : ""}
    ${D.decisions.length ? `<h2 class="h">${t("定下来的事")}</h2><div class="card gbox"><ul class="gnotes">${D.decisions.map(x => `<li>${esc(x.text)} <span class="muted">${esc(fmtAt(x.at))}</span></li>`).join("")}</ul></div>` : ""}
    ${FP}
  </div></div>`;
  $$("#screen .chips [data-f]").forEach(b => b.onclick = () => { dsFilter = b.dataset.f; SCREENS.status(_, live); });
  wireFb();
};
function wireFb() { $$("#screen [data-ev]").forEach(b => b.onclick = () => window.parent.postMessage({ type: "m2w-event", id: b.dataset.ev }, location.origin)); }

/* 「反馈和改进」 (feedback.py through /api/feedback): her feedback records and the loop's numbers (docs/feedback-loop.md 6). Her words as written. */
const FB_STATE = { new: ["刚记下", "todo"], interpreted: ["读懂了", "todo"], confirming: ["等你确认意思", "part"], answered: ["回答了", "ok"], dropped: ["不做了", "todo"],
  open: ["要改", "todo"], in_progress: ["在改", "part"], fixed: ["改好了，等你看", "part"], verifying: ["等你看对比图", "part"], closed: ["你确认了", "ok"], reopened: ["又出现了", "bad"] };
const FB_CLASS = { bug: "坏了", taste: "不对味", request: "要加 / 要改", question: "问题" };
const fbPct = x => x && x.n ? `${x.k}/${x.n} · ${Math.round(x.rate * 100)}%` : "—";
function fbPanel(F) {
  if (F && !F.study) return F.profile_on || F.exists ? `<div class="acts"><a class="btn ghost sm" href="#prefs">${t("我的偏好")}${F.profile_on ? ` · ${F.profile_on}` : ""}</a></div>` : "";   // study mode off: no panel (study.py)
  if (!F || !F.records || !F.records.length) return F && F.profile_on ? `<h2 class="h">${t("反馈和改进")}</h2><div class="card empty">${t("还没有反馈记录。你在对话或试玩页里说的每一条意见，都会在这里记成一条：你的原话、agent 的理解、改到哪了。")} <a class="btn ghost sm" href="#prefs">${t("我的偏好")}</a></div>` : "";
  const M = F.metrics, V = M.verification, H = M.rule_hits, mx = Math.max(1, ...M.versions.map(v => v.complaints));
  const kpi = `<div class="gkpi dskpi"><div class="card ${M.rfr_strict.k ? "dsbad" : ""}"><b>${esc(fbPct(M.rfr_strict))}</b><span>${t("同一件事说了第二遍（同一个地方）")}</span></div>
      <div class="card"><b>${esc(fbPct(M.rfr_loose))}</b><span>${t("同一类意见又出现")}</span></div>
      <div class="card"><b>${M.complaints}</b><span>${t("条意见（{n} 条记录）", { n: M.records })}</span></div>
      <div class="card"><b>${V.paired}/${V.fixed}</b><span>${t("改好的在同一画面复拍过")}</span></div>
      <div class="card"><b>${V.her_ok}</b><span>${t("你确认改好了")}</span></div>
      <div class="card"><b>${H.applicable ? `${H.hits}/${H.applicable}` : "—"}</b><span>${t("经验起了作用")}</span></div>
      ${M.rounds_to_accept ? `<div class="card"><b>${esc(M.rounds_to_accept.accepted)}</b><span>${t("你接受的版本（第 {n} 版）", { n: M.rounds_to_accept.rounds || "?" })}</span></div>` : ""}</div>`;
  const bars = M.versions.length ? `<div class="card gbox fbbars">${M.versions.map(v => `<div class="fbbar"><span class="fbm">${esc(v.m)}</span><span class="fbtrack"><i style="width:${v.complaints / mx * 100}%"></i>${v.repeats_loose ? `<i class="rep" style="width:${v.repeats_loose / mx * 100}%"></i>` : ""}</span>
      <span class="muted">${t("{n} 条", { n: v.complaints })}${v.repeats_loose ? " · " + t("{n} 条以前说过", { n: v.repeats_loose }) : ""}</span></div>`).join("")}</div>` : "";
  const rows = F.records.slice(0, 40).map(r => { const st = FB_STATE[r.state] || [r.state, "todo"];
    const where = [r.milestone, r.t != null ? `${Math.floor(r.t / 60)}:${String(Math.floor(r.t % 60)).padStart(2, "0")}` : "", r.target].filter(Boolean).join(" · ");
    return `<div class="card adc fbrec ds-${st[1]}"><div class="dsrow"><span class="dschip ds-${st[1]}">${t(st[0])}</span><b>“${esc(r.words)}”</b></div>
      <div class="gline">${where ? `<span>${esc(where)}</span>` : ""}<span class="chip">${esc(F.kinds[r.kind] || r.kind)}</span>${r.class ? `<span class="chip">${t(FB_CLASS[r.class])}</span>` : ""}
        ${r.repeat_of.length ? `<span class="chip fbrep">${t("你以前说过（{ids}）", { ids: esc(r.repeat_of.join(", ")) })}</span>` : ""}${r.status_item ? `<span>→ ${esc(r.status_item)}</span>` : ""}
        ${EMBED && r.event ? `<button class="btn ghost sm" data-ev="${esc(r.event)}">${t("在对话里看")}</button>` : ""}</div>
      ${r.interpretation ? `<div class="adl">${t("agent 的理解")}</div><p>${esc(r.interpretation)}</p>` : r.state === "new" ? `<p class="muted">${t("agent 还没写它的理解")}</p>` : ""}
      ${r.frame || r.pair ? `<div class="fbimgs">${r.frame && !r.pair ? `<a href="${esc(r.frame)}" target="_blank" rel="noopener"><img src="${esc(r.frame)}" loading="lazy" alt=""></a>` : ""}${r.pair ? `<a href="${esc(r.pair)}" target="_blank" rel="noopener"><img src="${esc(r.pair)}" loading="lazy" alt=""><small>${t("左：改之前 · 右：同一画面改之后")}</small></a>` : ""}</div>` : ""}</div>`; }).join("");
  return `<h2 class="h">${t("反馈和改进")} <span class="muted">${t("让你不用把同一件事说第二遍")}</span>${F.study_badge ? ` <span class="tag grey">${t("研究模式开着")}</span>` : ""} <a class="btn ghost sm" href="#prefs">${t("我的偏好")}${F.profile_on ? ` · ${F.profile_on}` : ""}</a></h2>
    ${kpi}${bars}<div class="adlist">${rows}</div>${F.records.length > 40 ? `<p class="muted">${t("还有 {n} 条更早的", { n: F.records.length - 40 })}</p>` : ""}`;
}

/* ------------------------------------------------------------ 我的偏好 (#prefs; profile.py through /api/profile): her own taste, private, every entry editable */
const PF_CONF = { low: "还不太确定", medium: "比较确定", high: "很确定" };
const PF_BY = { retrospective: "agent 从你的意见里总结的", resident: "agent 记下的", her: "你自己写的" };
const PF_MODES = { memory: "回忆", adaptation: "改编", feature: "功能", gameplay: "玩法" };
let pfEdit = null;
SCREENS.prefs = async (_, live) => {
  let P; try { P = await get("/api/profile"); } catch (e) { if (!live()) return; $("#screen").innerHTML = topbar(`<b>${t("我的偏好")}</b>`) + `<div class="page"><div class="doc"><div class="card empty">${t("只有项目的所有者能看自己的偏好。")}</div></div></div>`; return; }
  if (!live()) return;
  const scope = e => [...(e.modes || []).map(m => t(PF_MODES[m] || m)), ...(e.games || []).map(g => P.games[g] || g), ...(e.projects || [])].join(t("、")) || t("所有项目");
  const src = e => (e.from || []).map(x => x.here ? `<a class="chip" href="#status">${esc(x.record)}${x.words ? " “" + esc(x.words.slice(0, 40)) + "”" : ""}</a>`
      : `<span class="chip">${esc(x.project)} · ${esc(x.record)}${x.words ? " “" + esc(x.words.slice(0, 40)) + "”" : ""}</span>`).join(" ") || `<span class="muted">${t("你自己加的")}</span>`;
  const row = e => pfEdit === e.id ? `<div class="card adc pfent" data-id="${esc(e.id)}"><textarea class="pft">${esc(e.text)}</textarea><textarea class="pfen" placeholder="English (optional)">${esc(e.text_en || "")}</textarea>
      <div class="gline">${Object.keys(PF_MODES).map(m => `<label class="chip"><input type="checkbox" class="pfm" value="${m}" ${(e.modes || []).includes(m) ? "checked" : ""}> ${t(PF_MODES[m])}</label>`).join("")}</div>
      <div class="acts"><button class="btn sm" data-save="${esc(e.id)}">${t("保存")}</button><button class="btn ghost sm" data-cancel>${t("取消")}</button></div></div>`
    : `<div class="card adc pfent ${e.on ? "" : "off"}" data-id="${esc(e.id)}"><div class="dsrow"><span class="dschip ${e.on ? "ds-ok" : ""}">${t(e.on ? "在用" : "关着")}</span><b>${esc(e.shown)}</b></div>
      <div class="gline"><span>${t("用在：{s}", { s: esc(scope(e)) })}</span><span class="chip">${t(PF_CONF[e.confidence] || e.confidence || "")}</span>${e.status === "candidate" ? `<span class="chip">${t("候选：你打开以后才会用")}</span>` : ""}
        <span>${e.last_used ? t("上次用到 {t}", { t: esc(fmtAt(e.last_used)) }) : t("还没用到过")}${e.used ? " · " + t("{n} 次", { n: e.used }) : ""}</span></div>
      <div class="adl">${t("从哪来")} · ${t(PF_BY[e.by] || "")}</div><p>${src(e)}</p>
      <div class="acts"><button class="btn sm ${e.on ? "ghost" : ""}" data-tog="${esc(e.id)}" data-on="${e.on ? 0 : 1}">${t(e.on ? "关掉" : "打开")}</button><button class="btn ghost sm" data-edit="${esc(e.id)}">${t("改")}</button><button class="btn ghost sm" data-del="${esc(e.id)}">${t("删掉")}</button></div></div>`;
  $("#screen").innerHTML = topbar(`<b>${t("我的偏好")}</b>`) + `<div class="page"><div class="doc dsdoc"><div class="eyebrow">Preferences</div><h1 class="t">${t("我的偏好")}</h1>
    <p class="lede">${t("agent 从你的意见里学到的你的口味。每次开工前，只有「在用」并且适用于这个项目的几条会交给构建 agent。只存在这台电脑上，不会分享给别人，也不会写进公开的经验里。")}</p>
    <div class="adlist">${P.entries.map(row).join("") || `<div class="card empty">${t("还没有偏好。agent 发现你在不同的地方说了同一类意见，会在这里提一条候选；你也可以自己写。")}</div>`}</div>
    <h2 class="h">${t("自己加一条")}</h2><div class="card adc"><textarea id="pfnew" placeholder="${esc(t("例如：场景要丰富、精致，不要空荡荡的"))}"></textarea><div class="acts"><button class="btn sm" id="pfadd">${t("加上")}</button></div></div></div></div>`;
  const send = async b => { const r = await post("/api/profile", b); if (!r.ok) return toast(r.error || t("没能保存")); pfEdit = null; SCREENS.prefs(_, live); };
  $$("#screen [data-tog]").forEach(b => b.onclick = () => send({ op: "toggle", id: b.dataset.tog, on: b.dataset.on === "1" }));
  $$("#screen [data-edit]").forEach(b => b.onclick = () => { pfEdit = b.dataset.edit; SCREENS.prefs(_, live); });
  $$("#screen [data-cancel]").forEach(b => b.onclick = () => { pfEdit = null; SCREENS.prefs(_, live); });
  $$("#screen [data-del]").forEach(b => b.onclick = () => { if (confirm(t("删掉这条偏好？"))) send({ op: "remove", id: b.dataset.del }); });
  $$("#screen [data-save]").forEach(b => b.onclick = () => { const c = b.closest(".pfent");
    send({ op: "set", id: b.dataset.save, text: $(".pft", c).value, text_en: $(".pfen", c).value, modes: $$(".pfm", c).filter(x => x.checked).map(x => x.value) }); });
  const add = $("#pfadd"); if (add) add.onclick = () => { const v = $("#pfnew").value.trim(); if (!v) return toast(t("先写下你的偏好")); send({ op: "add", text: v }); };
};

/* ------------------------------------------------------------ 工作台 / Now (/api/now, live.py: what the background build does right now; polled while open) */
const NOW_ST = { running: "正在做", waiting_seat: "排队等位置", blocked: "暂时开始不了", preparing: "在准备环境", done: "做好了", ended: "停了", stopped: "到时间停了", interrupted: "中断了", failed: "没能开始" };
const NOW_KIND = { edit: "改", tool: "做", look: "看", wait: "等", say: "说", pause: "停", error: "错", plan: "列" };
const nowHm = n => { n = Math.round(n || 0); const h = Math.floor(n / 60), m = n % 60; return h ? t("{h} 小时 {m} 分", { h, m }) : t("{m} 分钟", { m }); };
function nowBanner(N) {
  const B = N && N.build, out = [];
  if (N && N.paused) out.push(`<div class="nalert pause">${N.paused.resets_hm ? t("agent 的用量到上限了，大约 {t} 恢复；所有后台 agent 都在等。", { t: esc(N.paused.resets_hm) }) : t("agent 的用量到上限了，所有后台 agent 都在等额度恢复。")}</div>`);
  if (B && B.alert && !(N.paused && B.alert.kind === "pause")) out.push(`<div class="nalert ${esc(B.alert.kind)}">${esc(B.alert.text)}</div>`);
  return out.join("");
}
/* full: the whole panel; else the short 「现在」 box on top of the 开发状态 page */
function nowHtml(N, full) {
  const B = N && N.build;
  if (!B) return full ? `${nowBanner(N)}<div class="card empty">${t("现在没有后台构建在跑。开工以后，这里会实时显示构建 agent 在做什么、做到第几轮、最新的截图。")}</div>`
    + (N && N.resident ? `<div class="card nres"><b>${t("agent 正在回复你")}</b>${N.resident.now ? `<p>${esc(N.resident.now)}</p>` : ""}</div>` : "") : "";
  const run = B.state === "running", est = B.est_h ? (B.est_h[0] === B.est_h[1] ? t("预计 {a} 小时", { a: B.est_h[0] }) : t("预计 {a}–{b} 小时", { a: B.est_h[0], b: B.est_h[1] })) : "";
  const time = [B.elapsed_min != null ? t("已进行 {t}", { t: nowHm(B.elapsed_min) }) : "", est, B.wall_h ? t("最多 {h} 小时", { h: B.wall_h }) : ""].filter(Boolean).join(" · ");
  const pct = B.est_h && B.elapsed_min != null ? Math.min(100, B.elapsed_min / 60 / B.est_h[1] * 100) : null;
  const head = `<div class="nhead"><span class="nstate ${run ? "on" : ""}">${run ? `<span class="ring"></span>` : ""}${t(NOW_ST[B.state] || "正在做")}</span>
    <b>${t("后台构建 · {m}", { m: esc(B.m) })}</b><span class="muted">${esc(B.where || "")}${B.provider ? " · " + esc(B.provider) : ""}</span></div>`;
  const now = B.now && run ? `<div class="nnow"><small>${t("现在")}</small><div>${esc(B.now)}</div><span class="muted">${B.now_at ? esc(fmtHM(B.now_at)) : ""}${B.quiet_min >= 3 ? " · " + t("{n} 分钟没有新动静", { n: B.quiet_min }) : ""}</span></div>` : "";
  const meters = `<div class="nmeter"><div><small>${t("试玩评审")}</small><b>${B.round ? t("第 {k} / {n} 轮", { k: B.round, n: B.max_rounds }) : t("还没开始（最多 {n} 轮）", { n: B.max_rounds || 0 })}</b></div>
    <div><small>${t("时间")}</small><b>${esc(time)}</b>${pct != null ? `<span class="nbar"><i style="width:${pct}%"></i></span>` : ""}</div></div>`;
  if (!full) return `<div class="card nowbox">${nowBanner(N)}${head}${now}${meters}<div class="foot"><a class="btn sm" href="#now">${t("打开工作台")}</a></div></div>`;
  const shots = (B.shots || []).length ? `<h2 class="h">${t("最新的画面")}</h2><div class="nshots">${B.shots.map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener"><img src="${esc(s.url)}" loading="lazy" alt=""><span>${esc(s.label || "")} ${esc(fmtHM(s.at))}</span></a>`).join("")}</div>` : "";
  const DS = typeof DS_STATE !== "undefined" ? DS_STATE : {};
  const items = (B.items || []).length ? `<h2 class="h">${t("你的要求")} <span class="muted">${t("{d} / {n} 做到了", { d: B.items.filter(x => x.state === "done").length, n: B.items.length })}</span></h2>
    <div class="card nitems">${B.items.map(x => `<div class="nit"><span class="dschip ds-${DS[x.state] ? DS[x.state][1] : "todo"}">${t(DS[x.state] ? DS[x.state][0] : "还没做")}</span><span>${esc(x.text)}</span></div>`).join("")}</div>` : "";
  const tl = (B.timeline || []).length ? `<h2 class="h">${t("它刚才做了什么")}</h2><div class="card ntl">${B.timeline.map(x => `<div class="ntr k-${esc(x.kind)}"><span class="muted">${esc(fmtHM(x.at))}</span><i>${t(NOW_KIND[x.kind] || "做")}</i><span>${esc(x.text)}${x.n > 1 ? ` <span class="muted">×${x.n}</span>` : ""}</span></div>`).join("")}</div>` : "";
  return `${nowBanner(N)}<div class="card nowbox">${head}${now}${meters}</div>${shots}${items}${tl}`;
}
/* the live game picture (liveview.py): asked once per lab build; after her yes an iframe with noVNC in view-only mode, served by this
   UI itself (/live/…); she can switch it off. Native builds: the newest picture of the game window instead (in the pictures above). */
const liveUrl = () => { const B_ = window.M2W_BASE || ""; return `${B_}/live/novnc/vnc.html?autoconnect=1&view_only=1&resize=scale&reconnect=1&reconnect_delay=2000&path=${encodeURIComponent((B_ + "/live/websockify").replace(/^\//, ""))}`; };
function liveBox(N) {
  const L = N && N.live; if (!L || !L.possible) return "";
  if (!L.on) return `<div class="card nlive off"><b>${t("游戏的实时画面")}</b><p class="muted">${t("只在你自己的电脑上能看，不对外公开；默认只能看、不能点。")}</p>
    <button class="btn sm" data-live="on">${t("打开实时画面")}</button></div>`;
  return `<div class="card nlive"><div class="nlhead"><b>${t("游戏的实时画面")}</b><span class="muted">${t("只能看、不能点")}</span><button class="btn ghost sm" data-live="off">${t("关掉")}</button></div>
    <iframe src="${esc(liveUrl())}" title="live" allow="fullscreen"></iframe></div>`;
}
SCREENS.now = async (_, live) => {
  let lv = null; $("#screen").innerHTML = "";
  const draw = N => {
    if (!$("#nowbody")) $("#screen").innerHTML = topbar(`<b>${t("工作台")}</b>`) + `<div class="page"><div class="doc nowdoc"><div class="eyebrow">Now</div><h1 class="t">${t("工作台")}</h1>
      <p class="lede">${t("后台在做什么，这里自己会更新，不用等 agent 汇报。")}</p><div id="nowlive"></div><div id="nowbody"></div></div></div>`;
    $("#nowbody").innerHTML = nowHtml(N, true);
    const sig = JSON.stringify(N.live || null);
    if (sig !== lv) { lv = sig; $("#nowlive").innerHTML = liveBox(N);
      $$("#nowlive [data-live]").forEach(b => b.onclick = async () => { b.disabled = true; await post("/api/live", { on: b.dataset.live === "on" }); try { draw(await get("/api/now")); } catch (e) {} }); }
  };
  draw(await get("/api/now")); if (!live()) return;
  const tick = async () => { if (!live()) return; try { const N = await get("/api/now"); if (live()) draw(N); } catch (e) { /* server restarting */ } setTimeout(tick, 5000); };
  setTimeout(tick, 5000);
};

route();          // last: the screens above must all be defined before the first route
