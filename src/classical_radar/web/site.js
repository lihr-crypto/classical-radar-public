"use strict";
// Bootstrap for the Cloudflare Pages site: load the published concert data and the signed-in user's state, then start the same UI as
// the local app. Discovery runs in the browser over the data file (demo.js); personal state is saved through /api/me (Pages Function).
(async function () {
  const view = document.getElementById("view");
  const say = (text) => { const p = document.createElement("p"); p.className = "empty"; p.textContent = text; view.replaceChildren(p); };
  say("加载中…");
  try {
    const get = async (url) => {
      const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (r.status === 401 || r.status === 403) throw Object.assign(new Error("auth"), { auth: true });
      if (!r.ok) throw new Error(`${url} ${r.status}`);
      return r.json();
    };
    const optional = async (url) => { try { return await get(url); } catch (e) { if (e.auth) throw e; return null; } };  // the leads file is an extra: the site works without it
    const [data, state, leads] = await Promise.all([get("data/concerts.json"), get("api/me/state"), optional("data/leads.json")]);
    if (leads) data.leads = leads;
    window.CR_DEMO_DATA = data;
    window.CR_REMOTE_STATE = {
      state,
      async send(op) {
        const r = await fetch("api" + op.path, { method: op.method, credentials: "same-origin", headers: op.body ? { "Content-Type": "application/json" } : {}, body: op.body ? JSON.stringify(op.body) : undefined });
        if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error || `保存失败（${r.status}）`); }
      },
    };
    for (const src of ["demo.js", "app.js"]) {
      await new Promise((resolve, reject) => { const s = document.createElement("script"); s.src = src; s.onload = resolve; s.onerror = () => reject(new Error(src)); document.body.append(s); });
    }
  } catch (e) {
    say(e.auth ? "需要登录。请刷新页面，用 Cloudflare Access 登录后再打开。" : `加载失败：${e.message}`);
  }
})();
