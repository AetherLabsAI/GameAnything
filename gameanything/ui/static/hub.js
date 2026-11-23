/* gameanything hub (ui/hub.py): the login form and the user's project list — their own projects (with members and access requests), the ones
   shared with them, and everyone else's (open read-only, or 申请权限). A project opens at /p/<id>/, the usual conversation shell.
   Pages by hash: #claude 「我的 agent」 (Claude Code, Codex, OpenCode, Gemini CLI or DeepSeek Harness; paste a subscription token or an API key, never shown again; or 「用 ChatGPT 登录 Codex」:
   the server's device-auth link + one-time code, polled until done), #password, #admin 「用户管理」.
   UI text goes through t() (i18n.js). */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function api(u, body) {
  const o = body === undefined ? { headers: { "X-Lang": M2W.lang } } : { method: "POST", headers: { "Content-Type": "application/json", "X-Lang": M2W.lang }, body: JSON.stringify(body) };
  const r = await fetch(u, o); let j;
  try { j = await r.json(); } catch (e) { j = { ok: false, error: t("服务没有回应（{s}）", { s: r.status }) }; }
  j._status = r.status; return j;
}
const KIND = { memory: "回忆项目", feature: "功能项目", adaptation: "改编项目", gameplay: "玩法项目" };
const ROLE = { view: "查看", comment: "评论", edit: "编辑", owner: "所有者" };
const ROLES = ["view", "comment", "edit"];
const STATE = { pending: "申请中", approved: "已同意", denied: "没同意", replaced: "申请中" };
let D = null, ERR = "";
const PAGES = { claude: paintClaude, password: paintPassword, admin: paintAdmin };
const route = () => (location.hash || "").replace(/^#/, "");

async function boot() {
  const d = await api("/api/hub");
  if (d._status === 401) { D = null; return paintLogin(); }
  D = d; const pg = PAGES[route()];
  if (pg && !(route() === "admin" && !D.user.admin)) return pg(); paint();
}
const topbar = right => `<div class="top"><a class="brand" href="#"><span class="logo"><i></i></span><span>Game<b>Anything</b></span></a><div class="me">${right || ""}${langSwitchHtml()}</div></div>`;
/* the signed-in header: who, the account pages, log out */
function userbar() {
  const cur = route(), lk = (h, s) => `<a class="nav ${cur === h ? "on" : ""}" href="#${h}">${s}</a>`;
  return topbar(`<span>${esc(D.user.display)}${D.user.admin ? ` · ${t("管理员")}` : ""}</span>${lk("", t("项目"))}${lk("claude", t("我的 agent"))}`
    + `${D.user.admin ? lk("admin", t("用户管理")) : ""}${lk("password", t("改密码"))}<button class="btn sm ghost" id="out">${t("退出登录")}</button>`);
}
function wireTop() {
  wireLangSwitch($("#app"));
  $("#out").onclick = async () => { await api("/api/logout", {}); D = null; history.replaceState(null, "", location.pathname); paintLogin(); };
}
/* an in-page confirm: -> Promise<bool> */
function ask(msg, ok, danger = true) {
  return new Promise(res => {
    const el = document.createElement("div"); el.className = "modal";
    el.innerHTML = `<div class="dlg" role="dialog" aria-modal="true"><p>${msg}</p><div class="acts"><button class="btn sm ghost" data-no>${t("取消")}</button>
      <button class="btn sm ${danger ? "danger" : ""}" data-yes>${esc(ok)}</button></div></div>`;
    const done = v => { el.remove(); document.removeEventListener("keydown", key); res(v); };
    const key = e => { if (e.key === "Escape") done(false); };
    el.onclick = e => { if (e.target === el) done(false); }; $("[data-no]", el).onclick = () => done(false); $("[data-yes]", el).onclick = () => done(true);
    document.addEventListener("keydown", key); document.body.appendChild(el); $("[data-yes]", el).focus();
  });
}

function paintLogin() {
  $("#app").innerHTML = topbar() + `<div class="box login"><h2>${t("登录")}</h2>
    <label class="fld">${t("用户名")}<input class="inp" id="lname" autocomplete="username" autocapitalize="off"></label>
    <label class="fld">${t("密码")}<input class="inp" id="lpw" type="password" autocomplete="current-password"></label>
    <button class="btn" id="lgo">${t("登录")}</button><div class="bad" id="lerr">${esc(ERR)}</div>
    <p class="note">${t("账号由管理员添加；忘了密码请找管理员重置。")}</p></div>`;
  wireLangSwitch($("#app"));
  const go = async () => {
    const r = await api("/api/login", { name: $("#lname").value.trim(), password: $("#lpw").value });
    if (!r.ok) { ERR = r.error || t("没能登录"); $("#lerr").textContent = ERR; return; }
    const next = new URLSearchParams(location.search).get("next") || "";
    ERR = ""; if (/^\/p\/[\w.-]+\//.test(next)) location.href = next; else if (location.pathname !== "/") location.href = "/" + location.hash; else boot();
  };
  $("#lgo").onclick = go; $("#lpw").onkeydown = e => { if (e.key === "Enter") go(); }; $("#lname").focus();
}

const sub = p => `${esc((D.games || {})[p.game] || p.game)} · ${t(KIND[p.kind] || KIND.memory)}`;
function reqTag(r) {
  if (!r) return "";
  return `<span class="tag ${r.state === "denied" ? "warn" : r.state === "approved" ? "" : "grey"}">${esc(t(STATE[r.state] || r.state))} · ${esc(t(ROLE[r.role] || r.role))}</span>`;
}
function mineHtml(p) {
  const others = (D.users || []).filter(u => u.name !== D.user.name && !(p.members || []).some(m => m.name === u.name));
  const sel = (cur, attr) => `<select ${attr}>${ROLES.map(r => `<option value="${r}" ${r === cur ? "selected" : ""}>${esc(t(ROLE[r]))}</option>`).join("")}</select>`;
  return `<div class="p" data-id="${esc(p.id)}"><div class="h"><a class="t" href="/p/${encodeURIComponent(p.id)}/">${esc(p.title)}</a><small>${sub(p)}</small>
      <span class="right">${p.private ? `<span class="tag grey">${t("私有")}</span>` : ""}${p.pending ? `<span class="tag warn">${t("{n} 个权限申请，在对话里处理", { n: p.pending })}</span>` : ""}
      <a class="btn sm" href="/p/${encodeURIComponent(p.id)}/">${t("打开")}</a></span></div>
    <div class="mem">${(p.members || []).length ? "" : `<span class="muted">${t("还没有共享给别人")}</span>`}
      ${(p.members || []).map(m => `<div class="m"><span>${m.removed ? esc(t("已移除用户")) + ` <small class="muted">(${esc(m.name)})</small>` : esc(m.display)}</span>${sel(m.role, `data-mem="${esc(m.name)}"`)}<button class="lnk" data-rm="${esc(m.name)}">${t("移除")}</button></div>`).join("")}
      ${others.length ? `<div class="m"><select data-add>${others.map(u => `<option value="${esc(u.name)}">${esc(u.display)}</option>`).join("")}</select>${sel("view", "data-addrole")}<button class="lnk" data-addgo>${t("加成员")}</button></div>` : ""}
    </div></div>`;
}
function otherHtml(p) {
  const can = ROLES.filter(r => ROLES.indexOf(r) > ROLES.indexOf(p.role));
  const open = p.role ? `<a class="btn sm ${p.role === "view" ? "ghost" : ""}" href="/p/${encodeURIComponent(p.id)}/">${p.role === "view" ? t("只读打开") : t("打开")}</a>` : `<span class="tag grey">${t("私有 · 可申请")}</span>`;
  return `<div class="p" data-id="${esc(p.id)}"><div class="h"><a class="t" ${p.role ? `href="/p/${encodeURIComponent(p.id)}/"` : ""}>${p.title_hidden ? `<i class="muted">${t("私有项目")}</i>` : esc(p.title)}</a><small>${sub(p)} · ${t("所有者：{n}", { n: p.owner_removed ? t("已移除用户") : p.owner_name || p.owner || "-" })}</small>
      <span class="right">${p.role && p.role !== "view" ? `<span class="tag">${esc(t(ROLE[p.role]))}</span>` : ""}${reqTag(p.request)}${open}
      ${can.length && !(p.request && p.request.state === "pending") ? `<button class="btn sm ghost" data-ask>${t("申请权限")}</button>` : ""}</span></div><div data-askbox></div></div>`;
}
function paint() {
  const mine = D.projects.filter(p => p.section === "mine"), shared = D.projects.filter(p => p.section === "shared"), others = D.projects.filter(p => p.section === "others");
  const ORDER = ["memory", "adaptation", "feature", "gameplay"];   // the main kinds first
  const kinds = [...(D.kinds || [])].sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99)).map(k => `<option value="${k}">${esc(t(KIND[k]))}</option>`).join("");
  const games = Object.entries(D.games || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#app").innerHTML = userbar()
    + (D.user.claude_login ? "" : `<a class="warnbox go" href="#claude">${t("你的 agent 还没连上：你的项目里 agent 暂时不会回复。去连接 →")}</a>`)
    + `<div class="box"><h2>${t("新项目")}</h2><div class="row"><label class="fld">${t("项目名")}<input class="inp" id="ntitle"></label>
        <label class="fld">${t("类型")}<select class="inp" id="nkind">${kinds}</select></label><label class="fld">${t("游戏")}<select class="inp" id="ngame">${games}</select></label>
        <label class="fld">${t("在哪里做")}<select class="inp" id="nmode"><option value="lab">${t("沙箱（镜像）")}</option><option value="native">${t("我的电脑（本机）")}</option></select></label>
        <button class="btn" id="ngo">${t("创建")}</button></div><div class="bad" id="nerr"></div></div>
      <h3>${t("我的项目")}</h3>${mine.map(mineHtml).join("") || `<p class="muted">${t("还没有项目")}</p>`}
      ${shared.length ? `<h3>${t("共享给我的")}</h3>${shared.map(otherHtml).join("")}` : ""}
      ${others.length ? `<h3>${t("其他人的项目")}</h3>${others.map(otherHtml).join("")}` : ""}
      <p class="note">${t("权限只管这个网页里能做什么：服务器上大家都是同一个系统账号，能直接读写所有文件，这不是系统级的隔离。")}<br>
        ${t("别人在你的项目里说话时，agent 用的是你的 Claude 登录和额度。")}</p>`;
  wireTop();
  $("#nkind").onchange = () => { const g = (D.default_game || {})[$("#nkind").value]; if (g) $("#ngame").value = g; };
  $("#ngo").onclick = async () => {
    const title = $("#ntitle").value.trim(); if (!title) { $("#nerr").textContent = t("给项目起个名字"); return; }
    $("#ngo").disabled = true;
    const r = await api("/api/hub/new", { title, kind: $("#nkind").value, game: $("#ngame").value, mode: $("#nmode").value, lang: M2W.lang });
    if (!r.ok) { $("#ngo").disabled = false; $("#nerr").textContent = r.error || t("没能发出去"); return; }
    location.href = r.go;
  };
  $$(".p").forEach(el => {
    const id = el.dataset.id, mem = (user, role) => api("/api/members", { project: id, user, role }).then(r => r.ok ? boot() : alert(r.error));
    $$("[data-mem]", el).forEach(s => s.onchange = () => mem(s.dataset.mem, s.value));
    $$("[data-rm]", el).forEach(b => b.onclick = async () => { if (await ask(t("把这个成员从项目里移除？"), t("移除"))) mem(b.dataset.rm, null); });
    const add = $("[data-addgo]", el); if (add) add.onclick = () => mem($("[data-add]", el).value, $("[data-addrole]", el).value);
    const ask = $("[data-ask]", el); if (!ask) return;
    ask.onclick = () => {
      const p = D.projects.find(x => x.id === id), can = ROLES.filter(r => ROLES.indexOf(r) > ROLES.indexOf(p.role));
      $("[data-askbox]", el).innerHTML = `<div class="ask"><select class="inp" data-role>${can.map(r => `<option value="${r}" ${r === "edit" ? "selected" : ""}>${esc(t(ROLE[r]))}</option>`).join("")}</select>
        <textarea class="inp" rows="2" data-note placeholder="${esc(t("想对所有者说一句（可选）"))}"></textarea>
        <small class="muted">${t("所有者会在自己的对话里看到一张卡片，同意后你就有这个权限。你说的话由所有者的 Claude 额度回答。")}</small>
        <div><button class="btn sm" data-send>${t("发送申请")}</button> <span class="bad" data-err></span></div></div>`;
      $("[data-send]", el).onclick = async () => {
        const r = await api("/api/access/request", { project: id, role: $("[data-role]", el).value, note: $("[data-note]", el).value });
        if (!r.ok) { $("[data-err]", el).textContent = r.error || t("没能发出去"); return; }
        boot();
      };
    };
  });
}

/* ---------------------------------------------------------------- 「我的 agent」: Claude Code or Codex, a subscription / login or an API key */
const KIND_ZH = { subscription: "订阅 token（你自己的 Claude Pro / Max 额度）", api_key: "API key（按用量计费）", login: "服务器上的 Claude 登录" };
const CODEX_KIND_ZH = { api_key: "OpenAI API key（按用量计费）", login: "你自己的 Codex / ChatGPT 登录" };
const OPENCODE_KIND_ZH = { api_key: "模型服务的 API key（按 token 计费）", login: "服务器上的 OpenCode 登录" };
const GEMINI_KIND_ZH = { api_key: "Gemini API key（按 token 计费）", login: "你自己的 Google 登录" };
const DSH_KIND_ZH = { api_key: "DeepSeek 或 OpenRouter 的 API key（按 token 计费）" };
const AGENT_ZH = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", gemini: "Gemini CLI", dsh: "DeepSeek Harness" };
const KINDS = { "claude-code": KIND_ZH, codex: CODEX_KIND_ZH, opencode: OPENCODE_KIND_ZH, gemini: GEMINI_KIND_ZH, dsh: DSH_KIND_ZH };
async function paintClaude(msg) {
  const r = await api("/api/me/claude"); if (r._status === 401) return paintLogin();
  const A = r.agent || { agent: "claude-code", claude: r.claude || {}, codex: {} }; const c = A.claude || {}, x = A.codex || {};
  const o = A.opencode || {}, g = A.gemini || {}, ds = A.dsh || {};
  const codex = A.agent === "codex"; const cur = { codex: x, opencode: o, gemini: g, dsh: ds }[A.agent] || c;
  D.user.claude_login = !!A.connected; D.user.claude = c; D.user.agent = A;
  const kindText = (KINDS[A.agent] || KIND_ZH)[cur.kind];
  const st = cur.connected
    ? `<span class="tag ok">${t("已连接")}</span> ${esc(AGENT_ZH[A.agent])} · ${esc(t(kindText || cur.kind))}${cur.last4 ? ` · ${t("末尾 {s}", { s: cur.last4 })}` : ""}`
    : `<span class="tag warn">${t("还没连上")}</span> ${t("你的项目里 agent 暂时不会回复。")}`;
  const field = (k, ph) => `<div class="row"><label class="fld">${t("粘贴到这里")}<input class="inp mono" type="password" autocomplete="off" spellcheck="false" data-tok="${k}" placeholder="${ph}"></label>
    <button class="btn" data-save="${k}">${t("保存")}</button></div><div class="bad" data-err="${k}"></div>`;
  const pick = a => `<button class="btn sm ${A.agent === a ? "" : "ghost"}" data-agent="${a}" ${A.agent === a ? "disabled" : ""}>${esc(AGENT_ZH[a])}</button>`;
  const claudeBoxes = `<div class="box"><h2>${t("方式一：订阅（推荐）")}</h2>
      <p class="muted">${t("用你自己的 Claude Pro / Max 订阅额度，不另外花钱。")}</p>
      <ol class="steps"><li>${t("在你自己的电脑上打开终端。还没有 claude 命令行工具的话先装：")}<code>npm install -g @anthropic-ai/claude-code</code></li>
        <li>${t("运行")} <code>claude setup-token</code>${t("，在弹出的浏览器里登录你自己的 Claude 账号。")}</li>
        <li>${t("终端里会打出一长串以 sk-ant-oat 开头的 token（有效期一年）。整段复制，粘贴到下面，点保存。")}</li></ol>
      ${field("subscription", "sk-ant-oat…")}</div>
    <div class="box"><h2>${t("方式二：API key（按用量计费）")}</h2>
      <p class="muted">${t("在 console.anthropic.com 的 API Keys 里新建一个 key（以 sk-ant-api 开头），粘贴到下面。按实际用量从你的 Anthropic 账户扣钱，不走订阅额度。")}</p>
      ${field("api_key", "sk-ant-api…")}</div>`;
  const codexBoxes = `<div class="box"><h2>${t("方式一：Codex / ChatGPT 登录（用你的 ChatGPT 订阅额度）")}</h2>
      <p class="muted">${t("点下面的按钮，服务器会为你开始一次 Codex 登录：打开它给的链接，用你自己的 ChatGPT 账号登录，再输入页面上的一次性代码。登录只存在你自己的文件夹里。")}</p>
      <p class="muted">${x.login ? `<span class="tag ok">${t("已登录")}</span>` : `<span class="tag warn">${t("还没登录")}</span>`}</p>
      <div id="cxlogin"><div class="acts"><button class="btn" id="cxstart">${t(x.login ? "重新用 ChatGPT 登录" : "用 ChatGPT 登录 Codex")}</button></div></div>
      <p class="muted">${t("也可以请管理员在服务器上运行：")}<code>gameanything hub user login ${esc(D.user.name)} --agent codex</code></p></div>
    <div class="box"><h2>${t("方式二：OpenAI API key（按用量计费）")}</h2>
      <p class="muted">${t("在 platform.openai.com 的 API keys 里新建一个 key（以 sk- 开头），粘贴到下面。按实际用量从你的 OpenAI 账户扣钱，不走订阅额度。")}</p>
      ${field("codex", "sk-…")}</div>`;
  const modelRow = (k, v, ph) => `<div class="row"><label class="fld">${t("模型")}<input class="inp mono" autocomplete="off" spellcheck="false" data-model="${k}" value="${esc(v || "")}" placeholder="${esc(ph)}"></label>
    <button class="btn ghost" data-setmodel="${k}">${t("只改模型")}</button></div>`;
  const opencodeBoxes = `<div class="box"><h2>${t("用一个模型服务的 API key（按 token 计费）")}</h2>
      <p class="muted">${t("OpenCode 能连 75 家以上的模型服务。最简单的是 OpenRouter：在 openrouter.ai/keys 新建一个 key（以 sk-or- 开头），粘贴到下面。一个 key 就能用很多家的模型，按实际用量从你的 OpenRouter 余额扣钱。")}</p>
      ${modelRow("opencode", o.model, "openrouter/moonshotai/kimi-k2.6")}
      <p class="muted">${t("模型写成 provider/model。用 OpenRouter 时是 openrouter/ 加上 OpenRouter 网站上的模型名。别的服务也行（例如 anthropic/…、deepseek/…），粘贴那家的 key 就好。")}</p>
      ${field("opencode", "sk-or-…")}</div>`;
  const geminiBoxes = `<div class="box"><h2>${t("方式一：Gemini API key（按 token 计费）")}</h2>
      <p class="muted">${t("在 aistudio.google.com 的 API keys 里新建一个 key（通常以 AIza 开头），粘贴到下面。按实际用量从你的 Google 账户扣钱（免费额度用完之后）。")}</p>
      ${field("gemini", "AIza…")}
      ${modelRow("gemini", g.model, "gemini-3.1-pro-preview")}
      <p class="muted">${t("模型可以不填：用 gemini-3.5-flash。")}</p></div>
    <div class="box"><h2>${t("方式二：你自己的 Google 登录")}</h2>
      <p class="muted">${g.login ? `<span class="tag ok">${t("已登录")}</span>` : `<span class="tag warn">${t("还没登录")}</span>`}</p>
      <p class="muted">${t("请管理员在服务器上运行：")}<code>gameanything hub user login ${esc(D.user.name)} --agent gemini</code></p></div>`;
  const dshBoxes = `<div class="box"><h2>${t("DeepSeek 或 OpenRouter 的 API key（按 token 计费）")}</h2>
      <p class="muted">${t("DeepSeek 自己的 key：在 platform.deepseek.com 新建（以 sk- 开头），模型可以不填（用 deepseek-v4-pro），想更便宜可以填 deepseek-flash。")}</p>
      <p class="muted">${t("OpenRouter 的 key（以 sk-or- 开头）：模型写成 openrouter/ 加上 OpenRouter 上的模型名，例如 openrouter/deepseek/deepseek-v4.1-flash。联网搜索用同一个 key 走 OpenRouter 上的 perplexity/sonar（每次约半美分）。")}</p>
      ${modelRow("dsh", ds.model, "deepseek-v4-pro")}
      ${field("dsh", ds.key_name === "OPENROUTER_API_KEY" ? "sk-or-…" : "sk-…")}</div>`;
  $("#app").innerHTML = userbar() + `<div class="box"><h2>${t("我的 agent")}</h2>
      <p class="muted">${t("你项目里的 agent（回复你、做构建）用你自己的账号跑。选一个，再连接一次就行，以后不用再管。")}</p>
      <div class="acts">${t("用哪个：")} ${pick("claude-code")} ${pick("codex")} ${pick("opencode")} ${pick("gemini")} ${pick("dsh")}</div>
      <div class="status">${st}</div>
      <div class="acts">${cur.connected ? `<button class="btn sm ghost" id="ctest">${t("测试连接")}</button>` : ""}
        ${(A.agent === "claude-code" && (c.kind === "subscription" || c.kind === "api_key")) || (A.agent !== "claude-code" && cur.kind === "api_key") ? `<button class="btn sm ghost danger-t" id="cdrop">${t("断开")}</button>` : ""}</div>
      <div id="cres" class="res">${msg || ""}</div></div>
    ${{ codex: codexBoxes, opencode: opencodeBoxes, gemini: geminiBoxes, dsh: dshBoxes }[A.agent] || claudeBoxes}
    <p class="note">${t("API key 按 token 计费：每次回复、每次构建都从你的账户扣钱。开工前，开工卡上会先写出这一期大约要多少钱和多久，你点了开工才会开始。")}</p>
    <p class="note">${t("保存在服务器上只属于你的文件里（权限 0600），网页上只显示最后 4 位，不会再显示完整内容。注意：服务器上大家都是同一个系统账号，管理员能读到这个文件。")}</p>
    <div class="box" id="genkeys"></div>`;
  wireTop(); paintGenKeys();
  $$("[data-agent]").forEach(b => b.onclick = async () => {
    b.disabled = true; const y = await api("/api/me/agent", { agent: b.dataset.agent });
    if (!y.ok) { b.disabled = false; $("#cres").innerHTML = `<span class="bad">${esc(y.error)}</span>`; return; }
    paintClaude();
  });
  $$("[data-save]").forEach(b => b.onclick = async () => {
    const k = b.dataset.save, inp = $(`[data-tok="${k}"]`), e = $(`[data-err="${k}"]`);
    if (!inp.value.trim()) { e.textContent = t("请先粘贴"); return; }
    if (cur.connected && cur.kind !== "login" && !(await ask(t("替换现在的连接？"), t("替换"), false))) return;
    b.disabled = true;
    const mi = $(`[data-model="${k}"]`);
    const y = k === "codex" ? await api("/api/me/codex", { token: inp.value })
      : k === "opencode" ? await api("/api/me/opencode", { token: inp.value, model: mi ? mi.value.trim() : "" })
      : k === "gemini" ? await api("/api/me/gemini", { token: inp.value })
      : k === "dsh" ? await api("/api/me/dsh", { token: inp.value, model: mi ? mi.value.trim() : "" })
      : await api("/api/me/claude", { kind: k, token: inp.value });
    b.disabled = false;
    if (!y.ok) { e.textContent = y.error || t("没能保存"); return; }
    inp.value = ""; paintClaude(`<span class="okt">${t("已保存。点「测试连接」确认能用。")}</span>`);
  });
  $$("[data-setmodel]").forEach(b => b.onclick = async () => {
    const k = b.dataset.setmodel, mi = $(`[data-model="${k}"]`); b.disabled = true;
    const y = await api("/api/me/model", { agent: k, model: mi.value.trim() }); b.disabled = false;
    $("#cres").innerHTML = y.ok ? `<span class="okt">${t("模型已保存。")}</span>` : `<span class="bad">${esc(y.error)}</span>`;
  });
  const tb = $("#ctest"); if (tb) tb.onclick = async () => {
    tb.disabled = true; $("#cres").innerHTML = `<span class="muted">${t("正在测试，最多一分钟…")}</span>`;
    const y = await api("/api/me/claude/test", {}); tb.disabled = false;
    if (!y.ok) { $("#cres").innerHTML = `<span class="bad">${esc(y.error)}</span>`; return; }
    const okText = { codex: "连接正常：Codex 回复了", opencode: "连接正常：OpenCode 回复了", gemini: "连接正常：Gemini 回复了",
      dsh: "连接正常：DeepSeek Harness 回复了" }[A.agent] || "连接正常：Claude 回复了";
    $("#cres").innerHTML = y.test.ok ? `<span class="okt">${t(okText)}「${esc(y.test.text)}」</span>`
      : `<span class="bad">${t("没能连上：")}</span><pre class="err">${esc(y.test.text)}</pre>`;
  };
  const db = $("#cdrop"); if (db) db.onclick = async () => {
    if (!(await ask(t("断开后，你项目里的 agent 不会再回复，直到你重新连接。确定断开？"), t("断开")))) return;
    const y = await api(A.agent === "claude-code" ? "/api/me/claude/disconnect" : `/api/me/${A.agent}/disconnect`, {}); if (!y.ok) return alert(y.error); paintClaude();
  };
  if (codex) wireCodexLogin();
}

/* 「素材生成 API keys」: keys for pictures / 3D / sound (gameanything gen); only whether each one is saved is shown, never the value */
const GEN_KEY_HINT = { FAL_KEY: "fal.ai → Dashboard → Keys", MESHY_API_KEY: "meshy.ai → Settings → API",
  OPENAI_API_KEY: "platform.openai.com → API keys", OPENROUTER_API_KEY: "openrouter.ai → Settings → Keys" };
async function paintGenKeys(msg) {
  const box = $("#genkeys"); if (!box) return;
  const r = await api("/api/me/genkeys"); if (!r.ok) { box.innerHTML = ""; return; }
  const row = k => `<div class="row"><span class="fld" style="min-width:9em"><b>${esc(k.title)}</b> <code>${esc(k.name)}</code><br>
      ${k.set ? `<span class="tag ok">${t("已保存")}</span>` : `<span class="tag warn">${t("没有")}</span>`}
      <span class="muted">${esc(GEN_KEY_HINT[k.name] || "")}</span>${k.codex ? `<br><span class="muted">${t("也是 Codex 用的 OpenAI key：删掉它 Codex 的 API key 方式也会断开。")}</span>` : ""}</span>
    <label class="fld">${t("粘贴到这里")}<input class="inp mono" type="password" autocomplete="off" spellcheck="false" data-gk="${esc(k.name)}"></label>
    <button class="btn sm" data-gksave="${esc(k.name)}">${t("保存")}</button>
    ${k.set ? `<button class="btn sm ghost danger-t" data-gkdrop="${esc(k.name)}">${t("删除")}</button>` : ""}</div>`;
  box.innerHTML = `<h2>${t("素材生成 API keys")}</h2>
    <p class="muted">${t("画预览图、做 3D 模型和声音时用你自己的 key。agent 自己拿不到这些 key：只有你在许可卡上同意、在开工卡上点了开工以后，后台才会用它们生成，每次发送都记在隐私记录里。")}</p>
    ${r.keys.map(row).join("")}<div id="gkres" class="res">${msg || ""}</div>`;
  $$("[data-gksave]").forEach(b => b.onclick = async () => {
    const k = b.dataset.gksave, inp = $(`[data-gk="${k}"]`);
    if (!inp.value.trim()) { $("#gkres").innerHTML = `<span class="bad">${t("请先粘贴")}</span>`; return; }
    b.disabled = true; const y = await api("/api/me/genkeys", { key: k, value: inp.value }); b.disabled = false; inp.value = "";
    if (!y.ok) { $("#gkres").innerHTML = `<span class="bad">${esc(y.error || t("没能保存"))}</span>`; return; }
    paintGenKeys(`<span class="okt">${t("已保存。")}</span>`);
  });
  $$("[data-gkdrop]").forEach(b => b.onclick = async () => {
    if (!(await ask(t("删除这个 key？以后用它的生成会被拒绝，直到你重新保存。"), t("删除")))) return;
    const y = await api("/api/me/genkeys/remove", { key: b.dataset.gkdrop }); if (!y.ok) return alert(y.error); paintGenKeys();
  });
}

/* 「用 ChatGPT 登录 Codex」: the server runs `codex login --device-auth` for her; the page shows its link and one-time code and polls */
let CX_POLL = null;
const CX_END = { failed: "登录没有完成（codex 退出了）。可以再试一次。", expired: "一次性代码过期了（15 分钟）。可以再试一次。", cancelled: "已取消登录。" };
function paintCodexLogin(lg) {
  const box = $("#cxlogin"); if (!box) { clearTimeout(CX_POLL); CX_POLL = null; return false; }
  if (lg.state === "done") { clearTimeout(CX_POLL); CX_POLL = null; paintClaude(`<span class="okt">${t("Codex 已经用你的 ChatGPT 账号登录好了。点「测试连接」确认能用。")}</span>`); return false; }
  if (lg.state === "starting") box.innerHTML = `<p class="muted">${t("正在启动 Codex 登录…")}</p><div class="acts"><button class="btn sm ghost" id="cxcancel">${t("取消")}</button></div>`;
  else if (lg.state === "waiting") {
    const mins = Math.max(0, Math.round((lg.expires * 1000 - Date.now()) / 60000));
    box.innerHTML = `<ol class="steps"><li>${t("打开这个链接（新标签页），用你自己的 ChatGPT 账号登录：")}<br><a href="${esc(lg.url)}" target="_blank" rel="noopener noreferrer">${esc(lg.url)}</a></li>
        <li>${t("输入这个一次性代码：")}<br><code class="mono" style="font-size:18px;letter-spacing:2px">${esc(lg.code)}</code>
          <span class="muted">${t("（大约 {n} 分钟内有效）", { n: mins })}</span></li>
        <li>${t("登录好以后这一页会自己更新，不用再做别的。")}</li></ol>
      <p class="muted">${t("只有你自己开始的这次登录才输入代码。别人发给你的代码不要输入。")}</p>
      <div class="acts"><button class="btn sm ghost" id="cxcancel">${t("取消")}</button></div>`;
  } else {
    box.innerHTML = `${CX_END[lg.state] ? `<p class="${lg.state === "cancelled" ? "muted" : "bad"}">${t(CX_END[lg.state])}</p>` : ""}
      <div class="acts"><button class="btn" id="cxstart">${t(lg.codex && lg.codex.login ? "重新用 ChatGPT 登录" : "用 ChatGPT 登录 Codex")}</button></div>`;
  }
  wireCodexLogin(false);
  return lg.state === "starting" || lg.state === "waiting";
}
function pollCodexLogin() {
  clearTimeout(CX_POLL);
  CX_POLL = setTimeout(async () => {
    if (!$("#cxlogin")) { CX_POLL = null; return; }
    const y = await api("/api/me/codex/login"); if (y._status === 401) return paintLogin();
    if (y.ok && paintCodexLogin(y.login)) pollCodexLogin();
  }, 2000);
}
function wireCodexLogin(check = true) {
  const sb = $("#cxstart"); if (sb) sb.onclick = async () => {
    if ((D.user.agent || {}).codex && D.user.agent.codex.login && !(await ask(t("重新登录会替换你现在的 Codex 登录。继续？"), t("继续"), false))) return;
    sb.disabled = true; const y = await api("/api/me/codex/login", {});
    if (!y.ok) { sb.disabled = false; $("#cres").innerHTML = `<span class="bad">${esc(y.error)}</span>`; return; }
    if (paintCodexLogin(y.login)) pollCodexLogin();
  };
  const cb = $("#cxcancel"); if (cb) cb.onclick = async () => {
    cb.disabled = true; clearTimeout(CX_POLL); CX_POLL = null;
    const y = await api("/api/me/codex/login/cancel", {}); if (y.ok) paintCodexLogin(y.login);
  };
  if (check) api("/api/me/codex/login").then(y => { if (y.ok && (y.login.state === "starting" || y.login.state === "waiting") && paintCodexLogin(y.login)) pollCodexLogin(); });
}

/* ---------------------------------------------------------------- change one's own password */
function paintPassword() {
  $("#app").innerHTML = userbar() + `<div class="box narrow"><h2>${t("改密码")}</h2>
    <label class="fld">${t("现在的密码")}<input class="inp" id="pold" type="password" autocomplete="current-password"></label>
    <label class="fld">${t("新密码（至少 8 个字符）")}<input class="inp" id="pnew" type="password" autocomplete="new-password"></label>
    <label class="fld">${t("再输一次新密码")}<input class="inp" id="pnew2" type="password" autocomplete="new-password"></label>
    <button class="btn" id="pgo">${t("改密码")}</button><div class="bad" id="perr"></div><div id="pok"></div>
    <p class="note">${t("改了以后，你在其他浏览器里的登录都会退出。")}</p></div>`;
  wireTop();
  $("#pgo").onclick = async () => {
    const o = $("#pold").value, n = $("#pnew").value; $("#perr").textContent = ""; $("#pok").innerHTML = "";
    if (n !== $("#pnew2").value) { $("#perr").textContent = t("两次输入的新密码不一样"); return; }
    const r = await api("/api/me/password", { old: o, new: n });
    if (!r.ok) { $("#perr").textContent = r.error || t("没能改"); return; }
    $$("#app input").forEach(i => i.value = ""); $("#pok").innerHTML = `<p class="okt">${t("密码已改好。")}</p>`;
  };
}

/* ---------------------------------------------------------------- 「用户管理」 (admins) */
const once = (who, pw) => `<div class="once"><b>${t("{n} 的密码（只显示这一次，请现在复制发给 TA）：", { n: esc(who) })}</b><code class="pw">${esc(pw)}</code>
  <button class="btn sm ghost" data-copy="${esc(pw)}">${t("复制")}</button></div>`;
async function paintAdmin(msg) {
  const r = await api("/api/admin/users");
  if (r._status === 401) return paintLogin();
  if (!r.ok) { $("#app").innerHTML = userbar() + `<div class="box"><p class="bad">${esc(r.error)}</p></div>`; wireTop(); return; }
  const row = u => `<tr data-u="${esc(u.name)}"><td><b>${esc(u.display)}</b><br><small class="muted">${esc(u.name)}${u.me ? " · " + t("你") : ""}</small></td>
    <td>${u.admin ? `<span class="tag">${t("管理员")}</span>` : `<span class="muted">-</span>`}</td>
    <td>${u.claude ? `<span class="tag ok">${t("已连接")}</span>` : `<span class="tag warn">${t("没连")}</span>`}</td>
    <td>${u.projects}</td><td><small class="muted">${esc((u.created || "").slice(0, 10))}</small></td>
    <td class="ops"><button class="lnk" data-op="passwd">${t("重置密码")}</button>
      ${u.me ? "" : `<button class="lnk" data-op="admin">${u.admin ? t("取消管理员") : t("设为管理员")}</button><button class="lnk danger-t" data-op="remove">${t("移除")}</button>`}</td></tr>`;
  $("#app").innerHTML = userbar() + `<div id="amsg">${msg || ""}</div>
    <div class="box"><h2>${t("加用户")}</h2><div class="row">
      <label class="fld">${t("用户名（小写字母、数字）")}<input class="inp" id="aname" autocapitalize="off" spellcheck="false"></label>
      <label class="fld">${t("显示名")}<input class="inp" id="adisp"></label>
      <label class="fld">${t("初始密码（留空自动生成）")}<input class="inp" id="apw" type="password" autocomplete="new-password"></label></div>
      <label class="chk"><input type="checkbox" id="aadm"> ${t("管理员")}</label>
      <div class="acts"><button class="btn" id="ago">${t("添加")}</button></div><div class="bad" id="aerr"></div></div>
    <div class="box"><h2>${t("用户")}</h2><div class="tblw"><table class="tbl"><thead><tr><th>${t("用户")}</th><th>${t("身份")}</th><th>Claude</th><th>${t("项目")}</th><th>${t("添加于")}</th><th></th></tr></thead>
      <tbody>${r.users.map(row).join("")}</tbody></table></div>
      ${(r.removed || []).length ? `<h3>${t("已移除用户的项目")}</h3><p class="muted">${r.removed.map(x => t("{u}：{n} 个项目（还在磁盘上，agent 不会运行）", { u: esc(x.name), n: x.projects })).join("<br>")}</p>` : ""}
      <p class="note">${t("移除用户：TA 的项目留在磁盘上，所有者不变，列表里显示为「已移除用户」。重置密码会让 TA 在所有地方退出登录。")}</p></div>`;
  wireTop();
  $$("[data-copy]").forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.copy); b.textContent = t("已复制"); } catch (e) {} });
  $("#ago").onclick = async () => {
    const name = $("#aname").value.trim().toLowerCase(), pw = $("#apw").value;
    if (!name) { $("#aerr").textContent = t("填用户名"); return; }
    const x = await api("/api/admin/user/add", { name, display: $("#adisp").value.trim(), password: pw, admin: $("#aadm").checked });
    if (!x.ok) { $("#aerr").textContent = x.error || t("没能添加"); return; }
    paintAdmin(`<div class="box okbox"><p>${t("已添加 {n}。请把网址、用户名和密码发给 TA；TA 登录后在「我的 Claude」里连上自己的 Claude。", { n: esc(x.name) })}</p>${x.password ? once(x.name, x.password) : ""}</div>`);
  };
  $$("tr[data-u]").forEach(tr => {
    const name = tr.dataset.u, u = r.users.find(x => x.name === name);
    $$("[data-op]", tr).forEach(b => b.onclick = async () => {
      const op = b.dataset.op; let body = { name };
      if (op === "passwd") {
        if (!(await ask(t("给 {n} 生成一个新密码？TA 会在所有地方退出登录。", { n: esc(u.display) }), t("重置密码")))) return;
      } else if (op === "remove") {
        if (!(await ask(t("移除用户 {n}？TA 不能再登录；TA 的项目留在磁盘上，显示为「已移除用户」。", { n: esc(u.display) }), t("移除")))) return;
      } else if (op === "admin") {
        if (!(await ask(u.admin ? t("取消 {n} 的管理员？", { n: esc(u.display) }) : t("把 {n} 设为管理员？管理员能加、删用户和改全局设置。", { n: esc(u.display) }), t("确认"), u.admin))) return;
        body.admin = !u.admin;
      }
      const x = await api(`/api/admin/user/${op}`, body);
      if (!x.ok) return paintAdmin(`<div class="box"><p class="bad">${esc(x.error)}</p></div>`);
      paintAdmin(op === "passwd" && x.password ? `<div class="box okbox">${once(u.display, x.password)}</div>` : "");
    });
  });
}

window.addEventListener("hashchange", () => { if (D) boot(); });
M2W.apply(); M2W.onLang(() => { if (!D) return paintLogin(); const pg = PAGES[route()]; pg ? pg() : paint(); });
boot();
