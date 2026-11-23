/* Photo tagging screen (#people/tag): the old /tag-old page as a workspace screen. Same state (/api/state) and same POST /api/save payload
   {rev, people, groups, tags, merged}; only the presentation is new. Uses the helpers of app.js ($, esc, t, get, post, topbar ...) at call time. */
"use strict";
const TG = { S: null, cur: null, sel: null, dirty: false, ver: 0, timer: null, merged: [], low: false, drag: null, pop: null, hl: 0, go: {}, saving: null };
const TG_PRESENCE = {   // D8: how long / how deep a person stays in the game is the user's choice; the cost of each level in plain words (zh source, through t())
  event_only: ["只在婚礼里出现", "只出现在婚礼当天的剧情和活动里。不进存档，卸载 mod 后什么也不留下。"],
  visits: ["之后偶尔出现", "婚礼后会在某些时候出现（比如夏天傍晚的海滩），可以聊天。不是正式村民，不进存档，卸载 mod 后什么也不留下。"],
  villager: ["正式村民", "成为镇上的村民：有日程、好感度，可以送礼。会写进存档；卸载 mod 对存档的影响要在设计阶段确认后再告诉你。"],
  spouse: ["你的配偶", "婚礼后成为你在游戏里的配偶，住进你的农舍，每天有配偶台词。会写进存档（World Plan 里你选的）。"],
};
const TG_KINDS = { family: "家人", friends: "朋友", colleagues: "同学 / 同事", community: "教会 / 社群", other: "其他" };
const tgLabel = p => p.name || ("？" + String(p.role_guess || p.role || p.id).replace(/（.*$/, "").slice(0, 16));
const tgLooks = p => typeof p.looks === "object" && p.looks ? Object.values(p.looks).join("；") : (p.looks || "");
const tgIou = (a, b) => {
  const x0 = Math.max(a[0], b[0]), y0 = Math.max(a[1], b[1]), x1 = Math.min(a[2], b[2]), y1 = Math.min(a[3], b[3]);
  const i = Math.max(0, x1 - x0) * Math.max(0, y1 - y0), u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i; return u > 0 ? i / u : 0;
};
const tgPerson = id => TG.S.people.find(p => p.id === id);
const tgPhoto = id => TG.S.photos.find(p => p.id === id);
const tgTagsOf = pid => TG.S.tags.filter(x => x.item === pid);
const tgOnScreen = () => location.hash.startsWith("#people/tag");
const TG_BLANK = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";

/* ---- saving (rev check against stale pages is the server's; a stale answer stops the autosave and asks for a reload) ---- */
function tgSaved(text, cls) { const e = $("#tgsaved"); if (e) { e.textContent = text; e.className = "tg-saved " + cls; } }
function tgChanged() { TG.dirty = true; TG.ver++; tgSaved(t("未保存"), "dirty"); clearTimeout(TG.timer); TG.timer = setTimeout(tgSave, 1200); }
function tgErr(msg, reload) {
  const old = $("#tgerr"); if (old) old.remove();
  const el = document.createElement("div"); el.id = "tgerr"; el.className = "tg-err";
  el.innerHTML = `<span>${esc(msg)}</span>${reload ? `<button class="btn sm" data-r="1">${t("刷新")}</button>` : ""}<button class="btn ghost sm" data-r="0">${t("关闭")}</button>`;
  el.onclick = e => { const b = e.target.closest("button"); if (!b) return; el.remove(); if (b.dataset.r === "1") route(); };
  document.body.append(el);
}
async function tgSave() {
  clearTimeout(TG.timer);
  while (TG.saving) await TG.saving;                      // one save at a time: a second one would carry the old rev
  if (!TG.dirty) return;
  const S = TG.S, v = TG.ver, m = TG.merged.slice();
  TG.saving = post("/api/save", { rev: S.rev, people: S.people, groups: S.groups, tags: S.tags, merged: m });
  let j; try { j = await TG.saving; } finally { TG.saving = null; }
  if (j.ok) {
    S.rev = j.rev; TG.merged = TG.merged.slice(m.length);
    if (TG.ver === v) { TG.dirty = false; tgSaved(t("已保存 {at}", { at: j.at }), "ok"); }
  } else if (j.stale) {
    clearTimeout(TG.timer); TG.dirty = false; tgSaved(t("页面已过期，请刷新"), "bad"); tgErr(j.error, true);
  } else { tgSaved(t("保存失败：{e}", { e: j.error }), "bad"); }
}
window.addEventListener("beforeunload", e => { if (TG.dirty) { tgSave(); e.preventDefault(); } });

/* ---- a small in-page dialog instead of prompt() / confirm(): resolves to the typed text, true, or null (cancelled) ---- */
function tgDlg({ title, body = "", input = null, ok = t("确认"), ph = "" }) {
  return new Promise(res => {
    const el = document.createElement("div"); el.className = "tg-modal";
    el.innerHTML = `<div class="card tg-dlg"><h3>${esc(title)}</h3>${body ? `<p>${esc(body)}</p>` : ""}${input !== null ? `<input class="tg-in" value="${esc(input)}" placeholder="${esc(ph)}">` : ""}
      <div class="acts" style="justify-content:flex-end"><button class="btn ghost sm" data-r="0">${t("取消")}</button><button class="btn sm" data-r="1">${esc(ok)}</button></div></div>`;
    const inp = $("input", el), done = v => { el.remove(); res(v); };
    const fin = () => done(input !== null ? inp.value : true);
    el.onclick = e => { if (e.target === el) return done(null); const b = e.target.closest("button"); if (b) b.dataset.r === "1" ? fin() : done(null); };
    el.onkeydown = e => { if (e.key === "Escape") done(null); else if (e.key === "Enter") { e.preventDefault(); fin(); } };
    document.body.append(el); (inp || $("button[data-r='1']", el)).focus(); if (inp) inp.select();
  });
}

/* ---- boxes of the current photo: user / tagged boxes plus the detector's (low-confidence ones only when asked) ---- */
function tgBoxes(ph) {
  const tags = tgTagsOf(ph.id), out = tags.map(x => ({ ...x, tag: x }));
  for (const b of ph.boxes) {
    if (b.score < ph.show_threshold && !TG.low) continue;
    if (tags.some(x => tgIou(x.box, b.box) > 0.6)) continue;
    out.push({ box: b.box, score: b.score, source: "detector", low: b.score < ph.show_threshold });
  }
  return out;
}
const tgProgress = ph => { const v = tgBoxes(ph); return [v.filter(b => b.tag && b.tag.person).length, v.length]; };

function tgAvatar(p) {
  const x = TG.S.tags.find(x => x.person === p.id);
  if (x) return `/crop?item=${encodeURIComponent(x.item)}&box=${x.box.join(",")}`;
  const ph = (p.appears_in || []).map(tgPhoto).find(Boolean);
  return ph ? ph.thumb : TG_BLANK;
}
const tgGroupsOf = pid => TG.S.groups.filter(g => (g.members || []).includes(pid));

/* ---- left: photos grouped by time ---- */
function tgLeft() {
  const S = TG.S, used = new Set(), segs = [];
  for (const s of S.segments) { const ps = s.items.filter(tgPhoto); ps.forEach(i => used.add(i)); if (ps.length) segs.push([s.label, ps]); }
  const rest = S.photos.map(p => p.id).filter(i => !used.has(i)); if (rest.length) segs.push([t("其他"), rest]);
  let total = 0, done = 0;
  $("#tgleft").innerHTML = segs.map(([lb, ids]) => {
    const cells = ids.map(id => {
      const ph = tgPhoto(id), [d, n] = tgProgress(ph); total += n; done += d;
      return `<div class="tg-th ${id === TG.cur ? "cur" : ""}" draggable="true" data-id="${esc(id)}" title="${esc(id)}"><img src="${esc(ph.thumb)}" loading="lazy" alt="">
        <span class="bd ${n && d === n ? "done" : ""}">${d}/${n}</span></div>`;
    });
    return `<div class="tg-seg"><div class="tg-segh"><b>${esc(lb)}</b><span>${t("{n} 张照片", { n: ids.length })}</span></div><div class="tg-thumbs">${cells.join("")}</div></div>`;
  }).join("");
  const pg = $("#tgprog"); if (pg) pg.textContent = t("已标 {d} / {n} 个框", { d: done, n: total });
  $$("#tgleft .tg-th").forEach(el => {
    el.onclick = () => { TG.cur = el.dataset.id; TG.sel = null; tgPhotoChanged(); };
    el.ondragstart = e => e.dataTransfer.setData("text/plain", "photo:" + el.dataset.id);
  });
  const c = $("#tgleft .tg-th.cur"); if (c) c.scrollIntoView({ block: "nearest" });
}
function tgPhotoChanged() { tgLeft(); tgStage(); }

/* ---- centre: the photo with its boxes ---- */
function tgStage() {
  const ph = tgPhoto(TG.cur); if (!ph) return;
  const img = $("#tgimg"); if (img.getAttribute("src") !== ph.image) img.src = ph.image;
  const ids = TG.S.photos.map(p => p.id), i = ids.indexOf(TG.cur);
  $("#tgname").textContent = ph.id; $("#tgpos").textContent = `${i + 1} / ${ids.length}`;
  $("#tgprev").disabled = i <= 0; $("#tgnext").disabled = i >= ids.length - 1;
  const ov = $("#tgov"); $$(".tg-box", ov).forEach(e => e.remove());
  tgBoxes(ph).forEach(b => {
    const el = document.createElement("div"), [x0, y0, x1, y1] = b.box;
    const p = b.tag && b.tag.person && b.tag.person !== "_ignore" ? tgPerson(b.tag.person) : null;
    el.className = "tg-box " + (b.tag ? (b.tag.person === "_ignore" ? "ign" : (p ? "tagged" : "untagged")) : "untagged") + (b.low ? " low" : "") + (TG.sel === b.box.join() ? " sel" : "");
    Object.assign(el.style, { left: x0 * 100 + "%", top: y0 * 100 + "%", width: (x1 - x0) * 100 + "%", height: (y1 - y0) * 100 + "%" });
    if (p || (b.tag && b.tag.person !== "_ignore")) el.innerHTML = `<span class="lb">${esc(p ? tgLabel(p) : "？")}</span>`;
    el.onmousedown = e => e.stopPropagation();
    el.onclick = e => { e.stopPropagation(); TG.sel = b.box.join(); tgStage(); tgOpenPop(e.clientX, e.clientY, b); };
    ov.appendChild(el);
  });
}

/* ---- person picker popup ---- */
function tgOpenPop(x, y, b) {
  TG.pop = b; const pop = $("#tgpop"); pop.style.display = "block";
  $("#tgq").value = ""; TG.hl = 0; tgPopList();
  pop.style.left = Math.max(8, Math.min(x + 8, innerWidth - 320)) + "px"; pop.style.top = Math.max(8, Math.min(y + 8, innerHeight - pop.offsetHeight - 8)) + "px";
  $("#tgq").focus();
}
function tgClosePop() { $("#tgpop").style.display = "none"; TG.pop = null; }
function tgMatches(q) {
  q = q.trim().toLowerCase();
  return TG.S.people.filter(p => !q || [p.name, p.role, p.role_guess, tgLooks(p)].join(" ").toLowerCase().includes(q)).sort((a, b) => (!!b.name - !!a.name));
}
function tgPopList() {
  const q = $("#tgq").value, ps = tgMatches(q).slice(0, 40);
  $("#tglist").innerHTML = ps.map((p, i) => `<div class="tg-opt ${i === TG.hl ? "hl" : ""}" data-id="${esc(p.id)}"><img src="${esc(tgAvatar(p))}" alt=""><div>${esc(tgLabel(p))}<small>${esc((p.role || p.role_guess || "").slice(0, 40))}</small></div></div>`).join("")
    + (q.trim() ? `<div class="tg-opt" data-new="1"><span class="plus">＋</span><div>${t("新建人物 “{n}”", { n: esc(q.trim()) })}</div></div>` : "");
  const x = TG.pop && TG.pop.tag, owner = x && x.person && x.person !== "_ignore" ? tgPerson(x.person) : null;
  const isRef = owner && owner.portrait_ref && owner.portrait_ref.item === x.item && owner.portrait_ref.box.join() === x.box.join();
  $("#tgacts").innerHTML = (owner ? `<button class="btn ghost sm" data-a="ref">${isRef ? t("✓ 已是头像参考照") : t("用这张做TA的头像")}</button>` : "")
    + (x && x.person ? `<button class="btn ghost sm" data-a="clear">${t("清除标记")}</button>` : "")
    + (x && x.source === "user" ? `<button class="btn ghost sm" data-a="del">${t("删除这个框")}</button>` : `<button class="btn ghost sm" data-a="ign">${t("不用标（忽略这个框）")}</button>`)
    + (EMBED && owner ? `<button class="btn ghost sm" data-a="say">${t("在对话里说")}</button>` : "")
    + `<button class="btn ghost sm" data-a="close">${t("关闭")}</button>`;
  $$("#tglist .tg-opt").forEach(el => el.onclick = () => el.dataset.new ? tgAssign(tgNewPerson(q.trim())) : tgAssign(el.dataset.id));
  $$("#tgacts button").forEach(el => el.onclick = () => tgAct(el.dataset.a));
}
function tgTagFor(b) {
  if (b.tag) return b.tag;
  const x = { item: TG.cur, box: b.box, person: null, source: "detector", score: b.score }; TG.S.tags.push(x); return x;
}
function tgAssign(pid) {
  const x = tgTagFor(TG.pop); x.person = pid; const p = tgPerson(pid);
  if (p && !p.appears_in.includes(TG.cur)) p.appears_in.push(TG.cur);
  tgChanged(); tgClosePop(); tgAll();
}
function tgAct(a) {
  if (a === "close") return tgClosePop();
  const x = tgTagFor(TG.pop);
  if (a === "say") { const p = tgPerson(x.person); tgClosePop(); return tellChat([{ kind: "person", id: p.id, label: tgLabel(p) }]); }
  if (a === "ref") { const p = tgPerson(x.person); p.portrait_ref = { item: x.item, box: x.box }; }
  if (a === "clear") x.person = null;
  if (a === "ign") x.person = "_ignore";
  if (a === "del") TG.S.tags.splice(TG.S.tags.indexOf(x), 1);
  tgChanged(); tgClosePop(); tgAll();
}
function tgNewPerson(name) {
  const p = { id: "person_" + Date.now().toString(36), name: name || null, role: null, appears_in: [], persona: null, confirmed_by: name ? "user" : null };
  TG.S.people.unshift(p); tgChanged(); return p.id;
}

/* ---- right: groups and people ---- */
function tgDrop(el, fn) {
  el.ondragover = e => { e.preventDefault(); el.classList.add("over"); };
  el.ondragleave = () => el.classList.remove("over");
  el.ondrop = e => { e.preventDefault(); e.stopPropagation(); el.classList.remove("over"); fn(e.dataTransfer.getData("text/plain")); };
}
function tgRight() {
  const S = TG.S;
  $("#tggroups").innerHTML = S.groups.map((g, gi) => `<div class="tg-group" data-gi="${gi}">
      <div class="gh"><span class="gname" data-gi="${gi}" title="${esc(t("点击改名"))}">${esc(g.name)}</span>
        <select class="tg-sel gkind" data-gi="${gi}">${Object.entries(TG_KINDS).map(([k, v]) => `<option value="${k}" ${g.kind === k ? "selected" : ""}>${t(v)}</option>`).join("")}</select>
        <button class="tg-x" data-gdel="${gi}" title="${esc(t("删除分组"))}">✕</button></div>
      <div class="tg-chips">${(g.members || []).map(m => tgPerson(m) ? `<span class="tg-chip" data-pid="${esc(m)}">${esc(tgLabel(tgPerson(m)))}<b data-rm="${gi}|${esc(m)}">×</b></span>` : "").join("") || `<span class="fine" style="margin:0">${t("把人物卡拖到这里")}</span>`}</div>
      ${g.note ? `<div class="fine" style="margin:6px 0 0">${esc(g.note)}</div>` : ""}</div>`).join("") || `<div class="fine" style="margin:0">${t("还没有分组。")}</div>`;
  const G = $("#tggroups");
  $$(".gname", G).forEach(el => el.onclick = async () => {
    const g = S.groups[el.dataset.gi], v = await tgDlg({ title: t("分组名字"), input: g.name }); if (v && v.trim()) { g.name = v.trim(); tgChanged(); tgAll(); }
  });
  $$(".gkind", G).forEach(el => el.onchange = () => { S.groups[el.dataset.gi].kind = el.value; tgChanged(); });
  $$("[data-gdel]", G).forEach(el => el.onclick = async () => {
    const g = S.groups[el.dataset.gdel];
    if (await tgDlg({ title: t("删除分组“{n}”？", { n: g.name }), body: t("不会删除里面的人。"), ok: t("删除") })) { S.groups.splice(el.dataset.gdel, 1); tgChanged(); tgRight(); }
  });
  $$("[data-rm]", G).forEach(el => el.onclick = e => { e.stopPropagation(); const [gi, m] = el.dataset.rm.split("|"), g = S.groups[gi]; g.members = g.members.filter(x => x !== m); tgChanged(); tgRight(); });
  $$(".tg-chip", G).forEach(el => el.onclick = () => tgFocus(el.dataset.pid));
  $$(".tg-group", G).forEach(el => tgDrop(el, d => {
    if (!d.startsWith("person:")) return; const g = S.groups[el.dataset.gi], pid = d.slice(7);
    g.members = g.members || []; if (!g.members.includes(pid)) { g.members.push(pid); tgChanged(); tgRight(); }
  }));
  tgPeople();
}
const tgVisible = () => { const q = $("#tgfilter").value.trim().toLowerCase(); return TG.S.people.filter(p => !q || [p.name, p.role, p.role_guess, tgLooks(p)].join(" ").toLowerCase().includes(q)); };
function tgDialogue(p) {         // what a person says in the game: one line per row; "later" only for people who stay after the wedding
  const d = p.dialogue || {}, later = p.persona && ["visits", "villager", "spouse"].includes(p.persona.presence);
  const src = d.source === "user" ? t("你改过") : d.source === "draft" ? t("GameAnything 起草，待你确认") : "";
  return `<div class="tg-dl"><div class="lbl" style="margin:0 0 4px">${t("婚礼上说的话")} <span class="src">${src}</span></div>
      <textarea rows="2" data-dl="${esc(p.id)}" data-k="wedding" placeholder="${esc(t("每行一句；留空就由 GameAnything 起草"))}">${esc((d.wedding || []).join("\n"))}</textarea>
      ${later ? `<div class="lbl" style="margin:8px 0 4px">${t("婚礼之后的日常台词")}</div><textarea rows="2" data-dl="${esc(p.id)}" data-k="later" placeholder="${esc(t("每行一句"))}">${esc((d.later || []).join("\n"))}</textarea>` : ""}</div>`;
}
function tgPeople() {
  const S = TG.S, ps = tgVisible(), P = $("#tgpeople");
  $("#tgbulkhint").textContent = t("作用于下面列出的 {n} 个人；可以先搜索筛选", { n: ps.length });
  P.innerHTML = ps.map(p => {
    const n = new Set([...(p.appears_in || []), ...S.tags.filter(x => x.person === p.id).map(x => x.item)]).size, pr = p.persona || {}, pid = esc(p.id);
    const pres = TG_PRESENCE[pr.presence || "event_only"];
    return `<div class="tg-person" draggable="true" data-pid="${pid}">
      <img class="tg-av" src="${esc(tgAvatar(p))}" draggable="true" alt="" title="${esc(t("按住头像拖动：拖到分组 = 加入分组；拖到另一张人物卡 = 合并"))}">
      <div class="tg-pb"><input class="tg-nm" value="${esc(p.name || "")}" placeholder="${esc(tgLabel(p) + t("（还没有名字）"))}" data-pid="${pid}">
        <input class="tg-rl" value="${esc(p.role || "")}" placeholder="${esc(p.role_guess || t("身份 / 和你们的关系"))}" data-pid="${pid}">
        <div class="tg-lk" title="${esc(tgLooks(p))}">${esc(tgLooks(p))}</div>
        <div class="tg-row"><a class="tg-go" data-go="${pid}">${t("照片 {n} 张", { n })}</a>${p.portrait_ref ? `<span class="fine" style="margin:0" title="${esc(p.portrait_ref.item)}">${t("已选头像照")}</span>` : ""}
          ${tgGroupsOf(p.id).map(g => `<span class="tg-chip static">${esc(g.name)}</span>`).join("")}<button class="tg-x" data-pdel="${pid}" title="${esc(t("删除这个人"))}">✕</button></div>
        <div class="tg-row"><select class="tg-sel" data-addg="${pid}"><option value="">${t("＋ 加入分组…")}</option>${S.groups.map((g, gi) => (g.members || []).includes(p.id) ? "" : `<option value="${gi}">${esc(g.name)}</option>`).join("")}</select>
          <select class="tg-sel" data-merge="${pid}"><option value="">${t("合并到…")}</option>${S.people.filter(q => q !== p).map(q => `<option value="${esc(q.id)}">${esc(tgLabel(q))}</option>`).join("")}</select></div>
        ${pr.player ? `<div class="tg-row"><span class="tag">${t("玩家（游戏里由你扮演）")}</span></div>`
          : `<div class="tg-row"><label class="tg-chk"><input type="checkbox" data-npc="${pid}" ${pr.npc ? "checked" : ""}> ${t("做成游戏角色")}</label>
              <select class="tg-sel" data-pres="${pid}" ${pr.npc ? "" : "disabled"} title="${esc(t(pres[1]))}">${Object.entries(TG_PRESENCE).map(([k, [lb]]) => `<option value="${k}" ${(pr.presence || "event_only") === k ? "selected" : ""}>${t(lb)}</option>`).join("")}</select></div>
            ${pr.npc ? `<div class="fine" style="margin:4px 0 0">${t(pres[1])}</div>` : ""}`}
        ${pr.player ? "" : tgDialogue(p)}
        ${EMBED ? `<div class="tg-row"><button class="btn ghost sm" data-say="${pid}">${icon("chat", "width:13px;height:13px")}${t("在对话里说")}</button></div>` : ""}
      </div></div>`;
  }).join("") || `<div class="fine" style="margin:0">${t("没有符合的人物。")}</div>`;
  $$(".tg-person", P).forEach(el => {
    el.ondragstart = e => { if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return; e.dataTransfer.setData("text/plain", "person:" + el.dataset.pid); e.dataTransfer.effectAllowed = "move"; };
    tgDrop(el, d => {
      const into = tgPerson(el.dataset.pid);
      if (d.startsWith("photo:")) { const ph = d.slice(6); if (!into.appears_in.includes(ph)) { into.appears_in.push(ph); tgChanged(); tgPeople(); } return; }
      if (d.startsWith("person:")) { const from = tgPerson(d.slice(7)); if (from && from !== into) tgAskMerge(from, into); }
    });
  });
  $$("input.tg-nm", P).forEach(el => el.onchange = () => { const p = tgPerson(el.dataset.pid); p.name = el.value.trim() || null; if (p.name) p.confirmed_by = "user"; tgChanged(); tgAll(); });
  $$("input.tg-rl", P).forEach(el => el.onchange = () => { tgPerson(el.dataset.pid).role = el.value.trim() || null; tgChanged(); });
  $$("[data-npc]", P).forEach(el => el.onchange = () => { const p = tgPerson(el.dataset.npc); p.persona = el.checked ? { npc: true, presence: (p.persona || {}).presence || "event_only" } : null; tgChanged(); tgPeople(); });
  $$("[data-pres]", P).forEach(el => el.onchange = () => { const p = tgPerson(el.dataset.pres); p.persona = { npc: true, presence: el.value }; tgChanged(); tgPeople(); });
  $$("[data-go]", P).forEach(el => el.onclick = () => tgGoto(el.dataset.go));
  $$("[data-dl]", P).forEach(el => el.onchange = () => {
    const p = tgPerson(el.dataset.dl); p.dialogue = p.dialogue || {};
    p.dialogue[el.dataset.k] = el.value.split("\n").map(x => x.trim()).filter(Boolean); p.dialogue.source = "user"; tgChanged(); tgPeople();
  });
  $$("[data-addg]", P).forEach(el => el.onchange = () => {
    if (el.value === "") return; const g = S.groups[el.value]; g.members = g.members || [];
    if (!g.members.includes(el.dataset.addg)) g.members.push(el.dataset.addg); tgChanged(); tgRight();
  });
  $$("[data-merge]", P).forEach(el => el.onchange = async () => {
    if (!el.value) return; const from = tgPerson(el.dataset.merge), into = tgPerson(el.value);
    if (!await tgAskMerge(from, into)) el.value = "";
  });
  $$("[data-pdel]", P).forEach(el => el.onclick = async () => {
    const p = tgPerson(el.dataset.pdel);
    if (!await tgDlg({ title: t("删除“{n}”？", { n: tgLabel(p) }), body: t("照片上的标记会清除。"), ok: t("删除") })) return;
    S.tags.forEach(x => { if (x.person === p.id) x.person = null; }); S.groups.forEach(g => g.members = (g.members || []).filter(m => m !== p.id));
    S.people.splice(S.people.indexOf(p), 1); tgChanged(); tgAll();
  });
  $$("[data-say]", P).forEach(el => el.onclick = () => { const p = tgPerson(el.dataset.say); tellChat([{ kind: "person", id: p.id, label: tgLabel(p) }]); });
}
async function tgAskMerge(from, into) {
  if (!await tgDlg({ title: t("把“{a}”合并进“{b}”？", { a: tgLabel(from), b: tgLabel(into) }), body: t("同一个人；照片和分组会合在一起。"), ok: t("合并") })) return false;
  tgMerge(from, into); return true;
}
function tgMerge(from, into) {
  const S = TG.S;
  S.tags.forEach(x => { if (x.person === from.id) x.person = into.id; });
  into.appears_in = [...new Set([...(into.appears_in || []), ...(from.appears_in || [])])];
  for (const k of ["name", "role", "role_guess", "looks", "persona"]) if (!into[k] && from[k]) into[k] = from[k];
  S.groups.forEach(g => { if ((g.members || []).includes(from.id)) g.members = [...new Set(g.members.map(m => m === from.id ? into.id : m))]; });
  S.people.splice(S.people.indexOf(from), 1); TG.merged.push({ from: from.id, into: into.id, at: new Date().toISOString().slice(0, 19) });
  tgChanged(); tgAll();
}
function tgGoto(pid) {
  const ids = [...new Set([...TG.S.tags.filter(x => x.person === pid).map(x => x.item), ...(tgPerson(pid).appears_in || [])])].filter(tgPhoto);
  if (!ids.length) return; TG.go[pid] = ((TG.go[pid] ?? -1) + 1) % ids.length; TG.cur = ids[TG.go[pid]]; TG.sel = null; tgPhotoChanged(); tgFocus(pid);
}
function tgFocus(pid) {
  $$("#tgpeople .tg-person").forEach(el => el.classList.toggle("hl", el.dataset.pid === pid));
  const c = $(`#tgpeople .tg-person[data-pid="${CSS.escape(pid)}"]`); if (c) c.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function tgAll() { tgLeft(); tgStage(); tgRight(); }

/* ---- page-wide handlers, registered once (they do nothing outside this screen) ---- */
let tgWired = false;
function tgWire() {
  if (tgWired) return; tgWired = true;
  window.addEventListener("mousemove", e => {
    if (!TG.drag || !tgOnScreen()) return;
    const { r } = TG.drag, x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height, d = $("#tgdraw");
    Object.assign(d.style, { display: "block", left: Math.min(x, TG.drag.x) * 100 + "%", top: Math.min(y, TG.drag.y) * 100 + "%", width: Math.abs(x - TG.drag.x) * 100 + "%", height: Math.abs(y - TG.drag.y) * 100 + "%" });
  });
  window.addEventListener("mouseup", e => {
    if (!TG.drag || !tgOnScreen()) { TG.drag = null; return; }
    const { r } = TG.drag, cl = v => Math.max(0, Math.min(1, v)), x = cl((e.clientX - r.left) / r.width), y = cl((e.clientY - r.top) / r.height);
    $("#tgdraw").style.display = "none";
    const box = [Math.min(x, TG.drag.x), Math.min(y, TG.drag.y), Math.max(x, TG.drag.x), Math.max(y, TG.drag.y)].map(v => +v.toFixed(4)); TG.drag = null;
    if (box[2] - box[0] < 0.015 || box[3] - box[1] < 0.015) return;
    const x2 = { item: TG.cur, box, person: null, source: "user" }; TG.S.tags.push(x2); tgChanged(); TG.sel = box.join(); tgStage();
    tgOpenPop(e.clientX, e.clientY, { ...x2, tag: x2 });
  });
  document.addEventListener("keydown", e => {
    if (!tgOnScreen() || !TG.S || $(".tg-modal")) return;
    if (e.key === "Escape") return tgClosePop();
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    const ids = TG.S.photos.map(p => p.id), i = ids.indexOf(TG.cur);
    if (e.key === "ArrowRight" && i < ids.length - 1) { TG.cur = ids[i + 1]; TG.sel = null; tgPhotoChanged(); }
    if (e.key === "ArrowLeft" && i > 0) { TG.cur = ids[i - 1]; TG.sel = null; tgPhotoChanged(); }
  });
  document.addEventListener("mousedown", e => {
    const pop = $("#tgpop"); if (pop && pop.style.display === "block" && !pop.contains(e.target) && !e.target.closest(".tg-box")) tgClosePop();
  });
}

/* ---- the screen ---- */
async function tagScreen(_, live) {
  if (TG.dirty) await tgSave();                       // a repaint (language switch, coming back) never drops an unsaved edit
  const S = await get("/api/state"); if (!live()) return;
  TG.S = S; S.people.forEach(p => { p.appears_in = p.appears_in || []; });
  if (!S.photos.some(p => p.id === TG.cur)) TG.cur = S.photos.length ? S.photos[0].id : null;
  Object.assign(TG, { sel: null, dirty: false, merged: [], drag: null, pop: null });
  const e0 = $("#tgerr"); if (e0) e0.remove();
  const crumb = `<a href="#people" style="color:inherit">${t("人物")}</a> / <b>${t("标记照片")}</b>`;
  const right = `<span class="tag grey" id="tgprog"></span><label class="tg-chk"><input type="checkbox" id="tgshowlow" ${TG.low ? "checked" : ""}> ${t("显示把握较低的框")}</label>
    <span class="tg-saved ok" id="tgsaved">${t("已保存")}</span><button class="btn sm" id="tgsave">${t("保存")}</button>`;
  if (!S.photos.length) {
    $("#screen").innerHTML = topbar(crumb) + `<div class="page"><div class="card empty">${t("还没有可以标记的照片。先在“素材”里放进照片。")}</div></div>`; return;
  }
  $("#screen").innerHTML = topbar(crumb, right) + `<div class="tg">
    <aside class="tg-left" id="tgleft"></aside>
    <section class="tg-mid">
      <div class="tg-bar"><b id="tgname"></b><span class="muted" id="tgpos"></span><span class="sp"></span>
        <button class="btn ghost sm" id="tgprev" title="←">${icon("arrow", "transform:scaleX(-1)")}</button><button class="btn ghost sm" id="tgnext" title="→">${icon("arrow")}</button></div>
      <div class="tg-hint">${t("← → 切换照片 · 点框选人 · 在空白处拖动画新框")}</div>
      <div class="tg-stage"><img id="tgimg" alt="" draggable="false"><div class="tg-ov" id="tgov"><div class="tg-draw" id="tgdraw"></div></div></div>
    </section>
    <aside class="tg-right">
      <details class="card tg-help"><summary>${t("怎么用")}</summary><ul>
        <li>${t("点照片上的框，选这是谁（或新建一个人）；框漏了就在空白处拖一个。")}</li>
        <li>${t("把人物卡拖到分组上，或用卡片上的“加入分组”= 加入分组。")}</li>
        <li>${t("拖到另一张人物卡上，或用“合并到”= 合并（同一个人）。")}</li>
        <li>${t("把左边的照片拖到人物卡上 = “这个人也在这张照片里”。")}</li>
        <li>${t("改动会自动保存。")}</li></ul></details>
      <div class="card tg-panel"><h2 class="h">${t("分组")}<span class="sp"></span><button class="btn ghost sm" id="tgaddgroup">${t("＋ 新建分组")}</button></h2><div id="tggroups"></div></div>
      <div class="card tg-panel"><h2 class="h">${t("人物")}<span class="sp"></span><button class="btn ghost sm" id="tgaddperson">${t("＋ 新建人物")}</button></h2>
        <input class="tg-in" id="tgfilter" placeholder="${esc(t("搜索名字 / 身份 / 外观"))}" value="${esc(TG.filter || "")}">
        <div class="tg-bulk"><button class="btn ghost sm" id="tgnpcall">${t("全部做成游戏角色")}</button><button class="btn ghost sm" id="tgnpcnone">${t("全部取消")}</button></div>
        <div class="fine" id="tgbulkhint" style="margin:0 0 10px"></div><div id="tgpeople"></div></div>
    </aside></div>
    <div class="tg-pop" id="tgpop"><input class="tg-in" id="tgq" placeholder="${esc(t("输入名字搜索，或输入新名字"))}"><div class="tg-list" id="tglist"></div><div class="tg-acts" id="tgacts"></div></div>`;
  tgWire();
  const ov = $("#tgov");
  ov.onmousedown = e => {
    if (e.button !== 0) return; tgClosePop(); const r = ov.getBoundingClientRect();
    TG.drag = { r, x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  };
  $("#tgq").oninput = () => { TG.hl = 0; tgPopList(); };
  $("#tgq").onkeydown = e => {
    const n = $("#tglist").children.length;
    if (e.key === "ArrowDown") { TG.hl = Math.min(n - 1, TG.hl + 1); tgPopList(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { TG.hl = Math.max(0, TG.hl - 1); tgPopList(); e.preventDefault(); }
    else if (e.key === "Enter") { const c = $("#tglist").children[TG.hl]; if (c) c.click(); }
    else if (e.key === "Escape") tgClosePop();
  };
  $("#tgfilter").oninput = () => { TG.filter = $("#tgfilter").value; tgPeople(); };
  $("#tgshowlow").onchange = () => { TG.low = $("#tgshowlow").checked; tgPhotoChanged(); };
  $("#tgsave").onclick = () => { TG.dirty = true; tgSave(); };
  const step = d => { const ids = S.photos.map(p => p.id), i = ids.indexOf(TG.cur) + d; if (ids[i]) { TG.cur = ids[i]; TG.sel = null; tgPhotoChanged(); } };
  $("#tgprev").onclick = () => step(-1); $("#tgnext").onclick = () => step(1);
  $("#tgaddgroup").onclick = async () => {
    const name = await tgDlg({ title: t("新建分组"), input: "", ph: t("例如：实验室同学") }); if (!name || !name.trim()) return;
    S.groups.push({ id: "group_" + Date.now().toString(36), name: name.trim(), kind: "friends", members: [] }); tgChanged(); tgRight();
  };
  $("#tgaddperson").onclick = async () => {
    const name = await tgDlg({ title: t("新建人物"), input: "", ph: t("名字") }); if (name === null) return; tgNewPerson(name.trim()); tgAll();
  };
  $("#tgnpcall").onclick = async () => {
    const ps = tgVisible(); if (!await tgDlg({ title: t("把列出的 {n} 个人都做成游戏角色？", { n: ps.length }), body: t("已经选过的保持原来的出现方式。") })) return;
    ps.forEach(p => { if (!(p.persona || {}).npc && !(p.persona || {}).player) p.persona = { npc: true, presence: "event_only" }; }); tgChanged(); tgPeople();
  };
  $("#tgnpcnone").onclick = async () => {
    const ps = tgVisible(); if (!await tgDlg({ title: t("取消列出的 {n} 个人的“做成游戏角色”？", { n: ps.length }) })) return;
    ps.forEach(p => { if (!(p.persona || {}).player) p.persona = null; }); tgChanged(); tgPeople();
  };
  tgAll();
}
