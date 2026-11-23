/* First run and orientation (../onboard.py): the welcome page (no project yet, or 「所有项目」), the 3-step new-project wizard with the
   per-game check and the 「在哪里做」 choice (/api/onboard/games: each game's `modes`, buildmode.py), the first-visit coach marks (the 「?」 in the conversation header reopens them) and the flow stepper above
   the workspace (/api/shell `flow`). Loaded after manage.js and before shell.js; uses their helpers ($, esc, icon, get, post, upload, toast,
   dialog, switchTo, importDialog, ws) when called. All text goes through t(). */
"use strict";
const KIND_EXAMPLE = { memory: "例：把婚礼那天做成星露谷里的一段剧情", feature: "例：在农场里加一台能点歌的唱片机",
  adaptation: "例：把小说里的城堡一块一块建进 Minecraft", gameplay: "例：把读博五年做成一套卡牌玩法" };
const KIND_DESC = { memory: "从照片、视频、文字开始，做成一段回忆的游戏内容", feature: "从你想要的东西开始：加衣服、唱片机、小游戏……",
  adaptation: "把你喜欢的小说、影视剧、动漫做进游戏：先抽取场景和地点，你确认方案和预览图，再开始建",
  gameplay: "把一段经历（读博、创业、带娃……）做成游戏里的一套玩法：先和你定下“经历 → 机制”的映射，再出卡牌、遗物、敌人，最后跑平衡测试" };
const KIND_ORDER = ["memory", "adaptation", "feature", "gameplay"];   // the wizard's cards: the two main kinds (memory, adaptation) on the first row
const KIND_REC = { memory: "stardew", feature: "stardew", adaptation: "minecraft", gameplay: "slay_the_spire" };   // the game the wizard suggests
const TITLE_PH = { memory: "例如：Anna 的毕业旅行", feature: "例如：农场唱片机", adaptation: "例如：霍格沃茨的第一天", gameplay: "例如：读博模拟器" };
const lsGet = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

/* ------------------------------------------------------------ welcome page */
let WELCOME = null;
async function showWelcome() {
  let W; try { W = await get("/api/welcome"); } catch (e) { return toast(t("服务没有回应（{s}）", { s: "welcome" })); }
  useGames(W.game_info);
  let el = $("#welcome"); if (!el) { el = document.createElement("div"); el.id = "welcome"; el.className = "welcome"; document.body.append(el); }
  WELCOME = { W, paint: () => paintWelcome(el, W) }; WELCOME.paint(); el.scrollTop = 0;
  document.body.classList.add("welcoming");
}
function closeWelcome() { const el = $("#welcome"); if (el) el.remove(); WELCOME = null; document.body.classList.remove("welcoming"); }
function exampleCard(x, i) {
  const kn = t(KIND_NAME[x.kind] || KIND_NAME.memory);
  return `<figure class="wl-card" data-ex="${i}"><div class="media">${x.image ? `<img src="${esc(x.image)}" alt="" loading="lazy">` : ""}
      ${x.video ? `<button class="play" data-video="${esc(x.video)}" data-poster="${esc(x.image || "")}" title="${esc(t("播放"))}">${icon("play", "width:26px;height:26px")}</button>` : x.source === "bundled" ? `<span class="still">${t("示意图")}</span>` : ""}</div>
    <figcaption><b>${esc(x.source === "bundled" ? t(x.title) : x.title)}</b><small>${esc(x.game_name)} · ${esc(kn)}</small></figcaption></figure>`;
}
function paintWelcome(el, W) {
  const ps = W.projects || [];
  el.innerHTML = `<div class="wl">
    <header class="wl-top"><div class="brand"><span class="logo"><i></i></span><span>Game<b>Anything</b></span></div><span class="sp"></span>
      ${W.open ? `<button class="btn ghost" id="wlback">${t("回到项目")}</button>` : ""}${langSwitchHtml()}</header>
    <section class="wl-hero">
      <h1>${t("把你的回忆、喜欢的作品和亲身经历，做成能在真实游戏里玩的内容。")}</h1>
      <p class="lede">${t("你放进素材、说说想法，agent 来设计和构建；每一步都先给你看。照片和文件都留在这台电脑上。")}</p>
      <div class="wl-cta"><button class="btn big" id="wlstart">${icon("plus", "width:18px;height:18px")}${ps.length ? t("新项目") : t("开始第一个项目")}</button>
        <button class="lnk" id="wlimport">${t("或者导入一个之前导出的项目")}</button></div>
    </section>
    ${(W.examples || []).length ? `<section class="wl-sec"><h2>${t("做出来的样子")}</h2><div class="wl-ex">${W.examples.map(exampleCard).join("")}</div></section>` : ""}
    ${ps.length ? `<section class="wl-sec"><h2>${t("你的项目")}</h2><div class="wl-projects">${ps.map(p => `<button class="wl-proj ${p.current ? "cur" : ""}" data-pid="${esc(p.id)}">
        <span class="dot ${esc(p.kind)}"></span><span class="tx"><b>${esc(p.title)}</b><small>${esc(GAME_NAME[p.game] || GAME_NAME.stardew)} · ${t(KIND_NAME[p.kind] || KIND_NAME.memory)}${p.last_opened ? " · " + fmtAt(p.last_opened) : ""}</small></span>
        ${p.current ? `<span class="rec">${t("正在打开")}</span>` : icon("send", "color:var(--mute)")}</button>`).join("")}</div></section>`
      : `<section class="wl-sec"><h2>${t("怎么进行")}</h2><ol class="wl-how">
        <li><b>${t("选类型和游戏")}</b><span>${t("回忆、功能、改编或玩法；做进哪个游戏")}</span></li>
        <li><b>${t("放素材，在对话里说")}</b><span>${t("agent 会问几个问题，把它的理解给你确认")}</span></li>
        <li><b>${t("确认方案，看试玩")}</b><span>${t("你点了开工才会开始；做好后看录像、提意见，最后带回家")}</span></li></ol></section>`}
    <p class="wl-priv">${icon("lock", "width:13px;height:13px")}${t("所有东西都留在这台电脑上；要发给模型之前，会先问你。")}</p></div>`;
  wireLangSwitch(el);
  $("#wlstart", el).onclick = () => newProjectDialog();
  $("#wlimport", el).onclick = () => importDialog();
  const back = $("#wlback", el); if (back) back.onclick = closeWelcome;
  $$("[data-pid]", el).forEach(b => b.onclick = () => b.classList.contains("cur") ? closeWelcome() : switchTo(b.dataset.pid));
  $$(".play", el).forEach(b => b.onclick = () => {
    const v = document.createElement("video"); v.src = b.dataset.video; v.controls = true; v.autoplay = true; v.muted = true; v.playsInline = true; v.preload = "metadata";
    if (b.dataset.poster) v.poster = b.dataset.poster;
    const m = b.closest(".media"); m.innerHTML = ""; m.append(v); v.play().catch(() => {});
  });
}

/* one 「在哪里做」 choice (buildmode.options): the wizard's step 3 and the project menu's dialog (manage.js). Greyed ones say why. */
function modeOptHtml(o, M, on) {
  const rec = M.recommended === o.mode;
  return `<div class="opt md ${on ? "on" : ""} ${o.ok ? "" : "off"}" data-mode="${o.mode}" ${o.ok ? "" : 'aria-disabled="true"'}><span class="k">${on ? icon("check", "width:12px;height:12px") : ""}</span><div>
      <b>${t(o.name)}</b>${rec ? `<span class="rec">${t("建议")}</span><small class="why">${esc(t(M.why, M.vars))}</small>` : ""}
      <small>${o.ok ? esc(t(o.note)) : `<span class="no">${esc(t(o.why, o.vars))}</span>`}</small></div></div>`;
}

/* ------------------------------------------------------------ new-project wizard (4 steps: kind, game, where builds run, name) */
let CHECKS = null;                // /api/onboard/games, kept for the page's life (the server caches it for a minute)
function newProjectDialog(preKind) {
  const S = { step: 1, kind: preKind || "memory", game: null, mode: null, modeFor: null, files: [], rejected: [], title: "", busy: false };
  const d = dialog(`<div id="wz"></div>`, true); $(".mbox", d).classList.add("wiz");
  d.onclick = null;                               // a click beside the wizard does not throw away what was picked (Esc and 取消 still close it)
  let CHECK_ERR = null, retried = false;
  const checkWait = () => CHECK_ERR
    ? `<div class="chk wait">${t("没能检查这台电脑")}（${esc(CHECK_ERR)}）。<button class="btn sm ghost" id="wzre2">${t("重新检查")}</button></div>`
    : `<div class="chk wait"><span class="ring"></span>${t("正在检查这台电脑…")}</div>`;
  let stills = { memory: "/examples/memory.svg", feature: "/examples/feature.svg", adaptation: "/examples/adaptation.svg", gameplay: "/examples/gameplay.svg" };
  get("/api/welcome").then(W => {                 // a real result picture of that kind, when the user's own projects have one
    useGames(W.game_info); stills = { ...stills, ...(W.kind_stills || {}) };
    // fixed per kind (kind_stills/ in the project list folder, else the drawings): never swapped for whatever project was opened last
    if (S.step === 1 && d.isConnected) draw();
  }).catch(() => {});
  const head = () => `<div class="wz-steps">${["类型", "游戏", "在哪里做", "名字和素材"].map((s, i) => `<span class="${i + 1 === S.step ? "on" : i + 1 < S.step ? "done" : ""}"><i>${i + 1 < S.step ? icon("check", "width:11px;height:11px") : i + 1}</i>${t(s)}</span>`).join("")}</div>`;
  const checkRow = c => {
    const cls = c.ok === true ? "ok" : c.ok === false && !c.optional ? "bad" : "na";
    return `<li class="${cls}"><i>${c.ok === true ? "✓" : c.ok === false ? "✗" : "–"}</i><span>${esc(t(c.text, c.vars))}${c.fix && c.ok === false ? `<small>${esc(t(c.fix, c.vars))}</small>` : ""}</span></li>`;
  };
  const gameOpt = g => {
    const C = CHECKS && CHECKS.games.find(x => x.id === g);
    return `<div class="opt gm ${S.game === g ? "on" : ""}" data-game="${g}"><span class="k">${S.game === g ? icon("check", "width:12px;height:12px") : ""}</span><div>
      <b>${esc(GAME_NAME[g])}</b>${KIND_REC[S.kind] === g ? `<span class="rec">${t("建议")}</span>` : ""}${C ? `<span class="rdy ${C.ready ? "ok" : ""}">${C.ready ? t("可以构建") : t("还差一步")}</span>` : ""}
      <small>${t(GAME_DESC[g] || "")}</small>
      ${C ? `<ul class="chk">${C.checks.map(checkRow).join("")}</ul>` : checkWait()}</div></div>`;
  };
  const sysName = s => ({ linux: "Linux", mac: "macOS", windows: "Windows" })[s] || s;
  const modesOf = () => { const C = CHECKS && CHECKS.games.find(x => x.id === S.game); return C && C.modes; };
  function pickMode() {                           // the recommended one, once per game (a choice the user made for this game is kept)
    const M = modesOf(); if (!M) return;
    const ok = m => M.options.some(o => o.mode === m && o.ok);
    if (S.modeFor !== S.game || (S.mode && !ok(S.mode))) { S.mode = M.recommended; S.modeFor = S.game; }
  }
  function draw() {
    const box = $("#wz", d); let body = "", foot = "";
    if (S.step === 1) {
      body = `<h3>${t("想做哪一种？")}</h3><p class="sub">${t("选一个最接近的；之后在对话里还可以细说。")}</p>
        <div class="kgrid">${KIND_ORDER.map(k => `<button class="kcard ${S.kind === k ? "on" : ""}" data-kind="${k}"><img src="${esc(stills[k] || "")}" alt="">
          <span class="tx"><b>${t(KIND_NAME[k])}</b><em>${t(KIND_EXAMPLE[k])}</em><small>${t(KIND_DESC[k])}</small></span></button>`).join("")}</div>`;
      foot = `<button class="btn" id="wznext">${t("下一步")}</button><button class="btn ghost" data-close>${t("取消")}</button>`;
    } else if (S.step === 2) {
      if (!S.game) S.game = KIND_REC[S.kind] || "stardew";
      body = `<h3>${t("在哪个游戏里做？")}</h3><p class="sub">${CHECKS ? t("这台电脑：{s}", { s: sysName(CHECKS.system) }) : CHECK_ERR ? t("没能检查这台电脑") : t("正在检查这台电脑…")}
          ${CHECKS || CHECK_ERR ? ` · <button class="lnk" id="wzre">${t("重新检查")}</button>` : ""}</p>
        <div class="glist">${Object.keys(GAME_NAME).map(gameOpt).join("")}</div>
        <p class="fine">${t("没准备好也没关系：可以先建项目、放素材、定方案，开工前再装好。")}</p>`;
      foot = `<button class="btn" id="wznext">${t("下一步")}</button><button class="btn ghost" id="wzprev">${t("上一步")}</button>`;
    } else if (S.step === 3) {
      pickMode(); const M = modesOf();
      body = `<h3>${t("在哪里做？")}</h3><p class="sub">${t("构建和试玩在哪里进行；之后在项目菜单里还能改。")}</p>
        ${M ? `<div class="glist">${M.options.map(o => modeOptHtml(o, M, S.mode === o.mode)).join("")}</div>${M.recommended ? "" : `<p class="fine">${esc(t(M.why))}</p>`}`
            : checkWait()}`;
      foot = `<button class="btn" id="wznext">${t("下一步")}</button><button class="btn ghost" id="wzprev">${t("上一步")}</button>`;
    } else {
      body = `<h3>${t("给项目起个名字")}</h3>
        <label class="fld">${t("项目名字")}<input class="inp" id="ptitle" maxlength="80" placeholder="${esc(t(TITLE_PH[S.kind]))}" value="${esc(S.title)}"></label>
        <div class="fld">${t("第一批素材（可选）")}</div>
        <label class="drop" id="wzdrop"><input type="file" id="wzfile" multiple hidden accept="${esc(upExts().map(x => "." + x).join(","))}">${icon("upload")}<span>${t("把文件拖到这里，或点这里选择")}</span></label>
        <div class="wzfiles">${S.files.map((f, i) => `<span class="chip">${icon("clip", "width:12px;height:12px")}${esc(f.name)}<button data-rm="${i}" title="${esc(t("去掉"))}">×</button></span>`).join("")}</div>
        ${S.rejected.length ? `<div class="bad" id="wzrej">${t("这些文件没有放进来：")}<ul style="margin:4px 0 0;padding-left:18px">${S.rejected.map(r => `<li>${esc(r.name)}${t("：")}${esc(r.why)}</li>`).join("")}</ul></div>` : ""}
        <p class="fine">${t("照片、视频、文字都可以；也可以建好之后再放。所有东西都留在这台电脑上。")}<br>${t("能放的文件：{x}", { x: upExts().map(x => x.toUpperCase()).join(" · ") })}</p><div id="wzjob"></div>`;
      foot = `<button class="btn" id="wzgo">${t("创建项目")}</button><button class="btn ghost" id="wzprev">${t("上一步")}</button>`;
    }
    box.innerHTML = head() + `<div class="wz-body">${body}</div><div class="foot">${foot}</div>`;
    $$("[data-close]", box).forEach(b => b.onclick = d.close);
    const nx = $("#wznext", box); if (nx) nx.onclick = () => { S.step++; draw(); if (S.step <= 3) loadChecks(false); };
    const pv = $("#wzprev", box); if (pv) pv.onclick = () => { const ti = $("#ptitle", box); if (ti) S.title = ti.value; S.step--; draw(); };
    $$(".kcard", box).forEach(b => { b.onclick = () => { S.kind = b.dataset.kind; S.game = null; draw(); }; b.ondblclick = () => { S.kind = b.dataset.kind; S.game = null; S.step = 2; draw(); loadChecks(false); }; });
    $$(".opt.gm", box).forEach(o => o.onclick = () => { S.game = o.dataset.game; draw(); });
    $$(".opt.md", box).forEach(o => o.onclick = () => { if (o.classList.contains("off")) return; S.mode = o.dataset.mode; S.modeFor = S.game; draw(); });
    for (const id of ["#wzre", "#wzre2"]) { const re = $(id, box); if (re) re.onclick = () => { CHECKS = null; CHECK_ERR = null; draw(); loadChecks(true); }; }
    if (S.step === 4) wireStep3(box);
  }
  async function loadChecks(force) {
    if (CHECKS && !force) return;
    CHECK_ERR = null;
    try { CHECKS = await get("/api/onboard/games" + (force ? "?force=1" : "")); useGames(CHECKS.game_info); }
    catch (e) {                                   // never spin forever: say so, offer 重新检查, and retry once by itself
      CHECKS = null; CHECK_ERR = (e && e.message) || "error";
      if (!retried) { retried = true; setTimeout(() => { if (d.isConnected && !CHECKS) loadChecks(true); }, 3000); }
    }
    if (d.isConnected && (S.step === 2 || S.step === 3)) draw();
  }
  function wireStep3(box) {
    const ti = $("#ptitle", box); ti.focus(); ti.oninput = () => S.title = ti.value;
    ti.onkeydown = e => { if (e.key === "Enter" && !e.isComposing) create(); };
    // the same checks as the chat and the 素材 page (upload.py ALLOWED), before anything is created, with the reason per file (QA 2026-10-29:
    // any file was taken, and the error after creating said only that some did not make it)
    const drop = $("#wzdrop", box), add = fs => {
      S.rejected = [];
      for (const f of fs) { const why = fileProblem(f); if (why) S.rejected.push({ name: f.name, why }); else S.files.push(f); }
      S.title = ti.value; draw();
    };
    $("#wzfile", box).onchange = e => add(e.target.files);
    ["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", ev => add(ev.dataTransfer.files));
    $$("[data-rm]", box).forEach(b => b.onclick = e => { e.preventDefault(); S.files.splice(+b.dataset.rm, 1); S.title = ti.value; draw(); });
    $("#wzgo", box).onclick = create;
  }
  async function create() {
    const box = $("#wz", d), title = ($("#ptitle", box).value || "").trim(), job = $("#wzjob", box);
    if (!title) { toast(t("给项目起个名字")); return $("#ptitle", box).focus(); }
    if (S.busy) return; S.busy = true; $("#wzgo", box).disabled = true; $("#wzprev", box).disabled = true;
    job.innerHTML = `<div class="st">${t("正在创建项目…")}</div>`;
    const r = await post("/api/projects/new", { title, kind: S.kind, game: S.game || KIND_REC[S.kind] || "stardew", lang: M2W.lang, ...(S.mode && S.modeFor === S.game ? { mode: S.mode } : {}) });
    if (!r.ok) { S.busy = false; $("#wzgo", box).disabled = false; $("#wzprev", box).disabled = false; job.innerHTML = ""; return toast(r.error || t("没能发出去")); }
    if (r.go) window.M2W_BASE = "/p/" + r.id;     // the uploads below go to the new project's address (every project has its own)
    const bad = [];
    for (let i = 0; i < S.files.length; i++) {               // into the new project's 0_inbox, the same chunked upload as the 素材 page
      const f = S.files[i];
      try { await upload(f, p => { job.innerHTML = bar(p) + `<div class="st">${t("正在放进素材 {i} / {n} · {p}%", { i: i + 1, n: S.files.length, p: Math.round(p) })}</div>`; }); }
      catch (e) { bad.push({ name: f.name, why: (e && e.message) || t("上传失败") }); }
    }
    if (bad.length) {                                          // which ones and why; the project is made, they can go in on the 素材 page
      job.innerHTML = `<div class="bad">${t("有 {n} 个文件没能放进来，可以在“素材”页再放一次", { n: bad.length })}<ul style="margin:4px 0 0;padding-left:18px">${bad.map(r => `<li>${esc(r.name)}${t("：")}${esc(r.why)}</li>`).join("")}</ul></div>`;
      await new Promise(z => setTimeout(z, 1800 + 900 * Math.min(bad.length, 4)));
    }
    const hash = S.files.length > bad.length ? "gather" : "";
    if (r.go) { location.href = r.go + (hash ? "#" + hash : ""); return; }
    location.hash = hash; location.reload();
  }
  draw();
}

/* ------------------------------------------------------------ flow stepper (top of the workspace) */
// the file kinds an upload takes (the server's list, /api/shell upload_allowed; the same as upload.py ALLOWED)
const UPLOAD_FALLBACK = ["aac", "docx", "epub", "flac", "heic", "jpeg", "jpg", "m4a", "m4v", "md", "mov", "mp3", "mp4", "ogg", "pdf", "png", "txt", "wav", "webp"];
const upExts = () => (SH && SH.upload_allowed) || UPLOAD_FALLBACK;
function fileProblem(f) {
  const name = f.name || "", ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
  if (name.startsWith(".")) return t("以点开头的文件（系统文件）不放进来");
  if (!ext) return t("没有扩展名，看不出是什么文件");
  if (!upExts().includes(ext)) return t("不支持 .{e} 文件。能放的是：{x}", { e: ext, x: upExts().join(" ") });
  if (!f.size) return t("空文件（0 字节）");
  return "";
}
function goRoute(r) {
  if (!r) return;
  if (r === "chat") {
    if (typeof mview === "function" && isPhone()) mview("chat");
    const th = $("#thread"), col = $("#chatcol"); if (th) th.scrollTop = th.scrollHeight;
    if (col) { col.classList.remove("flash"); void col.offsetWidth; col.classList.add("flash"); }
    const m = $("#msg"); if (m) m.focus(); return;
  }
  ws(r);
}
function renderFlow() {
  const el = $("#flow"); if (!el) return;
  const F = SH && SH.flow; if (!F) { el.innerHTML = ""; el.hidden = true; return; }
  el.hidden = false;
  const steps = F.steps.map((s, i) => `<a class="fs ${s.state}" data-route="${esc(s.route || "")}" title="${esc(s.state === "done" ? t("已完成") : s.state === "run" ? t("进行中") : s.state === "current" ? t("现在在这一步") : t("还没到"))}">
      <i>${s.state === "done" ? icon("check", "width:10px;height:10px") : s.state === "run" ? `<span class="ring"></span>` : i + 1}</i><span>${esc(t(s.label))}</span></a>`).join(`<span class="fsep"></span>`);
  const n = F.next || {};
  const nx = !n.route ? `<span class="fdone">${icon("check", "width:12px;height:12px")}${t("都完成了")}</span>`
    : `<button class="btn sm fnext ${n.wait ? "ghost" : ""}" data-route="${esc(n.route)}">${n.wait ? "" : t("下一步：")}${esc(t(n.label))}</button>`;
  el.innerHTML = `<div class="fsteps">${steps}</div><div class="fgo">${n.hint ? `<span class="fhint"><span class="ring"></span>${esc(t(n.hint))}</span>` : ""}${nx}</div>`;
  $$("[data-route]", el).forEach(a => a.onclick = () => goRoute(a.dataset.route));
}

/* ------------------------------------------------------------ coach marks */
const COACH_TAB = {
  memory: { gather: "放照片、视频、请柬、致辞稿", home: "看整理出的这一天，确认有哪些时刻", people: "标出照片里的人，看他们在游戏里的样子", plan: "确认这一版要做什么",
    play: "看试玩录像，一段一段说满意还是要改", keep: "把做好的装进你自己的游戏" },
  feature: { gather: "放参考图和说明（可选）", spec: "确认需求单：要做什么、怎样算做好", plan: "确认这一版的方案", play: "看试玩，说哪里要改", keep: "把做好的装进你自己的游戏" },
  adaptation: { gather: "放进要改编的作品", home: "确认从作品里抽取的场景和地点", people: "看从作品里抽取的角色", plan: "确认改编方案", play: "看试玩录像", keep: "把做好的装进你自己的游戏" },
  gameplay: { gather: "写下你的经历", mechanics: "确认“经历 → 机制”的映射", content: "确认卡牌、遗物和敌人", balance: "看模拟打出来的胜率和平衡", plan: "确认这一版的方案", play: "看试玩录像" } };
function coachSteps() {
  const help = COACH_TAB[SH.kind] || COACH_TAB.memory;
  return [
    { at: () => unionRect($$("#side #newproj, #side #allproj")), title: "在哪里新建项目",
      body: `<p>${t("左边栏下方的「＋ 新项目」随时可以开一个新项目；「全部」看所有项目、切换到别的项目。")}</p><p>${t("点左上角的项目名，可以导出、导入、备份、换游戏或删除这个项目。")}</p>` },
    { at: () => rectOf("#side #newproj"), title: "四种项目怎么选",
      body: `<ul><li><b>${t("回忆项目")}</b>${t("：")}${t("有照片、视频、文字，想把一段真实的回忆（婚礼、旅行、家人）做进游戏")}</li>`
        + `<li><b>${t("功能项目")}</b>${t("：")}${t("想给游戏加一样东西：新菜谱、新关卡、衣服、小游戏……先定需求单再做")}</li>`
        + `<li><b>${t("改编项目")}</b>${t("：")}${t("把喜欢的小说、影视剧、动漫做成游戏里的场景和剧情")}</li>`
        + `<li><b>${t("玩法项目")}</b>${t("：")}${t("把一段经历（读博、创业……）做成一套玩法，比如卡牌、敌人和平衡")}</li></ul>`
        + `<p>${t("新建时向导会让你先选游戏，再选项目类型，并检查这台电脑上的游戏能不能用；选错了，还没开工前可以在项目菜单里「换游戏」。")}</p>` },
    { at: () => unionRect($$("#side #gochat, #side .navi[data-w]")), title: "左边：每一页是做什么的",
      body: `<ul>${tabs().map(([k, , lb]) => `<li><b>${esc(t(lb))}</b>${t("：")}${esc(t(help[k] || ""))}</li>`).join("")}</ul>` },
    { at: () => rectOf("#chatcol"), title: "中间：和 agent 对话",
      body: `<p>${t("在这里和 agent 说话：补充、纠正、新想法都行，也可以把文件拖进来。")}</p><p>${t("agent 发来的卡片（许可、问题、方案、开工）要你点一下才算数，它不会替你决定。")}</p>` },
    { at: () => rectOf(".ws"), title: "右边：工作区",
      body: `<p>${t("agent 整理出来的东西都在这里给你看、给你改。")}</p><p>${t("最上面一行是项目走到了哪一步；“下一步”按钮总是指向现在该做的事。")}</p>` },
    { at: () => unionRect($$("#side [data-coach=rounds], #side .run[data-open]")), title: "每一版",
      body: `<p>${t("每次开工做出来的一版都列在这里，点一下看进度或试玩录像。")}</p><p>${t("正在构建时，对话上方会有一条“后台构建中”，写着第几轮、已经多久。")}</p>` },
    { at: () => rectOf("#side .sidefoot"), title: "隐私",
      body: `<p>${t("你的素材只在这台电脑上，整理也在这里完成。")}</p><p>${t("任何东西要发出去（比如发给模型看图）之前，都会先弹一张许可卡问你；发了什么都记在发送明细里。")}</p>` },
  ];
}
const rectOf = s => { const e = $(s); return e ? e.getBoundingClientRect() : null; };
function unionRect(els) {
  const rs = els.map(e => e.getBoundingClientRect()).filter(r => r.width && r.height); if (!rs.length) return null;
  const l = Math.min(...rs.map(r => r.left)), tp = Math.min(...rs.map(r => r.top)), rt = Math.max(...rs.map(r => r.right)), b = Math.max(...rs.map(r => r.bottom));
  return { left: l, top: tp, right: rt, bottom: b, width: rt - l, height: b - tp };
}
function startCoach() {
  if (!SH || SH.no_project || $("#coach")) return;
  const steps = coachSteps(); let i = 0;
  const ov = document.createElement("div"); ov.id = "coach"; ov.className = "coach";
  ov.innerHTML = `<div class="hole"></div><div class="tip" role="dialog" aria-modal="true"></div>`; document.body.append(ov);
  /* counted as seen as soon as it opens: closing the tab or reloading mid-way must not bring it back */
  lsSet("m2w.coach.kind." + SH.kind, "1"); lsSet("m2w.coach.p." + SH.project_id, "1"); SH.coach_seen = true; post("/api/coach", { seen: true }).catch(() => {});
  const finish = () => { ov.remove(); window.removeEventListener("resize", place); document.removeEventListener("keydown", key);
  };
  const key = e => { if (e.key === "Escape") finish(); else if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1); };
  const go = n => { i += n; if (i >= steps.length) return finish(); if (i < 0) i = 0; paint(); };
  function paint() {
    const s = steps[i], tip = $(".tip", ov);
    tip.innerHTML = `<div class="cn">${i + 1} / ${steps.length}</div><h4>${esc(t(s.title))}</h4><div class="cb">${s.body}</div>
      <div class="foot"><button class="lnk" data-c="skip">${t("跳过")}</button><span class="sp"></span>${i ? `<button class="btn ghost" data-c="prev">${t("上一步")}</button>` : ""}
        <button class="btn" data-c="next">${i === steps.length - 1 ? t("知道了") : t("下一步")}</button></div>`;
    $$("[data-c]", tip).forEach(b => b.onclick = () => b.dataset.c === "skip" ? finish() : go(b.dataset.c === "prev" ? -1 : 1));
    place(); $("[data-c=next]", tip).focus();
  }
  function place() {
    const s = steps[i], r = s.at(), hole = $(".hole", ov), tip = $(".tip", ov), W = innerWidth, H = innerHeight, pad = 6;
    if (!r) { hole.style.cssText = "display:none"; tip.style.left = Math.max(16, (W - tip.offsetWidth) / 2) + "px"; tip.style.top = Math.max(16, (H - tip.offsetHeight) / 2) + "px"; return; }
    const top = Math.max(4, r.top - pad), left = Math.max(4, r.left - pad), bottom = Math.min(H - 4, r.bottom + pad), right = Math.min(W - 4, r.right + pad);
    hole.style.cssText = `display:block;left:${left}px;top:${top}px;width:${right - left}px;height:${bottom - top}px`;
    const tw = tip.offsetWidth, th = tip.offsetHeight, gap = 14;
    let x = right + gap <= W - tw - 16 ? right + gap : left - gap - tw >= 16 ? left - gap - tw : Math.min(W - tw - 16, Math.max(16, left + 16));
    let y = Math.min(H - th - 16, Math.max(16, top + 12));
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  window.addEventListener("resize", place); document.addEventListener("keydown", key);
  ov.addEventListener("click", e => { if (e.target === ov || e.target.classList.contains("hole")) go(1); });
  paint();
}
/* shown once by itself per person and project kind (the server's ui-seen.yaml; it is marked when the tips open); the 「新手指引」 button replays them */
function maybeCoach() {
  if (!SH || SH.no_project || SH.coach_seen) return;
  if (lsGet("m2w.coach.p." + SH.project_id) || lsGet("m2w.coach.kind." + SH.kind)) return;
  setTimeout(startCoach, 700);
}
