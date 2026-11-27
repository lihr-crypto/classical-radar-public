// node tests/js/functions.test.mjs  -- Pages Function: Access JWT verification (fail closed) and per-user KV state
import assert from "node:assert/strict";
import { handle, verifyAccess } from "../../functions/api/me/[[path]].js";

const TEAM = "team.cloudflareaccess.com", AUD = "aud-123", NOW = Date.UTC(2026, 10, 4, 12);
const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const keys = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", keys.publicKey)), kid: "k1", alg: "RS256" };
const certs = async (url) => { assert.equal(url, `https://${TEAM}/cdn-cgi/access/certs`); return new Response(JSON.stringify({ keys: [jwk] })); };
async function token(claims = {}, header = {}) {
  const h = enc({ alg: "RS256", kid: "k1", ...header }), p = enc({ aud: [AUD], iss: `https://${TEAM}`, exp: NOW / 1000 + 600, email: "Me@Example.com", ...claims });
  const sig = Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", keys.privateKey, new TextEncoder().encode(`${h}.${p}`))).toString("base64url");
  return `${h}.${p}.${sig}`;
}
const env = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD };
const req = (t, path = "/api/me/state", init = {}) => new Request("https://x.pages.dev" + path, { ...init, headers: { ...(t ? { "Cf-Access-Jwt-Assertion": t } : {}), ...(init.headers || {}) } });
let n = 0;
const ok = async (name, fn) => { await fn(); n++; console.log("ok", name); };

await ok("valid token gives the lower-cased email", async () => assert.equal(await verifyAccess(req(await token()), env, certs, NOW), "me@example.com"));
await ok("cookie works too", async () => assert.equal(await verifyAccess(new Request("https://x/", { headers: { Cookie: `a=b; CF_Authorization=${await token()}` } }), env, certs, NOW), "me@example.com"));
await ok("not configured -> refused", async () => assert.equal(await verifyAccess(req(await token()), {}, certs, NOW), null));
await ok("no token -> refused", async () => assert.equal(await verifyAccess(req(null), env, certs, NOW), null));
await ok("wrong audience -> refused", async () => assert.equal(await verifyAccess(req(await token({ aud: ["other"] })), env, certs, NOW), null));
await ok("expired -> refused", async () => assert.equal(await verifyAccess(req(await token({ exp: NOW / 1000 - 1 })), env, certs, NOW), null));
await ok("other issuer -> refused", async () => assert.equal(await verifyAccess(req(await token({ iss: "https://evil.cloudflareaccess.com" })), env, certs, NOW), null));
await ok("tampered payload -> refused", async () => { const [h, , s] = (await token()).split("."); assert.equal(await verifyAccess(req(`${h}.${enc({ aud: [AUD], iss: `https://${TEAM}`, exp: NOW / 1000 + 600, email: "attacker@x" })}.${s}`), env, certs, NOW), null); });
await ok("alg none -> refused", async () => assert.equal(await verifyAccess(req(await token({}, { alg: "none" })), env, certs, NOW), null));
await ok("dev bypass only with ENVIRONMENT=development", async () => {
  assert.equal(await verifyAccess(req(null), { DEV_USER: "dev@x" }, certs, NOW), null);
  assert.equal(await verifyAccess(req(null), { DEV_USER: "dev@x", ENVIRONMENT: "development" }, certs, NOW), "dev@x");
});

const kv = () => { const m = new Map(); return { m, get: async (k, t) => (m.has(k) ? JSON.parse(m.get(k)) : null), put: async (k, v) => { m.set(k, v); } }; };
await ok("state round trip, per user, validated", async () => {
  const store = kv(), e = { ...env, CR_STATE: store }, t = await token(), id = "ea9faa17aea445ca9e996f1eb1dd68a0";
  const call = (path, method = "GET", body) => handle(req(t, path, { method, body: body ? JSON.stringify(body) : undefined, headers: body ? { "Content-Type": "application/json" } : {} }), e, { fetchImpl: certs, now: NOW });
  assert.equal((await call(`/api/me/pickups/${id}`, "PUT", { priority: "high" })).status, 200);
  assert.equal((await call(`/api/me/performances/${id}/state`, "PUT", { status: "purchased" })).status, 200);
  assert.equal((await call(`/api/me/performances/${id}/state`, "PUT", { status: "bought" })).status, 422);
  assert.equal((await call(`/api/me/reminders/${id}`, "PUT", { milestone: "sale_start", offset_minutes: 60, enabled: true })).status, 200);
  assert.equal((await call(`/api/me/reminders/${id}`, "PUT", { milestone: "sale_start", offset_minutes: -5, enabled: true })).status, 422);
  assert.equal((await call(`/api/me/pickups/not-an-id`, "PUT", {})).status, 404);
  const st = await (await call("/api/me/state")).json();
  assert.equal(st.pickups[id].priority, "high");
  assert.equal(st.states[id], "purchased");
  assert.equal(store.m.size, 1);
  assert.ok([...store.m.keys()][0].startsWith("u:") && ![...store.m.keys()][0].includes("example"));  // the email is not stored as the key
  assert.equal((await call(`/api/me/pickups/${id}`, "DELETE")).status, 200);
  assert.deepEqual((await (await call("/api/me/state")).json()).pickups, {});
  const other = await handle(req(await token({ email: "someone@else.com" }), "/api/me/state"), e, { fetchImpl: certs, now: NOW });
  assert.deepEqual((await other.json()).states, {});  // another account never sees this user's state
  assert.equal((await handle(req(null, "/api/me/state"), e, { fetchImpl: certs, now: NOW })).status, 401);
  const big = await call(`/api/me/pickups/${id}`, "PUT", { notes: "x".repeat(5000) });
  assert.equal(big.status, 413);
});
await ok("plans to attend: saved, listed, removed; a record saved before `plans` existed is filled in field by field (ADR-0012)", async () => {
  const store = kv(), e = { ...env, CR_STATE: store }, t = await token(), id = "ea9faa17aea445ca9e996f1eb1dd68a0";
  const call = (path, method = "GET", body) => handle(req(t, path, { method, body: body ? JSON.stringify(body) : undefined, headers: body ? { "Content-Type": "application/json" } : {} }), e, { fetchImpl: certs, now: NOW });
  const state = async () => (await call("/api/me/state")).json();
  assert.deepEqual((await state()).plans, {}, "a user with no record at all");
  assert.equal((await call(`/api/me/pickups/${id}`, "PUT", {})).status, 200);
  const key = [...store.m.keys()][0], rec = JSON.parse(store.m.get(key));
  delete rec.plans;  // the shape stored before this feature
  store.m.set(key, JSON.stringify(rec));
  assert.deepEqual((await state()).plans, {}, "an older record: GET /state fills the missing map in");
  assert.equal((await call(`/api/me/plans/${id}`, "PUT")).status, 200);  // no crash at the item count or at s.plans[...]
  let st = await state();
  assert.ok(st.plans[id].created_at && st.pickups[id].priority === "normal", "the plan is saved and the pickup is untouched");
  assert.equal((await call(`/api/me/plans/${id}`, "PUT")).status, 200);
  assert.equal((await state()).plans[id].created_at, st.plans[id].created_at, "saving twice keeps the first date");
  assert.equal((await call(`/api/me/plans/not-an-id`, "PUT")).status, 404);
  assert.equal((await call(`/api/me/plans/${id}`, "DELETE")).status, 200);
  assert.deepEqual((await state()).plans, {});
  store.m.set(key, JSON.stringify({ pickups: { [id]: { priority: "normal" } } }));  // a very old record: only one map
  assert.equal((await call(`/api/me/plans/${id}`, "PUT")).status, 200);
  st = await state();
  assert.deepEqual([Object.keys(st.states), Object.keys(st.reminders), Object.keys(st.plans)], [[], [], [id]]);
});
console.log(`${n} checks passed`);
