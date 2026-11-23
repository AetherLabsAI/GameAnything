/* Demo mode: the real pages, opened from a static folder made by `gameanything demo export` (gameanything/demo.py). Only active when the
   exported page sets window.GA_DEMO before this script; a page served by `gameanything ui` never loads it.
   - every GET the pages make to /api/... is answered from demo-data/<lang>/api/<name>[@<query>].json (the same key demoKey() in demo.py makes)
   - every other root-absolute address (/build/..., /media/..., /conv/..., /fonts/...) is the same file under the demo folder
   - every write (POST, an upload) is refused with a small "This is a demo" toast; nothing leaves the page
   - controls that make no sense without a server (model chips, attachments, project menu, backup, notifications, live view) are hidden */
(function () {
  "use strict";
  var D = window.GA_DEMO; if (!D) return;
  var ROOT = location.pathname.replace(/[^/]*$/, "");            // the folder of this page, e.g. /hlm/
  var LANGS = D.langs || ["zh", "en"];
  var MSG = { zh: "这是演示：只能看，不能修改", en: "This is a demo: you can look around, not change anything" };
  document.documentElement.classList.add("ga-demo");
  var css = document.createElement("style");                     // what needs a server or an account is hidden; the rest looks as usual
  css.textContent = [
    "#pills, #offline, #building, #hubbar, #coachbtn, #mchips, #chips, #ups, .composer label.ic, .composer .hint, #send { display:none !important; }",
    ".projwrap .menu, #projbtn > svg, .lbl2, #newproj, #allproj, .sidefoot #bkstate, .sidefoot br + br, #nbell { display:none !important; }",
    "#drop, #pick, #pickdir, a[href='#prefs'], #nowlive, .nlive, a[href='/looks-old'] { display:none !important; }",
    "#msg { cursor:default; } #msg[readonly] { background:#FAFAFB; }",
    "#ga-demo-tag { position:fixed; right:14px; bottom:12px; z-index:60; font:600 12px/1 Inter, system-ui, sans-serif; color:#5B21B6; background:#F6F3FD;",
    "  border:1px solid #E3DCF4; border-radius:999px; padding:7px 12px; text-decoration:none; box-shadow:0 4px 14px rgba(43,37,64,.10); }",
    "#ga-demo-toast { position:fixed; left:50%; bottom:22px; transform:translateX(-50%); z-index:80; display:none; background:#18181B; color:#fff;",
    "  font:13px/1.4 Inter, system-ui, sans-serif; padding:8px 14px; border-radius:10px; }"].join("\n");
  (document.head || document.documentElement).appendChild(css);

  function lang(h) {
    var l = h && (h["X-Lang"] || h["x-lang"]);
    if (!l) try { l = typeof M2W !== "undefined" && M2W.lang; } catch (e) {}      // M2W is a global const (i18n.js), not on window
    return LANGS.indexOf(l) >= 0 ? l : LANGS[0];
  }
  function demoKey(path, search) {                                // keep in step with demo.py demo_key()
    var q = new URLSearchParams(search || ""), ps = [];
    q.forEach(function (v, k) { if (k !== "after") ps.push([k, v]); });
    ps.sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; });
    var s = path.replace(/^\//, "") + (ps.length ? "@" + ps.map(function (p) { return p[0] + "=" + p[1]; }).join("&") : "");
    return s.replace(/[^A-Za-z0-9._=@&\/-]/g, "_") + ".json";
  }
  // an address the page asks for -> the file in the demo folder (null: not ours, leave it)
  function map(u, h) {
    if (typeof u !== "string" || u.charAt(0) !== "/" || u.charAt(1) === "/" || u.indexOf(ROOT) === 0) return null;
    var x = new URL(u, location.origin);
    if (x.pathname.indexOf("/api/") === 0) return ROOT + "demo-data/" + lang(h) + "/" + demoKey(x.pathname, x.search);
    if (x.pathname === "/" || x.pathname === "/app") return ROOT + (D.app || "app.html?embed=1") + x.hash;
    return ROOT + x.pathname.slice(1) + (x.search ? "@" + x.search.slice(1).replace(/[^A-Za-z0-9._=&-]/g, "_") : "");
  }
  window.GA_DEMO.map = map; window.GA_DEMO.key = demoKey;

  function say() {
    var m = MSG[lang()] || MSG.en;
    if (typeof window.toast === "function") { try { window.toast(m); return; } catch (e) {} }
    var e = document.getElementById("ga-demo-toast");
    if (!e) { e = document.createElement("div"); e.id = "ga-demo-toast"; document.body.appendChild(e); }
    e.textContent = m; e.style.display = "block"; clearTimeout(e._t); e._t = setTimeout(function () { e.style.display = "none"; }, 2400);
  }
  window.GA_DEMO.say = say;
  function refused() { return new Response(JSON.stringify({ ok: false, demo: true, error: MSG[lang()] || MSG.en }), { status: 200, headers: { "Content-Type": "application/json" } }); }

  var f0 = window.fetch.bind(window), cache = {};
  window.fetch = function (u, o) {
    var url = typeof u === "string" ? u : u && u.url, h = (o && o.headers) || {}, m = ((o && o.method) || "GET").toUpperCase();
    if (m !== "GET" && m !== "HEAD") { say(); return Promise.resolve(refused()); }
    var t = map(url, h); if (!t) return f0(u, o);
    if (/^\/api\/thread(\?|$)/.test(url) && /[?&]after=/.test(url)) {      // the 2-second poll: nothing new ever happens in a demo
      var k = t; return (cache[k] || (cache[k] = f0(t).then(function (r) { return r.ok ? r.json() : { events: [] }; })))
        .then(function (j) { return new Response(JSON.stringify({ events: [], agent: j.agent, build: j.build }), { headers: { "Content-Type": "application/json" } }); });
    }
    return f0(t);
  };
  var op = XMLHttpRequest.prototype.open, sd = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) {
    var a = [].slice.call(arguments); this._gaWrite = String(m).toUpperCase() !== "GET";
    var t = map(u); if (t) a[1] = t; return op.apply(this, a);
  };
  XMLHttpRequest.prototype.send = function () {
    if (!this._gaWrite) return sd.apply(this, arguments);
    say(); var x = this; setTimeout(function () { try { x.abort(); } catch (e) {} if (x.onerror) x.onerror(new Event("error")); }, 0);
  };

  // pictures, videos and links the pages write as /build/..., /media/...: point them into the demo folder
  var ATTRS = ["src", "href", "poster", "data-zoom"];
  function fix(el) {
    if (!el || el.nodeType !== 1) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var v = el.getAttribute(ATTRS[i]); if (!v) continue;
      if (ATTRS[i] === "href" && el.tagName === "A" && v.charAt(0) === "#") continue;
      var t = map(v); if (t) el.setAttribute(ATTRS[i], t);
    }
    var s = el.getAttribute("style");
    if (s && s.indexOf("url(") >= 0) el.setAttribute("style", s.replace(/url\((['"]?)(\/[^)'"]+)\1\)/g, function (a, q, u) { var t = map(u); return t ? "url(" + q + t + q + ")" : a; }));
  }
  function walk(n) { if (n.nodeType !== 1) return; fix(n); var all = n.querySelectorAll("[src],[href],[poster],[data-zoom],[style]"); for (var i = 0; i < all.length; i++) fix(all[i]); }
  new MutationObserver(function (ms) {
    ms.forEach(function (m) { if (m.type === "attributes") fix(m.target); else m.addedNodes.forEach(walk); });
  }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ATTRS.concat(["style"]) });

  // a click on something that only writes or needs a server: the toast instead (capture phase, before the page's own handler)
  var BLOCK = "#projbtn, #newproj, #allproj, #bkstate, #send, label.ic, #pick, #pickdir, #drop, #mchips, #coachbtn, #nbell, [data-live]";
  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest && e.target.closest(BLOCK);
    if (b) { e.preventDefault(); e.stopPropagation(); say(); }
  }, true);
  ["dragover", "drop"].forEach(function (k) { document.addEventListener(k, function (e) { e.preventDefault(); e.stopPropagation(); if (k === "drop") say(); }, true); });
  document.addEventListener("keydown", function (e) { if (e.target && e.target.id === "msg") { e.preventDefault(); if (e.key === "Enter") say(); } }, true);

  function chrome() {
    var msg = document.getElementById("msg");
    if (msg) { msg.readOnly = true; msg.placeholder = (lang() === "en" ? "This is a demo of a finished project: browse the conversation and the pages on the right." : "这是一个做好的项目的演示：可以翻看对话和右边的各个页面。"); }
    if (document.getElementById("chatcol") && !document.getElementById("ga-demo-tag")) {
      var a = document.createElement("a"); a.id = "ga-demo-tag"; a.href = D.home || "../";
      a.textContent = lang() === "en" ? "Demo · read only · all examples" : "演示 · 只读 · 所有示例";
      document.body.appendChild(a);
    }
    var tag = document.getElementById("ga-demo-tag"); if (tag) tag.textContent = lang() === "en" ? "Demo · read only · all examples" : "演示 · 只读 · 所有示例";
  }
  document.addEventListener("DOMContentLoaded", function () {
    chrome(); try { if (typeof M2W !== "undefined" && M2W.onLang) M2W.onLang(chrome); } catch (e) {}
    walk(document.documentElement);
  });
})();
