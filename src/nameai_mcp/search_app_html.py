"""The MCP Apps view for search_domain — a self-contained HTML document the
host renders in a sandboxed iframe (ext-apps spec, `text/html;profile=mcp-app`).

Wire protocol (JSON-RPC over postMessage, see the ext-apps specification):
  View -> Host   ui/initialize (request), ui/notifications/initialized,
                 ui/notifications/size-changed
  Host -> View   ui/notifications/tool-input {arguments},
                 ui/notifications/tool-result (a CallToolResult),
                 ui/notifications/host-context-changed {theme, ...}
The view renders search_domain's structured result as availability cards and
degrades to the plain JSON text when structuredContent is absent.
"""

SEARCH_APP_URI = "ui://nameai/search-results.html"

SEARCH_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https://name.ai data:; font-src 'self'; connect-src https://mcp.name.ai https://nameai-mcp.h.namekart.com https://name.ai; form-action https://name.ai; frame-ancestors https://chatgpt.com https://claude.ai https://claude.com; base-uri 'none'">
<title>Name.ai domain search</title>
<style>
  :root {
    --bg: var(--color-background-primary, #ffffff);
    --fg: var(--color-text-primary, #1f2937);
    --muted: var(--color-text-secondary, #6b7280);
    --border: var(--color-border-primary, #e5e7eb);
    --ok: #16a34a; --warn: #ca8a04; --bad: #dc2626; --brand: #1b4332;
    --radius: var(--border-radius-md, 10px);
    --font: var(--font-sans, system-ui, -apple-system, Segoe UI, Roboto, sans-serif);
  }
  html[data-theme="dark"] { --bg:#111418; --fg:#e5e7eb; --muted:#9ca3af; --border:#2a2f36; }
  * { box-sizing: border-box; }
  body { margin:0; padding:12px; background:var(--bg); color:var(--fg); font:14px/1.45 var(--font); }
  .head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin:0 0 10px; }
  .head h1 { font-size:15px; margin:0; font-weight:600; }
  .head a { color:var(--brand); font-size:12px; text-decoration:none; }
  .status { color:var(--muted); font-size:12px; }
  ul { list-style:none; margin:0; padding:0; display:grid; gap:8px; }
  li { display:grid; grid-template-columns:1fr auto; gap:4px 12px; align-items:center;
       border:1px solid var(--border); border-radius:var(--radius); padding:10px 12px; }
  .dom { font-weight:600; font-size:14px; word-break:break-all; }
  .sub { color:var(--muted); font-size:12px; grid-column:1; }
  .pill { justify-self:end; font-size:12px; font-weight:600; padding:3px 9px; border-radius:999px;
          border:1px solid currentColor; white-space:nowrap; }
  .pill.ok { color:var(--ok); } .pill.warn { color:var(--warn); } .pill.bad { color:var(--bad); } .pill.muted { color:var(--muted); }
  .price { grid-column:2; justify-self:end; font-size:13px; color:var(--fg); }
  .price.masked { color:var(--muted); font-size:12px; }
  pre { white-space:pre-wrap; font-size:12px; color:var(--muted); }
</style>
</head>
<body>
<div class="head"><h1>Domain availability</h1><a id="link" href="https://name.ai/search" target="_blank" rel="noopener">Open on name.ai ↗</a></div>
<div id="status" class="status">Waiting for results…</div>
<ul id="list"></ul>
<script>
(function () {
  var host = window.parent;
  var nextId = 1;
  var pending = {};
  function send(msg) { try { host.postMessage(msg, "*"); } catch (e) {} }
  function request(method, params) {
    var id = nextId++;
    return new Promise(function (resolve) {
      pending[id] = resolve;
      send({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    });
  }
  function notify(method, params) { send({ jsonrpc: "2.0", method: method, params: params || {} }); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function reportSize() {
    var h = document.documentElement.scrollHeight;
    notify("ui/notifications/size-changed", { height: h });
  }
  function applyTheme(ctx) {
    if (ctx && ctx.theme) document.documentElement.setAttribute("data-theme", ctx.theme);
    if (ctx && ctx.styles && ctx.styles.variables) {
      Object.keys(ctx.styles.variables).forEach(function (k) {
        var v = ctx.styles.variables[k];
        if (v != null) document.documentElement.style.setProperty("--" + k, v);
      });
    }
  }
  function label(row) {
    var st = row.state, avail = row.available;
    if (avail === true || st === "S1") return ["Available", "ok"];
    if (st === "S2" || st === "S3" || (row.listing && row.listing.id)) return ["For sale", "warn"];
    if (avail === false) return ["Taken", "bad"];
    return [row.state_label || "Unknown", "muted"];
  }
  function priceText(row) {
    var p = row.price;
    if (p == null && row.listing && row.listing.bin_price == null && (row.state === "S2" || row.state === "S3")) return ["Price on request — sign in for pricing", true];
    if (p == null) return ["", false];
    if (typeof p === "number") return ["$" + p.toLocaleString(), false];
    if (typeof p === "object" && p.bin != null) return ["$" + Number(p.bin).toLocaleString(), false];
    return ["", false];
  }
  function render(data) {
    var list = document.getElementById("list");
    var status = document.getElementById("status");
    var rows = (data && data.results) || [];
    if (!rows.length) { status.textContent = "No results."; reportSize(); return; }
    status.textContent = rows.length + " result" + (rows.length === 1 ? "" : "s") + " for " + (data.query || "");
    document.getElementById("link").href = "https://name.ai/search?q=" + encodeURIComponent(data.query || "");
    list.innerHTML = rows.map(function (r) {
      var l = label(r), pt = priceText(r);
      var sub = r.whois_summary && r.whois_summary.registrar ? "Registrar: " + esc(r.whois_summary.registrar) : (r.state_label ? esc(r.state_label) : "");
      return '<li><span class="dom">' + esc(r.domain) + '</span><span class="pill ' + l[1] + '">' + esc(l[0]) + '</span>' +
             (sub ? '<span class="sub">' + sub + '</span>' : '<span class="sub"></span>') +
             (pt[0] ? '<span class="price' + (pt[1] ? ' masked' : '') + '">' + esc(pt[0]) + '</span>' : '') + '</li>';
    }).join("");
    reportSize();
  }
  function fromResult(result) {
    if (!result) return null;
    if (result.structuredContent) return result.structuredContent;
    var c = (result.content || []).filter(function (x) { return x && x.type === "text"; })[0];
    if (c) { try { return JSON.parse(c.text); } catch (e) { return { query: "", results: [], raw: c.text }; } }
    return null;
  }
  window.addEventListener("message", function (ev) {
    var msg = ev.data;
    if (!msg || msg.jsonrpc !== "2.0") return;
    if (msg.id != null && pending[msg.id]) { var r = pending[msg.id]; delete pending[msg.id]; r(msg.result || {}); return; }
    if (msg.method === "ui/notifications/tool-input") {
      var q = msg.params && msg.params.arguments && msg.params.arguments.domain;
      if (q) document.getElementById("status").textContent = "Checking " + q + "…";
    } else if (msg.method === "ui/notifications/tool-result") {
      var data = fromResult(msg.params);
      if (data && data.raw) { document.getElementById("status").textContent = ""; document.getElementById("list").innerHTML = "<pre>" + esc(data.raw) + "</pre>"; reportSize(); }
      else render(data);
    } else if (msg.method === "ui/notifications/tool-cancelled") {
      document.getElementById("status").textContent = "Cancelled" + (msg.params && msg.params.reason ? ": " + msg.params.reason : ".");
    } else if (msg.method === "ui/notifications/host-context-changed") {
      applyTheme(msg.params);
    } else if (msg.method === "ping" && msg.id != null) {
      send({ jsonrpc: "2.0", id: msg.id, result: {} });
    }
  });
  request("ui/initialize", { appCapabilities: { availableDisplayModes: ["inline"] } }).then(function (res) {
    applyTheme(res && res.hostContext);
    notify("ui/notifications/initialized", {});
    reportSize();
  });
})();
</script>
</body>
</html>
"""
