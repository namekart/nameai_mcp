"""The MCP Apps view for search_premium_domains: a price list of premium domains
for sale, rendered by the host in a sandboxed iframe (ext-apps spec,
`text/html;profile=mcp-app`). Same wire protocol as search_app_html.py.

Rows open the listing page through the host (`ui/open-link`), only for URLs
on the same origin as the result's browse_url (name.ai, or stage when the
server points at stage). The view makes no network calls of its own.
"""

MARKET_APP_URI = "ui://nameai/market-results.html"

MARKET_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https://name.ai data:; connect-src 'none'; form-action 'none'; frame-ancestors https://chatgpt.com https://claude.ai https://claude.com; base-uri 'none'">
<title>Name.ai premium domains</title>
<style>
  :root {
    --bg: var(--color-background-primary, #ffffff);
    --fg: var(--color-text-primary, #1f2937);
    --muted: var(--color-text-secondary, #6b7280);
    --border: var(--color-border-primary, #e5e7eb);
    --hover: var(--color-background-secondary, #f6f7f8);
    --brand: #1b4332;
    --radius: var(--border-radius-md, 10px);
    --font: var(--font-sans, system-ui, -apple-system, Segoe UI, Roboto, sans-serif);
  }
  html[data-theme="dark"] { --bg:#111418; --fg:#e5e7eb; --muted:#9ca3af; --border:#2a2f36; --hover:#1a1f25; --brand:#74c69d; }
  * { box-sizing: border-box; }
  body { margin:0; padding:12px; background:var(--bg); color:var(--fg); font:14px/1.45 var(--font); }
  .head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin:0 0 10px; }
  .head h1 { font-size:15px; margin:0; font-weight:600; }
  .head button { all:unset; cursor:pointer; color:var(--brand); font-size:12px; }
  .status { color:var(--muted); font-size:12px; margin-bottom:8px; }
  ul { list-style:none; margin:0; padding:0; display:grid; gap:8px; max-height:320px; overflow-y:auto; }
  li button { all:unset; box-sizing:border-box; width:100%; cursor:pointer; display:flex; align-items:center;
              justify-content:space-between; gap:12px; border:1px solid var(--border); border-radius:var(--radius); padding:10px 12px; }
  li button:hover, li button:focus-visible { background:var(--hover); outline:none; }
  .dom { font-weight:600; word-break:break-all; }
  .price { font-weight:700; white-space:nowrap; }
  .price.masked { font-weight:400; color:var(--muted); font-size:12px; }
  .foot { color:var(--muted); font-size:11px; margin-top:8px; }
  pre { white-space:pre-wrap; font-size:12px; color:var(--muted); }
</style>
</head>
<body>
<div class="head"><h1>Premium domains for sale on name.ai</h1><button id="browse" type="button">Browse all ↗</button></div>
<div id="status" class="status">Searching premium domains…</div>
<ul id="list"></ul>
<div class="foot">Prices in USD. Purchase completes on name.ai.</div>
<script>
(function () {
  var host = window.parent, nextId = 1, pending = {}, origin = "https://name.ai", browseUrl = "https://name.ai/market";
  function send(msg) { try { host.postMessage(msg, "*"); } catch (e) {} }
  function request(method, params) {
    var id = nextId++;
    return new Promise(function (resolve) { pending[id] = resolve; send({ jsonrpc: "2.0", id: id, method: method, params: params || {} }); });
  }
  function notify(method, params) { send({ jsonrpc: "2.0", method: method, params: params || {} }); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function reportSize() { notify("ui/notifications/size-changed", { height: document.documentElement.scrollHeight }); }
  function applyTheme(ctx) {
    if (ctx && ctx.theme) document.documentElement.setAttribute("data-theme", ctx.theme);
    if (ctx && ctx.styles && ctx.styles.variables) {
      Object.keys(ctx.styles.variables).forEach(function (k) {
        var v = ctx.styles.variables[k];
        if (v != null) document.documentElement.style.setProperty("--" + k, v);
      });
    }
  }
  function sameOrigin(url) { try { return new URL(url).origin === origin; } catch (e) { return false; } }
  function open(url) { if (sameOrigin(url)) request("ui/open-link", { url: url }); }
  function render(data) {
    var list = document.getElementById("list"), status = document.getElementById("status");
    if (data && data.browse_url) { try { origin = new URL(data.browse_url).origin; browseUrl = data.browse_url; } catch (e) {} }
    var rows = (data && data.results) || [];
    if (!rows.length) { status.textContent = "No premium domains matched. Try another keyword."; list.innerHTML = ""; reportSize(); return; }
    var more = data.total && data.total > rows.length ? " of " + data.total : "";
    status.textContent = rows.length + more + " for sale";
    list.innerHTML = rows.map(function (r, i) {
      var price = r.price_usd != null ? '<span class="price">$' + Number(r.price_usd).toLocaleString("en-US") + '</span>'
                                       : '<span class="price masked">View price</span>';
      return '<li><button type="button" data-i="' + i + '"><span class="dom">' + esc(r.domain) + '</span>' + price + '</button></li>';
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () { open(rows[Number(b.getAttribute("data-i"))].url); });
    });
    reportSize();
  }
  function fromResult(result) {
    if (!result) return null;
    if (result.structuredContent) return result.structuredContent;
    var c = (result.content || []).filter(function (x) { return x && x.type === "text"; })[0];
    if (c) { try { return JSON.parse(c.text); } catch (e) { return { results: [], raw: c.text }; } }
    return null;
  }
  document.getElementById("browse").addEventListener("click", function () { open(browseUrl); });
  window.addEventListener("message", function (ev) {
    var msg = ev.data;
    if (!msg || msg.jsonrpc !== "2.0") return;
    if (msg.id != null && pending[msg.id]) { var r = pending[msg.id]; delete pending[msg.id]; r(msg.result || {}); return; }
    if (msg.method === "ui/notifications/tool-result") {
      var data = fromResult(msg.params);
      if (data && data.raw) { document.getElementById("status").textContent = ""; document.getElementById("list").innerHTML = "<pre>" + esc(data.raw) + "</pre>"; reportSize(); }
      else render(data);
    } else if (msg.method === "ui/notifications/tool-cancelled") {
      document.getElementById("status").textContent = "Cancelled.";
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
