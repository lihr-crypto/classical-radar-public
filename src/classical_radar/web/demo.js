"use strict";
// Read-only demo backend for the static artifact: the same queries as discover.py / api.py over an embedded snapshot.
// Personal state (pickups, plans to attend, performance states, reminders) lives in this browser only. Parity with the Python implementation is
// checked by scripts/check_demo_parity.js (same ids, same order for a set of queries).
(function () {
  const D = window.CR_DEMO_DATA;
  const KANTO = new Set(["11", "12", "13", "14"]);
  const RANK = { open: 4, announced: 3, closed: 2, unknown: 1 };
  const CATS = ["domestic_orchestra", "overseas_orchestra_visit", "piano_recital", "other"];
  const USER = ["interested", "planning", "applied", "won", "purchased", "skipped", "attended"];
  // demo: fixed at the snapshot time so the 12-month window stays meaningful whenever it is opened; site: the real current time
  const LIVE = D.fixed_as_of === false;
  let asOf = LIVE ? new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00") : D.as_of;

  const norm = (s) => String(s || "").normalize("NFKC").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[\s.・·\-=＝]/g, "");
  const jstDate = (iso) => new Date(Date.parse(iso) + 9 * 3600e3).toISOString().slice(0, 10);
  const jstTime = (iso) => new Date(Date.parse(iso) + 9 * 3600e3).toISOString().slice(11, 16);
  function addMonths(ymd, m) {
    const [y, mo, d] = ymd.split("-").map(Number);
    const t = mo - 1 + m, yy = y + Math.floor(t / 12), mm = ((t % 12) + 12) % 12;
    const last = new Date(Date.UTC(yy, mm + 1, 0)).getUTCDate();
    return `${yy}-${String(mm + 1).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
  }
  const aliasKey = (text) => { const base = String(text || "").normalize("NFKC").replace(/[（(][^）)]*[）)]/g, ""); return D.alias[norm(base)] || null; };

  // ---- personal state: this browser only (demo) or the signed-in user's server-side store (site, window.CR_REMOTE_STATE) ----
  const REMOTE = window.CR_REMOTE_STATE || null;
  let mem = null;
  // every map is filled in field by field: a state saved before "plans" existed (old localStorage or an old server record) has no such key
  const withDefaults = (s) => ({ pickups: {}, plans: {}, states: {}, reminders: {}, ...(s && typeof s === "object" ? s : {}) });
  const load = () => {
    if (REMOTE) return (REMOTE.state = withDefaults(REMOTE.state));
    if (mem) return mem;
    try { mem = JSON.parse(localStorage.getItem("cr_demo_state") || "null"); } catch { mem = null; }
    return (mem = withDefaults(mem));
  };
  // apply one change: remote first (so a failed save never shows as saved), then the local cache
  async function change(op, mutate) {
    if (REMOTE) await REMOTE.send(op);
    mutate(load());
    if (!REMOTE) { try { localStorage.setItem("cr_demo_state", JSON.stringify(mem)); } catch { /* private mode: keep in memory */ } }
  }

  const concerts = D.concerts;
  const byId = new Map(concerts.map((c) => [c.id, c]));

  function cleanFilters(q) {
    const out = {};
    for (const dim of ["orchestra", "composer", "work", "conductor", "performer", "venue"]) {
      const vals = (q.getAll(dim) || []).map((v) => v.trim()).filter(Boolean);
      if (vals.length > 10 || vals.some((v) => v.length > 100)) throw new Error("筛选值过多或过长");
      if (vals.length) out[dim] = vals;
    }
    return out;
  }
  function matchIds(flt) {
    let ids = null;
    const narrow = (s) => { ids = ids === null ? s : new Set([...ids].filter((x) => s.has(x))); };
    const ORC = D.orchestras;
    const orchMatch = (keys, v) => {
      if (v === "overseas" || v === "seven") return keys.some((k) => ORC[k].origin === v);
      if (ORC[v]) return keys.includes(v);
      const nv = norm(v);
      return !!nv && keys.some((k) => norm(ORC[k].display).includes(nv));
    };
    if (flt.orchestra) narrow(new Set(concerts.filter((c) => flt.orchestra.some((v) => orchMatch(c.orchestras, v))).map((c) => c.id)));
    if (flt.composer) {
      const wanted = flt.composer.map((v) => [aliasKey(v), norm(v)]);
      const f = new Set();
      for (const c of concerts) for (const p of c.program) {
        const disp = norm(p.composer_display || "");
        if (wanted.some(([k, nv]) => (k && p.composer_key === k) || (nv && disp.includes(nv)))) f.add(c.id);
      }
      narrow(f);
    }
    if (flt.work) {
      const f = new Set();
      for (const c of concerts) for (const p of c.program) {
        const text = norm((p.work_display || "") + " " + (p.raw_text || ""));
        if (flt.work.some((v) => (v.includes(":") && (p.work_key || "") === v.toLowerCase()) || (!v.includes(":") && norm(v) && text.includes(norm(v))))) f.add(c.id);
      }
      narrow(f);
    }
    for (const [dim, onlyConductor] of [["conductor", true], ["performer", false]]) {
      if (!flt[dim]) continue;
      const f = new Set();
      for (const c of concerts) for (const a of c.artists) if ((!onlyConductor || a.role === "conductor") && flt[dim].some((v) => norm(a.name_display).includes(norm(v)))) f.add(c.id);
      narrow(f);
    }
    return ids;
  }
  function windowRows(category, months) {
    const today = jstDate(asOf), end = addMonths(today, months), out = [];
    for (const c of concerts) {
      if (category !== "all" && c.category !== category) continue;
      for (const p of c.performances) {
        if (["cancelled", "completed"].includes(p.status) || p.local_date >= end) continue;
        const ok = (p.date_precision === "exact_time" && p.starts_at >= asOf) || (p.date_precision === "date_only" && p.local_date >= today);
        if (ok) out.push({ c, p });
      }
    }
    return { rows: out, today, end };
  }
  function filterRows(rows, flt) {
    const ids = matchIds(flt);
    let r = ids === null ? rows : rows.filter((x) => ids.has(x.c.id));
    if (flt.venue) { const w = flt.venue.map(norm); r = r.filter((x) => w.some((v) => norm(x.p.venue_name).includes(v))); }
    return r;
  }
  // ADR-0006 (same rule as discover._absorb): a performance of a card a reviewer merged under another is dropped only when one of the
  // keeper performances that stand in for it (same_as, computed at export) is in the same row set. Returns the rows kept and, per keeper, the cards absorbed.
  const card = (c) => ({ concert_id: c.id, source_id: c.source_id, source_url: c.source_url, title_ja: c.title_ja });
  const cardSort = (a, b) => (a.source_id + "\u0000" + a.source_url < b.source_id + "\u0000" + b.source_url ? -1 : 1);
  function absorb(rows) {
    const present = new Set(rows.map((x) => x.p.id)), taken = new Map();
    const kept = rows.filter(({ c, p }) => {
      if (!c.duplicate_of || !byId.has(c.duplicate_of) || !(p.same_as || []).some((id) => present.has(id))) return true;
      if (!taken.has(c.duplicate_of)) taken.set(c.duplicate_of, new Set());
      taken.get(c.duplicate_of).add(c.id);
      return false;
    });
    return { kept, taken };
  }
  function discover(q) {
    const category = q.get("category") || "all", months = Number(q.get("months") || 12), regionMode = q.get("region_mode") || "kanto_first";
    const page = Number(q.get("page") || 1), limit = Number(q.get("limit") || 20);
    if (!(category === "all" || CATS.includes(category)) || ![12, 24].includes(months) || !["kanto_first", "nationwide"].includes(regionMode) || page < 1 || limit < 1 || limit > 100) throw new Error("请求参数不合法");
    const flt = cleanFilters(q);
    const { rows, today, end } = windowRows(category, months);
    const grouped = new Map();
    const { kept, taken } = absorb(filterRows(rows, flt));
    for (const { c, p } of kept) { if (!grouped.has(c.id)) grouped.set(c.id, { c, perfs: [] }); grouped.get(c.id).perfs.push(p); }
    const st = load();
    const items = [];
    for (const { c, perfs } of grouped.values()) {
      perfs.sort((a, b) => (a.local_date < b.local_date ? -1 : a.local_date > b.local_date ? 1 : (a.starts_at || "") < (b.starts_at || "") ? -1 : (a.starts_at || "") > (b.starts_at || "") ? 1 : 0));
      const official = c.official_announcement_date != null;
      const sortDate = official ? c.official_announcement_date : jstDate(c.first_verified_at);
      const phases = perfs.flatMap((p) => p.ticket_phases);
      const ticket = phases.length ? phases.map((t) => t.current_status).sort((a, b) => (RANK[b] || 0) - (RANK[a] || 0))[0] : "not_announced";
      const kanto = perfs.some((p) => KANTO.has(p.prefecture_code));
      const composers = [], conductors = [], soloists = [];
      for (const p of c.program) if (p.composer_display && !composers.includes(p.composer_display)) composers.push(p.composer_display);
      for (const a of c.artists) { if (a.role === "conductor") conductors.push(a.name_display); else if (["recital_headliner", "concerto_soloist"].includes(a.role)) soloists.push(a.name_display); }
      items.push({
        concert_id: c.id, category: c.category, title_ja: c.title_ja, organization_id: c.source_id || null, announcement_sort_date: sortDate, announcement_basis: official ? "official" : "first_verified_fallback",
        announcement_label: official ? "官方公布" : "首次收录", region_group: regionMode === "kanto_first" ? (kanto ? "kanto" : "rest_of_japan") : null,
        performance_ids: perfs.map((p) => p.id), performances: perfs.map((p) => ({ performance_id: p.id, local_date: p.local_date, starts_at: p.starts_at, date_precision: p.date_precision, prefecture_code: p.prefecture_code, venue_name: p.venue_name, last_seen_at: p.last_seen_at })),
        ticket_status: ticket, source_url: c.source_url, last_verified_at: perfs.map((p) => p.last_seen_at || "").sort().pop() || c.first_verified_at, user_pickup: !!st.pickups[c.id],
        image: c.image || null,
        orchestras: c.orchestras.map((k) => ({ key: k, display: D.orchestras[k].display, origin: D.orchestras[k].origin, names: D.orchestras[k].names || "" })),
        composers: composers.slice(0, 6), conductors, soloists, _fv: c.first_verified_at,
        pieces: c.program.map((p) => ({ composer: p.composer_display || "", composer_key: p.composer_key || null, work: p.work_display || p.raw_text || "", work_key: p.work_key || null })),  // same as discover.py: every programme row, for the browse pages
        other_sources: [...(taken.get(c.id) || [])].map((id) => card(byId.get(id))).sort(cardSort),
      });
    }
    const near = (i) => i.performances[0].starts_at || i.performances[0].local_date;
    const cmp = (a, b) => {
      if (regionMode === "kanto_first" && (a.region_group !== "kanto") !== (b.region_group !== "kanto")) return a.region_group === "kanto" ? -1 : 1;
      if (a.announcement_sort_date !== b.announcement_sort_date) return a.announcement_sort_date < b.announcement_sort_date ? 1 : -1;
      if (a._fv !== b._fv) return a._fv < b._fv ? 1 : -1;
      if (near(a) !== near(b)) return near(a) < near(b) ? -1 : 1;
      return a.concert_id < b.concert_id ? -1 : a.concert_id > b.concert_id ? 1 : 0;
    };
    items.sort(cmp);
    const win = items.slice((page - 1) * limit, page * limit).map(({ _fv, ...rest }) => rest);
    return { filters: { category, months, region_mode: regionMode, sort: "announcement_desc", view: "concerts", page, limit, ...flt }, as_of: asOf, window: { from: today, to_exclusive: end }, total: items.length,
      groups: regionMode === "kanto_first" ? [{ key: "kanto", title: "首都圈" }, { key: "rest_of_japan", title: "日本其他地区" }] : [], items: win, coverage_notice: "演示快照" };
  }
  function facets(q) {
    const category = q.get("category") || "all", months = Number(q.get("months") || 12);
    if (![12, 24].includes(months)) throw new Error("请求参数不合法");
    const flt = cleanFilters(q);
    const rows = filterRows(windowRows(category, months).rows, flt);
    const cids = [...new Set(rows.map((r) => r.c.id))];
    const count = (fn) => { const m = new Map(); for (const r of rows) { const k = fn(r); if (!m.has(k)) m.set(k, new Set()); m.get(k).add(r.c.id); } return [...m].map(([value, s]) => ({ value, concerts: s.size })).sort((a, b) => b.concerts - a.concerts || (a.value < b.value ? -1 : 1)); };
    const comp = new Map(), cond = new Map(), perf = new Map();
    for (const id of cids) {
      const c = byId.get(id);
      for (const p of c.program) if (p.composer_display) { if (!comp.has(p.composer_display)) comp.set(p.composer_display, new Set()); comp.get(p.composer_display).add(id); }
      for (const a of c.artists) { if (!perf.has(a.name_display)) perf.set(a.name_display, new Set()); perf.get(a.name_display).add(id); if (a.role === "conductor") { if (!cond.has(a.name_display)) cond.set(a.name_display, new Set()); cond.get(a.name_display).add(id); } }
    }
    const orch = new Map();
    for (const id of cids) for (const k of byId.get(id).orchestras) { if (!orch.has(k)) orch.set(k, new Set()); orch.get(k).add(id); }
    const orchestra = [...orch].map(([value, st]) => ({ value, label: D.orchestras[value].display, origin: D.orchestras[value].origin, concerts: st.size })).sort((a, b) => b.concerts - a.concerts || (a.value < b.value ? -1 : 1));
    const groups = Object.fromEntries(["seven", "overseas"].map((g) => [g, cids.filter((id) => byId.get(id).orchestras.some((k) => D.orchestras[k].origin === g)).length]));
    const top = (m) => [...m].map(([value, s]) => ({ value, concerts: s.size })).sort((a, b) => b.concerts - a.concerts || (a.value < b.value ? -1 : 1)).slice(0, 100);
    return { category: count((r) => r.c.category), prefecture_code: count((r) => r.p.prefecture_code || "unknown"), venue_name: count((r) => r.p.venue_name), orchestra, orchestra_groups: groups, composer: top(comp), conductor: top(cond), performer: top(perf), total_concerts: cids.length, filters: { category, months, ...flt } };
  }
  function detail(id) {
    const c = byId.get(id);
    if (!c) throw new Error("没有找到这个节目");
    const st = load();
    return { concert: { id: c.id, category: c.category, title_ja: c.title_ja, organization_id: c.source_id, verification_status: "official_confirmed", official_announcement_date: c.official_announcement_date, first_verified_at: c.first_verified_at, last_material_change_at: c.last_material_change_at },
      performances: c.performances.map((p) => ({ ...p, ticket_phases: p.ticket_phases.map((t) => ({ ...t, reminder: (st.reminders || {})[t.id] || null })), user_state: st.states[p.id] ? { status: st.states[p.id], notes: null } : null })), program_items: c.program, concert_artists: c.artists, source_url: c.source_url, user_pickup: !!st.pickups[c.id], user_plan: !!st.plans[c.id],
      other_sources: concerts.filter((x) => x.duplicate_of === c.id).map(card).sort(cardSort), merged_into: c.duplicate_of && byId.has(c.duplicate_of) ? card(byId.get(c.duplicate_of)) : null };
  }
  const orchestrasOf = (c) => c.orchestras.map((k) => ({ key: k, display: D.orchestras[k].display, origin: D.orchestras[k].origin, names: D.orchestras[k].names || "" }));
  function calendar(q) {
    const from = q.get("from"), to = q.get("to");
    if (!from || !to || to < from || (Date.parse(to) - Date.parse(from)) / 864e5 > 62) throw new Error("日期范围需在 0–62 天内");
    const inRange = [], sales = [];
    for (const c of concerts) for (const p of c.performances) if (p.status !== "cancelled" && p.local_date >= from && p.local_date <= to) inRange.push({ c, p });
    const shown = new Set(absorb(inRange).kept.map((x) => x.p.id)), performances = [];
    for (const c of concerts) for (const p of c.performances) {
      if (shown.has(p.id)) performances.push({ id: p.id, concert_id: c.id, title_ja: c.title_ja, category: c.category, organization_id: c.source_id || null, orchestras: orchestrasOf(c), local_date: p.local_date, starts_at: p.starts_at, date_precision: p.date_precision, venue_name: p.venue_name, prefecture_code: p.prefecture_code, status: p.status });
      for (const t of p.ticket_phases) {
        if (!t.starts_at) continue;
        const d = jstDate(t.starts_at);
        if (d >= from && d <= to) sales.push({ id: t.id, performance_id: p.id, phase_type: t.phase_type, eligibility: t.eligibility, starts_at: t.starts_at, start_precision: t.start_precision, current_status: t.current_status, concert_id: c.id, title_ja: c.title_ja, category: c.category, organization_id: c.source_id || null, orchestras: orchestrasOf(c), local_date: d, local_time: t.start_precision === "exact_time" ? jstTime(t.starts_at) : null });
      }
    }
    performances.sort((a, b) => a.local_date + (a.starts_at || "") + "\u0000" + a.id < b.local_date + (b.starts_at || "") + "\u0000" + b.id ? -1 : 1);
    sales.sort((a, b) => a.local_date + (a.local_time || "") + "\u0000" + a.id < b.local_date + (b.local_time || "") + "\u0000" + b.id ? -1 : 1);
    return { from, to, performances, sales };
  }
  // the performances of a pickup / plan row, each with my status
  const rowPerformances = (c, st) => c.performances.map((p) => ({ performance_id: p.id, local_date: p.local_date, starts_at: p.starts_at, date_precision: p.date_precision, venue_name: p.venue_name, prefecture_code: p.prefecture_code, status: p.status, user_status: st.states[p.id] || null }));
  function pickups() {
    const st = load(), out = [];
    for (const [cid, v] of Object.entries(st.pickups)) {
      const c = byId.get(cid);
      if (!c) continue;
      out.push({ concert_id: cid, priority: v.priority, notes: v.notes || null, created_at: v.created_at, title_ja: c.title_ja, category: c.category, organization_id: c.source_id || null,
        performances: rowPerformances(c, st) });
    }
    out.sort((a, b) => (a.priority === b.priority ? (a.created_at < b.created_at ? 1 : -1) : a.priority === "high" ? -1 : 1));
    return { items: out };
  }
  // plans to attend (ADR-0012): same row shape as a pickup without the priority
  function plans() {
    const st = load(), out = [];
    for (const [cid, v] of Object.entries(st.plans)) {
      const c = byId.get(cid);
      if (!c) continue;
      out.push({ concert_id: cid, created_at: v.created_at, title_ja: c.title_ja, category: c.category, organization_id: c.source_id || null, performances: rowPerformances(c, st) });
    }
    out.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return { items: out };
  }
  function findPhase(id) { for (const c of concerts) for (const p of c.performances) for (const t of p.ticket_phases) if (t.id === id) return t; return null; }

  // tour leads (ADR-0007): second-hand, published in data/leads.json (covered_by is computed at build time); the same shapes as the API
  function leadsPage() {
    const today = jstDate(asOf), all = (D.leads && D.leads.leads) || [];
    const items = all.filter((l) => { const end = l.date_to || l.date_from; return end ? end >= today : !!l.month_hint && l.month_hint >= today.slice(0, 7); });
    return { items, source: (D.leads && D.leads.source) || { name: "オケミン！", url: null }, as_of: today, notice: "第三方整理，未经官方核实" };
  }
  async function handle(method, path, body) {
    if (LIVE) asOf = new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
    const url = new URL(path, "http://x"), p = url.pathname, q = url.searchParams;
    let m;
    if (method === "GET" && p === "/discover") return discover(q);
    if (method === "GET" && p === "/discover/facets") return facets(q);
    if (method === "GET" && p === "/discover/coverage") return D.coverage;
    if (method === "GET" && p === "/calendar") return calendar(q);
    if (method === "GET" && p === "/leads") return leadsPage();
    if (method === "GET" && (m = p.match(/^\/leads\/(lead-[0-9a-f]{20})$/))) { const l = leadsPage().items.find((x) => x.lead_id === m[1]); if (!l) throw new Error("没有找到这条线索"); return l; }
    if (method === "GET" && p === "/me/pickups") return pickups();
    if (method === "GET" && p === "/me/plans") return plans();
    if (method === "GET" && (m = p.match(/^\/concerts\/(.+)$/))) return detail(m[1]);
    if (p.startsWith("/me/pickups/") && (m = p.match(/^\/me\/pickups\/(.+)$/))) {
      const id = m[1];
      if (method === "PUT") {
        if (!byId.has(id)) throw new Error("没有找到这个节目");
        const v = { priority: (body && body.priority) || "normal", notes: (body && body.notes) || null, created_at: new Date().toISOString() };
        await change({ method: "PUT", path: `/me/pickups/${id}`, body: v }, (s) => { s.pickups[id] = v; });
        return { ok: true };
      }
      if (method === "DELETE") { await change({ method: "DELETE", path: `/me/pickups/${id}` }, (s) => { delete s.pickups[id]; }); return null; }
    }
    if (p.startsWith("/me/plans/") && (m = p.match(/^\/me\/plans\/(.+)$/))) {
      const id = m[1];
      if (method === "PUT") {
        if (!byId.has(id)) throw new Error("没有找到这个节目");
        const v = { created_at: load().plans[id]?.created_at || new Date().toISOString() };
        await change({ method: "PUT", path: `/me/plans/${id}` }, (s) => { s.plans[id] = v; });
        return { ok: true };
      }
      if (method === "DELETE") { await change({ method: "DELETE", path: `/me/plans/${id}` }, (s) => { delete s.plans[id]; }); return null; }
    }
    if (method === "PUT" && (m = p.match(/^\/me\/performances\/(.+)\/state$/))) {
      const id = m[1];
      if (!USER.includes(body && body.status)) throw new Error("状态不合法");
      await change({ method: "PUT", path: `/me/performances/${id}/state`, body: { status: body.status } }, (s) => { s.states[id] = body.status; });
      return { ok: true };
    }
    if (method === "PUT" && (m = p.match(/^\/me\/reminders\/(.+)$/))) {
      const id = m[1], t = findPhase(id);
      if (!t) throw new Error("没有找到这个售票阶段");
      if (body.enabled && (t.start_precision !== "exact_time" || !t.starts_at)) throw new Error("开售时间没有精确到分钟，不能设置提醒");
      await change({ method: "PUT", path: `/me/reminders/${id}`, body }, (s) => { s.reminders[id] = body; });
      return body;
    }
    throw new Error("网页版不支持这个操作（需要本地后端）");
  }
  window.CR_DEMO = { handle, asOf, snapshot: D.snapshot_label, concertCount: concerts.length, mode: REMOTE ? "site" : "demo" };
})();
