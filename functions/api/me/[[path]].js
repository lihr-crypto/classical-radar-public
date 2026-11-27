// Cloudflare Pages Function: the signed-in user's personal state (pickups, plans to attend, performance states, reminder subscriptions).
//
// Identity comes only from Cloudflare Access: the request must carry a valid Access JWT (Cf-Access-Jwt-Assertion header or the
// CF_Authorization cookie) signed for this application's AUD. Without ACCESS_TEAM_DOMAIN / ACCESS_AUD configured every request is
// refused (fail closed). ENVIRONMENT=development + DEV_USER is the only bypass and is meant for `wrangler pages dev` on a laptop.
//
// Storage: one KV value per user, key "u:" + sha256(email), JSON {pickups, plans, states, reminders}. A record saved before `plans` existed has no such key: read() fills every missing field in. Single user, so read-modify-write is
// enough; KV is eventually consistent across locations, which can briefly show an older state on a second device.

const ID = /^[0-9a-f]{16,64}$/;
const USER_STATUS = new Set(["interested", "planning", "applied", "won", "purchased", "skipped", "attended"]);
const PRIORITY = new Set(["normal", "high"]);
const MILESTONE = new Set(["sale_start", "sale_end"]);
const MAX_ITEMS = 5000;
const MAX_BODY = 4096;

const json = (status, data) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
const b64urlBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));
const b64urlJson = (s) => JSON.parse(new TextDecoder().decode(b64urlBytes(s)));

let certCache = { at: 0, team: "", keys: [] };

export async function verifyAccess(request, env, fetchImpl = fetch, now = Date.now()) {
  if (env.ENVIRONMENT === "development" && env.DEV_USER) return env.DEV_USER;
  const team = (env.ACCESS_TEAM_DOMAIN || "").trim(), aud = (env.ACCESS_AUD || "").trim();
  if (!team || !aud) return null;
  const cookie = (request.headers.get("Cookie") || "").match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  const token = request.headers.get("Cf-Access-Jwt-Assertion") || (cookie && cookie[1]);
  if (!token || token.split(".").length !== 3) return null;
  const [h, p, sig] = token.split(".");
  let header, payload;
  try { header = b64urlJson(h); payload = b64urlJson(p); } catch { return null; }
  if (header.alg !== "RS256") return null;
  if (certCache.team !== team || now - certCache.at > 3600e3) {
    const r = await fetchImpl(`https://${team}/cdn-cgi/access/certs`);
    if (!r.ok) return null;
    certCache = { at: now, team, keys: (await r.json()).keys || [] };
  }
  const jwk = certCache.keys.find((k) => k.kid === header.kid);
  if (!jwk) return null;
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlBytes(sig), new TextEncoder().encode(`${h}.${p}`));
  if (!ok) return null;
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(aud) || payload.iss !== `https://${team}` || !(payload.exp * 1000 > now) || !payload.email) return null;
  return String(payload.email).toLowerCase();
}

async function userKey(email) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(email));
  return "u:" + [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function handle(request, env, { fetchImpl = fetch, now = Date.now() } = {}) {
  const email = await verifyAccess(request, env, fetchImpl, now);
  if (!email) return json(401, { error: "需要通过 Cloudflare Access 登录" });
  if (!env.CR_STATE) return json(500, { error: "KV 绑定 CR_STATE 未配置" });
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/me/, "") || "/";
  const key = await userKey(email);
  const read = async () => ({ pickups: {}, plans: {}, states: {}, reminders: {}, ...((await env.CR_STATE.get(key, "json")) || {}) });  // field by field, so an older record never lacks a map
  const write = (s) => env.CR_STATE.put(key, JSON.stringify(s));

  if (request.method === "GET" && path === "/state") return json(200, await read());

  let body = null;
  if (request.method === "PUT") {
    const text = await request.text();
    if (text.length > MAX_BODY) return json(413, { error: "请求过大" });
    try { body = text ? JSON.parse(text) : {}; } catch { return json(400, { error: "不是合法的 JSON" }); }
    if (typeof body !== "object" || body === null || Array.isArray(body)) return json(400, { error: "请求格式不对" });
  }
  let m;
  const s = await read();
  const count = Object.keys(s.pickups).length + Object.keys(s.plans).length + Object.keys(s.states).length + Object.keys(s.reminders).length;
  if ((m = path.match(/^\/pickups\/([^/]+)$/)) && ID.test(m[1])) {
    if (request.method === "PUT") {
      if (!PRIORITY.has(body.priority || "normal")) return json(422, { error: "优先级不合法" });
      if (!s.pickups[m[1]] && count >= MAX_ITEMS) return json(422, { error: "条目过多" });
      s.pickups[m[1]] = { priority: body.priority || "normal", notes: typeof body.notes === "string" ? body.notes.slice(0, 500) : null, created_at: s.pickups[m[1]]?.created_at || new Date(now).toISOString() };
      await write(s);
      return json(200, { ok: true });
    }
    if (request.method === "DELETE") { delete s.pickups[m[1]]; await write(s); return json(200, { ok: true }); }
  }
  if ((m = path.match(/^\/plans\/([^/]+)$/)) && ID.test(m[1])) {
    if (request.method === "PUT") {
      if (!s.plans[m[1]] && count >= MAX_ITEMS) return json(422, { error: "条目过多" });
      s.plans[m[1]] = { created_at: s.plans[m[1]]?.created_at || new Date(now).toISOString() };
      await write(s);
      return json(200, { ok: true });
    }
    if (request.method === "DELETE") { delete s.plans[m[1]]; await write(s); return json(200, { ok: true }); }
  }
  if ((m = path.match(/^\/performances\/([^/]+)\/state$/)) && ID.test(m[1]) && request.method === "PUT") {
    if (!USER_STATUS.has(body.status)) return json(422, { error: "状态不合法" });
    if (!s.states[m[1]] && count >= MAX_ITEMS) return json(422, { error: "条目过多" });
    s.states[m[1]] = body.status;
    await write(s);
    return json(200, { ok: true });
  }
  if ((m = path.match(/^\/reminders\/([^/]+)$/)) && ID.test(m[1]) && request.method === "PUT") {
    const off = body.offset_minutes;
    if (!MILESTONE.has(body.milestone) || !Number.isInteger(off) || off < 0 || off > 43200 || typeof body.enabled !== "boolean") return json(422, { error: "提醒设置不合法" });
    if (!s.reminders[m[1]] && count >= MAX_ITEMS) return json(422, { error: "条目过多" });
    s.reminders[m[1]] = { milestone: body.milestone, offset_minutes: off, enabled: body.enabled };
    await write(s);
    return json(200, s.reminders[m[1]]);
  }
  return json(404, { error: "没有这个接口" });
}

export const onRequest = (context) => handle(context.request, context.env);
